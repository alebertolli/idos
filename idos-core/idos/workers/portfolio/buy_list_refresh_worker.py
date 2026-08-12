from datetime import datetime
from pathlib import Path
from typing import Any
from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.portfolio.buylist import BuyListManager
from idos.portfolio.engine import PortfolioEngine
from idos.workers.base import BaseWorker
from idos.models.enums import OpportunityStatus
from idos.timezone import AR_TZ

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
        self._load_existing_buylist(bp)

        portfolio_engine = PortfolioEngine(journal)
        positions = portfolio_engine.get_positions()
        total_weight = sum(p.get("weight_pct", 0) for p in positions)

        opportunities = journal.list_all_opportunities()
        approved = [o for o in opportunities if o["status"] == OpportunityStatus.APPROVED.value]
        entry_pending = [o for o in opportunities if o["status"] == OpportunityStatus.ENTRY_PENDING.value]

        if not approved and not entry_pending:
            print("[BUYLIST] No approved/entry-pending opportunities in journal; preserving existing buylist")
            return {
                "status": "completed",
                "updated": 0,
                "added": 0,
                "removed": 0,
                "total_entries": self.buylist.count(),
                "fail_safe": True,
            }

        updated = 0
        added = 0
        removed = 0

        margin_of_safety = self._load_margin_of_safety(bp)

        for opp in approved + entry_pending:
            ticker = opp["ticker"]
            opp_id = opp["id"]
            conviction = opp.get("conviction", {})
            intrinsic = conviction.get("intrinsic_value", 0) or opp.get("intrinsic_value", 0)
            current_price = conviction.get("current_price", 0) or opp.get("current_price", 0)

            if not intrinsic or not current_price:
                continue

            # Zona de compra con MoS configurable: precio <= intrinsic/(1+MoS/100)
            # (coherente con el fallback MoS del EntryEngine y la UI).
            buy_zone_top = intrinsic / (1 + margin_of_safety / 100)
            max_pos = min(3.0, conviction.get("overall", 50) / 100 * 5)

            existing = self.buylist.get(ticker)
            if existing:
                existing.target_price = intrinsic
                existing.buy_zone_top = buy_zone_top
                existing.max_position_pct = max_pos
                existing.conviction_score = conviction.get("overall", 0)
                existing.kb_last_update = datetime.now(AR_TZ).isoformat()
                updated += 1
            else:
                from idos.portfolio.buylist import BuyListEntry
                self.buylist.add(BuyListEntry(
                    ticker=ticker,
                    target_price=intrinsic,
                    buy_zone_top=buy_zone_top,
                    max_position_pct=max_pos,
                    conviction_score=conviction.get("overall", 0),
                    horizon=opp.get("horizon", "12-36 months"),
                    catalysts=opp.get("catalysts", []),
                ))
                added += 1

        all_tickers = {o["ticker"] for o in opportunities if o["status"] in ("APPROVED", "ENTRY_PENDING")}
        for entry in self.buylist.all():
            if entry.ticker not in all_tickers:
                self.buylist.remove(entry.ticker)
                removed += 1

        self._save_buylist(bp)

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

    def _load_margin_of_safety(self, bp: Path) -> float:
        """Umbral MoS desde Settings (idos-config/portfolio.yml margin_of_safety)."""
        from idos.config import load_settings
        if (bp / "idos-config" / "portfolio.yml").exists():
            settings = load_settings(bp / "idos-config")
            return float(settings.portfolio.get("margin_of_safety", 30.0))
        return 30.0

    def _load_existing_buylist(self, bp: Path):
        """Load existing buylist.yml entries into the in-memory manager so
        updates preserve opp_id and monitoring flags."""
        import yaml
        from idos.portfolio.buylist import BuyListEntry
        buylist_path = bp / "idos-journal" / "portfolio" / "buylist.yml"
        if not buylist_path.exists():
            return
        try:
            data = yaml.safe_load(buylist_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return
        for e in data.get("entries", []):
            ticker = e.get("ticker", "").upper()
            if not ticker:
                continue
            existing = self.buylist.get(ticker)
            if existing:
                existing.opp_id = e.get("opp_id", "")
                existing.monitoring = e.get("monitoring", True)
                continue
            self.buylist.add(BuyListEntry(
                ticker=ticker,
                target_price=float(e.get("target_price", 0) or 0),
                buy_zone_top=float(e.get("buy_zone_top", 0) or 0),
                max_position_pct=float(e.get("max_position_pct", 3.0) or 3.0),
                conviction_score=int(e.get("conviction_score", 0) or 0),
                horizon=e.get("horizon", "12-36 months"),
                catalysts=e.get("catalysts", []),
                kb_last_update=e.get("kb_last_update", ""),
                added_at=e.get("added_at", ""),
                opp_id=e.get("opp_id", ""),
                monitoring=e.get("monitoring", True),
            ))

    def _save_buylist(self, bp: Path):
        """Persist Buy List in buylist.yml preserving opp_id and monitoring flags."""
        import yaml
        buylist_path = bp / "idos-journal" / "portfolio" / "buylist.yml"
        existing = {}
        if buylist_path.exists():
            existing = yaml.safe_load(buylist_path.read_text(encoding="utf-8")) or {}
        old_entries = {e.get("ticker", "").upper(): e for e in existing.get("entries", [])}

        entries = []
        for e in self.buylist.all():
            ticker = e.ticker.upper()
            prev = old_entries.get(ticker, {})
            entries.append({
                "ticker": ticker,
                "opp_id": getattr(e, "opp_id", "") or prev.get("opp_id", ""),
                "target_price": round(e.target_price, 2),
                "buy_zone_top": round(e.buy_zone_top, 2),
                "max_position_pct": round(e.max_position_pct, 2),
                "conviction_score": e.conviction_score,
                "horizon": e.horizon,
                "catalysts": e.catalysts,
                "kb_last_update": e.kb_last_update,
                "added_at": e.added_at,
                "monitoring": prev.get("monitoring", getattr(e, "monitoring", True)),
            })
        buylist_path.parent.mkdir(parents=True, exist_ok=True)
        buylist_path.write_text(
            yaml.dump({"entries": entries}, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        print(f"[BUYLIST] Saved {len(entries)} entries to {buylist_path}")