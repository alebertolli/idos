from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
import yaml

from idos.timezone import AR_TZ


@dataclass
class Trade:
    trade_id: str = ""
    ticker: str = ""
    type: str = ""
    date: str = ""
    price: float = 0.0
    quantity: int = 0
    value: float = 0.0
    fee: float = 0.0
    reason: str = ""
    opp_id: str = ""
    pnl: float = 0.0

    def __post_init__(self):
        if not self.trade_id:
            self.trade_id = f"trade-{uuid4().hex[:8]}"
        if not self.date:
            self.date = datetime.now(AR_TZ).isoformat()


class TradeLedger:
    def __init__(self, journal):
        self.journal = journal
        self._trades: list[Trade] = []
        self._load()

    def _ledger_path(self, year: int | None = None) -> Path:
        y = year or datetime.now(AR_TZ).year
        p = Path(str(self.journal.base_path)) / "paper" / "ledger"
        p.mkdir(parents=True, exist_ok=True)
        return p / f"{y}.yml"

    def _load(self):
        path = self._ledger_path()
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            self._trades = [Trade(**t) for t in data]

    def _save(self):
        path = self._ledger_path()
        data = [vars(t) for t in self._trades]
        path.write_text(
            yaml.dump(data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

    def record(self, trade: Trade):
        self._trades.append(trade)
        self._save()

    def history(self, ticker: str | None = None) -> list[Trade]:
        if ticker:
            return [t for t in self._trades if t.ticker.upper() == ticker.upper()]
        return list(self._trades)

    def buy_trades(self, ticker: str) -> list[Trade]:
        return [t for t in self._trades if t.ticker.upper() == ticker.upper() and t.type == "BUY"]

    def sell_trades(self, ticker: str) -> list[Trade]:
        return [t for t in self._trades if t.ticker.upper() == ticker.upper() and t.type == "SELL"]

    def total_bought(self, ticker: str) -> int:
        return sum(t.quantity for t in self.buy_trades(ticker))

    def total_sold(self, ticker: str) -> int:
        return sum(t.quantity for t in self.sell_trades(ticker))

    def net_position(self, ticker: str) -> int:
        return self.total_bought(ticker) - self.total_sold(ticker)

    def all_tickers(self) -> list[str]:
        return list(set(t.ticker for t in self._trades))
