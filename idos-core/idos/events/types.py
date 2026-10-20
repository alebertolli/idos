from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine
from idos.timezone import AR_TZ

EventHandler = Callable[["Event"], Coroutine[Any, Any, None] | None]

@dataclass
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    source: str = "system"
    timestamp: datetime = field(default_factory=lambda: datetime.now(AR_TZ))
    correlation_id: str = ""
