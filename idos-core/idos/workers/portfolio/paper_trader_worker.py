from pathlib import Path
from typing import Any

from idos.data.journal import JournalRepository
from idos.portfolio.paper import PaperTrader
from idos.portfolio.ledger import TradeLedger
from idos.portfolio.report import generate_monthly_report, save_report
from idos.workers.base import BaseWorker
from idos.timezone import AR_TZ
from datetime import datetime
import calendar


class PaperTraderWorker(BaseWorker):
    name = "paper_trader_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.config_data = config or {}

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        action = context.get("action", "")
        base_path = context.get("base_path", "")
        bp = Path(base_path) if base_path else Path.cwd()
        journal = JournalRepository(bp / "idos-journal")

        portfolio_config = {
            "bankroll": self.config_data.get("bankroll", 100000),
            "max_position_pct": self.config_data.get("max_position_pct", 3.0),
            "fee_pct": self.config_data.get("fee_pct", 0.1),
            "stop_loss_asymmetry_divisor": self.config_data.get("stop_loss_asymmetry_divisor", 3),
        }
        trader = PaperTrader(portfolio_config, journal)

        if action == "buy":
            ticker = context.get("ticker", "")
            price = context.get("price", 0)
            conviction = context.get("conviction", 50)
            opp_id = context.get("opp_id", "")
            intrinsic = context.get("intrinsic_value", 0)
            if not ticker or not price:
                return {"status": "error", "reason": "ticker and price required"}
            result = trader.buy(ticker, price, conviction, opp_id, intrinsic)
            return result

        if action == "sell":
            ticker = context.get("ticker", "")
            price = context.get("price", 0)
            reason = context.get("reason", "manual")
            exit_pct = context.get("exit_pct", 1.0)
            if not ticker or not price:
                return {"status": "error", "reason": "ticker and price required"}
            result = trader.sell(ticker, price, reason, exit_pct=exit_pct)
            return result

        if action == "report":
            report_date = context.get("report_date", datetime.now(AR_TZ).isoformat())
            ledger = TradeLedger(journal)
            report = generate_monthly_report(ledger, trader, portfolio_config["bankroll"], report_date)
            save_report(report, journal, report_date)
            print(report)
            return {"status": "completed", "report_path": str(journal.base / "paper" / "reports")}

        return {"status": "error", "reason": f"Unknown action: {action}"}
