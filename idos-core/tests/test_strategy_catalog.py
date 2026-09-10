from pathlib import Path

from idos.strategy.catalog import StrategyCatalog
from idos.data.sqlite import SQLiteStore


def test_catalog_contains_all_initial_strategies():
    catalog = StrategyCatalog(Path(__file__).parents[1].parent / "idos-config" / "strategies.yml")
    ids = {p.strategy_id for p in catalog.list()}
    assert ids == {
        "EMERGENCY_LIQ", "OPPORTUNITY_LIQ", "MONETARY_HEDGE", "COMPOUNDER", "GROWTH",
        "MOMENTUM_ETF", "GLOBAL_ETF", "TACTICAL_SWING", "ASYMETRIC", "DEEP_VALUE", "SPECULATIVE",
    }


def test_legacy_default_is_compounder():
    profile = StrategyCatalog().get(None)
    assert profile.strategy_id == "COMPOUNDER"
    assert profile.entry_policy == "VALUATION_ZONE"


def test_strategy_core_mapping():
    catalog = StrategyCatalog(Path(__file__).parents[1].parent / "idos-config" / "strategies.yml")
    assert catalog.require("MOMENTUM_ETF").core == "CORE_3_GROWTH"
    assert catalog.require("DEEP_VALUE").core == "CORE_4_ALPHA_ASYMMETRY"


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
