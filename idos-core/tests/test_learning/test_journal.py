import pytest
from idos.learning.journal import BehavioralJournal, BiasEntry, BiasType


class TestBehavioralJournal:
    def test_log_and_count(self):
        bj = BehavioralJournal()
        bj.log(BiasEntry(ticker="AAPL", bias_type=BiasType.CONFIRMATION, description="Only looked for confirming evidence"))
        assert bj.count() == 1

    def test_filter_by_ticker(self):
        bj = BehavioralJournal()
        bj.log(BiasEntry(ticker="AAPL", bias_type=BiasType.OVERCONFIDENCE, description="Too sure"))
        bj.log(BiasEntry(ticker="MSFT", bias_type=BiasType.ANCHORING, description="Stuck on initial price"))
        assert len(bj.get_by_ticker("AAPL")) == 1

    def test_filter_by_severity(self):
        bj = BehavioralJournal()
        bj.log(BiasEntry(ticker="A", bias_type=BiasType.LOSS_AVERSION, description="", severity="high"))
        bj.log(BiasEntry(ticker="B", bias_type=BiasType.HERDING, description="", severity="low"))
        assert len(bj.get_by_severity("high")) == 1

    def test_bias_frequencies(self):
        bj = BehavioralJournal()
        bj.log(BiasEntry(ticker="A", bias_type=BiasType.CONFIRMATION, description=""))
        bj.log(BiasEntry(ticker="B", bias_type=BiasType.CONFIRMATION, description=""))
        bj.log(BiasEntry(ticker="C", bias_type=BiasType.OVERCONFIDENCE, description=""))
        freqs = bj.bias_frequencies()
        assert freqs["confirmation_bias"] == 2
        assert freqs["overconfidence"] == 1
