"""Deterministic, evidence-aware discovery for the MULTIBAGGERS profile."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any


CRITICAL_METRICS = (
    "revenue_cagr_3y_pct", "eps_growth_pct", "fcf_growth_pct", "roic_pct",
    "operating_margin_pct", "fcf_conversion_pct", "net_debt_ebitda",
    "dilution_yoy_pct", "market_cap_usd", "avg_dollar_volume_usd",
    "relative_strength_12m_pct", "expectation_gap_pct",
)


@dataclass(frozen=True)
class DiscoveryResult:
    ticker: str
    strategy_id: str
    strategy_version: str
    passed: bool
    discovery_score: float
    research_priority: float
    discovery_type: str
    component_scores: dict[str, float]
    metrics_snapshot: dict[str, dict[str, Any]]
    red_flags: list[dict[str, Any]]
    data_quality: dict[str, Any]
    reason_codes: list[str]
    as_of: str
    snapshot_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MultibaggersDiscoveryEngine:
    """Scores only reproducible evidence; absent or unsafe inputs fail closed."""

    def __init__(self, parameters: dict[str, Any], strategy_version: str = "1.0"):
        self.parameters = parameters
        self.strategy_version = strategy_version

    def evaluate(self, ticker: str, payload: dict[str, Any], as_of: str | None = None) -> DiscoveryResult:
        now = as_of or payload.get("as_of") or datetime.now(timezone.utc).isoformat()
        metrics = payload.get("merged_data", payload.get("metrics", payload)) or {}
        metric_sources = payload.get("metric_sources", {}) or {}
        metric_values = payload.get("metric_values", {}) or {}
        conflicts = payload.get("conflicts", []) or []
        snapshot = self._metric_snapshot(metrics, metric_sources, metric_values, now, conflicts)
        quality = self._quality(snapshot, conflicts)
        flags = self._hard_flags(snapshot, conflicts)
        minimum_coverage = float(self.parameters.get("data_quality", {}).get("critical_coverage_min", .8))
        if quality["critical_coverage"] < minimum_coverage:
            flags.append({"code": "CRITICAL_COVERAGE_BELOW_MINIMUM", "severity": "hard", "metric": "critical_coverage", "message": "Critical metric coverage is below policy", "evidence": quality["critical_coverage"]})
        components = self._components(snapshot)
        weights = self.parameters.get("weights", {})
        score = round(sum(components.get(k, 0.0) * float(w) for k, w in weights.items()), 2)
        reasons = [f"HARD_FLAG:{flag['code']}" for flag in flags]
        if quality["critical_coverage"] < minimum_coverage:
            reasons.append("DATA_COVERAGE_BELOW_MINIMUM")
        if quality["critical_source_failures"]:
            reasons.append("CRITICAL_METRIC_SOURCE_COVERAGE_FAILED")
        if quality["critical_conflicts"]:
            reasons.append("CRITICAL_METRIC_CONFLICT")
        if quality["critical_stale"]:
            reasons.append("CRITICAL_METRIC_STALE")
        threshold = float(self.parameters.get("discovery_threshold", 65))
        passed = not reasons and score >= threshold
        if score < threshold:
            reasons.append("DISCOVERY_SCORE_BELOW_THRESHOLD")
        if quality["critical_coverage"] == 0:
            kind = "BLOCKED_DATA"
        elif flags or quality["critical_conflicts"] or quality["critical_stale"] or quality["critical_source_failures"]:
            kind = "BLOCKED_DATA"
        elif components["economic_transition"] >= 65 and components["quality"] >= 65 and components["reinvestment"] >= 60:
            kind = "FUNDAMENTAL_COMPOUNDING"
        elif components["economic_transition"] >= 60 and components["market_confirmation"] < 50:
            kind = "EARLY_TRANSITION"
        elif components["economic_transition"] >= 60 and components["market_confirmation"] >= 60:
            kind = "MARKET_CONFIRMED_GROWTH"
        elif snapshot.get("expectation_gap_pct", {}).get("value") is not None:
            kind = "EXPECTATION_GAP"
        else:
            kind = "RESEARCH_REQUIRED"
        priority = round(score * quality["coverage_factor"] * quality["freshness_factor"], 2)
        body = {
            "ticker": ticker.upper(), "strategy_id": "MULTIBAGGERS", "strategy_version": self.strategy_version,
            "passed": passed, "discovery_score": score, "research_priority": priority,
            "discovery_type": kind, "component_scores": components, "metrics_snapshot": snapshot,
            "red_flags": flags, "data_quality": quality, "reason_codes": reasons, "as_of": now,
        }
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        return DiscoveryResult(**body, snapshot_hash=digest)

    def _metric_snapshot(self, metrics: dict[str, Any], source_map: dict[str, Any], source_values: dict[str, Any], now: str, conflicts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        aliases = {
            "revenue_cagr_3y_pct": ("revenue_cagr_3y_pct", "revenue_cagr_3y"),
            "eps_growth_pct": ("eps_growth_pct", "eps_growth"),
            "fcf_growth_pct": ("fcf_growth_pct", "fcf_growth"),
            "roic_pct": ("roic_pct", "roic"),
            "operating_margin_pct": ("operating_margin_pct", "operating_margin"),
            "fcf_conversion_pct": ("fcf_conversion_pct",),
            "net_debt_ebitda": ("net_debt_ebitda",),
            "dilution_yoy_pct": ("dilution_yoy_pct",),
            "market_cap_usd": ("market_cap_usd", "market_cap"),
            "avg_dollar_volume_usd": ("avg_dollar_volume_usd", "avg_dollar_volume"),
            "relative_strength_12m_pct": ("relative_strength_12m_pct", "relative_strength_12m"),
            "expectation_gap_pct": ("expectation_gap_pct",),
            "current_ratio": ("current_ratio",), "interest_coverage": ("interest_coverage", "interest_coverage_ratio"),
            "fcf_runway_months": ("fcf_runway_months",), "share_count_cagr_3y_pct": ("share_count_cagr_3y_pct",),
            "gross_margin_pct": ("gross_margin_pct",), "revenue_growth_pct": ("revenue_growth_pct",),
            "recurring_revenue_pct": ("recurring_revenue_pct",), "rd_to_revenue_pct": ("rd_to_revenue_pct",),
            "capex_to_revenue_pct": ("capex_to_revenue_pct",), "drawdown_pct": ("drawdown_pct",),
            "volatility_90d_pct": ("volatility_90d_pct", "volatility_90d"),
        }
        conflicted_fields = {str(c.get("field", "")) for c in conflicts}
        conflict_aliases = {"market_cap": "market_cap_usd", "avg_dollar_volume": "avg_dollar_volume_usd", "roic": "roic_pct", "fcf_growth": "fcf_growth_pct"}
        quality_cfg = self.parameters.get("data_quality", {})
        stale_after = int(quality_cfg.get("stale_after_days", 120))
        result: dict[str, dict[str, Any]] = {}
        for name, candidates in aliases.items():
            raw_key = next((key for key in candidates if metrics.get(key) is not None), None)
            raw = metrics.get(raw_key) if raw_key else None
            value = self._number(raw)
            sources = source_map.get(raw_key or name, source_map.get(name, []))
            if isinstance(sources, dict):
                sources = list(sources)
            as_metric = metrics.get(f"{raw_key or name}_as_of") or metrics.get(f"{name}_as_of")
            stale = self._is_stale(as_metric, stale_after, now)
            status = "missing" if value is None or not as_metric else ("stale" if stale else "observed")
            currency = "USD" if raw_key and raw_key.endswith("_usd") else metrics.get(f"{raw_key}_currency") if raw_key else None
            if name.endswith("_usd") and value is not None and str(currency or metrics.get("currency", "")).upper() != "USD":
                status = "missing"
                value = None
            if raw_key in conflicted_fields or name in conflicted_fields or conflict_aliases.get(raw_key) in conflicted_fields:
                status = "conflicted"
            if raw_key and raw_key in {"roic", "operating_margin", "revenue_growth", "eps_growth", "fcf_growth"}:
                value *= 100 if abs(value) <= 1 else 1
            if status in {"missing", "stale", "conflicted"}:
                value = None
            unit = "USD" if name.endswith("_usd") else ("percent" if name.endswith("_pct") or name in {"drawdown_pct", "volatility_90d_pct"} else "ratio")
            period = metrics.get(f"{raw_key or name}_period")
            result[name] = {
                "value": value, "unit": unit, "period": period,
                "source": list(sources) if isinstance(sources, (list, tuple, set)) else [],
                "as_of": as_metric if value is not None else None,
                "coverage": len(sources) if isinstance(sources, (list, tuple, set)) else 0,
                "source_values": source_values.get(raw_key or name, source_values.get(name, {})),
                "currency": "USD" if name.endswith("_usd") and status != "missing" else currency,
                "status": status,
            }
        return result

    def _quality(self, snapshot: dict[str, dict[str, Any]], conflicts: list[dict[str, Any]]) -> dict[str, Any]:
        critical = [snapshot[name] for name in CRITICAL_METRICS]
        covered = sum(item["status"] in {"observed", "derived"} for item in critical)
        min_sources = int(self.parameters.get("data_quality", {}).get("critical_sources_min", 2))
        source_failures = sum(item["status"] != "missing" and item["coverage"] < min_sources for item in critical)
        conflict_fields = {str(c.get("field", "")) for c in conflicts}
        critical_fields = set(CRITICAL_METRICS) | {"market_cap", "avg_dollar_volume", "revenue_cagr_3y", "roic", "fcf_growth"}
        critical_conflicts = sorted(conflict_fields & critical_fields)
        stale = sum(item["status"] == "stale" for item in critical)
        coverage = covered / len(critical)
        return {
            "critical_metric_count": len(critical), "critical_metrics_covered": covered,
            "critical_coverage": round(coverage, 4), "critical_source_failures": source_failures,
            "critical_conflicts": critical_conflicts, "critical_stale": stale,
            "coverage_factor": round(coverage, 4), "freshness_factor": round(1 - stale / len(critical), 4),
        }

    def _hard_flags(self, snapshot: dict[str, dict[str, Any]], conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def val(key: str) -> float | None:
            return snapshot.get(key, {}).get("value")
        cfg = self.parameters.get("hard_flags", {})
        flags: list[dict[str, Any]] = []
        def add(code: str, metric: str, message: str, evidence: Any):
            flags.append({"code": code, "severity": "hard", "metric": metric, "message": message, "evidence": evidence})
        for name in CRITICAL_METRICS:
            item = snapshot[name]
            if item["status"] == "missing":
                continue
            if item["status"] == "stale":
                add("STALE_CRITICAL_METRIC", name, "Critical metric is stale", item["as_of"])
            if item["coverage"] < int(self.parameters.get("data_quality", {}).get("critical_sources_min", 2)):
                add("SINGLE_SOURCE_CRITICAL_METRIC", name, "Critical metric lacks independent source coverage", item["source"])
        for conflict in conflicts:
            field = str(conflict.get("field", ""))
            tolerance = float(self.parameters.get("data_quality", {}).get("conflict_tolerance_pct", 20))
            if field in CRITICAL_METRICS or field in {"market_cap", "avg_dollar_volume", "roic", "fcf_growth"}:
                if float(conflict.get("deviation_pct", 0) or 0) > tolerance:
                    add("CRITICAL_METRIC_CONFLICT", field, "Critical metric differs across sources beyond tolerance", conflict)
        cap = val("market_cap_usd")
        if cap is not None and cap < float(self.parameters.get("market_cap_min_usd", 2e9)):
            add("MARKET_CAP_BELOW_MINIMUM", "market_cap_usd", "Company is below the configured minimum market capitalization", cap)
        liquidity = val("avg_dollar_volume_usd")
        if liquidity is not None and liquidity < float(self.parameters.get("avg_dollar_volume_min_usd", 1e6)):
            add("DOLLAR_VOLUME_BELOW_MINIMUM", "avg_dollar_volume_usd", "Average dollar volume is below the configured minimum", liquidity)
        checks = [
            ("current_ratio", "current_ratio_below", lambda v, t: v < t, "LOW_CURRENT_RATIO"),
            ("interest_coverage", "interest_coverage_below", lambda v, t: v < t, "LOW_INTEREST_COVERAGE"),
            ("net_debt_ebitda", "net_debt_ebitda_above", lambda v, t: v > t, "HIGH_NET_DEBT_EBITDA"),
            ("fcf_runway_months", "negative_fcf_runway_months_below", lambda v, t: v < t, "LOW_FCF_RUNWAY"),
            ("dilution_yoy_pct", "dilution_yoy_above_pct", lambda v, t: v > t, "HIGH_DILUTION"),
            ("share_count_cagr_3y_pct", "share_count_cagr_3y_above_pct", lambda v, t: v > t, "HIGH_SHARE_COUNT_GROWTH"),
        ]
        for metric, key, predicate, code in checks:
            value, threshold = val(metric), cfg.get(key)
            if value is not None and threshold is not None and predicate(value, float(threshold)):
                add(code, metric, f"{metric} breached configured hard threshold", value)
        return flags

    @staticmethod
    def _components(snapshot: dict[str, dict[str, Any]]) -> dict[str, float]:
        def get(key: str, default: float = 0.0) -> float:
            item = snapshot.get(key, {})
            v = item.get("value") if item.get("status") in {"observed", "derived"} else None
            return float(v) if v is not None else default
        def scale(value: float, low: float, high: float) -> float:
            return round(max(0.0, min(100.0, (value - low) / (high - low) * 100)), 2)
        transition = sum((scale(get("revenue_cagr_3y_pct"), 0, 40), scale(get("eps_growth_pct"), 0, 40), scale(get("revenue_growth_pct"), 0, 40), scale(get("operating_margin_pct"), 0, 25))) / 4
        quality = sum((scale(get("roic_pct"), 0, 25), scale(get("gross_margin_pct"), 0, 70), scale(get("operating_margin_pct"), 0, 30), scale(get("fcf_conversion_pct"), 0, 100))) / 4
        reinvestment = sum((scale(get("rd_to_revenue_pct"), 0, 25), scale(get("capex_to_revenue_pct"), 0, 25), scale(get("roic_pct"), 0, 25), scale(get("fcf_growth_pct"), 0, 40))) / 4
        gap = get("expectation_gap_pct")
        expectation = 0.0 if snapshot["expectation_gap_pct"]["status"] != "observed" else round(max(0, min(100, 50 + gap)), 2)
        market = sum(score for key, score in [("relative_strength_12m_pct", scale(get("relative_strength_12m_pct"), -50, 50)), ("drawdown_pct", 100 - min(100, abs(get("drawdown_pct")))), ("volatility_90d_pct", 100 - min(100, get("volatility_90d_pct")))] if snapshot[key]["status"] == "observed") / max(1, sum(snapshot[key]["status"] == "observed" for key in ("relative_strength_12m_pct", "drawdown_pct", "volatility_90d_pct")))
        return {"economic_transition": round(transition, 2), "quality": round(quality, 2), "reinvestment": round(reinvestment, 2), "expectation_gap": expectation, "market_confirmation": round(market, 2)}

    @staticmethod
    def _number(value: Any) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value) if math.isfinite(value) else None
        if isinstance(value, str):
            normalized = value.strip().replace(",", "").replace("$", "").replace("%", "")
            try:
                number = float(normalized)
                return number if math.isfinite(number) else None
            except ValueError:
                return None
        return None

    @staticmethod
    def _is_stale(value: Any, max_days: int, now: str) -> bool:
        if not value:
            return False
        try:
            then = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            current = datetime.fromisoformat(now.replace("Z", "+00:00"))
            if then.tzinfo is None:
                then = then.replace(tzinfo=timezone.utc)
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            return (current - then).days > max_days
        except (TypeError, ValueError):
            return True


def build_research_intake(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic, versioned handoff from Discovery to Research."""
    config_json = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    missing = [name for name, metric in result["metrics_snapshot"].items() if metric["status"] in {"missing", "stale", "conflicted"}]
    flags = result["red_flags"]
    return {
        "ticker": result["ticker"], "strategy_id": result["strategy_id"],
        "strategy_version": result["strategy_version"], "discovery_profile": "multibaggers",
        "research_profile": "multibaggers", "as_of": result["as_of"],
        "config_hash": hashlib.sha256(config_json.encode()).hexdigest(),
        "metrics_snapshot": result["metrics_snapshot"], "component_scores": result["component_scores"],
        "discovery_score": result["discovery_score"], "research_priority": result["research_priority"],
        "discovery_type": result["discovery_type"], "reason_codes": result["reason_codes"],
        "red_flags": flags, "data_quality": result["data_quality"],
        "historical_windows": {name: item.get("period") for name, item in result["metrics_snapshot"].items()},
        "initial_hypotheses": [f"Assess whether evidence for {name} supports durable reinvestment and growth." for name in ("economic_transition", "quality", "reinvestment")],
        "research_questions": ["What observable mechanism can sustain growth?", "How does reinvestment translate into returns on capital?", "What expectations are embedded in the current valuation?", "Which evidence would falsify the thesis?", "What risks could impair solvency or dilute owners?"],
        "missing_evidence": missing, "invalidation_conditions": [f"Reassess if {flag['metric']} remains breached or worsens." for flag in flags] or ["Reassess on material deterioration in growth, returns, liquidity, dilution, or thesis evidence."],
        "priority_reason": "Evidence quality, coverage, freshness, component scores, and hard-gate outcomes; not probability or conviction.",
        "constraints": ["Do not invent missing facts.", "Cite each material claim to a source.", "Separate verified facts, inference, and unknowns.", "Research cannot approve an investment or set a position size."],
        "snapshot_hash": result["snapshot_hash"],
    }
