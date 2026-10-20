#!/usr/bin/env python3
"""Build a source-linked, batched repository_dispatch payload for earnings."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import yaml
from idos.research.events import normalize_event_evidence


def build_payload(
    trigger_path: str | Path,
    earnings_config_path: str | Path,
    *,
    observed_at: datetime | None = None,
) -> dict:
    trigger = json.loads(Path(trigger_path).read_text(encoding="utf-8"))
    if not isinstance(trigger, dict) or not isinstance(trigger.get("triggered"), list):
        raise ValueError("earnings trigger debe contener una lista triggered")
    config = yaml.safe_load(Path(earnings_config_path).read_text(encoding="utf-8")) or {}
    tickers_config = config.get("tickers", {}) if isinstance(config, dict) else {}
    if not isinstance(tickers_config, dict):
        raise ValueError("earnings config tiene un mapa tickers inválido")

    timestamp = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    tickers = sorted({str(ticker).upper().strip() for ticker in trigger["triggered"] if str(ticker).strip()})
    events = []
    for ticker in tickers:
        details = tickers_config.get(ticker)
        if not isinstance(details, dict):
            raise ValueError(f"falta metadata de resultados para {ticker}")
        occurred_at = details.get("earnings_date")
        source_name = details.get("source_name")
        source_url = details.get("source_url")
        if not all(isinstance(value, str) and value.strip() for value in (occurred_at, source_name, source_url)):
            raise ValueError(f"falta fecha o procedencia para {ticker}")
        event = {
            "ticker": ticker,
            "event_type": "quarterly_results",
            "occurred_at": occurred_at,
            "observed_at": timestamp,
            "source_name": source_name,
            "source_url": source_url,
            "summary": (
                f"El calendario de resultados indica la fecha {occurred_at}. "
                "La fecha no confirma por sí sola la publicación del reporte; "
                "Research debe verificar el resultado en una fuente primaria."
            ),
        }
        events.append(normalize_event_evidence(
            "quarterly_results",
            ticker,
            event,
            now=observed_at or datetime.now(timezone.utc),
        ))
    if not events:
        raise ValueError("no hay tickers para despachar")
    return {
        "event_type": "quarterly-results",
        "client_payload": {
            "ticker": ",".join(tickers),
            "events": events,
        },
    }


def main() -> int:
    try:
        payload = build_payload(
            "cache/earnings_trigger.json",
            "idos-config/events/earnings.yml",
        )
    except (OSError, json.JSONDecodeError, ValueError, yaml.YAMLError) as exc:
        print(f"[DISPATCH] Invalid earnings evidence: {exc}", file=sys.stderr)
        return 2
    output = Path("cache/earnings_dispatch_payload.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DISPATCH] Prepared {len(payload['client_payload']['events'])} source-linked earnings events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
