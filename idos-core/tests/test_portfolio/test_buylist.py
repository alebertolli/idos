import pytest
from idos.portfolio.buylist import BuyListManager, BuyListEntry


class TestBuyListManager:
    @pytest.fixture
    def manager(self):
        return BuyListManager()

    def test_add_and_get(self, manager):
        entry = BuyListEntry(ticker="AAPL", target_price=200, buy_zone_top=160, conviction_score=85)
        manager.add(entry)
        assert manager.get("AAPL") is entry
        assert manager.count() == 1

    def test_remove(self, manager):
        entry = BuyListEntry(ticker="AAPL", target_price=200, buy_zone_top=160)
        manager.add(entry)
        assert manager.remove("AAPL") is True
        assert manager.remove("NONEXIST") is False

    def test_buy_zone(self, manager):
        entry = BuyListEntry(ticker="AAPL", target_price=200, buy_zone_top=160)
        manager.add(entry)
        assert manager.is_in_buy_zone("AAPL", 150) is True
        assert manager.is_in_buy_zone("AAPL", 170) is False

    def test_update_targets(self, manager):
        entry = BuyListEntry(ticker="AAPL", target_price=200, buy_zone_top=160)
        manager.add(entry)
        manager.update_targets("AAPL", 220, 170)
        assert entry.target_price == 220
        assert entry.buy_zone_top == 170

    def test_list_ready_to_buy(self, manager):
        manager.add(BuyListEntry(ticker="AAPL", target_price=200, buy_zone_top=160, conviction_score=85))
        manager.add(BuyListEntry(ticker="MSFT", target_price=300, buy_zone_top=250, conviction_score=70))
        ready = manager.list_ready_to_buy({"AAPL": 150, "MSFT": 300})
        assert len(ready) == 1
        assert ready[0].ticker == "AAPL"
