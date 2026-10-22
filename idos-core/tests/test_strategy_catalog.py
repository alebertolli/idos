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


def test_multibaggers_policy_is_enabled_and_configured():
    catalog = StrategyCatalog(Path(__file__).parents[1].parent / "idos-config" / "strategies.yml")
    profile = catalog.require("MULTIBAGGERS")

    assert profile.enabled is True
    assert profile.core == "CORE_4_ALPHA_ASYMMETRY"
    assert profile.sleeve == "ALPHA_ASYMMETRY"
    assert profile.entry_policy == "MANUAL_REVIEW"
    assert profile.discovery_profile == "multibaggers"
    assert profile.research_profile == "multibaggers"
    assert profile.parameters["discovery_threshold"] == 65
    assert profile.parameters["position_limit_pct"] == 1.0
    assert profile.parameters["thesis_review_interval_days"] == 30
    assert profile.parameters["small_caps_enabled"] is False
    assert profile.strategy_version == "1.5"
    assert "fcf_conversion_pct" in profile.parameters["research"]["ratios_to_review"]
    assert profile.parameters["research"]["ratio_input_fields"]["current_ratio"] == [
        "current_ratio", "current_assets", "current_liabilities",
    ]
    assert profile.parameters["supported_asset_types"] == ["us_equity"]
    assert "avg_dollar_volume_min_usd" not in profile.parameters
    assert profile.parameters["weights"] == {"market_confirmation": 1.0}
    assert profile.parameters["data_quality"]["critical_metrics"] == [
        "price_momentum_12m_pct", "drawdown_pct", "volatility_90d_pct",
    ]
    assert profile.parameters["research"]["required_analysis"] == [
        "fundamental_ratio_review", "bear_bull_scenarios",
        "source_cited_expectation_gap", "validated_asymmetry",
    ]
    assert profile.parameters["research"]["ratio_units"]["current_ratio"] == "x"
    assert set(profile.parameters["research"]["ratios_to_review"]) == set(
        profile.parameters["research"]["ratio_units"]
    )

    assert "universe_path" not in profile.parameters


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
