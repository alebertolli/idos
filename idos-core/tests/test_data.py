import tempfile
from pathlib import Path
from idos.data.sqlite import SQLiteStore
from idos.data.knowledge import KnowledgeRepository
from idos.data.journal import JournalRepository


def test_sqlite_opportunity_crud():
    store = SQLiteStore(":memory:")
    opp = {
        "id": "OPP-2026-001",
        "ticker": "MELI",
        "status": "DISCOVERED",
        "conviction": {"overall": 0},
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    store.save_opportunity(opp)
    loaded = store.get_opportunity("OPP-2026-001")
    assert loaded is not None
    assert loaded["ticker"] == "MELI"
    assert loaded["status"] == "DISCOVERED"

    opps = store.list_opportunities()
    assert len(opps) == 1

    opps_filtered = store.list_opportunities("DISCOVERED")
    assert len(opps_filtered) == 1
    opps_filtered = store.list_opportunities("APPROVED")
    assert len(opps_filtered) == 0


def test_sqlite_transition():
    store = SQLiteStore(":memory:")
    store.record_transition("OPP-001", "DISCOVERED", "SCREENED", cause="scout ok", worker="ScoutWorker")
    store.record_transition("OPP-001", "SCREENED", "WATCHLIST", cause="score high", worker="ScoutWorker")
    # Just verify no errors


def test_sqlite_commit_queue():
    store = SQLiteStore(":memory:")
    store.enqueue_commit("idos-knowledge", "companies/MELI/company.yml", "content here", "Add MELI")
    store.enqueue_commit("idos-journal", "companies/MELI/case_file/case_file.yml", "content", "Init case")
    pending = store.get_pending_commits()
    assert len(pending) == 2
    store.mark_commit_done(pending[0]["id"])
    remaining = store.get_pending_commits()
    assert len(remaining) == 1


def test_knowledge_repository():
    with tempfile.TemporaryDirectory() as tmp:
        repo = KnowledgeRepository(Path(tmp))
        repo.save_company("MELI", {"ticker": "MELI", "name": "MercadoLibre"})
        assert repo.exists("MELI")
        data = repo.load_company("MELI")
        assert data["ticker"] == "MELI"
        assert not repo.exists("UNKNOWN")


def test_journal_repository():
    with tempfile.TemporaryDirectory() as tmp:
        repo = JournalRepository(Path(tmp))
        repo.save_case_file("MELI", {"ticker": "MELI", "opportunity_ids": []})
        cf = repo.load_case_file("MELI")
        assert cf["ticker"] == "MELI"
        repo.save_opportunity("MELI", {"id": "OPP-001", "ticker": "MELI", "status": "DISCOVERED"})
        opp = repo.load_opportunity("MELI", "OPP-001")
        assert opp["id"] == "OPP-001"
