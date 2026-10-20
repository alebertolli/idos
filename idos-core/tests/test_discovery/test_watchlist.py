from idos.discovery.watchlist import WatchlistManager


def test_add_and_get():
    wl = WatchlistManager()
    assert wl.add("MELI", 85, "Strong fundamentals")
    entry = wl.get("MELI")
    assert entry is not None
    assert entry.score == 85


def test_max_entries():
    wl = WatchlistManager(max_entries=3)
    assert wl.add("A", 90)
    assert wl.add("B", 80)
    assert wl.add("C", 70)
    assert wl.add("D", 85) is True  # replaces lowest (C with 70)
    assert wl.get("C") is None
    assert wl.get("D") is not None


def test_remove():
    wl = WatchlistManager()
    wl.add("MELI", 85)
    assert wl.remove("MELI") is True
    assert wl.get("MELI") is None
    assert wl.remove("UNKNOWN") is False


def test_alerts():
    wl = WatchlistManager()
    wl.add("MELI", 85)
    wl.add_alert("MELI", "Price dropped 10%")
    alerts = wl.get_alerts()
    assert len(alerts) == 1
    assert alerts[0]["alert"] == "Price dropped 10%"


def test_update_score():
    wl = WatchlistManager()
    wl.add("MELI", 85)
    wl.update_score("MELI", 90, "Improved fundamentals")
    assert wl.get("MELI").score == 90


def test_top_n():
    wl = WatchlistManager()
    for i, s in enumerate([50, 80, 90, 70]):
        wl.add(f"TICK{i}", s)
    top = wl.get_top(2)
    assert len(top) == 2
    assert top[0].score >= top[1].score
