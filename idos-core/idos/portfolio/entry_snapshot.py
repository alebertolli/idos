"""Entry snapshot: congelado de todo el estado analitico al momento de la entrada.

Guarda thesis, assessments (todos los engines), tecnicos (wyckoff de entrada),
catalizadores, riesgos, dominios y fundamentales. El Learning domain
(PostMortemWorker) lo usa al cierre para evaluar si hubo error de analisis
contra los datos exactos del momento de la entrada, no los del cierre.
"""
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from idos.timezone import AR_TZ


def _load_yaml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def snapshot_path(journal, ticker: str, opp_id: str) -> Path:
    return journal.opportunity_path(ticker, opp_id) / "entry_snapshot.yml"


def save_entry_snapshot(journal, ticker: str, opp_id: str, snapshot: dict[str, Any]):
    path = snapshot_path(journal, ticker, opp_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(snapshot, f, default_flow_style=False, allow_unicode=True)


def load_entry_snapshot(journal, ticker: str, opp_id: str) -> dict[str, Any] | None:
    return _load_yaml(snapshot_path(journal, ticker, opp_id))


def _parse_dt(value: Any):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _load_assessments(journal, ticker: str, opp_id: str) -> list[dict[str, Any]]:
    opp = journal.opportunity_path(ticker, opp_id)
    assessments: dict[str, dict[str, Any]] = {}

    proposal = _load_yaml(opp / "decision_proposal.yml")
    if proposal and isinstance(proposal.get("assessments"), dict):
        for engine, spec in (proposal["assessments"] or {}).items():
            if isinstance(spec, dict):
                assessments[engine] = {
                    "engine": spec.get("engine") or engine,
                    "score": spec.get("score"),
                    "confidence": spec.get("confidence"),
                    "recommendation": spec.get("recommendation"),
                    "findings": spec.get("findings", []),
                    "risks": spec.get("risks", []),
                    "generated_at": spec.get("generated_at"),
                }

    ass_dir = opp / "assessments"
    if ass_dir.exists():
        for f in sorted(ass_dir.glob("*.yml")):
            data = _load_yaml(f)
            if not data:
                continue
            engine = data.get("engine") or f.stem
            assessments[engine] = {
                "engine": engine,
                "score": data.get("score"),
                "confidence": data.get("confidence"),
                "recommendation": data.get("recommendation"),
                "findings": data.get("findings", []),
                "risks": data.get("risks", []),
                "generated_at": data.get("generated_at"),
            }
    return list(assessments.values())


def _load_wyckoff_at_entry(journal, ticker: str, opp_id: str,
                           entry_date: str | None) -> dict[str, Any] | None:
    """Wyckoff del momento de la entrada: el que disparo la entrada, si no el
    ultimo anterior/igual a la fecha de entrada."""
    w_dir = journal.opportunity_path(ticker, opp_id) / "wyckoff"
    if not w_dir.exists():
        return None
    analyses: list[dict[str, Any]] = []
    for f in sorted(w_dir.glob("*.yml")):
        data = _load_yaml(f)
        if data:
            analyses.append(data)
    if not analyses:
        return None

    for a in analyses:
        if a.get("triggered_entry"):
            return a

    if entry_date:
        entry_dt = _parse_dt(entry_date)
        if entry_dt:
            before = [a for a in analyses
                      if _parse_dt(a.get("analyzed_at")) is not None
                      and _parse_dt(a.get("analyzed_at")) <= entry_dt]
            if before:
                return before[-1]
    return analyses[-1]


def _technical_block(wyckoff: dict[str, Any] | None) -> dict[str, Any]:
    if not wyckoff:
        return {}
    return {
        "wyckoff_phase": wyckoff.get("phase"),
        "wyckoff_score": wyckoff.get("score"),
        "wyckoff_confidence": wyckoff.get("confidence"),
        "wyckoff_entry_point": wyckoff.get("entry_point"),
        "wyckoff_price_target": wyckoff.get("price_target"),
        "indicators": wyckoff.get("indicators") or {},
        "llm_response": wyckoff.get("llm_response") or {},
        "analyzed_at": wyckoff.get("analyzed_at"),
        "triggered_entry": wyckoff.get("triggered_entry"),
    }


def build_entry_snapshot(journal, ticker: str, opp_id: str,
                         entry_info: dict[str, Any] | None = None) -> dict[str, Any]:
    ticker = ticker.upper()
    entry_info = entry_info or {}
    opp = journal.opportunity_path(ticker, opp_id)
    ddd = _load_yaml(opp / "ddd_report.yml") or {}
    proposal = _load_yaml(opp / "decision_proposal.yml") or {}

    entry_date = entry_info.get("entry_date")
    if not entry_date:
        pos = journal.load_position(ticker)
        entry_date = (pos or {}).get("entry_date")

    wyckoff = _load_wyckoff_at_entry(journal, ticker, opp_id, entry_date)
    dominios = {k: v for k, v in ddd.items() if k.startswith("dominio_")}
    error_mercado = ddd.get("error_mercado") or {}

    snapshot = {
        "snapshot_at": datetime.now(AR_TZ).isoformat(),
        "ticker": ticker,
        "opp_id": opp_id,
        "entry": {
            "entry_price": entry_info.get("entry_price"),
            "entry_date": entry_date,
            "quantity": entry_info.get("quantity"),
            "stop_loss": entry_info.get("stop_loss"),
            "target_price": entry_info.get("target_price") or entry_info.get("intrinsic_value"),
            "intrinsic_value": entry_info.get("intrinsic_value"),
            "conviction_at_entry": entry_info.get("conviction"),
            "margin_of_safety_pct": entry_info.get("margin_of_safety_pct"),
            "current_price": entry_info.get("current_price"),
        },
        "thesis": {
            "tesis_inversion": ddd.get("tesis_inversion"),
            "resumen_ejecutivo": ddd.get("resumen_ejecutivo"),
            "opinion_valoracion": ddd.get("opinion_valoracion"),
            "score_general": ddd.get("score_general"),
            "clasificacion_oportunidad": ddd.get("clasificacion_oportunidad"),
            "error_mercado": error_mercado,
            "catalizador_cambio": error_mercado.get("catalizador_cambio"),
        },
        "fundamentals": ddd.get("prompt_inputs") or {},
        "assessments": _load_assessments(journal, ticker, opp_id),
        "technical": _technical_block(wyckoff),
        "catalysts": ddd.get("dominio_catalizadores") or [],
        "risks": ddd.get("dominio_riesgos") or [],
        "dominios": dominios,
        "rules_passed": proposal.get("rules_passed") or [],
        "rules_failed": proposal.get("rules_failed") or [],
        "recommendation": proposal.get("recommendation"),
    }
    return snapshot
