import pytest
from idos.resilience.audit import AuditTrail


class TestAuditTrail:
    def test_record_and_count(self):
        at = AuditTrail()
        at.record("CREATE", "opportunity", "opp-1", "analyst-1", {"name": "Test"})
        assert at.count() == 1

    def test_verify_chain_valid(self):
        at = AuditTrail()
        at.record("CREATE", "opp", "1", "alice")
        at.record("UPDATE", "opp", "1", "alice")
        at.record("ARCHIVE", "opp", "1", "bob")
        assert at.verify_chain() is True

    def test_verify_chain_tampered(self):
        at = AuditTrail()
        at.record("CREATE", "opp", "1", "alice")
        at.record("UPDATE", "opp", "1", "alice")
        at._entries[0].details = {"tampered": True}
        assert at.verify_chain() is False

    def test_filter_by_entity(self):
        at = AuditTrail()
        at.record("CREATE", "opp", "1", "alice")
        at.record("CREATE", "decision", "2", "alice")
        assert len(at.get_by_entity("opp", "1")) == 1

    def test_filter_by_actor(self):
        at = AuditTrail()
        at.record("A", "opp", "1", "alice")
        at.record("B", "opp", "2", "bob")
        assert len(at.get_by_actor("alice")) == 1

    def test_filter_by_action(self):
        at = AuditTrail()
        at.record("CREATE", "opp", "1", "alice")
        at.record("DELETE", "opp", "2", "bob")
        assert len(at.get_by_action("CREATE")) == 1
