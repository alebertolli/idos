"""Tests del ciclo de vida de hipótesis (SDD-6 §9) y la cascade.

Cubre:
  - HypothesisStateMachine.close_hypothesis: CLOSED solo desde CONFIRMED/INVALIDATED.
  - apply_hypothesis_cascade: solo la hipótesis principal INVALIDADA activa la
    salida total (EXITED); CLOSED de una hipótesis NO cierra la oportunidad.
"""
from pathlib import Path

import pytest

from idos.core.errors import StateTransitionError
from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.models.enums import HypothesisStatus, OpportunityStatus
from idos.research.lifecycle import HypothesisStateMachine, apply_hypothesis_cascade


@pytest.fixture
def repos(tmp_path: Path) -> tuple[SQLiteStore, JournalRepository]:
    sqlite = SQLiteStore(tmp_path / "idos.db")
    journal = JournalRepository(tmp_path / "idos-journal")
    return sqlite, journal


def _seed_opportunity(sqlite: SQLiteStore, status: str = OpportunityStatus.MONITORING.value,
                      ticker: str = "HYP", opp_id: str = "OPP-HYP-001") -> None:
    sqlite.save_opportunity({
        "id": opp_id,
        "ticker": ticker,
        "status": status,
        "conviction": {"overall": 70},
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    })


def _principal(status: str) -> dict:
    return {
        "id": "H-PRINCIPAL",
        "parent_id": "",
        "status": status,
        "statement": "Tesis principal",
        "opportunity_id": "OPP-HYP-001",
    }


def _secondary(status: str) -> dict:
    return {
        "id": "H-SEC",
        "parent_id": "H-PRINCIPAL",
        "status": status,
        "statement": "Tesis secundaria",
        "opportunity_id": "OPP-HYP-001",
    }


class TestCloseHypothesis:
    def test_closed_solo_desde_confirmed_o_invalidated(self):
        sm = HypothesisStateMachine()
        for src in (HypothesisStatus.CONFIRMED, HypothesisStatus.INVALIDATED):
            t = sm.close_hypothesis(src, cause="archivo", worker="test")
            assert t.to_status == HypothesisStatus.CLOSED
            assert t.cause == "archivo"

    def test_cerrar_desde_activo_rechazado(self):
        sm = HypothesisStateMachine()
        for src in (HypothesisStatus.ACTIVE, HypothesisStatus.WEAKENING,
                    HypothesisStatus.AT_RISK, HypothesisStatus.DRAFT,
                    HypothesisStatus.STRENGTHENING, HypothesisStatus.CLOSED):
            with pytest.raises(StateTransitionError):
                sm.close_hypothesis(src)

    def test_closed_es_estado_terminal(self):
        sm = HypothesisStateMachine()
        assert len(sm._allowed[HypothesisStatus.CLOSED]) == 0


class TestApplyCascade:
    def test_principal_invalidada_exita_la_oportunidad(self, repos):
        sqlite, journal = repos
        _seed_opportunity(sqlite)
        result = apply_hypothesis_cascade(
            journal, sqlite, "HYP", "OPP-HYP-001",
            _principal(HypothesisStatus.INVALIDATED.value), is_principal=True,
        )
        assert result["cascade"] == "exited"
        assert result["to_status"] == OpportunityStatus.EXITED.value
        opp = sqlite.get_opportunity("OPP-HYP-001")
        assert opp["status"] == OpportunityStatus.EXITED.value
        assert opp["exit_reason"] == "hypothesis_invalidated"

    def test_secundaria_invalidada_no_cierra_oportunidad(self, repos):
        sqlite, journal = repos
        _seed_opportunity(sqlite)
        result = apply_hypothesis_cascade(
            journal, sqlite, "HYP", "OPP-HYP-001",
            _secondary(HypothesisStatus.INVALIDATED.value), is_principal=False,
        )
        assert result["cascade"] == "none"
        assert sqlite.get_opportunity("OPP-HYP-001")["status"] == "MONITORING"

    def test_principal_closed_no_cierra_oportunidad(self, tmp_path):
        sqlite, journal = SQLiteStore(tmp_path / "idos.db"), \
            JournalRepository(tmp_path / "idos-journal")
        _seed_opportunity(sqlite)
        result = apply_hypothesis_cascade(
            journal, sqlite, "HYP", "OPP-HYP-001",
            _principal(HypothesisStatus.CLOSED.value), is_principal=True,
        )
        assert result["cascade"] == "none"
        assert sqlite.get_opportunity("OPP-HYP-001")["status"] == "MONITORING"

    def test_principal_activa_no_cierra_oportunidad(self, repos):
        sqlite, journal = repos
        _seed_opportunity(sqlite)
        result = apply_hypothesis_cascade(
            journal, sqlite, "HYP", "OPP-HYP-001",
            _principal(HypothesisStatus.ACTIVE.value), is_principal=True,
        )
        assert result["cascade"] == "none"
        assert sqlite.get_opportunity("OPP-HYP-001")["status"] == "MONITORING"

    def test_estado_ya_exited_no_duplica_cascade(self, repos):
        sqlite, journal = repos
        _seed_opportunity(sqlite, status=OpportunityStatus.EXITED.value)
        result = apply_hypothesis_cascade(
            journal, sqlite, "HYP", "OPP-HYP-001",
            _principal(HypothesisStatus.INVALIDATED.value), is_principal=True,
        )
        assert result["cascade"] == "already_exited"

    def test_cascade_registra_evento_de_cambio(self, repos):
        sqlite, journal = repos
        _seed_opportunity(sqlite)
        apply_hypothesis_cascade(
            journal, sqlite, "HYP", "OPP-HYP-001",
            _principal(HypothesisStatus.INVALIDATED.value), is_principal=True,
        )
        rows = list(sqlite.conn.execute(
            "SELECT from_status, to_status, cause FROM state_transitions "
            "WHERE opportunity_id = 'OPP-HYP-001' AND cause = 'hypothesis_invalidated'",
        ))
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["from_status"] == "MONITORING"
        assert row["to_status"] == "EXITED"