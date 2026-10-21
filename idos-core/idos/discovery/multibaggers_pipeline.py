"""Strategy-scoped runner over the shared operable universe."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
import yaml

from idos.data.sqlite import SQLiteStore
from idos.discovery.multibaggers import MultibaggersDiscoveryEngine, build_research_intake
from idos.discovery.multibaggers_store import MultibaggersStore
from idos.discovery.operability import OperabilityFilter
from idos.market.liquidity import MarketDataSettings, evaluate_global_market_eligibility
from idos.models.conviction import Conviction
from idos.models.enums import OpportunityStatus
from idos.models.journal import Opportunity
from idos.strategy.catalog import StrategyCatalog


class MultibaggersPipeline:
    """Runs MULTIBAGGERS over operable symbols supported by its profile."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.root = Path(self.config.get("base_path", Path.cwd())).resolve()
        config_dir = Path(self.config.get("config_path", self.root / "idos-config"))
        if not config_dir.is_absolute():
            config_dir = self.root / config_dir
        self.profile = StrategyCatalog(config_dir / "strategies.yml").require("MULTIBAGGERS")
        if not self.profile.enabled:
            raise ValueError("Strategy is disabled: MULTIBAGGERS")
        operable_path = Path(self.config.get("operable_path", config_dir / "universe/operable.yml"))
        if not operable_path.is_absolute():
            operable_path = self.root / operable_path
        self.operability = OperabilityFilter(str(operable_path))
        self.market_data_settings = MarketDataSettings.load(str(config_dir))
        self.journal_root = Path(self.config.get("journal_path", self.root / "idos-journal"))
        if not self.journal_root.is_absolute():
            self.journal_root = self.root / self.journal_root
        self.db_path = self.root / "idos.db"
        self.candidate_source = "idos-config/universe/operable.yml"

    def run(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = context or {}
        requested = context.get("candidate_tickers")
        tickers = (
            self.operability.validate_selection(requested)
            if requested is not None
            else sorted(self.operability.tickers)
        )
        entries = {entry["ticker"]: entry for entry in self.operability.list()}
        supported_types = {
            str(value).strip().lower()
            for value in self.profile.parameters.get("supported_asset_types", ["us_equity"])
            if str(value).strip()
        }
        excluded_tickers = sorted(
            ticker for ticker in tickers
            if str(entries.get(ticker, {}).get("type", "us_equity")).strip().lower() not in supported_types
        )
        excluded_set = set(excluded_tickers)
        tickers = [ticker for ticker in tickers if ticker not in excluded_set]
        if not tickers:
            return {"status": "no_eligible_tickers", "strategy_id": "MULTIBAGGERS", "processed": 0, "created": 0,
                    "candidate_source": self.candidate_source,
                    "excluded_tickers": excluded_tickers,
                    "message": "No operable symbols match the MULTIBAGGERS asset-type policy"}

        from idos.workers.data.cache import DataCache
        cache = self.config.get("data_cache") or DataCache(str(self.db_path))
        engine = MultibaggersDiscoveryEngine(self.profile.parameters, self.profile.strategy_version)
        discovery_store = MultibaggersStore(self.db_path)
        sqlite = SQLiteStore(self.db_path)
        output = {"status": "completed", "strategy_id": "MULTIBAGGERS", "processed": 0, "passed": 0, "blocked": 0,
                  "created": 0, "existing": 0, "candidate_source": self.candidate_source,
                  "excluded_tickers": excluded_tickers, "results": []}
        universe_hash = hashlib.sha256(self.operability.path.read_bytes()).hexdigest()
        for ticker in tickers:
            payload = cache.get(f"merged:{ticker}")
            needs_refresh = payload is None or self._market_data_needs_refresh(ticker, payload)
            if needs_refresh and self.config.get("refresh_missing", True):
                factory = self.config.get("refresh_worker_factory")
                worker = (
                    factory(self.config)
                    if factory
                    else __import__(
                        "idos.workers.data.refresh_worker", fromlist=["DataRefreshWorker"]
                    ).DataRefreshWorker(self.config)
                )
                worker.execute({"tickers": [ticker]})
                payload = cache.get(f"merged:{ticker}")
            payload = payload or {"merged_data": {}, "metric_sources": {}, "conflicts": [], "as_of": None}
            merged_data = payload.get("merged_data", payload) if isinstance(payload, dict) else {}
            market_eligibility = evaluate_global_market_eligibility(
                merged_data if isinstance(merged_data, dict) else {},
                asset_type=self._asset_type(ticker),
                settings=self.market_data_settings,
            )
            as_of = payload.get("as_of") if isinstance(payload, dict) else None
            result = (
                engine.evaluate(ticker, payload, as_of)
                if market_eligibility["passed"]
                else engine.blocked_by_global_market_gate(ticker, market_eligibility, as_of)
            )
            result_data = result.to_dict()
            result_data["global_market_eligibility"] = market_eligibility
            hash_body = {key: value for key, value in result_data.items() if key != "snapshot_hash"}
            result_data["snapshot_hash"] = hashlib.sha256(
                json.dumps(hash_body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            ).hexdigest()
            if result_data["passed"]:
                intake = build_research_intake(result_data, {
                    "parameters": self.profile.parameters,
                    "candidate_source": self.candidate_source,
                    "candidate_universe_sha256": universe_hash,
                    "candidate_count": len(tickers),
                })
            else:
                intake = {}
            discovery_store.save(result_data, intake)
            output["processed"] += 1
            passed = result_data["passed"]
            output["passed" if passed else "blocked"] += 1
            output["results"].append({
                "ticker": ticker,
                "passed": passed,
                "score": result.discovery_score,
                "priority": result.research_priority,
                "discovery_type": result_data["discovery_type"],
                "reason_codes": result_data["reason_codes"],
                "snapshot_hash": result_data["snapshot_hash"],
                "global_market_eligibility": market_eligibility,
            })
            if not passed:
                continue

            from idos.data.journal import JournalRepository
            journal = JournalRepository(self.journal_root)
            existing = next((o for o in journal.list_all_opportunities() if o.get("ticker", "").upper() == ticker and o.get("strategy_id", "COMPOUNDER").upper() == "MULTIBAGGERS"), None)
            if existing:
                opp_id = existing["id"]
                output["existing"] += 1
            else:
                opp_id = f"OPP-MB-{ticker}"
                opp = Opportunity(
                    id=opp_id,
                    ticker=ticker,
                    status=OpportunityStatus.SCREENED,
                    strategy_id="MULTIBAGGERS",
                    strategy_version=self.profile.strategy_version,
                    core=self.profile.core,
                    sleeve=self.profile.sleeve,
                    thesis_type=self.profile.thesis_type,
                    entry_policy=self.profile.entry_policy,
                    research_profile=self.profile.research_profile,
                    origin="multibaggers_discovery",
                    conviction=Conviction(),
                )
                opp_data = opp.model_dump(mode="json")
                position_limit = float(self.profile.parameters.get("position_limit_pct", 1.0))
                opp_data.update({
                    "discovery_score": result.discovery_score,
                    "research_priority": result.research_priority,
                    "discovery_type": result_data["discovery_type"],
                    "snapshot_hash": result_data["snapshot_hash"],
                    "position_limit_pct": position_limit,
                    "risk_limits": {"max_position_pct": position_limit},
                })
                journal.save_opportunity(ticker, opp_data)
                sqlite.save_opportunity(opp_data)
                output["created"] += 1
            opp_path = journal.opportunity_path(ticker, opp_id)
            opp_path.mkdir(parents=True, exist_ok=True)
            (opp_path / "discovery_snapshot.yml").write_text(
                yaml.safe_dump(result_data, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            (opp_path / "research_intake.yml").write_text(
                yaml.safe_dump(intake, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
        return output

    def _asset_type(self, ticker: str) -> str | None:
        entry = self.operability.check(ticker)
        return str(entry.get("type", "")).strip().lower() if entry else None

    def _market_eligibility(self, ticker: str, payload: Any) -> dict[str, Any]:
        merged = payload.get("merged_data", payload) if isinstance(payload, dict) else {}
        return evaluate_global_market_eligibility(
            merged if isinstance(merged, dict) else {},
            asset_type=self._asset_type(ticker),
            settings=self.market_data_settings,
        )

    def _market_data_needs_refresh(self, ticker: str, payload: Any) -> bool:
        reasons = self._market_eligibility(ticker, payload)["reason_codes"]
        incomplete_evidence = {
            "MARKET_DATA_NORMALIZATION_INCOMPLETE",
            "GLOBAL_LIQUIDITY_EVIDENCE_INCOMPLETE",
            "GLOBAL_MARKET_CAP_EVIDENCE_INCOMPLETE",
        }
        return bool(incomplete_evidence.intersection(reasons))

