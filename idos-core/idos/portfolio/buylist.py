from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from idos.timezone import AR_TZ

@dataclass
class BuyListEntry:
    ticker: str
    target_price: float = 0.0
    buy_zone_top: float = 0.0
    max_position_pct: float = 3.0
    conviction_score: int = 0
    horizon: str = "12-36 months"
    catalysts: list[str] = field(default_factory=list)
    kb_last_update: str = ""
    added_at: str = ""
    opp_id: str = ""
    monitoring: bool = True
    strategy_id: str = "COMPOUNDER"
    entry_policy: str = "VALUATION_ZONE"
    strategy_signal: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.added_at:
            self.added_at = datetime.now(AR_TZ).isoformat()
        if not self.kb_last_update:
            self.kb_last_update = self.added_at

class BuyListManager:
    def __init__(self):
        self._entries: dict[str, BuyListEntry] = {}

    def add(self, entry: BuyListEntry) -> bool:
        self._entries[self._key(entry.ticker, entry.strategy_id)] = entry
        return True

    @staticmethod
    def _key(ticker: str, strategy_id: str = "COMPOUNDER") -> str:
        return f"{strategy_id.upper()}::{ticker.upper()}"

    def remove(self, ticker: str) -> bool:
        if "::" in ticker:
            return self._entries.pop(ticker.upper(), None) is not None
        keys = [key for key, entry in self._entries.items() if entry.ticker.upper() == ticker.upper()]
        for key in keys:
            self._entries.pop(key, None)
        return bool(keys)

    def get(self, ticker: str) -> BuyListEntry | None:
        if "::" in ticker:
            return self._entries.get(ticker.upper())
        matches = [entry for entry in self._entries.values() if entry.ticker.upper() == ticker.upper()]
        if len(matches) == 1:
            return matches[0]
        if matches:
            return None
        return self._entries.get(self._key(ticker))

    def is_in_buy_zone(self, ticker: str, current_price: float) -> bool:
        entry = self.get(ticker)
        if not entry or entry.target_price <= 0:
            return False
        return current_price <= entry.buy_zone_top

    def update_targets(self, ticker: str, target: float, buy_zone_top: float):
        entry = self.get(ticker)
        if entry:
            entry.target_price = target
            entry.buy_zone_top = buy_zone_top
            entry.kb_last_update = datetime.now(AR_TZ).isoformat()

    def list_ready_to_buy(self, prices: dict[str, float]) -> list[BuyListEntry]:
        ready = []
        for entry in self._entries.values():
            price = prices.get(entry.ticker.upper(), 0)
            if price > 0 and price <= entry.buy_zone_top:
                ready.append(entry)
        return sorted(ready, key=lambda e: e.conviction_score, reverse=True)

    def all(self) -> list[BuyListEntry]:
        return list(self._entries.values())

    def count(self) -> int:
        return len(self._entries)

    def clear(self):
        self._entries.clear()
