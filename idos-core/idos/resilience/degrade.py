from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable


class FallbackMode(StrEnum):
    CACHED = "cached"
    DEFAULTS = "defaults"
    EMPTY = "empty"
    DEGRADED = "degraded"
    NULL = "null"


@dataclass
class FallbackConfig:
    mode: FallbackMode = FallbackMode.EMPTY
    default_value: Any = None
    cache_ttl: int = 300


class GracefulDegradation:
    def __init__(self):
        self._fallbacks: dict[str, FallbackConfig] = {}
        self._cached: dict[str, Any] = {}

    def register_fallback(self, component: str, config: FallbackConfig):
        self._fallbacks[component] = config

    def get_fallback(self, component: str) -> FallbackConfig | None:
        return self._fallbacks.get(component)

    def cache_result(self, component: str, value: Any):
        self._cached[component] = value

    def get_cached(self, component: str) -> Any | None:
        return self._cached.get(component)

    def execute(self, component: str, fn: Callable, *args, **kwargs) -> Any:
        config = self._fallbacks.get(component, FallbackConfig())
        try:
            result = fn(*args, **kwargs)
            if config.mode == FallbackMode.CACHED:
                self.cache_result(component, result)
            return result
        except Exception:
            if config.mode == FallbackMode.CACHED:
                cached = self.get_cached(component)
                if cached is not None:
                    return cached
            if config.mode == FallbackMode.DEFAULTS:
                return config.default_value
            if config.mode == FallbackMode.EMPTY:
                return {}
            if config.mode == FallbackMode.NULL:
                return None
            return None
