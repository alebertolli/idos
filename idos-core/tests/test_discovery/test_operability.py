from pathlib import Path

import pytest

from idos.discovery.operability import OperabilityFilter


def _operable():
    repository = Path(__file__).resolve().parents[3]
    return OperabilityFilter(str(repository / "idos-config/universe/operable.yml"))


def test_manual_selection_requires_valid_operable_tickers():
    operable = _operable()

    assert operable.validate_manual_selection(" qqq, AAPL ") == ["AAPL", "QQQ"]
    with pytest.raises(ValueError, match="at least one ticker"):
        operable.validate_manual_selection(" , ")
    with pytest.raises(ValueError, match="not in the operable registry"):
        operable.validate_manual_selection("AAPL,UNKNOWN")


def test_manual_selection_enforces_configured_candidate_limit():
    operable = _operable()

    assert operable.validate_manual_selection("AAPL,QQQ,SPY", limit=3) == ["AAPL", "QQQ", "SPY"]
    with pytest.raises(ValueError, match="2-ticker limit"):
        operable.validate_manual_selection("AAPL,QQQ,SPY", limit=2)
