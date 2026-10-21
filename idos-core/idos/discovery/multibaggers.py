"""Deterministic, evidence-aware discovery for the MULTIBAGGERS profile."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from math import isclose, isfinite, sqrt
from typing import Any

from idos.discovery.financial_evidence import reconcile_metric_observations


CRITICAL_METRICS = ("price_momentum_12m_pct", "drawdown_pct", "volatility_90d_pct")
# Discovery uses source-backed market evidence only. Financial fundamentals and
# ratios are gathered and evaluated during Research.
DISCOVERY_METRICS = CRITICAL_METRICS


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
        metric_observations = payload.get("metric_observations")
        if not isinstance(metric_observations, dict):
            merged_payload = payload.get("merged_data")
            metric_observations = (
                merged_payload.get("metric_observations", {})
                if isinstance(merged_payload, dict)
                else {}
            )
        if not isinstance(metric_observations, dict):
            metric_observations = {}
        metric_observations = dict(metric_observations)
        metric_observations.update(self._market_confirmation_observations(payload, ticker, now))
        snapshot = self._metric_snapshot(metric_observations, now)
        quality = self._quality(snapshot)
        critical_metrics = self._critical_metrics()
        flags = self._hard_flags(snapshot, critical_metrics)
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
        if quality["critical_coverage"] == 0:
            kind = "BLOCKED_DATA"
        elif flags or quality["critical_conflicts"] or quality["critical_stale"] or quality["critical_source_failures"]:
            kind = "BLOCKED_DATA"
        elif passed:
            kind = "RESEARCH_REQUIRED"
        else:
            kind = "WATCH"
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

    @staticmethod
    def _market_confirmation_observations(
        payload: dict[str, Any], ticker: str, observed_at: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """Derive auditable technical inputs from Yahoo daily price history."""
        merged = payload.get("merged_data") if isinstance(payload.get("merged_data"), dict) else payload
        if not isinstance(merged, dict):
            return {}
        raw_prices, raw_dates = merged.get("price_history"), merged.get("price_history_dates")
        if merged.get("price_history_basis") != "close_unadjusted":
            return {}
        if not isinstance(raw_prices, list) or not isinstance(raw_dates, list):
            return {}
        series: list[tuple[date, float]] = []
        for day, price in zip(raw_dates, raw_prices):
            if isinstance(price, bool):
                continue
            try:
                parsed_day, numeric_price = date.fromisoformat(str(day)[:10]), float(price)
            except (TypeError, ValueError):
                continue
            if isfinite(numeric_price) and numeric_price > 0:
                series.append((parsed_day, numeric_price))
        series.sort(key=lambda item: item[0])
        if len(series) < 91:
            return {}
        latest_day, latest_price = series[-1]
        derived: dict[str, float] = {}
        if len(series) >= 220 and (latest_day - series[0][0]).days >= 330:
            derived["price_momentum_12m_pct"] = (latest_price / series[0][1] - 1.0) * 100.0
        period_prices = [price for _, price in series[-252:]]
        peak = max(period_prices)
        derived["drawdown_pct"] = (peak - latest_price) / peak * 100.0
        returns = [current / prior - 1.0 for prior, current in zip(period_prices[-91:-1], period_prices[-90:])]
        if len(returns) == 90:
            mean_return = sum(returns) / len(returns)
            variance = sum((value - mean_return) ** 2 for value in returns) / len(returns)
            derived["volatility_90d_pct"] = sqrt(variance) * sqrt(252.0) * 100.0
        report_date = latest_day.isoformat()
        source_url = f"https://finance.yahoo.com/quote/{ticker.upper()}/history/"
        return {metric: [{
            "source_id": "yfinance", "value": value, "unit": "percent", "currency": None,
            "period": f"{metric}:{series[0][0].isoformat()}/{report_date}",
            "reported_at": report_date, "observed_at": observed_at, "source_url": source_url,
        }] for metric, value in derived.items()}

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
            "critical_metric_count": len(self._critical_metrics()),
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
        critical_metrics = set(self._critical_metrics())
        result: dict[str, dict[str, Any]] = {}
        for name in DISCOVERY_METRICS:
            expected_unit = "USD" if name.endswith("_usd") else "percent" if name.endswith("_pct") else "months" if name.endswith("_months") else "ratio"
            evidence = reconcile_metric_observations(
                metric_observations.get(name),
                expected_unit=expected_unit,
                expected_currency="USD" if expected_unit == "USD" else None,
                minimum_sources=(
                    int(quality_cfg.get("critical_sources_min", 2))
                    if name in critical_metrics else 1
                ),
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
        critical_metrics = self._critical_metrics()
        critical = [snapshot[name] for name in critical_metrics]
        covered = sum(item["status"] in {"observed", "derived"} for item in critical)
        min_sources = int(self.parameters["data_quality"]["critical_sources_min"])
        source_failures = sum(item["coverage"] < min_sources for item in critical)
        stale = sum(item["status"] == "stale" for item in critical)
        critical_conflicts = sorted(name for name in critical_metrics if snapshot[name]["status"] == "conflicted")
        coverage = covered / len(critical)
        return {
            "critical_metric_count": len(critical), "critical_metrics_covered": covered,
            "critical_coverage": round(coverage, 4), "critical_source_failures": source_failures,
            "critical_conflicts": critical_conflicts, "critical_stale": stale,
            "coverage_factor": round(coverage, 4), "freshness_factor": round(1 - stale / len(critical), 4),
        }

    def _critical_metrics(self) -> tuple[str, ...]:
        configured = self.parameters.get("data_quality", {}).get("critical_metrics", CRITICAL_METRICS)
        if (
            not isinstance(configured, (list, tuple))
            or not configured
            or any(not isinstance(name, str) or name not in DISCOVERY_METRICS for name in configured)
            or len(set(configured)) != len(configured)
        ):
            raise ValueError("MULTIBAGGERS critical_metrics must be unique configured discovery metrics")
        return tuple(configured)

    def _hard_flags(
        self, snapshot: dict[str, dict[str, Any]], critical_metrics: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        flags: list[dict[str, Any]] = []
        def add(code: str, metric: str, message: str, evidence: Any):
            flags.append({"code": code, "severity": "hard", "metric": metric, "message": message, "evidence": evidence})
        for name in critical_metrics or self._critical_metrics():
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
    profile_parameters = config.get("parameters", {})
    research_parameters = profile_parameters.get("research", {}) if isinstance(profile_parameters, dict) else {}
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
        "research_requirements": {
            "required_analysis": list(research_parameters.get("required_analysis", [])),
            "ratios_to_review": list(research_parameters.get("ratios_to_review", [])),
            "ratio_definitions": dict(research_parameters.get("ratio_definitions", {})),
            "ratio_units": dict(research_parameters.get("ratio_units", {})),
            "ratio_input_fields": dict(research_parameters.get("ratio_input_fields", {})),
            "risk_review_thresholds": dict(research_parameters.get("risk_review_thresholds", {})),
            "scenario_schema_version": "bear_base_bull_v1",
        },
        "historical_windows": {name: item.get("period") for name, item in result["metrics_snapshot"].items()},
        "initial_hypotheses": [f"Assess whether evidence for {name} supports durable reinvestment and growth." for name in ("economic_transition", "quality", "reinvestment")],
        "research_questions": ["What observable mechanism can sustain growth?", "How does reinvestment translate into returns on capital?", "What expectations are embedded in the current valuation?", "Which evidence would falsify the thesis?", "What risks could impair solvency or dilute owners?"],
        "missing_evidence": missing, "invalidation_conditions": [f"Reassess if {flag['metric']} remains breached or worsens." for flag in flags] or ["Reassess on material deterioration in growth, returns, liquidity, dilution, or thesis evidence."],
        "priority_reason": "Evidence quality, coverage, freshness, component scores, and hard-gate outcomes; not probability or conviction.",
        "constraints": ["Do not invent missing facts.", "Cite each material claim to a source.", "Separate verified facts, inference, and unknowns.", "Research cannot approve an investment or set a position size."],
        "snapshot_hash": result["snapshot_hash"],
    }
