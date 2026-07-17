import pytest
from idos.resilience.degrade import GracefulDegradation, FallbackConfig, FallbackMode


class TestGracefulDegradation:
    def test_empty_fallback(self):
        gd = GracefulDegradation()
        gd.register_fallback("scout", FallbackConfig(mode=FallbackMode.EMPTY))
        result = gd.execute("scout", lambda: (_ for _ in ()).throw(ValueError("fail")))
        assert result == {}

    def test_defaults_fallback(self):
        gd = GracefulDegradation()
        gd.register_fallback("scout", FallbackConfig(mode=FallbackMode.DEFAULTS, default_value=42))
        result = gd.execute("scout", lambda: (_ for _ in ()).throw(ValueError("fail")))
        assert result == 42

    def test_cached_fallback(self):
        gd = GracefulDegradation()
        gd.register_fallback("api", FallbackConfig(mode=FallbackMode.CACHED))
        gd.cache_result("api", {"cached": "data"})
        result = gd.execute("api", lambda: (_ for _ in ()).throw(ValueError("fail")))
        assert result == {"cached": "data"}

    def test_success_caches_value(self):
        gd = GracefulDegradation()
        gd.register_fallback("api", FallbackConfig(mode=FallbackMode.CACHED))
        result = gd.execute("api", lambda: {"fresh": "data"})
        assert result == {"fresh": "data"}
        assert gd.get_cached("api") == {"fresh": "data"}
