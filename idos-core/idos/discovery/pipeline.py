from typing import Any
from idos.discovery.scout import ScoutEngine, ScoutResult
from idos.discovery.watchlist import WatchlistManager
from idos.state.machine import OpportunityStateMachine
from idos.models.enums import OpportunityStatus
from idos.events.bus import get_event_bus
from idos.events.types import Event


class ScreeningPipeline:
    def __init__(self, scout: ScoutEngine | None = None,
                 watchlist: WatchlistManager | None = None,
                 state_machine: OpportunityStateMachine | None = None,
                 min_watchlist_score: int = 60):
        self.scout = scout or ScoutEngine()
        self.watchlist = watchlist or WatchlistManager()
        self.state_machine = state_machine or OpportunityStateMachine()
        self.min_watchlist_score = min_watchlist_score

    def process(self, ticker: str, data: dict[str, Any],
                sqlite_store: Any = None) -> ScoutResult:
        result = self.scout.scan(ticker, data)

        if result.passed:
            if result.score >= self.min_watchlist_score:
                added = self.watchlist.add(ticker, result.score, result.reason)
                if added:
                    bus = get_event_bus()
                    bus.publish(Event(
                        type="scout:watchlist_added",
                        data={"ticker": ticker, "score": result.score},
                    ))
        else:
            bus = get_event_bus()
            bus.publish(Event(
                type="scout:rejected",
                data={"ticker": ticker, "score": result.score, "reason": result.reason},
            ))

        return result
