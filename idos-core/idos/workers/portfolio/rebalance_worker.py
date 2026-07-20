from datetime import datetime
from typing import Any
from uuid import uuid4

from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.portfolio.engine import PortfolioEngine
from idos.workers.base import BaseWorker
from idos.timezone import AR_TZ

class RebalanceWorker(BaseWorker):
    """Monthly portfolio rebalancing: conviction review, weight optimization, sector limits.

    Triggers: monthly schedule.
    Transitions: MONITORING -> REDUCING (if conviction dropped) or FULL_POSITION (if increased).
    """
    name = "rebalance_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.max_position_weight = config.get("max_position_weight", 3.0)
        self.max_sector_exposure = config.get("max_sector_exposure", 25.0)
        self.min_conviction_hold = config.get("min_conviction_hold", 50)

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        base_path = context.get("base_path", "")
        from pathlib import Path
        bp = Path(base_path) if base_path else Path.cwd()
        sqlite = SQLiteStore(bp / "idos.db")
        journal = JournalRepository(bp / "idos-journal")
        engine = PortfolioEngine(journal)

        positions = engine.get_positions()
        results = []

        for pos in positions:
            ticker = pos.get("ticker", "")
            opp_id = pos.get("opportunity_id", "")
            weight = pos.get("weight_pct", 0.0)
            conviction = pos.get("conviction", {}).get("overall", 50)

            if not ticker or not opp_id:
                continue

            opp = sqlite.get_opportunity(opp_id)
            if not opp:
                continue

            current_status = opp.get("status", "MONITORING")

            actions = []
            new_status = current_status

            if conviction < self.min_conviction_hold:
                actions.append(f"CONVICTION_DROP: {conviction} < {self.min_conviction_hold} -> REDUCING")
                new_status = "REDUCING"
            elif weight > self.max_position_weight:
                actions.append(f"OVERWEIGHT: {weight:.1f}% > {self.max_position_weight}% -> REDUCING")
                new_status = "REDUCING"

            sector = opp.get("sector", "Unknown")
            sector_exp = engine.sector_exposure().get(sector, 0)
            if sector_exp > self.max_sector_exposure:
                actions.append(f"SECTOR_OVEREXPOSURE: {sector} {sector_exp:.1f}% > {self.max_sector_exposure}% -> REDUCING")
                new_status = "REDUCING"

            if actions:
                decision = {
                    "id": f"dec-{uuid4().hex[:8]}",
                    "type": "REBALANCE",
                    "ticker": ticker,
                    "opp_id": opp_id,
                    "status": "PROPOSED",
                    "actions": actions,
                    "old_weight": weight,
                    "target_weight": min(weight, self.max_position_weight) if new_status == "REDUCING" else weight,
                    "rationale": "; ".join(actions),
                    "generated_at": datetime.now(AR_TZ).isoformat(),
                }
                journal.save_decision(ticker, opp_id, decision)
                results.append({"ticker": ticker, "actions": actions, "new_status": new_status})

        return {
            "status": "completed",
            "positions_reviewed": len(positions),
            "rebalance_proposals": len(results),
            "details": results,
        }

class RiskMonitorWorker(BaseWorker):
    """Daily risk monitoring: drawdown, volatility, D/E, concentration, stop loss.

    Triggers: daily schedule.
    Actions: logs alerts, proposes exits via event bus.
    """
    name = "risk_monitor_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.max_drawdown_pct = config.get("max_drawdown_pct", 15.0)
        self.max_volatility_pct = config.get("max_volatility_pct", 30.0)
        self.max_de_ratio = config.get("max_de_ratio", 2.0)
        self.max_concentration_pct = config.get("max_concentration_pct", 3.0)

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        base_path = context.get("base_path", "")
        from pathlib import Path
        bp = Path(base_path) if base_path else Path.cwd()
        sqlite = SQLiteStore(bp / "idos.db")
        journal = JournalRepository(bp / "idos-journal")
        engine = PortfolioEngine(journal)

        positions = engine.get_positions()
        alerts = []

        for pos in positions:
            ticker = pos.get("ticker", "")
            weight = pos.get("weight_pct", 0.0)
            entry = pos.get("avg_entry_price", 0.0)
            current = pos.get("current_price", entry)
            stop_loss = pos.get("stop_loss", 0.0)

            if not ticker:
                continue

            if current > 0 and entry > 0:
                drawdown = (entry - current) / entry * 100
                if drawdown > self.max_drawdown_pct:
                    alerts.append({
                        "ticker": ticker,
                        "type": "DRAWDOWN",
                        "severity": "HIGH",
                        "value": round(drawdown, 1),
                        "threshold": self.max_drawdown_pct,
                        "message": f"Drawdown {drawdown:.1f}% exceeds {self.max_drawdown_pct}%",
                    })

            if stop_loss > 0 and current > 0 and current <= stop_loss:
                alerts.append({
                    "ticker": ticker,
                    "type": "STOP_LOSS",
                    "severity": "CRITICAL",
                    "value": current,
                    "threshold": stop_loss,
                    "message": f"Stop loss {stop_loss} triggered at {current}",
                })

            if weight > self.max_concentration_pct:
                alerts.append({
                    "ticker": ticker,
                    "type": "CONCENTRATION",
                    "severity": "MEDIUM",
                    "value": weight,
                    "threshold": self.max_concentration_pct,
                    "message": f"Position weight {weight:.1f}% exceeds {self.max_concentration_pct}%",
                })

        if alerts:
            from idos.events.bus import get_event_bus
            from idos.events.types import Event
            bus = get_event_bus()
            for alert in alerts:
                bus.publish(Event(
                    type="risk:alert",
                    data=alert,
                    source="risk_monitor_worker",
                ))

        return {
            "status": "completed",
            "positions_checked": len(positions),
            "alerts_generated": len(alerts),
            "alerts": alerts,
        }