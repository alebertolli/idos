"""Deterministic strategy runners used by scheduled IDOS workflows."""

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.discovery.operability import OperabilityFilter
from idos.market.prices import PriceProvider
from idos.models.enums import OpportunityStatus
from idos.strategy.catalog import StrategyCatalog
from idos.timezone import AR_TZ
from idos.workers.base import BaseWorker


def momentum_score(closes: list[float]) -> float:
    """Monthly momentum formula from the validated IDE v2 runner."""
    if len(closes) < 13:
        raise ValueError("At least 13 monthly closes are required")
    p0 = closes[-1]
    return 12 * p0 / closes[-2] + 4 * p0 / closes[-4] + 2 * p0 / closes[-7] + p0 / closes[-13] - 19


class MonthlyStrategyWorker(BaseWorker):
    name = "monthly_strategy_pipeline"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.strategy_id = str(self.config.get("strategy_id", "MOMENTUM_ETF")).upper()

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        base = Path(context.get("base_path", "."))
        config_path = Path(self.config.get("config_path", base / "idos-config" / "strategies.yml"))
        if not config_path.exists():
            config_path = Path("idos-config") / "strategies.yml"
        catalog = StrategyCatalog(config_path)
        profile = catalog.require(self.strategy_id)
        if not profile.enabled:
            return {"status": "skipped", "reason": "strategy_disabled", "strategy_id": self.strategy_id}
        if self.strategy_id != "MOMENTUM_ETF":
            return {"status": "skipped", "reason": "runner_not_implemented", "strategy_id": self.strategy_id}

        params = profile.parameters
        configured_universe = [str(t).upper() for t in params.get("universe", [])]
        operable_path = config_path.parent / "universe" / "operable.yml"
        if not operable_path.exists():
            raise FileNotFoundError(f"Operable universe registry not found: {operable_path}")
        operable = OperabilityFilter(str(operable_path))
        entries_by_ticker = {entry["ticker"]: entry for entry in operable.list()}
        operable_universe = [
            ticker for ticker in configured_universe if operable.is_operable(ticker)
        ]
        excluded_not_operable = sorted(set(configured_universe) - set(operable_universe))
        supported_types = set(params.get("supported_asset_types", []))
        excluded_unsupported_asset_types = sorted(
            ticker for ticker in operable_universe
            if supported_types and entries_by_ticker.get(ticker, {}).get("type") not in supported_types
        )
        strategy_universe = [
            ticker for ticker in operable_universe
            if not supported_types or entries_by_ticker.get(ticker, {}).get("type") in supported_types
        ]
        eligible_universe_count = len(strategy_universe)
        requested_tickers = context.get("candidate_tickers") or []
        excluded_manual_tickers = []
        run_scope = "bounded" if requested_tickers else "full"
        universe = strategy_universe
        if requested_tickers:
            requested_tickers = operable.validate_selection(requested_tickers)
            requested = set(requested_tickers)
            excluded_manual_tickers = sorted(requested - set(strategy_universe))
            universe = [ticker for ticker in strategy_universe if ticker in requested]
            if not universe:
                return {
                    "status": "skipped",
                    "reason": "no_manual_candidates_in_strategy_universe",
                    "strategy_id": self.strategy_id,
                    "run_scope": run_scope,
                    "requested_tickers": requested_tickers,
                    "candidate_tickers": [],
                    "candidate_count": 0,
                    "configured_universe_count": len(configured_universe),
                    "eligible_universe_count": eligible_universe_count,
                    "excluded_not_operable": excluded_not_operable,
                    "excluded_unsupported_asset_types": excluded_unsupported_asset_types,
                    "excluded_manual_tickers": excluded_manual_tickers,
                    "candidate_source": str(operable_path),
                }
        if not universe:
            raise ValueError(
                f"Strategy {self.strategy_id} has no configured candidates in the operable universe"
            )
        provider = self.config.get("price_provider") or PriceProvider()
        rows: list[dict[str, Any]] = []
        missing: list[str] = []
        for ticker in universe:
            history = provider.get_history(ticker, period="2y", interval="1mo")
            closes = [float(r["close"]) for r in history]
            if len(closes) < 13:
                missing.append(ticker)
                continue
            rows.append({"ticker": ticker, "momentum": momentum_score(closes), "as_of_date": history[-1]["date"][:10]})

        eligible = [r for r in rows if params["minimum_signal"] <= r["momentum"] <= params["maximum_signal"]]
        ranking = sorted(rows, key=lambda r: r["momentum"], reverse=True)
        selected = sorted(eligible, key=lambda r: r["momentum"], reverse=True)[: int(params["select_top"])]
        action = "CASH_FALLBACK" if not selected else "REVIEW_ALLOCATION"
        generated_at = datetime.now(AR_TZ).isoformat(timespec="microseconds")
        coverage_complete = not missing and len(rows) == eligible_universe_count
        output = {
            "strategy_id": self.strategy_id,
            "as_of_date": datetime.now(AR_TZ).date().isoformat(),
            "generated_at": generated_at,
            "run_scope": run_scope,
            "coverage_complete": coverage_complete,
            "candidate_source": str(operable_path),
            "candidate_count": len(universe),
            "configured_universe_count": len(configured_universe),
            "eligible_universe_count": eligible_universe_count,
            "requested_tickers": requested_tickers,
            "excluded_not_operable": excluded_not_operable,
            "excluded_unsupported_asset_types": excluded_unsupported_asset_types,
            "excluded_manual_tickers": excluded_manual_tickers,
            "candidate_tickers": universe,
            "formula": "12*P0/P1 + 4*P0/P3 + 2*P0/P6 + P0/P12 - 19",
            "ranking": ranking, "eligible": eligible, "selected": selected,
            "missing_history": missing, "action": action,
        }
        if context.get("dry_run", False) or not context.get("persist", True):
            return output
        self._persist(base, profile, output)
        return output

    def _persist(self, base: Path, profile: Any, output: dict[str, Any]) -> None:
        journal = JournalRepository(base / "idos-journal")
        sqlite = SQLiteStore(base / "idos.db")
        signal_dir = base / "idos-journal" / "strategies" / self.strategy_id
        signal_dir.mkdir(parents=True, exist_ok=True)
        generated = datetime.fromisoformat(output["generated_at"])
        timestamp = generated.strftime("%H%M%S%f")
        report_path = signal_dir / f"{output['as_of_date']}-{timestamp}-{output['run_scope']}.yml"
        suffix = 1
        while report_path.exists():
            report_path = signal_dir / f"{output['as_of_date']}-{timestamp}-{output['run_scope']}-{suffix}.yml"
            suffix += 1
        report_path.write_text(yaml.dump(output, allow_unicode=True), encoding="utf-8")
        for row in output["selected"]:
            ticker = row["ticker"]
            opp_id = f"OPP-{output['as_of_date'].replace('-', '')}-MOM-{ticker}"
            if sqlite.get_opportunity(opp_id) or journal.load_opportunity(ticker, opp_id):
                continue  # A repeated monthly run must not reset a reviewed decision.
            opp = {
                "id": opp_id, "ticker": ticker, "status": OpportunityStatus.SCREENED.value,
                "strategy_id": profile.strategy_id, "strategy_version": "1.0",
                "core": profile.core, "sleeve": profile.sleeve, "thesis_type": profile.thesis_type,
                "entry_policy": profile.entry_policy, "research_profile": profile.research_profile,
                "origin": "monthly_strategy_pipeline", "signal": row,
                "conviction": {"overall": 0}, "created_at": datetime.now(AR_TZ).isoformat(),
                "updated_at": datetime.now(AR_TZ).isoformat(),
            }
            journal.save_opportunity(ticker, opp)
            sqlite.save_opportunity(opp)
