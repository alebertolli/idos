"""End-to-end test of the full investment lifecycle.

Simulates the complete pipeline from DISCOVERED to ARCHIVED,
validating every state transition and worker execution.
Uses tmp_path for isolation and mock LLM clients to avoid network calls.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from idos.data.journal import JournalRepository
from idos.data.knowledge import KnowledgeRepository
from idos.data.sqlite import SQLiteStore
from idos.discovery.scout import ScoutEngine
from idos.models.enums import OpportunityStatus
from idos.portfolio.exit import ExitEngine
from idos.state.machine import OpportunityStateMachine
from idos.workers.ai.decision_board_worker import DecisionBoardWorker
from idos.workers.ai.research_worker import ResearchWorker
from idos.workers.learning.post_mortem_worker import PostMortemWorker
from idos.workers.portfolio.entry_monitor_worker import EntryMonitorWorker

pytestmark = pytest.mark.e2e


class TestFullLifecycle:
    """Complete lifecycle: DISCOVERED → SCREENED → WATCHLIST → UNDER_DEEP_DD
    → APPROVED → ENTRY_PENDING → ACCUMULATING → FULL_POSITION → MONITORING
    → EXITED → POST_MORTEM → ARCHIVED."""

    def test_full_lifecycle(self, tmp_path: Path, mock_llm_client: MagicMock, base_path: str):
        ticker = "LIFECYCLE"
        opp_id = "OPP-2026-LIFECYCLE-001"
        state_machine = OpportunityStateMachine()

        sqlite = SQLiteStore(tmp_path / "idos.db")
        knowledge = KnowledgeRepository(tmp_path / "idos-knowledge")
        journal = JournalRepository(tmp_path / "idos-journal")

        # ── Step 0: Create company + opportunity ──
        company_path = knowledge.company_path(ticker)
        company_path.mkdir(parents=True, exist_ok=True)
        (company_path / "company.yml").write_text(
            f"ticker: {ticker}\nname: Lifecycle Test\nsector: Technology\n",
            encoding="utf-8",
        )

        opp = {
            "id": opp_id,
            "ticker": ticker,
            "status": OpportunityStatus.DISCOVERED.value,
            "conviction": {"overall": 70, "intrinsic_value": 130, "current_price": 95},
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        sqlite.save_opportunity(opp)
        journal.save_opportunity(ticker, opp)
        assert sqlite.get_opportunity(opp_id)["status"] == "DISCOVERED"

        # ── Step 1: DISCOVERED → SCREENED → WATCHLIST (Scout) ──
        scout = ScoutEngine(min_score=30)
        scout_result = scout.scan(ticker, data={"metrics": {
            "market_cap": 10_000_000_000,
            "avg_volume": 5_000_000,
            "pe_ratio": 15,
            "ev_ebitda": 10,
            "roic": 22,
            "operating_margin": 25,
            "debt_to_equity": 0.3,
            "revenue_growth": 12,
        }})

        assert scout_result.passed, f"Scout should pass: {scout_result.reason}"

        for status in ["SCREENED", "WATCHLIST"]:
            transition = state_machine.transition(
                OpportunityStatus(opp["status"]), OpportunityStatus(status),
                cause="scout_passed", worker="scout",
            )
            opp["status"] = status
            opp["updated_at"] = "2026-01-01T00:00:01"
            sqlite.save_opportunity(opp)
            sqlite.record_transition(opp_id, transition.from_status.value,
                                     transition.to_status.value,
                                     cause=transition.cause, worker=transition.worker)

        assert sqlite.get_opportunity(opp_id)["status"] == "WATCHLIST"

        # ── Step 2: WATCHLIST → UNDER_DEEP_DD (ResearchWorker) ──
        rw = ResearchWorker({"provider": "test"})
        rw.llm = mock_llm_client
        rw.registry = MagicMock()
        registry_side_effects = {
            "ddd": "FASE 0 - clasificacion oportunidad for {ticker} ({name})",
            "hypothesis": "Genera hipotesis de inversion para {ticker}",
            "aoif": "AOIF 8-step protocol for {ticker} ({name})",
        }
        rw.registry.get.side_effect = lambda name, category="research", d=registry_side_effects: d.get(name, "template {ticker}")
        rw.registry.get_system.return_value = "system"

        rw_result = rw.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "base_path": base_path,
        })
        assert rw_result.status == "success"
        assert rw_result.output["status"] == "completed"
        assert sqlite.get_opportunity(opp_id)["status"] == "UNDER_DEEP_DD"

        # ── Step 3: UNDER_DEEP_DD → APPROVED (DecisionBoardWorker) ──
        dbw = DecisionBoardWorker({"provider": "test"})
        dbw.llm = mock_llm_client

        dbw_result = dbw.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "base_path": base_path,
        })
        assert dbw_result.status == "success"
        assert dbw_result.output["decision"] == "APPROVED"
        assert sqlite.get_opportunity(opp_id)["status"] == "APPROVED"

        # ── Step 4: APPROVED → ENTRY_PENDING → ACCUMULATING (EntryMonitorWorker) ──
        emw = EntryMonitorWorker({"provider": "test", "prompts_path": base_path})
        emw.entry_engine.min_margin_of_safety = 20.0

        from idos.portfolio.wyckoff import WyckoffPhase
        with patch.object(emw.entry_engine.wyckoff, "analyze",
                          return_value=WyckoffPhase.ACCUMULATION):
            emw_result = emw.execute({
                "ticker": ticker,
                "opp_id": opp_id,
                "base_path": base_path,
            })
        assert emw_result.status == "success"
        assert emw_result.output["entry_executed"] is True
        assert sqlite.get_opportunity(opp_id)["status"] == "ACCUMULATING"

        # ── Step 5: ACCUMULATING → FULL_POSITION ──
        opp = sqlite.get_opportunity(opp_id)
        for status in ["FULL_POSITION"]:
            transition = state_machine.transition(
                OpportunityStatus(opp["status"]), OpportunityStatus(status),
                cause="target_position_reached", worker="system",
            )
            opp["status"] = status
            opp["updated_at"] = "2026-01-01T00:00:02"
            sqlite.save_opportunity(opp)
            sqlite.record_transition(opp_id, transition.from_status.value,
                                     transition.to_status.value,
                                     cause=transition.cause, worker=transition.worker)

        assert sqlite.get_opportunity(opp_id)["status"] == "FULL_POSITION"

        # ── Step 6: FULL_POSITION → MONITORING ──
        transition = state_machine.transition(
            OpportunityStatus(opp["status"]), OpportunityStatus.MONITORING,
            cause="position_established", worker="system",
        )
        opp["status"] = "MONITORING"
        opp["updated_at"] = "2026-01-01T00:00:03"
        sqlite.save_opportunity(opp)
        sqlite.record_transition(opp_id, transition.from_status.value,
                                 transition.to_status.value,
                                 cause=transition.cause, worker=transition.worker)

        assert sqlite.get_opportunity(opp_id)["status"] == "MONITORING"

        # ── Step 7: MONITORING → EXITED (via ExitEngine) ──
        exit_engine = ExitEngine()
        exit_signal = exit_engine.evaluate_thesis_exit(ticker, thesis_active=False)
        assert exit_signal is not None
        assert exit_signal.should_exit is True

        transition = state_machine.transition(
            OpportunityStatus(opp["status"]), OpportunityStatus.EXITED,
            cause="thesis_broken", worker="exit_engine",
        )
        opp["status"] = "EXITED"
        opp["updated_at"] = "2026-01-01T00:00:04"
        sqlite.save_opportunity(opp)
        sqlite.record_transition(opp_id, transition.from_status.value,
                                 transition.to_status.value,
                                 cause=transition.cause, worker=transition.worker)

        assert sqlite.get_opportunity(opp_id)["status"] == "EXITED"

        # ── Step 8: EXITED → POST_MORTEM → ARCHIVED (PostMortemWorker) ──
        pos = {"ticker": ticker, "status": "ACTIVE", "avg_entry_price": 95.0,
               "weight_pct": 2.5, "shares": 100}
        journal.save_position(ticker, pos)

        ass = {"id": "ass-lc", "engine": "ResearchWorker", "score": 82,
               "status": "COMPLETED", "findings": ["Thesis: compounder"],
               "generated_at": "2026-01-01T00:00:00"}
        journal.save_assessment(ticker, opp_id, ass)

        dec = {"id": "dec-lc", "type": "BUY", "ticker": ticker, "opp_id": opp_id,
               "rationale": "Entry", "price": 95.0, "generated_at": "2026-01-01T00:00:00"}
        journal.save_decision(ticker, opp_id, dec)

        pmw = PostMortemWorker({"provider": "test"})
        pmw.llm = mock_llm_client

        pmw_result = pmw.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "exit_reason": "thesis_broken",
            "base_path": base_path,
        })
        assert pmw_result.status == "success"
        assert pmw_result.output["status"] == "completed"
        assert pmw_result.output["archived"] is True

        # ── Final check: ARCHIVED ──
        final_opp = sqlite.get_opportunity(opp_id)
        assert final_opp["status"] == OpportunityStatus.ARCHIVED.value, \
            f"Expected ARCHIVED, got {final_opp['status']}"

        # ── Verify all transitions recorded ──
        rows = list(sqlite.conn.execute(
            "SELECT from_status, to_status FROM state_transitions "
            "WHERE opportunity_id = ? ORDER BY id",
            (opp_id,),
        ))
        recorded = [(r["from_status"], r["to_status"]) for r in rows]
        expected_sequence = [
            ("DISCOVERED", "SCREENED"),
            ("SCREENED", "WATCHLIST"),
            ("WATCHLIST", "UNDER_DEEP_DD"),
            ("UNDER_DEEP_DD", "APPROVED"),
            ("APPROVED", "ENTRY_PENDING"),
            ("ENTRY_PENDING", "ACCUMULATING"),
            ("ACCUMULATING", "FULL_POSITION"),
            ("FULL_POSITION", "MONITORING"),
            ("MONITORING", "EXITED"),
            ("EXITED", "POST_MORTEM"),
            ("POST_MORTEM", "ARCHIVED"),
        ]
        for expected in expected_sequence:
            assert expected in recorded, f"Missing transition: {expected}"

    def test_lifecycle_with_rejection(
        self, tmp_path: Path, mock_llm_reject_client: MagicMock, base_path: str
    ):
        """Opportunity rejected by DecisionBoard returns to WATCHLIST."""
        ticker = "REJECT"
        opp_id = "OPP-2026-REJECT-001"

        sqlite = SQLiteStore(tmp_path / "idos.db")
        journal = JournalRepository(tmp_path / "idos-journal")

        opp = {
            "id": opp_id,
            "ticker": ticker,
            "status": OpportunityStatus.UNDER_DEEP_DD.value,
            "conviction": {"overall": 45},
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        sqlite.save_opportunity(opp)

        ass = {
            "id": "ass-rej",
            "engine": "ResearchWorker",
            "score": 45,
            "status": "COMPLETED",
            "findings": ["Low quality"],
            "generated_at": "2026-01-01T00:00:00",
        }
        journal.save_assessment(ticker, opp_id, ass)

        dbw = DecisionBoardWorker({"provider": "test"})
        dbw.llm = mock_llm_reject_client

        result = dbw.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "base_path": base_path,
        })

        assert result.status == "success"
        assert result.output["decision"] == "WATCHLIST"
        assert sqlite.get_opportunity(opp_id)["status"] == "WATCHLIST"
