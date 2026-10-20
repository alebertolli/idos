"""Deterministic, evidence-only post-mortem analysis."""

from typing import Any


def build_post_mortem_analysis(
    *,
    decisions: list[dict[str, Any]],
    assessments: list[dict[str, Any]],
    position: dict[str, Any] | None,
    exit_reason: str,
    wyckoff_analyses: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    entry_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Summarize recorded outcomes without inferring causes or strategy changes."""
    prediction_evaluations: list[dict[str, Any]] = []
    falsification_triggers: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        hypothesis_id = hypothesis.get("id", "")
        for prediction in hypothesis.get("predictions", []) or []:
            met = prediction.get("met")
            status = "MET" if met is True else "MISSED" if met is False else "NOT_EVALUATED"
            prediction_evaluations.append({
                "hypothesis_id": hypothesis_id,
                "metric": prediction.get("metric", ""),
                "expected": prediction.get("expected", prediction.get("expected_value")),
                "actual": prediction.get("actual", prediction.get("actual_value")),
                "met": met if isinstance(met, bool) else None,
                "status": status,
            })
        for falsification in hypothesis.get("falsification", []) or []:
            if falsification.get("triggered") is True:
                falsification_triggers.append({
                    "hypothesis_id": hypothesis_id,
                    "condition": falsification.get("condition", ""),
                })

    evaluated = [item for item in prediction_evaluations if item["met"] is not None]
    went_right = [
        _prediction_observation(item) for item in evaluated if item["met"] is True
    ]
    went_wrong = [
        _prediction_observation(item) for item in evaluated if item["met"] is False
    ]
    observations = went_right + went_wrong + [
        f"Se registraron {len(falsification_triggers)} condiciones de falsación disparadas."
    ] if falsification_triggers else went_right + went_wrong

    data_gaps = []
    if not entry_snapshot:
        data_gaps.append("No hay snapshot analítico de entrada.")
    if not evaluated:
        data_gaps.append("No hay predicciones con resultado evaluado.")
    if not _has_realized_exit_data(position):
        data_gaps.append("No hay fecha y precio/P&L realizado de salida para medir el resultado financiero.")
    if not hypotheses:
        data_gaps.append("No hay hipótesis registradas para contrastar.")
    if not decisions:
        data_gaps.append("No hay decisiones registradas para revisar el proceso de decisión.")

    entry = (entry_snapshot or {}).get("entry") or {}
    thesis = (entry_snapshot or {}).get("thesis") or {}
    technical = (entry_snapshot or {}).get("technical") or {}
    latest_wyckoff = wyckoff_analyses[-1] if wyckoff_analyses else {}

    return {
        "analysis_version": "deterministic_post_mortem_v1",
        "exit_analysis": "Resumen factual. No atribuye causalidad ni evalúa el resultado financiero sin datos de salida.",
        "exit_reason": exit_reason,
        "thesis_was_correct": None,
        "what_went_wrong": went_wrong,
        "what_went_right": went_right,
        "observations": observations,
        "lessons_learned": [],
        "methodological_errors": [],
        "methodology_assessment": "NOT_ASSESSED",
        "biases_detected": [],
        "biases_assessment": "NOT_ASSESSED",
        "would_invest_again": None,
        "wyckoff_accuracy": "no_evaluada",
        "wyckoff_phase_was_correct": None,
        "wyckoff_lessons": [],
        "hypothesis_evaluation": {
            "predictions_analyzed": bool(prediction_evaluations),
            "predictions_total": len(prediction_evaluations),
            "predictions_evaluated": len(evaluated),
            "predictions_met": sum(item["met"] is True for item in evaluated),
            "was_falsification_applied": bool(falsification_triggers),
            "confirmation_bias": "NOT_ASSESSED",
        },
        "evidence": {
            "decision_count": len(decisions),
            "decisions": [_decision_evidence(item) for item in decisions],
            "assessment_count": len(assessments),
            "assessments": [_assessment_evidence(item) for item in assessments],
            "entry_snapshot_available": bool(entry_snapshot),
            "entry": {
                "entry_price": entry.get("entry_price"),
                "entry_date": entry.get("entry_date"),
                "target_price": entry.get("target_price"),
                "thesis": thesis.get("tesis_inversion"),
                "thesis_score": thesis.get("score_general"),
                "catalysts_count": len((entry_snapshot or {}).get("catalysts", []) or []),
                "risks_count": len((entry_snapshot or {}).get("risks", []) or []),
                "wyckoff_phase": technical.get("wyckoff_phase") or technical.get("phase"),
                "wyckoff_score": technical.get("wyckoff_score", technical.get("score")),
            },
            "predictions": prediction_evaluations,
            "falsification_triggers": falsification_triggers,
            "latest_wyckoff": {
                "phase": latest_wyckoff.get("phase"),
                "score": latest_wyckoff.get("score"),
                "analyzed_at": latest_wyckoff.get("analyzed_at"),
            },
            "position_available": bool(position),
            "realized_exit_available": _has_realized_exit_data(position),
        },
        "portfolio_metrics": {
            "financial_pnl_usd": {
                "value": None,
                "status": "NOT_ASSESSED",
                "reason": "No existe fuente privada conectada y resultado reconciliado.",
            },
            "purchasing_power_impact_ars": {
                "value": None,
                "status": "NOT_ASSESSED",
                "reason": "No existe cartera privada, FX de salida y metodología de poder adquisitivo conciliados.",
            },
        },
        "data_gaps": data_gaps,
        "strategy_recommendations_status": "SINGLE_CASE_REPORT_ONLY",
    }


def _prediction_observation(prediction: dict[str, Any]) -> str:
    metric = prediction.get("metric") or "predicción sin métrica"
    expected = prediction.get("expected")
    actual = prediction.get("actual")
    outcome = "se cumplió" if prediction["met"] else "no se cumplió"
    return f"La predicción {metric} {outcome} (esperado={expected!r}, observado={actual!r})."


def _decision_evidence(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": decision.get("id"),
        "type": decision.get("type"),
        "status": decision.get("status"),
        "rationale": decision.get("rationale"),
        "generated_at": decision.get("generated_at"),
    }


def _assessment_evidence(assessment: dict[str, Any]) -> dict[str, Any]:
    return {
        "engine": assessment.get("engine"),
        "score": assessment.get("score"),
        "recommendation": assessment.get("recommendation"),
        "generated_at": assessment.get("generated_at"),
    }


def _has_realized_exit_data(position: dict[str, Any] | None) -> bool:
    if not isinstance(position, dict):
        return False
    has_exit_date = bool(position.get("exited_at") or position.get("exit_date"))
    has_exit_price = position.get("exit_price") is not None
    has_realized_pnl = position.get("realized_pnl") is not None or position.get("pnl") is not None
    return has_exit_date and (has_exit_price or has_realized_pnl)
