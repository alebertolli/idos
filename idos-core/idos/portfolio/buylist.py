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

    def __post_init__(self):
        if not self.added_at:
            self.added_at = datetime.now(AR_TZ).isoformat()
        if not self.kb_last_update:
            self.kb_last_update = self.added_at

class BuyListManager:
    def __init__(self):
        self._entries: dict[str, BuyListEntry] = {}

    def add(self, entry: BuyListEntry) -> bool:
        self._entries[entry.ticker.upper()] = entry
        return True

    def remove(self, ticker: str) -> bool:
        return self._entries.pop(ticker.upper(), None) is not None

    def get(self, ticker: str) -> BuyListEntry | None:
        return self._entries.get(ticker.upper())

    def is_in_buy_zone(self, ticker: str, current_price: float) -> bool:
        entry = self._entries.get(ticker.upper())
        if not entry or entry.target_price <= 0:
            return False
        return current_price <= entry.buy_zone_top

    def update_targets(self, ticker: str, target: float, buy_zone_top: float):
        entry = self._entries.get(ticker.upper())
        if entry:
            entry.target_price = target
            entry.buy_zone_top = buy_zone_top
            entry.kb_last_update = datetime.now(AR_TZ).isoformat()

    def list_ready_to_buy(self, prices: dict[str, float]) -> list[BuyListEntry]:
        ready = []
        for ticker, entry in self._entries.items():
            price = prices.get(ticker, 0)
            if price > 0 and price <= entry.buy_zone_top:
                ready.append(entry)
        return sorted(ready, key=lambda e: e.conviction_score, reverse=True)

    def all(self) -> list[BuyListEntry]:
        return list(self._entries.values())

    def count(self) -> int:
        return len(self._entries)

    def clear(self):
        self._entries.clear()
