from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def load_config(path: str | Path) -> dict[str, Any] | None:
    import yaml
    p = Path(path)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


_DEFAULT_RULES = {
    "RULE-001": {"min_score": 70},
    "RULE-002": {"min_price_margin_pct": 20},
    "RULE-003": {"min_score": 50},
    "RULE-004": {"min_score": 50},
    "RULE-005": {"min_score": 65},
    "RULE-006": {"max_position_pct": 3.0},
    "RULE-007": {"max_sector_exposure_pct": 25.0},
    "RULE-008": {"min_ratio": 3.0},
    "RULE-009": {"max_positions": 10},
}

_DEFAULT_CONVICTION = {
    "engine_weights": {
        "BusinessAssessmentEngine": 0.30,
        "ValuationAssessmentEngine": 0.25,
        "RecoveryAssessmentEngine": 0.20,
        "RiskAssessmentEngine": 0.15,
        "PortfolioAssessmentEngine": 0.10,
    },
    "approval_threshold": 70,
    "block_threshold": 50,
    "high_confidence_count": 3,
    "track_event_diff": 5,
}

_DEFAULT_SIZING = {
    "max_position_pct": 3.0,
    "min_asymmetry": 3.0,
    "tranches": [
        {"number": 1, "pct_of_portfolio": 1.0, "condition": "Initial entry"},
        {"number": 2, "pct_of_portfolio": 1.0, "condition": "First quarterly results align with thesis"},
        {"number": 3, "pct_of_portfolio": 1.0, "condition": "Catalyst confirmation or technical support"},
    ],
}

_DEFAULT_PORTFOLIO = {
    "bankroll": 100000,
    "max_position_pct": 3.0,
    "max_total_weight_pct": 20.0,
    "margin_of_safety": 30.0,
    "fee_pct": 0.1,
    "min_entry_score": 45,
    "max_sector_exposure_pct": 25.0,
    "max_positions": 10,
    "proposal_default_weight_pct": 3.0,
    "proposal_horizon": "12-36 months",
}


@dataclass
class Settings:
    config_path: Path
    rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    conviction: dict[str, Any] = field(default_factory=dict)
    sizing: dict[str, Any] = field(default_factory=dict)
    portfolio: dict[str, Any] = field(default_factory=dict)
    scoring: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    # --- Accessores por regla ---
    def rule_params(self, rule_id: str) -> dict[str, Any]:
        return self.rules.get(rule_id, {})

    def rule_min_score(self, rule_id: str, default: int) -> int:
        return int(self.rules.get(rule_id, {}).get("min_score", default))

    def rule_price_margin(self, rule_id: str, default: float) -> float:
        return float(self.rules.get(rule_id, {}).get("min_price_margin_pct", default))

    def rule_min_ratio(self, rule_id: str, default: float) -> float:
        return float(self.rules.get(rule_id, {}).get("min_ratio", default))

    def conviction_weights(self) -> dict[str, float]:
        return self.conviction.get("engine_weights", {})

    @property
    def max_position_pct(self) -> float:
        return float(self.portfolio.get("max_position_pct", 3.0))

    @property
    def max_sector_exposure_pct(self) -> float:
        return float(self.rules.get("RULE-007", {}).get("max_sector_exposure_pct",
                        self.portfolio.get("max_sector_exposure_pct", 25.0)))

    @property
    def max_positions(self) -> int:
        return int(self.rules.get("RULE-009", {}).get("max_positions",
                     self.portfolio.get("max_positions", 10)))

    @property
    def default_weight_pct(self) -> float:
        return float(self.portfolio.get("proposal_default_weight_pct", 3.0))


def load_settings(config_dir: str | Path) -> Settings:
    cfg_path = Path(config_dir)
    hmf = load_config(cfg_path / "hmf.yml") or {}
    portfolio = load_config(cfg_path / "portfolio.yml") or {}
    scoring = load_config(cfg_path / "scoring.yml") or {}
    risk = load_config(cfg_path / "risk.yml") or {}

    # Reglas: defaults actualizados con hmf.yml
    rules: dict[str, dict[str, Any]] = {}
    for rid, params in _DEFAULT_RULES.items():
        rules[rid] = dict(params)
    for rid, params in (hmf.get("rules", {}) or {}).items():
        rules[rid] = dict(params)

    conviction = _DEFAULT_CONVICTION.copy()
    if isinstance(hmf.get("conviction"), dict):
        conviction = _merge(conviction, hmf["conviction"])

    sizing = _DEFAULT_SIZING.copy()
    if isinstance(hmf.get("sizing"), dict):
        sizing = _merge(sizing, hmf["sizing"])

    port = _DEFAULT_PORTFOLIO.copy()
    if isinstance(portfolio, dict):
        port = _merge(port, portfolio)
    if isinstance(sizing, dict) and "max_position_pct" in sizing:
        port["max_position_pct"] = sizing["max_position_pct"]
    for rid in ("RULE-006", "RULE-007", "RULE-009"):
        params = rules.get(rid, {})
        if rid == "RULE-006" and "max_position_pct" in params:
            port["max_position_pct"] = params["max_position_pct"]
        if rid == "RULE-007" and "max_sector_exposure_pct" in params:
            port["max_sector_exposure_pct"] = params["max_sector_exposure_pct"]
        if rid == "RULE-009" and "max_positions" in params:
            port["max_positions"] = params["max_positions"]
    if isinstance(hmf.get("proposal"), dict):
        port["proposal_default_weight_pct"] = hmf["proposal"].get("default_weight_pct", port["proposal_default_weight_pct"])
        port["proposal_horizon"] = hmf["proposal"].get("horizon", port["proposal_horizon"])

    return Settings(
        config_path=cfg_path,
        rules=rules,
        conviction=conviction,
        sizing=sizing,
        portfolio=port,
        scoring=scoring,
        risk=risk,
        raw={"hmf": hmf, "portfolio": portfolio, "scoring": scoring, "risk": risk},
    )