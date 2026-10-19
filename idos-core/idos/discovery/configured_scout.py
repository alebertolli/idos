"""Profile-owned screening predicates; compliance is not investment conviction."""
from pathlib import Path
import math

from idos.discovery.scout import ScoutEngine, ScoutResult
from idos.market.liquidity import MarketDataSettings
from idos.strategy.catalog import StrategyCatalog
from idos.workers.data.refresh_worker import DataRefreshWorker


def resolve_config_directory(config_path: str | Path) -> Path:
    """Resolve config paths from the current directory or the source checkout."""
    path = Path(config_path)
    if path.is_absolute() or path.exists():
        return path
    checkout_config = Path(__file__).resolve().parents[3] / path
    return checkout_config if checkout_config.exists() else path


class ConfiguredScoutEngine(ScoutEngine):
    def __init__(self, policy: dict, settings: MarketDataSettings, supported_types: list[str]):
        super().__init__(market_cap_min_usd=settings.market_cap_min_usd,
                         avg_dollar_volume_min_usd=settings.avg_dollar_volume_min_usd)
        self.policy = policy
        self.supported_types = supported_types
        filters = policy.get("filters")
        if not policy.get("version") or not isinstance(filters, list) or not filters:
            raise ValueError("Scout requires a versioned, nonempty filter policy")
        metrics = []
        for rule in filters:
            if (not isinstance(rule, dict) or not isinstance(rule.get("metric"), str)
                    or rule.get("operator") != "gt" or self.number(rule.get("value")) is None):
                raise ValueError("Invalid Scout predicate: expected metric, gt and finite value")
            metrics.append(rule["metric"])
        if len(metrics) != len(set(metrics)) or not supported_types:
            raise ValueError("Scout requires unique metrics and supported asset types")

    @staticmethod
    def number(value):
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            return None
        return float(value) if math.isfinite(value) else None

    def scan(self, ticker: str, data: dict) -> ScoutResult:
        metrics = data.get("metrics", {})
        asset_type = metrics.get("asset_type")
        missing, failed, details = [], [], {}
        observed = {}
        for rule in self.policy["filters"]:
            key = rule["metric"]
            value = self.number(metrics.get(key))
            observed[key] = value
            observations = (metrics.get("financial_observations") or {}).get(key, {}).get("values", {})
            outcomes = {v > rule["value"] for v in observations.values() if self.number(v) is not None}
            if len(outcomes) > 1:
                value = None  # Conflicting evidence cannot promote an opportunity.
            details[key] = None if value is None else (100 if value > rule["value"] else 0)
            if value is None:
                missing.append(key)
            elif value <= rule["value"]:
                failed.append(key)
        gates = {"avg_dollar_volume_usd": self.avg_dollar_volume_min_usd}
        if asset_type != "etf":
            gates["size_metric_usd"] = self.market_cap_min_usd
        for key, minimum in gates.items():
            value = self.number(metrics.get(key))
            if value is None or value <= 0:
                missing.append(key)
            elif value < minimum:
                failed.append(key)
        supported = asset_type in self.supported_types
        details["investability"] = 100 if supported and not any(k in missing + failed for k in gates) else 0
        status = "PENDING_DATA" if missing else "PASSED" if not failed and supported else "REJECTED"
        labels = {rule["metric"]: rule.get("label", rule["metric"])
                  for rule in self.policy["filters"]}
        labels.update({"avg_dollar_volume_usd": "liquidez promedio en USD",
                       "size_metric_usd": "capitalización en USD"})
        reasons = []
        if missing:
            reasons.append("Datos pendientes: " + ", ".join(labels.get(key, key) for key in missing))
        if failed:
            reasons.append("No cumple: " + ", ".join(labels.get(key, key) for key in failed))
        if not supported:
            reasons.append("Tipo de activo no habilitado en esta estrategia")
        result = ScoutResult(ticker=ticker.upper(), score=100 if status == "PASSED" else 0,
                             passed=status == "PASSED", details=details,
                             reason="; ".join(reasons) or "All configured filters passed; Research required",
                             discovery_type="FUNDAMENTAL_SCREEN", flags=[status])
        result.status = status
        result.missing_metrics = missing
        result.policy_version = self.policy["version"]
        result.observed_metrics = observed
        result.filter_results = {rule["metric"]: details[rule["metric"]]
                                 for rule in self.policy["filters"]}
        return result

    def scan_market_data(self, ticker: str, data: dict) -> ScoutResult:
        metrics = dict(data.get("metrics", data))
        if not DataRefreshWorker._has_normalized_market_gates(data):
            metrics["size_metric_usd"] = metrics["avg_dollar_volume_usd"] = None
        return self.scan(ticker, {"metrics": metrics})


def configured_scout(config_path: str | Path = "idos-config", strategy_id: str = "COMPOUNDER") -> ConfiguredScoutEngine:
    path = resolve_config_directory(config_path)
    profile = StrategyCatalog(path / "strategies.yml").require(strategy_id)
    if not profile.enabled:
        raise ValueError(f"Strategy is disabled: {strategy_id}")
    return ConfiguredScoutEngine(profile.parameters.get("scout", {}), MarketDataSettings.load(path),
                                 profile.parameters.get("supported_asset_types", []))
