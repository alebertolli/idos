"""Validated, auditable evidence envelopes for thesis re-research triggers."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SUPPORTED_THESIS_EVENT_TYPES = frozenset({
    "quarterly_results",
    "guidance_change",
    "material_restatement",
    "red_flag_change",
    "material_financial_deterioration",
    "thesis_change",
})


def canonical_event_type(value: Any) -> str | None:
    canonical = str(value or "").strip().lower().replace("-", "_")
    return canonical if canonical in SUPPORTED_THESIS_EVENT_TYPES else None


def load_event_evidence(
    event_type: str,
    ticker: str,
    *,
    event_path: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read and validate evidence from a GitHub Actions event payload.

    Manual workflow inputs provide one evidence record. repository_dispatch
    accepts an ``events`` list so earnings events can be batched safely.
    """
    canonical = canonical_event_type(event_type)
    if canonical is None:
        raise ValueError("event_type no es un evento material soportado")
    payload_value = event_path or os.environ.get("GITHUB_EVENT_PATH")
    if not payload_value:
        raise ValueError("GITHUB_EVENT_PATH no está configurado")
    payload_path = Path(payload_value)
    try:
        envelope = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("no se pudo leer el payload de GitHub Actions") from exc
    if not isinstance(envelope, dict):
        raise ValueError("el payload de GitHub Actions debe ser un objeto")

    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    records: list[dict[str, Any]] = []
    if event_name == "repository_dispatch":
        client_payload = envelope.get("client_payload")
        raw_events = client_payload.get("events") if isinstance(client_payload, dict) else None
        if not isinstance(raw_events, list):
            raise ValueError("repository_dispatch requiere client_payload.events")
        records = [item for item in raw_events if isinstance(item, dict)]
    elif event_name == "workflow_dispatch":
        inputs = envelope.get("inputs")
        if not isinstance(inputs, dict):
            raise ValueError("workflow_dispatch requiere inputs")
        records = [{
            "ticker": ticker,
            "event_type": canonical,
            "occurred_at": inputs.get("event_date"),
            "source_name": inputs.get("event_source_name"),
            "source_url": inputs.get("event_source_url"),
            "summary": inputs.get("event_summary"),
        }]
    else:
        raise ValueError(f"el evento GitHub {event_name or '(desconocido)'} no puede disparar re-research material")

    target_ticker = str(ticker).upper().strip()
    matching = [
        item for item in records
        if str(item.get("ticker", "")).upper().strip() == target_ticker
        and canonical_event_type(item.get("event_type", canonical)) == canonical
    ]
    if len(matching) != 1:
        raise ValueError(f"se esperaba una evidencia única para {target_ticker}; recibidas {len(matching)}")
    return normalize_event_evidence(
        canonical,
        target_ticker,
        matching[0],
        now=now,
    )


def normalize_event_evidence(
    event_type: str,
    ticker: str,
    value: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate and normalize one event; missing/conflicting evidence fails closed."""
    canonical = canonical_event_type(event_type)
    if canonical is None or not isinstance(value, dict):
        raise ValueError("tipo de evento o evidencia inválidos")
    raw_type = value.get("event_type")
    if raw_type and canonical_event_type(raw_type) != canonical:
        raise ValueError("el tipo de evidencia no coincide con el trigger")
    target_ticker = str(ticker).upper().strip()
    raw_ticker = value.get("ticker")
    if raw_ticker and str(raw_ticker).upper().strip() != target_ticker:
        raise ValueError("el ticker de evidencia no coincide con la oportunidad")

    occurred_at = value.get("occurred_at") or value.get("event_date")
    if not isinstance(occurred_at, str):
        raise ValueError("occurred_at debe ser una fecha ISO")
    try:
        occurred = date.fromisoformat(occurred_at)
    except ValueError as exc:
        raise ValueError("occurred_at debe ser una fecha ISO") from exc
    if occurred.isoformat() != occurred_at:
        raise ValueError("occurred_at debe usar YYYY-MM-DD")
    reference_time = now or datetime.now(timezone.utc)
    reference_utc = (
        reference_time.astimezone(timezone.utc)
        if reference_time.tzinfo is not None
        else reference_time.replace(tzinfo=timezone.utc)
    )
    if occurred > reference_utc.date():
        raise ValueError("occurred_at no puede estar en el futuro")

    source_name = str(value.get("source_name", "")).strip()
    if not source_name or len(source_name) > 160:
        raise ValueError("source_name es obligatorio y no puede superar 160 caracteres")
    source_url = str(value.get("source_url", "")).strip()
    parsed_url = urlparse(source_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.username or parsed_url.password:
        raise ValueError("source_url debe ser una URL HTTPS válida")
    summary = str(value.get("summary", "")).strip()
    if len(summary) < 8 or len(summary) > 1000:
        raise ValueError("summary debe tener entre 8 y 1000 caracteres")

    observed_at = value.get("observed_at")
    if observed_at:
        try:
            observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("observed_at debe ser un timestamp ISO con zona horaria") from exc
        if observed.tzinfo is None:
            raise ValueError("observed_at debe incluir zona horaria")
        if observed > reference_utc:
            raise ValueError("observed_at no puede estar en el futuro")
    else:
        observed_at = reference_time.astimezone(timezone.utc).isoformat()

    canonical_record = {
        "event_type": canonical,
        "ticker": target_ticker,
        "occurred_at": occurred_at,
        "source_name": source_name,
        "source_url": source_url,
        "summary": summary,
    }
    event_id = hashlib.sha256(
        json.dumps(canonical_record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        **canonical_record,
        "observed_at": observed_at if isinstance(observed_at, str) else observed_at.isoformat(),
        "event_id": event_id,
    }
