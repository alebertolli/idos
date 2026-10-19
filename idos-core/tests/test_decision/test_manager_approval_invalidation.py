import yaml

from idos.decision.manager_approval import invalidate_manager_approval_after_research


def test_new_research_invalidates_only_matching_buylist_approval_and_keeps_history(tmp_path):
    opp_dir = tmp_path / "idos-journal/companies/TEST/case_file/opportunities/OPP-1"
    opp_dir.mkdir(parents=True)
    opportunity_path = opp_dir / "opportunity.yml"
    opportunity_path.write_text(yaml.safe_dump({
        "id": "OPP-1", "ticker": "TEST", "approved_for_buylist": True,
    }), encoding="utf-8")
    proposal_path = opp_dir / "decision_proposal.yml"
    proposal_path.write_text(yaml.safe_dump({
        "opportunity_id": "OPP-1", "status": "MANAGER_APPROVED",
    }), encoding="utf-8")
    resolution_path = opp_dir / "board_resolution.yml"
    resolution_path.write_text(yaml.safe_dump({
        "approved": True, "status": "approved", "decision_id": "DEC-OLD",
    }), encoding="utf-8")
    decisions_dir = opp_dir / "decisions"
    decisions_dir.mkdir()
    history_path = decisions_dir / "DEC-OLD.yml"
    immutable_history = "approved: true\nstatus: approved\ndecision_id: DEC-OLD\n"
    history_path.write_text(immutable_history, encoding="utf-8")
    buylist_path = tmp_path / "idos-journal/portfolio/buylist.yml"
    buylist_path.parent.mkdir(parents=True)
    buylist_path.write_text(yaml.safe_dump({"entries": [
        {"ticker": "TEST", "opp_id": "OPP-1"},
        {"ticker": "TEST", "opp_id": "OPP-OTHER"},
        {"ticker": "AAPL", "opp_id": "OPP-AAPL"},
    ]}), encoding="utf-8")

    invalidated = invalidate_manager_approval_after_research(
        tmp_path, "TEST", "OPP-1", invalidated_at="2026-10-19T12:00:00-03:00",
    )

    assert invalidated is True
    assert yaml.safe_load(opportunity_path.read_text(encoding="utf-8"))["approved_for_buylist"] is False
    assert yaml.safe_load(proposal_path.read_text(encoding="utf-8"))["status"] == "INVALIDATED_BY_NEW_RESEARCH"
    resolution = yaml.safe_load(resolution_path.read_text(encoding="utf-8"))
    assert resolution["approved"] is False
    assert resolution["decision_id"] == "DEC-OLD"
    entries = yaml.safe_load(buylist_path.read_text(encoding="utf-8"))["entries"]
    assert entries == [
        {"ticker": "TEST", "opp_id": "OPP-OTHER"},
        {"ticker": "AAPL", "opp_id": "OPP-AAPL"},
    ]
    assert history_path.read_text(encoding="utf-8") == immutable_history


def test_research_without_existing_manager_approval_is_a_noop(tmp_path):
    opp_dir = tmp_path / "idos-journal/companies/TEST/case_file/opportunities/OPP-1"
    opp_dir.mkdir(parents=True)
    (opp_dir / "opportunity.yml").write_text(yaml.safe_dump({
        "id": "OPP-1", "ticker": "TEST", "approved_for_buylist": False,
    }), encoding="utf-8")
    buylist_path = tmp_path / "idos-journal/portfolio/buylist.yml"
    buylist_path.parent.mkdir(parents=True)
    buylist_path.write_text(yaml.safe_dump({"entries": [{"ticker": "AAPL", "opp_id": "OPP-AAPL"}]}), encoding="utf-8")

    invalidated = invalidate_manager_approval_after_research(
        tmp_path, "TEST", "OPP-1", invalidated_at="2026-10-19T12:00:00-03:00",
    )

    assert invalidated is False
    assert yaml.safe_load(buylist_path.read_text(encoding="utf-8"))["entries"] == [
        {"ticker": "AAPL", "opp_id": "OPP-AAPL"},
    ]
