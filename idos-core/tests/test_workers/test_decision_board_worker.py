from unittest.mock import MagicMock

from idos.models.enums import OpportunityStatus
from idos.workers.ai.decision_board_worker import DecisionBoardWorker
from idos.workers.base import WorkerStatus


def test_legacy_worker_skips_without_changing_opportunity_or_saving_decision(
    seeded_opportunity_under_dd: tuple[str, str],
    mock_llm_client: MagicMock,
    base_path: str,
    tmp_sqlite,
    tmp_journal,
):
    ticker, opp_id = seeded_opportunity_under_dd
    before = tmp_sqlite.get_opportunity(opp_id)

    result = DecisionBoardWorker({"llm_service": mock_llm_client}).execute({
        "ticker": ticker,
        "opp_id": opp_id,
        "base_path": base_path,
    })

    assert result.status == WorkerStatus.SKIPPED
    assert result.output["reason"] == "legacy_automatic_decision_disabled"
    assert tmp_sqlite.get_opportunity(opp_id) == before
    decisions_dir = tmp_journal.opportunity_path(ticker, opp_id) / "decisions"
    assert not decisions_dir.exists()
    mock_llm_client.generate_structured.assert_not_called()


def test_legacy_worker_skip_is_independent_of_status_and_provider_config(
    base_path: str,
    tmp_sqlite,
    mock_llm_reject_client: MagicMock,
):
    for index, status in enumerate((OpportunityStatus.UNDER_RESEARCH, OpportunityStatus.APPROVED)):
        opp_id = f"OPP-LEGACY-{index}"
        tmp_sqlite.save_opportunity({
            "id": opp_id,
            "ticker": f"LEGACY{index}",
            "status": status.value,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        })
        before = tmp_sqlite.get_opportunity(opp_id)

        result = DecisionBoardWorker({"provider": "test", "llm_service": mock_llm_reject_client}).execute({
            "ticker": f"LEGACY{index}",
            "opp_id": opp_id,
            "base_path": base_path,
        })

        assert result.status == WorkerStatus.SKIPPED
        assert tmp_sqlite.get_opportunity(opp_id) == before
    mock_llm_reject_client.generate_structured.assert_not_called()
