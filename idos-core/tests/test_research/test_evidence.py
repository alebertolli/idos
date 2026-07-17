from idos.research.evidence import EvidenceChainManager
from idos.models.enums import EvidenceType, ConfidenceLevel


def test_add_and_get_evidence():
    mgr = EvidenceChainManager()
    ev = mgr.add_evidence("ROIC improved to 28%", "Annual Report 2025", "2025-12-31",
                          EvidenceType.FINANCIAL, ConfidenceLevel.HIGH)
    assert ev.description == "ROIC improved to 28%"
    assert mgr.count() == 1
    loaded = mgr.get_evidence(ev.id)
    assert loaded is not None


def test_evidence_chain():
    mgr = EvidenceChainManager()
    ev1 = mgr.add_evidence("Revenue grew 22%", "10-K", "2025-12-31")
    ev2 = mgr.add_evidence("Margin expanded 300bps", "10-K", "2025-12-31")
    mgr.link("THESIS-001", ev1.id)
    mgr.link("THESIS-001", ev2.id)
    chain = mgr.get_chain("THESIS-001")
    assert len(chain) == 2


def test_link_not_found():
    mgr = EvidenceChainManager()
    import pytest
    with pytest.raises(ValueError):
        mgr.link("TARGET", "INVALID")
