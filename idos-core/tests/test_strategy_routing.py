from pathlib import Path

import pytest

from idos.strategy.catalog import StrategyCatalog
from idos.strategy.routing import enabled_profiles_for_runner


CONFIG_PATH = Path(__file__).resolve().parents[2] / "idos-config" / "strategies.yml"


def test_enabled_profiles_route_to_their_monthly_runner():
    catalog = StrategyCatalog(CONFIG_PATH)

    assert [p.strategy_id for p in enabled_profiles_for_runner(catalog, "universe")] == [
        "COMPOUNDER", "MULTIBAGGERS"
    ]
    assert [p.strategy_id for p in enabled_profiles_for_runner(catalog, "monthly_signal")] == [
        "MOMENTUM_ETF"
    ]


def test_new_strategy_with_supported_profile_uses_configured_runner(tmp_path: Path):
    config = tmp_path / "strategies.yml"
    config.write_text(
        "strategies:\n"
        "  MOMENTUM_ETF:\n"
        "    enabled: true\n"
        "    core: CORE_3_GROWTH\n"
        "    sleeve: SYSTEMATIC_RETURN\n"
        "    thesis_type: SYSTEMATIC\n"
        "    discovery_profile: momentum_monthly\n"
        "    research_profile: systematic\n"
        "    entry_policy: SIGNAL_REBALANCE\n"
        "  TEST_SYSTEMATIC:\n"
        "    enabled: true\n"
        "    core: CORE_3_GROWTH\n"
        "    sleeve: SYSTEMATIC_RETURN\n"
        "    thesis_type: SYSTEMATIC\n"
        "    discovery_profile: momentum_monthly\n"
        "    research_profile: systematic\n"
        "    entry_policy: SIGNAL_REBALANCE\n",
        encoding="utf-8",
    )

    profiles = enabled_profiles_for_runner(StrategyCatalog(config), "monthly_signal")

    assert [profile.strategy_id for profile in profiles] == ["MOMENTUM_ETF", "TEST_SYSTEMATIC"]


def test_enabled_strategy_without_runner_fails_closed(tmp_path: Path):
    config = tmp_path / "strategies.yml"
    config.write_text(
        "strategies:\n"
        "  EXPERIMENTAL:\n"
        "    enabled: true\n"
        "    core: CORE_3_GROWTH\n"
        "    sleeve: HIGH_CONVICTION\n"
        "    thesis_type: STRATEGIC\n"
        "    discovery_profile: experimental_v1\n"
        "    research_profile: strategic\n"
        "    entry_policy: MANUAL_REVIEW\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="EXPERIMENTAL"):
        enabled_profiles_for_runner(StrategyCatalog(config), "universe")
