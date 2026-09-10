"""Strategy profiles used to route Discovery, Research and Portfolio policies."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml

@dataclass(frozen=True)
class StrategyProfile:
    strategy_id: str
    core: str
    sleeve: str
    thesis_type: str
    discovery_profile: str
    research_profile: str
    entry_policy: str
    enabled: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)

    @property
    def is_systematic(self) -> bool:
        return self.thesis_type == "SYSTEMATIC"

class StrategyCatalog:
    """Loads strategy policy without changing existing lifecycle states."""
    def __init__(self, config_path: str | Path = "idos-config/strategies.yml"):
        self.path = Path(config_path)
        self._profiles: dict[str, StrategyProfile] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._profiles = {"COMPOUNDER": self.default_compounder()}
            return
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        for strategy_id, data in (raw.get("strategies", {}) or {}).items():
            self._profiles[strategy_id] = StrategyProfile(
                strategy_id=strategy_id, core=data["core"], sleeve=data["sleeve"],
                thesis_type=data["thesis_type"], discovery_profile=data["discovery_profile"],
                research_profile=data["research_profile"], entry_policy=data["entry_policy"],
                enabled=bool(data.get("enabled", False)), parameters=data.get("parameters", {}) or {},
            )
        self._profiles.setdefault("COMPOUNDER", self.default_compounder())

    @staticmethod
    def default_compounder() -> StrategyProfile:
        return StrategyProfile("COMPOUNDER", "CORE_3_GROWTH", "HIGH_CONVICTION", "STRATEGIC", "compounder", "strategic", "VALUATION_ZONE", True)

    def get(self, strategy_id: str | None) -> StrategyProfile:
        return self._profiles.get((strategy_id or "COMPOUNDER").upper(), self.default_compounder())

    def list(self, enabled_only: bool = False) -> list[StrategyProfile]:
        values = list(self._profiles.values())
        return [p for p in values if p.enabled] if enabled_only else values

    def require(self, strategy_id: str) -> StrategyProfile:
        key = strategy_id.upper()
        if key not in self._profiles:
            raise ValueError(f"Unknown strategy_id: {strategy_id}")
        return self._profiles[key]
