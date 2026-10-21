from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from run_monthly_universe_pipeline import format_strategy_summary


def test_format_multibaggers_summary_uses_discovery_metrics_without_false_zeros():
    summary = format_strategy_summary(
        "MULTIBAGGERS",
        "success",
        {
            "candidate_source": "idos-config/universe/operable.yml",
            "processed": 1,
            "passed": 1,
            "blocked": 0,
            "created": 1,
            "existing": 0,
        },
    )

    assert "candidate_source=idos-config/universe/operable.yml" in summary
    assert "processed=1" in summary
    assert "passed=1" in summary
    assert "created=1" in summary
    assert "candidate_count=0" not in summary
    assert "opportunities_created=0" not in summary


def test_format_compounder_summary_keeps_universe_and_scout_metrics():
    summary = format_strategy_summary(
        "COMPOUNDER",
        "success",
        {
            "candidate_source": "idos-config/universe/operable.yml",
            "candidate_count": 12,
            "operable_count": 10,
            "scout_passed": 3,
            "scout_rejected": 7,
            "opportunities_created": 2,
        },
    )

    assert "candidate_count=12" in summary
    assert "operable_count=10" in summary
    assert "scout_passed=3" in summary
    assert "scout_rejected=7" in summary
    assert "opportunities_created=2" in summary
