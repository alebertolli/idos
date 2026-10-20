import pytest
from idos.resilience.health import HealthMonitor, HealthCheck, HealthStatus


class TestHealthMonitor:
    def test_healthy_when_all_pass(self):
        hm = HealthMonitor()
        hm.register("db", lambda: HealthCheck(name="db", healthy=True))
        hm.register("api", lambda: HealthCheck(name="api", healthy=True))
        results = hm.run_all()
        assert hm.status == HealthStatus.HEALTHY
        assert len(results) == 2

    def test_degraded_when_half_fail(self):
        hm = HealthMonitor()
        hm.register("db", lambda: HealthCheck(name="db", healthy=True))
        hm.register("api", lambda: HealthCheck(name="api", healthy=False))
        results = hm.run_all()
        assert hm.status == HealthStatus.DEGRADED

    def test_unhealthy_when_all_fail(self):
        hm = HealthMonitor()
        hm.register("db", lambda: HealthCheck(name="db", healthy=False))
        hm.register("api", lambda: HealthCheck(name="api", healthy=False))
        hm.run_all()
        assert hm.status == HealthStatus.UNHEALTHY

    def test_healthy_when_no_checks(self):
        hm = HealthMonitor()
        hm.run_all()
        assert hm.status == HealthStatus.HEALTHY

    def test_register_unregister(self):
        hm = HealthMonitor()
        hm.register("db", lambda: HealthCheck(name="db", healthy=True))
        assert hm.registered_count == 1
        hm.unregister("db")
        assert hm.registered_count == 0
