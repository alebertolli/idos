from pathlib import Path

from idos.models.opportunity_identity import (
    build_opportunity_id,
    is_active_opportunity,
    next_opportunity_cycle,
)


def test_opportunity_id_is_canonical_and_strategy_scoped():
    assert build_opportunity_id("COMPOUNDER", "aapl", 1) == "OPP-COMPOUNDER-AAPL-0001"
    assert build_opportunity_id("MULTIBAGGERS", "AAPL", 1) == "OPP-MULTIBAGGERS-AAPL-0001"
    assert build_opportunity_id("MOMENTUM_ETF", "XLF", 12) == "OPP-MOMENTUM-ETF-XLF-0012"


def test_closed_legacy_opportunity_advances_cycle_but_active_case_is_reused():
    history = [
        {"id": "OPP-MB-AAPL", "ticker": "AAPL", "strategy_id": "MULTIBAGGERS", "status": "ARCHIVED"},
        {"id": "OPP-MULTIBAGGERS-AAPL-0002", "ticker": "AAPL", "strategy_id": "MULTIBAGGERS", "status": "EXITED", "opportunity_cycle": 2},
    ]
    assert next_opportunity_cycle(history, "MULTIBAGGERS", "AAPL") == 3
    assert is_active_opportunity({"status": "UNDER_RESEARCH"})
    assert not is_active_opportunity({"status": "ARCHIVED"})


def test_dashboard_explains_failed_rules_without_collapsing_them():
    builder_source = Path(__file__).parents[1] / "idos" / "site" / "builder.py"
    source = builder_source.read_text(encoding="utf-8")

    assert "Motivos de reglas fallidas" in source
    assert "ruleDetails[id]||ruleFallbacks[id]" in source
    assert "RULE-005':'La convicción no alcanzó el mínimo configurado.'" in source
    assert "RULE-008':'La asimetría no alcanzó el mínimo requerido" in source


def test_workflow_schedules_map_to_argentina_local_times():
    root = Path(__file__).parents[2]
    expected = {
        ".github/workflows/monthly-universe-pipeline.yml": 'cron: "0 3 1 * *"',
        ".github/workflows/ddd-pipeline.yml": 'cron: "0 3 2 * *"',
        ".github/workflows/daily-refresh.yml": 'cron: "0 11 * * 1-5"',
        ".github/workflows/monthly-rebalance.yml": 'cron: "0 9 3 * *"',
        ".github/workflows/board-review.yml": 'cron: "0 9 4 * *"',
        ".github/workflows/friday-digest.yml": 'cron: "0 0 * * 6"',
    }
    for relative_path, cron in expected.items():
        content = (root / relative_path).read_text(encoding="utf-8")
        assert cron in content
        assert "America/Argentina/Buenos_Aires" in content
