"""Strategy-scoped runner for the curated MULTIBAGGERS universe."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

from idos.data.sqlite import SQLiteStore
from idos.discovery.multibaggers import MultibaggersDiscoveryEngine, build_research_intake
from idos.discovery.multibaggers_store import MultibaggersStore
from idos.discovery.operability import OperabilityFilter
from idos.models.conviction import Conviction
from idos.models.enums import OpportunityStatus
from idos.models.journal import Opportunity
from idos.strategy.catalog import StrategyCatalog


class MultibaggersPipeline:
    """Runs Discovery only when both the strategy and curated universe are enabled."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.root = Path(self.config.get("base_path", Path.cwd())).resolve()
        config_dir = Path(self.config.get("config_path", self.root / "idos-config"))
        if not config_dir.is_absolute():
            config_dir = self.root / config_dir
        self.profile = StrategyCatalog(config_dir / "strategies.yml").require("MULTIBAGGERS")
        if not self.profile.enabled:
            raise ValueError("Strategy is disabled: MULTIBAGGERS")
        universe_path = Path(self.profile.parameters.get("universe_path", config_dir / "universe/multibaggers.yml"))
        if not universe_path.is_absolute():
            universe_path = self.root / universe_path
        self.universe_path = universe_path
        operable_path = Path(self.config.get("operable_path", config_dir / "universe/operable.yml"))
        if not operable_path.is_absolute():
            operable_path = self.root / operable_path
        self.operability = OperabilityFilter(str(operable_path))
        self.journal_root = Path(self.config.get("journal_path", self.root / "idos-journal"))
        if not self.journal_root.is_absolute():
            self.journal_root = self.root / self.journal_root
        self.db_path = self.root / "idos.db"

    def run(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        universe = yaml.safe_load(self.universe_path.read_text(encoding="utf-8")) or {}
        if universe.get("strategy_id") != "MULTIBAGGERS":
            raise ValueError("Curated universe strategy_id must be MULTIBAGGERS")
        if not universe.get("enabled", False):
            raise ValueError("Curated MULTIBAGGERS universe is disabled")
        curated_tickers = sorted({str(t).strip().upper() for t in universe.get("tickers", []) if str(t).strip()})
        tickers, excluded_tickers = self.operability.filter_tickers(curated_tickers)
        if not tickers:
            return {"status": "no_eligible_tickers", "strategy_id": "MULTIBAGGERS", "processed": 0, "created": 0,
                    "excluded_tickers": excluded_tickers, "message": "No curated tickers are present in the operable allowlist"}

        from idos.workers.data.cache import DataCache
        cache = self.config.get("data_cache") or DataCache(str(self.db_path))
        engine = MultibaggersDiscoveryEngine(self.profile.parameters, self.profile.strategy_version)
        discovery_store = MultibaggersStore(self.db_path)
        sqlite = SQLiteStore(self.db_path)
        output = {"status": "completed", "strategy_id": "MULTIBAGGERS", "processed": 0, "passed": 0, "blocked": 0,
                  "created": 0, "existing": 0, "excluded_tickers": excluded_tickers, "results": []}
        for ticker in tickers:
            payload = cache.get(f"merged:{ticker}")
            if payload is None and self.config.get("refresh_missing", True):
                factory = self.config.get("refresh_worker_factory")
                worker = factory(self.config) if factory else __import__("idos.workers.data.refresh_worker", fromlist=["DataRefreshWorker"]).DataRefreshWorker(self.config)
                worker.execute({"tickers": [ticker]})
                payload = cache.get(f"merged:{ticker}")
            payload = payload or {"merged_data": {}, "metric_sources": {}, "conflicts": [], "as_of": None}
            result = engine.evaluate(ticker, payload, payload.get("as_of"))
            result_data = result.to_dict()
            intake = build_research_intake(result_data, {"parameters": self.profile.parameters, "universe": universe}) if result.passed else {}
            discovery_store.save(result_data, intake)
            output["processed"] += 1
            output["passed" if result.passed else "blocked"] += 1
            output["results"].append({"ticker": ticker, "passed": result.passed, "score": result.discovery_score, "priority": result.research_priority, "discovery_type": result.discovery_type, "reason_codes": result.reason_codes, "snapshot_hash": result.snapshot_hash})
            if not result.passed:
                continue

            from idos.data.journal import JournalRepository
            journal = JournalRepository(self.journal_root)
            existing = next((o for o in journal.list_all_opportunities() if o.get("ticker", "").upper() == ticker and o.get("strategy_id", "COMPOUNDER").upper() == "MULTIBAGGERS"), None)
            if existing:
                opp_id = existing["id"]
                output["existing"] += 1
            else:
                opp_id = f"OPP-MB-{ticker}"
                opp = Opportunity(id=opp_id, ticker=ticker, status=OpportunityStatus.SCREENED, strategy_id="MULTIBAGGERS", strategy_version=self.profile.strategy_version, core=self.profile.core, sleeve=self.profile.sleeve, thesis_type=self.profile.thesis_type, entry_policy=self.profile.entry_policy, research_profile=self.profile.research_profile, origin="multibaggers_discovery", conviction=Conviction())
                opp_data = opp.model_dump(mode="json")
                opp_data.update({"discovery_score": result.discovery_score, "research_priority": result.research_priority, "discovery_type": result.discovery_type, "snapshot_hash": result.snapshot_hash, "position_limit_pct": float(self.profile.parameters.get("position_limit_pct", 1.0)), "risk_limits": {"max_position_pct": float(self.profile.parameters.get("position_limit_pct", 1.0))}})
                journal.save_opportunity(ticker, opp_data)
                sqlite.save_opportunity(opp_data)
                output["created"] += 1
            opp_path = journal.opportunity_path(ticker, opp_id)
            opp_path.mkdir(parents=True, exist_ok=True)
            (opp_path / "discovery_snapshot.yml").write_text(yaml.safe_dump(result_data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            (opp_path / "research_intake.yml").write_text(yaml.safe_dump(intake, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return output
