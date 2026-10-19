import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from idos.decision.pipeline import DecisionPipeline, PipelineContext, PipelineStage
from idos.decision.inbox import DecisionInbox, InboxPriority, InboxStatus


def test_pipeline_full_run():
    pipe = DecisionPipeline()
    ctx = PipelineContext(event_type="scout_completed", ticker="MELI")
    result = pipe.run(ctx)
    assert result.completed_at != ""
    assert result.findings.get("classified_as") == "scout_completed"
    assert result.findings.get("relevant") is True
    assert len(result.rules_applied) == 2


def test_pipeline_no_ticker():
    pipe = DecisionPipeline()
    ctx = PipelineContext(event_type="unknown", ticker="")
    result = pipe.run(ctx)
    assert result.findings.get("relevant") is False
    assert result.proposal.get("action") == "ignore"


def test_inbox_add():
    inbox = DecisionInbox()
    item = inbox.add("Review GOOGL opportunity", priority=InboxPriority.HIGH, ticker="GOOGL")
    assert item.id.startswith("INBOX-")
    assert item.status == InboxStatus.PENDING


def test_inbox_approve():
    inbox = DecisionInbox()
    item = inbox.add("Test approval", ticker="TEST")
    inbox.approve(item.id, "Looks good")
    retrieved = inbox.get(item.id)
    assert retrieved.status == InboxStatus.APPROVED
    assert retrieved.resolution == "Looks good"


def test_inbox_reject():
    inbox = DecisionInbox()
    item = inbox.add("Test rejection")
    inbox.reject(item.id, "Not enough evidence")
    retrieved = inbox.get(item.id)
    assert retrieved.status == InboxStatus.REJECTED


def test_inbox_urgent():
    inbox = DecisionInbox()
    inbox.add("Low priority", priority=InboxPriority.LOW)
    inbox.add("Urgent", priority=InboxPriority.HIGH)
    assert len(inbox.urgent()) == 1


def test_inbox_pending():
    inbox = DecisionInbox()
    inbox.add("Item 1")
    inbox.add("Item 2")
    item3 = inbox.add("Item 3")
    inbox.approve(item3.id)
    assert len(inbox.pending()) == 2


def test_inbox_ordering():
    inbox = DecisionInbox()
    inbox.add("Low", priority=InboxPriority.LOW)
    inbox.add("High", priority=InboxPriority.HIGH)
    all_items = inbox.all()
    assert all_items[0].priority == InboxPriority.HIGH
    assert all_items[-1].priority == InboxPriority.LOW
