from idos.research.kb_updater import KnowledgeBaseUpdater


def test_update_metrics():
    updater = KnowledgeBaseUpdater()
    kb = {}
    kb = updater.update_metrics(kb, {"roic": 25, "operating_margin": 20})
    assert kb["dynamic"]["metrics"]["roic"] == 25
    assert "last_updated" in kb["dynamic"]


def test_update_financials():
    updater = KnowledgeBaseUpdater()
    kb = {}
    kb = updater.update_financials(kb, "2026-Q2", {"revenue": 1000, "net_income": 200})
    assert kb["dynamic"]["financials"]["2026-Q2"]["revenue"] == 1000


def test_add_event():
    updater = KnowledgeBaseUpdater()
    kb = {}
    kb = updater.add_event(kb, "CEO_CHANGE", "New CEO appointed")
    assert kb["generated"]["events"][0]["type"] == "CEO_CHANGE"
