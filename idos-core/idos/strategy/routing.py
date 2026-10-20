"""Explicit routing from strategy discovery profiles to monthly runners."""

from __future__ import annotations

from idos.strategy.catalog import StrategyCatalog, StrategyProfile


RUNNER_BY_DISCOVERY_PROFILE = {
    "compounder": "universe",
    "multibaggers": "universe",
    "momentum_monthly": "monthly_signal",
}


def enabled_profiles_for_runner(
    catalog: StrategyCatalog,
    runner: str,
) -> list[StrategyProfile]:
    """Return enabled strategies routed to ``runner``; fail closed if any lack a route."""
    enabled = catalog.list(enabled_only=True)
    unsupported = sorted(
        profile.strategy_id
        for profile in enabled
        if profile.discovery_profile not in RUNNER_BY_DISCOVERY_PROFILE
    )
    if unsupported:
        raise ValueError(
            "Enabled strategies have no monthly runner for discovery profile: "
            + ", ".join(unsupported)
        )

    return [
        profile
        for profile in enabled
        if RUNNER_BY_DISCOVERY_PROFILE[profile.discovery_profile] == runner
    ]
