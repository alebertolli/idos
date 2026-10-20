"""Read the latest applicable strategy selection without changing its policy."""

from datetime import date, datetime
import math
from pathlib import Path
from typing import Any

import yaml


class SignalEvidenceError(ValueError):
    """A current, reproducible selection cannot be established."""


def current_selection(base: Path, strategy_id: str, ticker: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """A bounded run supersedes only its requested tickers; a full run supersedes all.

    Legacy reports without generation time/scope are history, not authority.
    A newer incomplete or negative result must never fall back to an older buy signal.
    """
    reports = []
    root = base / "idos-journal" / "strategies" / strategy_id
    for path in root.glob("*.yml"):
        try:
            report = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(report, dict):
                raise ValueError("report must be an object")
            if not report.get("generated_at"):
                continue
            generated = datetime.fromisoformat(str(report["generated_at"]))
            if generated.tzinfo is None or report.get("strategy_id") != strategy_id:
                raise ValueError("timestamp or strategy identity invalid")
            scope = report.get("run_scope")
            if scope not in {"full", "bounded"}:
                raise ValueError("explicit run scope required")
            requested = report.get("requested_tickers")
            if scope == "bounded":
                if not isinstance(requested, list):
                    raise ValueError("bounded scope requires requested tickers")
                if ticker not in requested:
                    continue
            reports.append((generated, path, report))
        except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            raise SignalEvidenceError(f"invalid_signal_snapshot: {path.name}") from exc
    if not reports:
        raise SignalEvidenceError("signal_snapshot_unavailable")
    generated, path, report = max(reports, key=lambda item: item[0])
    policy = {key: parameters.get(key) for key in ("minimum_signal", "maximum_signal", "select_top")}
    if (
        any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in (policy["minimum_signal"], policy["maximum_signal"]))
        or not policy["minimum_signal"] < policy["maximum_signal"]
        or isinstance(policy["select_top"], bool) or not isinstance(policy["select_top"], int)
        or policy["select_top"] <= 0
    ):
        raise SignalEvidenceError("invalid_signal_policy")
    if report.get("signal_policy") != policy:
        raise SignalEvidenceError("signal_policy_changed_or_unrecorded")
    gate = report.get("market_gate")
    if report.get("coverage_complete") is not True or not isinstance(gate, dict) or gate.get("coverage_complete") is not True:
        raise SignalEvidenceError("signal_snapshot_incomplete")
    selected = report.get("selected")
    if not isinstance(selected, list) or any(not isinstance(row, dict) for row in selected):
        raise SignalEvidenceError("invalid_signal_selection")
    matches = [row for row in selected if row.get("ticker") == ticker]
    if not matches:
        raise SignalEvidenceError("not_selected_in_latest_snapshot")
    if len(matches) != 1 or report.get("action") != "REVIEW_ALLOCATION":
        raise SignalEvidenceError("invalid_signal_selection")
    signal = matches[0]
    value = signal.get("momentum")
    try:
        as_of = date.fromisoformat(signal["as_of_date"])
        valid = (
            not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
            and as_of.isoformat() == signal["as_of_date"] and as_of <= generated.date()
            and policy["minimum_signal"] <= value <= policy["maximum_signal"]
            and signal in report.get("ranking", []) and signal in report.get("eligible", [])
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise SignalEvidenceError("invalid_signal_evidence")
    return {
        "signal": dict(signal), "signal_policy": policy,
        "source": path.relative_to(base).as_posix(),
        "generated_at": report["generated_at"], "run_scope": report["run_scope"],
    }
