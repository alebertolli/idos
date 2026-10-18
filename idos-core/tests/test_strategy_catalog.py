from pathlib import Path
import pytest

from idos.strategy.catalog import StrategyCatalog
from idos.data.sqlite import SQLiteStore


def test_catalog_contains_all_initial_strategies():
    catalog = StrategyCatalog(Path(__file__).parents[1].parent / "idos-config" / "strategies.yml")
    ids = {p.strategy_id for p in catalog.list()}
    assert ids == {
        "EMERGENCY_LIQ", "OPPORTUNITY_LIQ", "MONETARY_HEDGE", "COMPOUNDER", "GROWTH",
        "MOMENTUM_ETF", "GLOBAL_ETF", "TACTICAL_SWING", "ASYMETRIC", "DEEP_VALUE", "SPECULATIVE", "MULTIBAGGERS",
    }


def test_legacy_default_is_compounder():
    profile = StrategyCatalog().get(None)
    assert profile.strategy_id == "COMPOUNDER"
    assert profile.entry_policy == "VALUATION_ZONE"


def test_unknown_strategy_cannot_fall_back_to_compounder():
    with pytest.raises(ValueError, match="Unknown strategy_id"):
        StrategyCatalog().get("UNKNOWN_STRATEGY")


def test_discovery_rejects_profile_without_runner():
    from idos.workers.data.universe_pipeline import UniversePipeline

    config_path = Path(__file__).parents[1].parent / "idos-config"
    with pytest.raises(ValueError, match="no runner"):
        UniversePipeline({"strategy_id": "MOMENTUM_ETF", "config_path": str(config_path)})


def test_strategy_core_mapping():
    catalog = StrategyCatalog(Path(__file__).parents[1].parent / "idos-config" / "strategies.yml")
    assert catalog.require("MOMENTUM_ETF").core == "CORE_3_GROWTH"
    assert catalog.require("DEEP_VALUE").core == "CORE_4_ALPHA_ASYMMETRY"


def test_multibaggers_policy_is_disabled_and_configured():
    catalog = StrategyCatalog(Path(__file__).parents[1].parent / "idos-config" / "strategies.yml")
    profile = catalog.require("MULTIBAGGERS")

    assert profile.enabled is False
    assert profile.core == "CORE_4_ALPHA_ASYMMETRY"
    assert profile.sleeve == "ALPHA_ASYMMETRY"
    assert profile.entry_policy == "MANUAL_REVIEW"
    assert profile.discovery_profile == "multibaggers"
    assert profile.research_profile == "multibaggers"
    assert profile.parameters["discovery_threshold"] == 65
    assert profile.parameters["position_limit_pct"] == 1.0
    assert profile.parameters["small_caps_enabled"] is False
    assert "avg_dollar_volume_min_usd" not in profile.parameters
    assert profile.parameters["weights"] == {
        "economic_transition": 0.25,
        "quality": 0.20,
        "reinvestment": 0.20,
        "expectation_gap": 0.20,
        "market_confirmation": 0.15,
    }

    import yaml

    universe_path = Path(__file__).parents[1].parent / "idos-config" / "universe" / "multibaggers.yml"
    universe = yaml.safe_load(universe_path.read_text(encoding="utf-8"))
    assert "avg_dollar_volume_min_usd" not in universe


def test_strategy_metadata_round_trips_through_sqlite(tmp_path: Path):
    store = SQLiteStore(tmp_path / "idos.db")
    store.save_opportunity({
        "id": "OPP-MOM-001", "ticker": "QQQ", "status": "SCREENED",
        "strategy_id": "MOMENTUM_ETF", "strategy_version": "1.0",
        "core": "CORE_3_GROWTH", "sleeve": "SYSTEMATIC_RETURN",
        "entry_policy": "SIGNAL_REBALANCE", "research_profile": "systematic",
        "origin": "monthly_strategy_pipeline", "conviction": {},
    })
    persisted = store.get_opportunity("OPP-MOM-001")
    assert persisted["strategy_id"] == "MOMENTUM_ETF"
    assert persisted["entry_policy"] == "SIGNAL_REBALANCE"
    assert persisted["origin"] == "monthly_strategy_pipeline"
