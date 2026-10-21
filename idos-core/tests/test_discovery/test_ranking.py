from idos.discovery.ranking import RankingSystem


def test_ranking_orders_by_score():
    ranking = RankingSystem()
    entries = [
        {"ticker": "A", "scout_score": 80, "conviction_score": 90},
        {"ticker": "B", "scout_score": 90, "conviction_score": 70},
        {"ticker": "C", "scout_score": 60, "conviction_score": 50},
    ]
    ranked = ranking.rank(entries)
    assert len(ranked) == 3
    assert ranked[0].combined_score >= ranked[1].combined_score >= ranked[2].combined_score


def test_top_n():
    ranking = RankingSystem()
    entries = [{"ticker": chr(65+i), "scout_score": 100-i*10, "conviction_score": 100-i*10} for i in range(20)]
    top = ranking.top_n(entries, 5)
    assert len(top) == 5
    assert top[0].ticker == "A"


def test_custom_weights():
    ranking = RankingSystem(scout_weight=0.7, conviction_weight=0.3)
    entries = [
        {"ticker": "HIGH_SCOUT", "scout_score": 90, "conviction_score": 50},
        {"ticker": "HIGH_CONV", "scout_score": 50, "conviction_score": 90},
    ]
    ranked = ranking.rank(entries)
    assert ranked[0].ticker == "HIGH_SCOUT"
