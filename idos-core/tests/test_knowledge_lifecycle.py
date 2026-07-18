import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from idos.knowledge.claims import Claim, ClaimStore, ClaimStatus, EvidenceCategory
from idos.knowledge.wiki import AtomicWiki, WikiSection, WikiMetadata
from idos.knowledge.lifecycle import KnowledgeLifecycle, KnowledgeObject, KnowledgeStatus
from idos.knowledge.contradiction import ContradictionDetector


def test_claim_create_and_store():
    store = ClaimStore("idon-knoledge")
    claim = Claim(claim_id="CLAIM-001", statement="MELI dominates LatAm e-commerce",
                  confidence=0.92, category=EvidenceCategory.FACT)
    store.put(claim)
    retrieved = store.get("CLAIM-001")
    assert retrieved is not None
    assert retrieved.statement == claim.statement
    assert retrieved.confidence == 0.92
    assert retrieved.status == ClaimStatus.ACTIVE


def test_claim_search():
    store = ClaimStore("idon-knoledge")
    c1 = Claim(claim_id="C-001", statement="Revenue growing 30%+", tags=["growth"])
    c2 = Claim(claim_id="C-002", statement="High debt levels", tags=["risk"])
    store.put(c1)
    store.put(c2)
    results = store.search(tag="growth")
    assert len(results) == 1
    assert results[0].claim_id == "C-001"


def test_claim_deprecate():
    store = ClaimStore("idon-knoledge")
    c = Claim(claim_id="C-DEP", statement="Old prediction")
    store.put(c)
    store.deprecate("C-DEP", "superseded by new data")
    retrieved = store.get("C-DEP")
    assert retrieved.status == ClaimStatus.DEPRECATED


def test_atomic_wiki_set_get():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        wiki = AtomicWiki(tmp)
        section = WikiSection(name="business", content="Leading e-commerce platform")
        section.metadata.confidence = 0.85
        wiki.set_section("TEST", section)
        retrieved = wiki.get_section("TEST", "business")
        assert retrieved is not None
        assert retrieved.content == "Leading e-commerce platform"
        assert retrieved.metadata.confidence == 0.85


def test_atomic_wiki_all_sections():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        wiki = AtomicWiki(tmp)
        for name in ["business", "competition", "risks"]:
            wiki.set_section("TEST", WikiSection(name=name, content=f"Content for {name}"))
        sections = wiki.all_sections("TEST")
        assert len(sections) == 3
        names = [s.name for s in sections]
        assert "business" in names
        assert "competition" in names


def test_knowledge_lifecycle():
    lc = KnowledgeLifecycle()
    obj = KnowledgeObject(object_id="OBJ-001", object_type="wiki", ticker="MELI",
                          content={"section": "business"})
    lc.register(obj)
    assert obj.status == KnowledgeStatus.CREATED
    lc.verify("OBJ-001")
    assert obj.status == KnowledgeStatus.VERIFIED
    lc.publish("OBJ-001")
    assert obj.status == KnowledgeStatus.PUBLISHED
    lc.update_content("OBJ-001", {"new_field": "value"})
    assert obj.version == 2
    assert obj.status == KnowledgeStatus.UPDATED


def test_contradiction_detection():
    d = ContradictionDetector()
    result = d.evaluate("MELI", "Revenue is growing strongly",
                        "Revenue declined 10% this quarter", source="Earnings Q2")
    assert result is not None
    assert result.ticker == "MELI"
    assert result.severity.value == "HIGH"
    assert not result.resolved


def test_no_false_positive():
    d = ContradictionDetector()
    result = d.evaluate("MELI", "MELI dominates LatAm",
                        "Amazon invests in Brazil logistics")
    assert result is None


def test_contradiction_resolve():
    d = ContradictionDetector()
    c = d.evaluate("MELI", "Profit margins expanding",
                   "Operating margin fell 200bps")
    assert c is not None
    assert len(d.unresolved()) == 1
    d.resolve(c.id, "Confirmed by new CFO guidance - temporary dip")
    assert len(d.unresolved()) == 0


def test_knowledge_object_needs_review():
    from datetime import timedelta, datetime, UTC
    now = datetime.now(UTC)
    obj = KnowledgeObject(object_id="OLD", object_type="wiki", ticker="MELI",
                          last_review=(now - timedelta(days=200)).isoformat(),
                          review_frequency_days=90)
    assert obj.needs_review() is True


def test_atomic_wiki_migrate():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        monolith = Path(tmp) / "wiki.md"
        monolith.write_text(
            "## Business\n\nE-commerce leader\n\n---\n\n"
            "## Risks\n\nCurrency risk\n\n---\n\n"
            "## Valuation\n\nPER 25x\n",
            encoding="utf-8"
        )
        wiki = AtomicWiki(tmp)
        wiki.migrate_from_monolith("TEST", monolith)
        sections = wiki.all_sections("TEST")
        assert len(sections) >= 2
        names = [s.name for s in sections]
        assert "business" in names
        assert "risks" in names


if __name__ == "__main__":
    test_claim_create_and_store()
    test_claim_search()
    test_claim_deprecate()
    test_atomic_wiki_set_get()
    test_atomic_wiki_all_sections()
    test_knowledge_lifecycle()
    test_contradiction_detection()
    test_no_false_positive()
    test_contradiction_resolve()
    test_knowledge_object_needs_review()
    test_atomic_wiki_migrate()
    print("ALL KNOWLEDGE LIFECYCLE TESTS PASSED")
