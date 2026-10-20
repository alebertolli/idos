from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from idos.models.enums import OpportunityStatus
from idos.workers.portfolio.entry_monitor_worker import EntryMonitorWorker


class TestEntryMonitorWorker:
    def test_accumulates_when_conditions_met(
        self,
        seeded_opportunity_approved: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_sqlite,
    ):
        ticker, opp_id = seeded_opportunity_approved

        opp = tmp_sqlite.get_opportunity(opp_id)
        opp["conviction"]["intrinsic_value"] = 130
        opp["conviction"]["current_price"] = 95
        tmp_sqlite.save_opportunity(opp)

        worker = EntryMonitorWorker({
            "provider": "test",
            "prompts_path": base_path,
        })
        worker.entry_engine.min_margin_of_safety = 20.0

        from idos.portfolio.wyckoff import WyckoffPhase, WyckoffResult
        wyckoff_mock = MagicMock()
        wyckoff_mock.is_entry_confirmed.return_value = True
        wyckoff_mock.analyze.return_value = WyckoffResult(
            phase=WyckoffPhase.ACCUMULATION,
            score=85,
            confidence_label="alta",
            entry_point="lps",
        )
        wyckoff_mock._analyze_algorithmic.return_value = WyckoffPhase.ACCUMULATION
        worker.entry_engine.wyckoff = wyckoff_mock

        with patch.object(worker.entry_engine.wyckoff, "analyze",
                          return_value=WyckoffResult(
                              phase=WyckoffPhase.ACCUMULATION,
                              score=85,
                              confidence_label="alta",
                              entry_point="lps",
                          )):
            result = worker.execute({
                "ticker": ticker,
                "opp_id": opp_id,
                "base_path": base_path,
            })

        assert result.status == "success"
        output = result.output
        assert output["entry_executed"] is True
        assert output["wyckoff_confirmed"] is True
        assert output["price_in_zone"] is True

        # La transicion a ACCUMULATING la ejecuta el PaperTraderWorker (post-entry).
        opp_after = tmp_sqlite.get_opportunity(opp_id)
        assert opp_after["status"] == OpportunityStatus.ENTRY_PENDING.value

    def test_blocks_when_price_out_of_zone(
        self,
        seeded_opportunity_approved: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_sqlite,
    ):
        ticker, opp_id = seeded_opportunity_approved

        opp = tmp_sqlite.get_opportunity(opp_id)
        opp["intrinsic_value"] = 100
        opp["current_price"] = 98
        tmp_sqlite.save_opportunity(opp)

        worker = EntryMonitorWorker({
            "provider": "test",
            "prompts_path": base_path,
        })
        worker.entry_engine.min_margin_of_safety = 30.0

        from idos.portfolio.wyckoff import WyckoffPhase, WyckoffResult
        with patch.object(worker.entry_engine.wyckoff, "analyze",
                          return_value=WyckoffResult(
                              phase=WyckoffPhase.ACCUMULATION,
                              score=85,
                              confidence_label="alta",
                          )):
            result = worker.execute({
                "ticker": ticker,
                "opp_id": opp_id,
                "base_path": base_path,
            })

        assert result.status == "success"
        output = result.output
        assert output["entry_executed"] is False
        assert output["price_in_zone"] is False

    def test_skips_wrong_state(
        self,
        tmp_sqlite,
        base_path: str,
    ):
        ticker = "TEST"
        opp_id = "OPP-SKIP"
        opp = {
            "id": opp_id,
            "ticker": ticker,
            "status": OpportunityStatus.WATCHLIST.value,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        tmp_sqlite.save_opportunity(opp)

        worker = EntryMonitorWorker({"provider": "test", "prompts_path": base_path})

        result = worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "base_path": base_path,
        })

        assert result.status == "success"
        assert result.output["status"] == "skipped"

    def test_margin_of_safety_calculated(
        self,
        seeded_opportunity_approved: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_sqlite,
    ):
        ticker, opp_id = seeded_opportunity_approved

        opp = tmp_sqlite.get_opportunity(opp_id)
        opp["intrinsic_value"] = 200
        opp["current_price"] = 100
        tmp_sqlite.save_opportunity(opp)

        worker = EntryMonitorWorker({
            "provider": "test",
            "prompts_path": base_path,
        })
        worker.entry_engine.min_margin_of_safety = 30.0

        from idos.portfolio.wyckoff import WyckoffPhase, WyckoffResult
        with patch.object(worker.entry_engine.wyckoff, "analyze",
                          return_value=WyckoffResult(
                              phase=WyckoffPhase.ACCUMULATION,
                              score=85,
                              confidence_label="alta",
                          )):
            result = worker.execute({
                "ticker": ticker,
                "opp_id": opp_id,
                "base_path": base_path,
            })

        assert result.status == "success"
        assert result.output["margin_of_safety_pct"] == 100.0

    def test_uses_fresh_price_history_close_over_stored_current_price(
        self,
        seeded_opportunity_approved: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_sqlite,
    ):
        ticker, opp_id = seeded_opportunity_approved

        opp = tmp_sqlite.get_opportunity(opp_id)
        opp["intrinsic_value"] = 200
        opp["current_price"] = 100  # precio viejo almacenado
        tmp_sqlite.save_opportunity(opp)

        # price_history más reciente que el current_price almacenado
        tmp_sqlite.save_price_history(ticker, [
            {"date": "2026-07-31", "close": 90.0, "volume": 1000},
            {"date": "2026-08-03", "close": 80.0, "volume": 1000},
        ])

        worker = EntryMonitorWorker({
            "provider": "test",
            "prompts_path": base_path,
        })
        worker.entry_engine.min_margin_of_safety = 30.0

        from idos.portfolio.wyckoff import WyckoffPhase, WyckoffResult
        with patch.object(worker.entry_engine.wyckoff, "analyze",
                          return_value=WyckoffResult(
                              phase=WyckoffPhase.ACCUMULATION,
                              score=85,
                              confidence_label="alta",
                          )):
            result = worker.execute({
                "ticker": ticker,
                "opp_id": opp_id,
                "base_path": base_path,
            })

        assert result.status == "success"
        output = result.output
        assert output["current_price"] == 80.0
        assert output["margin_of_safety_pct"] == pytest.approx((200 - 80) / 80 * 100, rel=1e-6)

    def test_approves_to_entry_pending(
        self,
        seeded_opportunity_approved: tuple[str, str],
        base_path: str,
        tmp_sqlite,
    ):
        ticker, opp_id = seeded_opportunity_approved
        worker = EntryMonitorWorker({"provider": "test", "prompts_path": base_path})

        from idos.portfolio.wyckoff import WyckoffPhase, WyckoffResult
        with patch.object(worker.entry_engine.wyckoff, "analyze",
                          return_value=WyckoffResult(
                              phase=WyckoffPhase.ACCUMULATION,
                              score=85,
                              confidence_label="alta",
                          )):
            result = worker.execute({
                "ticker": ticker,
                "opp_id": opp_id,
                "base_path": base_path,
            })

        transitions = list(tmp_sqlite.conn.execute(
            "SELECT from_status, to_status FROM state_transitions WHERE opportunity_id = ?",
            (opp_id,),
        ))
        statuses = [(r["from_status"], r["to_status"]) for r in transitions]
        assert ("APPROVED", "ENTRY_PENDING") in statuses
