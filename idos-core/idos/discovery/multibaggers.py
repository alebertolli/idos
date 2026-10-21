"""Deterministic, evidence-aware discovery for the MULTIBAGGERS profile."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from math import isclose, isfinite
from typing import Any

from idos.discovery.financial_evidence import reconcile_metric_observations


CRITICAL_METRICS = (
    "revenue_cagr_3y_pct", "eps_growth_pct", "fcf_growth_pct", "roic_pct",
    "operating_margin_pct", "fcf_conversion_pct", "net_debt_ebitda",
    "dilution_yoy_pct", "market_cap_usd", "avg_dollar_volume_usd",
    "relative_strength_12m_pct", "expectation_gap_pct",
)
DISCOVERY_METRICS = CRITICAL_METRICS + (
    "current_ratio", "interest_coverage", "fcf_runway_months", "share_count_cagr_3y_pct",
    "gross_margin_pct", "revenue_growth_pct", "rd_to_revenue_pct", "capex_to_revenue_pct",
    "drawdown_pct", "volatility_90d_pct",
)


@dataclass(frozen=True)
class DiscoveryResult:
    ticker: str
    strategy_id: str
    strategy_version: str
    passed: bool
    discovery_score: float | None
    research_priority: float | None
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
        metric_observations = payload.get("metric_observations", {}) or {}
        if not isinstance(metric_observations, dict):
            metric_observations = {}
        snapshot = self._metric_snapshot(metric_observations, now)
        quality = self._quality(snapshot)
        flags = self._hard_flags(snapshot)
        minimum_coverage = float(self.parameters["data_quality"]["critical_coverage_min"])
        if quality["critical_coverage"] < minimum_coverage:
            flags.append({"code": "CRITICAL_COVERAGE_BELOW_MINIMUM", "severity": "hard", "metric": "critical_coverage", "message": "Critical metric coverage is below policy", "evidence": quality["critical_coverage"]})
        components = self._components(snapshot)
        weights = self.parameters.get("weights", {})
        if (
            not isinstance(weights, dict)
            or set(weights) != set(components)
            or any(not isinstance(weight, (int, float)) or not isfinite(float(weight)) or weight < 0 for weight in weights.values())
            or not isclose(sum(float(weight) for weight in weights.values()), 1.0, abs_tol=1e-9)
        ):
            raise ValueError("MULTIBAGGERS component weights must be non-negative, complete and sum to 1")
        required_components = set(weights)
        missing_components = sorted(
            name for name in required_components if components.get(name) is None
        )
        score = (
            round(sum(float(components[name]) * float(weights[name]) for name in required_components), 2)
            if not missing_components
            else None
        )
        reasons = [f"HARD_FLAG:{flag['code']}" for flag in flags]
        if quality["critical_coverage"] < minimum_coverage:
            reasons.append("DATA_COVERAGE_BELOW_MINIMUM")
        if quality["critical_source_failures"]:
            reasons.append("CRITICAL_METRIC_SOURCE_COVERAGE_FAILED")
        if quality["critical_conflicts"]:
            reasons.append("CRITICAL_METRIC_CONFLICT")
        if quality["critical_stale"]:
            reasons.append("CRITICAL_METRIC_STALE")
        if missing_components:
            reasons.append("SCORING_INPUT_MISSING")
        threshold = float(self.parameters["discovery_threshold"])
        if not isfinite(threshold) or not 0 <= threshold <= 100:
            raise ValueError("MULTIBAGGERS discovery_threshold must be between 0 and 100")
        passed = not reasons and score is not None and score >= threshold
        if score is not None and score < threshold:
            reasons.append("DISCOVERY_SCORE_BELOW_THRESHOLD")
        classification = self.parameters.get("classification")
        classification_keys = {
            "fundamental_transition_min", "fundamental_quality_min",
            "fundamental_reinvestment_min", "early_transition_min",
            "early_market_confirmation_max", "market_confirmed_transition_min",
            "market_confirmed_min",
        }
        if not isinstance(classification, dict) or not classification_keys.issubset(classification):
            raise ValueError("MULTIBAGGERS classification thresholds must be configured")
        classification = {key: float(classification[key]) for key in classification_keys}
        if any(not isfinite(value) or not 0 <= value <= 100 for value in classification.values()):
            raise ValueError("MULTIBAGGERS classification thresholds must be between 0 and 100")
        transition = components.get("economic_transition")
        quality_score = components.get("quality")
        reinvestment = components.get("reinvestment")
        market = components.get("market_confirmation")
        if quality["critical_coverage"] == 0:
            kind = "BLOCKED_DATA"
        elif flags or quality["critical_conflicts"] or quality["critical_stale"] or quality["critical_source_failures"]:
            kind = "BLOCKED_DATA"
        elif all(value is not None for value in (transition, quality_score, reinvestment)) and transition >= classification["fundamental_transition_min"] and quality_score >= classification["fundamental_quality_min"] and reinvestment >= classification["fundamental_reinvestment_min"]:
            kind = "FUNDAMENTAL_COMPOUNDING"
        elif transition is not None and market is not None and transition >= classification["early_transition_min"] and market < classification["early_market_confirmation_max"]:
            kind = "EARLY_TRANSITION"
        elif transition is not None and market is not None and transition >= classification["market_confirmed_transition_min"] and market >= classification["market_confirmed_min"]:
            kind = "MARKET_CONFIRMED_GROWTH"
        elif snapshot.get("expectation_gap_pct", {}).get("value") is not None:
            kind = "EXPECTATION_GAP"
        else:
            kind = "RESEARCH_REQUIRED"
        priority = (
            round(score * quality["coverage_factor"] * quality["freshness_factor"], 2)
            if score is not None
            else None
        )
        body = {
            "ticker": ticker.upper(), "strategy_id": "MULTIBAGGERS", "strategy_version": self.strategy_version,
            "passed": passed, "discovery_score": score, "research_priority": priority,
            "discovery_type": kind, "component_scores": components, "metrics_snapshot": snapshot,
            "red_flags": flags, "data_quality": quality, "reason_codes": reasons, "as_of": now,
        }
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        return DiscoveryResult(**body, snapshot_hash=digest)

    def blocked_by_global_market_gate(
        self, ticker: str, eligibility: dict[str, Any], as_of: str | None = None,
    ) -> DiscoveryResult:
        """Stop before strategy scoring when shared market eligibility fails."""
        reasons = sorted({str(code) for code in eligibility.get("reason_codes", []) if code})
        flags = [
            {
                "code": code,
                "severity": "hard",
                "metric": "global_market_eligibility",
                "message": code.replace("_", " ").lower(),
                "evidence": eligibility,
            }
            for code in reasons
        ]
        now = as_of or datetime.now(timezone.utc).isoformat()
        quality = {
            "status": "not_evaluated",
            "critical_metric_count": len(CRITICAL_METRICS),
            "critical_metrics_covered": 0,
            "critical_coverage": 0.0,
            "critical_source_failures": [],
            "critical_conflicts": [],
            "critical_stale": [],
            "coverage_factor": 0.0,
            "freshness_factor": 0.0,
            "global_market_eligibility": eligibility,
        }
        body = {
            "ticker": ticker.upper(),
            "strategy_id": "MULTIBAGGERS",
            "strategy_version": self.strategy_version,
            "passed": False,
            "discovery_score": None,
            "research_priority": None,
            "discovery_type": "BLOCKED_DATA",
            "component_scores": {},
            "metrics_snapshot": {},
            "red_flags": flags,
            "data_quality": quality,
            "reason_codes": reasons,
            "as_of": now,
        }
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        return DiscoveryResult(**body, snapshot_hash=digest)

    def _metric_snapshot(self, metric_observations: dict[str, Any], now: str) -> dict[str, dict[str, Any]]:
        quality_cfg = self.parameters.get("data_quality", {})
        stale_after = int(quality_cfg["stale_after_days"])
        result: dict[str, dict[str, Any]] = {}
        for name in DISCOVERY_METRICS:
            expected_unit = "USD" if name.endswith("_usd") else "percent" if name.endswith("_pct") else "months" if name.endswith("_months") else "ratio"
            evidence = reconcile_metric_observations(
                metric_observations.get(name),
                expected_unit=expected_unit,
                expected_currency="USD" if expected_unit == "USD" else None,
                minimum_sources=int(quality_cfg.get("critical_sources_min", 2)),
                conflict_tolerance_pct=float(quality_cfg["conflict_tolerance_pct"]),
                stale_after_days=stale_after,
                now=now,
            )
            result[name] = {
                **evidence,
                "as_of": max(
                    (
                        reported_at
                        for obs in evidence["source_evidence"]
                        if isinstance(obs, dict)
                        and isinstance((reported_at := obs.get("reported_at")), str)
                        and reported_at
                    ),
                    default=None,
                ),
            }
        return result

    def _quality(self, snapshot: dict[str, dict[str, Any]]) -> dict[str, Any]:
        critical = [snapshot[name] for name in CRITICAL_METRICS]
        covered = sum(item["status"] in {"observed", "derived"} for item in critical)
        min_sources = int(self.parameters["data_quality"]["critical_sources_min"])
        source_failures = sum(item["coverage"] < min_sources for item in critical)
        stale = sum(item["status"] == "stale" for item in critical)
        critical_conflicts = sorted(name for name in CRITICAL_METRICS if snapshot[name]["status"] == "conflicted")
        coverage = covered / len(critical)
        return {
            "critical_metric_count": len(critical), "critical_metrics_covered": covered,
            "critical_coverage": round(coverage, 4), "critical_source_failures": source_failures,
            "critical_conflicts": critical_conflicts, "critical_stale": stale,
            "coverage_factor": round(coverage, 4), "freshness_factor": round(1 - stale / len(critical), 4),
        }

    def _hard_flags(self, snapshot: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        def val(key: str) -> float | None:
            return snapshot.get(key, {}).get("value")
        cfg = self.parameters.get("hard_flags", {})
        flags: list[dict[str, Any]] = []
        def add(code: str, metric: str, message: str, evidence: Any):
            flags.append({"code": code, "severity": "hard", "metric": metric, "message": message, "evidence": evidence})
        for name in CRITICAL_METRICS:
            item = snapshot[name]
            if item["status"] == "missing":
                add("MISSING_CRITICAL_METRIC", name, "Critical metric is missing", None)
            if item["status"] == "stale":
                add("STALE_CRITICAL_METRIC", name, "Critical metric is stale", item["as_of"])
            evidence_flags = {
                "incomplete": "INCOMPLETE_CRITICAL_EVIDENCE",
                "insufficient_sources": "INSUFFICIENT_CRITICAL_SOURCES",
                "incompatible_period": "INCOMPATIBLE_CRITICAL_PERIOD",
                "incompatible_currency": "INCOMPATIBLE_CRITICAL_CURRENCY",
                "conflicted": "CRITICAL_METRIC_CONFLICT",
            }
            evidence_flag = evidence_flags.get(item["status"])
            if evidence_flag:
                add(evidence_flag, name, "Critical metric evidence does not satisfy the source contract", item.get("source_evidence", []))
            if item["coverage"] < int(self.parameters["data_quality"]["critical_sources_min"]):
                code = "SINGLE_SOURCE_CRITICAL_METRIC" if item["coverage"] == 1 else "INSUFFICIENT_CRITICAL_SOURCES"
                add(code, name, "Critical metric lacks independent source coverage", item["source"])
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

    def _components(self, snapshot: dict[str, dict[str, Any]]) -> dict[str, float | None]:
        scoring = self.parameters.get("scoring")
        if not isinstance(scoring, dict) or scoring.get("method") != "absolute_linear_clamped":
            raise ValueError("MULTIBAGGERS requires a configured absolute scoring policy")
        components = scoring.get("components")
        if not isinstance(components, dict):
            raise ValueError("MULTIBAGGERS scoring components must be configured")

        result: dict[str, float | None] = {}
        for component_name, component_cfg in components.items():
            inputs = component_cfg.get("inputs") if isinstance(component_cfg, dict) else None
            if not isinstance(inputs, list) or not inputs:
                raise ValueError(f"Scoring component {component_name!r} needs configured inputs")
            normalized: list[float] = []
            for rule in inputs:
                if not isinstance(rule, dict):
                    raise ValueError(f"Scoring input for {component_name!r} must be a mapping")
                metric = rule.get("metric")
                low, high, direction = rule.get("min"), rule.get("max"), rule.get("direction")
                if (
                    not isinstance(metric, str)
                    or not isinstance(low, (int, float))
                    or not isinstance(high, (int, float))
                    or not isfinite(float(low))
                    or not isfinite(float(high))
                    or low >= high
                    or direction not in {"higher", "lower"}
                ):
                    raise ValueError(f"Invalid absolute scoring range for {component_name!r}")
                observation = snapshot.get(metric, {})
                value = observation.get("value")
                if observation.get("status") not in {"observed", "derived"} or not isinstance(value, (int, float)) or not isfinite(float(value)):
                    continue
                ratio = (float(value) - float(low)) / (float(high) - float(low))
                if direction == "lower":
                    ratio = 1.0 - ratio
                normalized.append(round(max(0.0, min(100.0, ratio * 100.0)), 2))
            result[component_name] = round(sum(normalized) / len(inputs), 2) if len(normalized) == len(inputs) else None
        return result

def build_research_intake(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic, versioned handoff from Discovery to Research."""
    config_json = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    missing = [name for name, metric in result["metrics_snapshot"].items() if metric["status"] not in {"observed", "derived"}]
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

