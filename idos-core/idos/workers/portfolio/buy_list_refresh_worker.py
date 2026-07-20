from datetime import datetime, UTC
from typing import Any
from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.portfolio.buylist import BuyListManager
from idos.portfolio.engine import PortfolioEngine
from idos.workers.base import BaseWorker
from idos.models.enums import OpportunityStatus


class BuyListRefreshWorker(BaseWorker):
    """Updates Buy List daily with latest targets, conviction, and buy zones.

    Triggers: daily schedule (pre-market).
    Updates: target_price, buy_zone_top, max_position_pct, conviction_score, kb_last_update.
    """
    name = "buy_list_refresh_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.buylist = BuyListManager()

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        base_path = context.get("base_path", "")
        from pathlib import Path
        bp = Path(base_path) if base_path else Path.cwd()
        sqlite = SQLiteStore(bp / "idos.db")
        journal = JournalRepository(bp / "idos-journal")

        portfolio_engine = PortfolioEngine(journal)
        positions = portfolio_engine.get_positions()
        total_weight = sum(p.get("weight_pct", 0) for p in positions)

        opportunities = sqlite.list_opportunities()
        approved = [o for o in opportunities if o["status"] == OpportunityStatus.APPROVED.value]
        entry_pending = [o for o in opportunities if o["status"] == OpportunityStatus.ENTRY_PENDING.value]

        updated = 0
        added = 0
        removed = 0

        for opp in approved + entry_pending:
            ticker = opp["ticker"]
            opp_id = opp["id"]
            conviction = opp.get("conviction", {})
            intrinsic = conviction.get("intrinsic_value", 0) or opp.get("intrinsic_value", 0)
            current_price = conviction.get("current_price", 0) or opp.get("current_price", 0)

            if not intrinsic or not current_price:
                continue

            margin_pct = ((intrinsic - current_price) / current_price) * 100
            buy_zone_top = intrinsic * 0.9
            max_pos = min(3.0, conviction.get("overall", 50) / 100 * 5)

            existing = self.buylist.get(ticker)
            if existing:
                existing.target_price = intrinsic
                existing.buy_zone_top = buy_zone_top
                existing.max_position_pct = max_pos
                existing.conviction_score = conviction.get("overall", 0)
                existing.kb_last_update = datetime.now(UTC).isoformat()
                updated += 1
            else:
                self.buylist.add(type("Entry", (), {
                    "ticker": ticker,
                    "target_price": intrinsic,
                    "buy_zone_top": buy_zone_top,
                    "max_position_pct": max_pos,
                    "conviction_score": conviction.get("overall", 0),
                    "horizon": opp.get("horizon", "12-36 months"),
                    "catalysts": opp.get("catalysts", []),
                })())
                added += 1

        all_tickers = {o["ticker"] for o in opportunities if o["status"] in ("APPROVED", "ENTRY_PENDING")}
        for entry in self.buylist.all():
            if entry.ticker not in all_tickers:
                self.buylist.remove(entry.ticker)
                removed += 1

        journal.save_watchlist([{
            "ticker": e.ticker,
            "target_price": e.target_price,
            "buy_zone_top": e.buy_zone_top,
            "max_position_pct": e.max_position_pct,
            "conviction_score": e.conviction_score,
            "horizon": e.horizon,
            "catalysts": e.catalysts,
            "kb_last_update": e.kb_last_update,
            "added_at": e.added_at,
        } for e in self.buylist.all()])

        sqlite.log_event("buy_list:refreshed", {
            "updated": updated,
            "added": added,
            "removed": removed,
            "total_entries": self.buylist.count(),
        })

        return {
            "status": "completed",
            "updated": updated,
            "added": added,
            "removed": removed,
            "total_entries": self.buylist.count(),
        }