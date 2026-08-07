from dataclasses import dataclass
from datetime import datetime
from typing import Any
from idos.models.enums import HypothesisStatus, OpportunityStatus
from idos.state.machine import StateMachine, Transition
from idos.core.errors import StateTransitionError
from idos.timezone import AR_TZ


class HypothesisStateMachine(StateMachine):
    """Ciclo de vida de una hipótesis según SDD-6 §3.

    DRAFT ─► ACTIVE ─► STRENGTHENING ─► CONFIRMED
                │            │              │
                ▼            ▼              ▼
            WEAKENING ─► AT_RISK ─► INVALIDATED
                                        │
                                        ▼
                                      CLOSED

    Reglas de negocio (refinamiento usuario):
      - CLOSED SOLO es alcanzable desde CONFIRMED o INVALIDATED.
      - WEAKENING/AT_RISK no permiten transicionar hacia estados de refuerzo
        (anti-movimiento ascendente tras debilitamiento).
    """

    _transitions: dict[HypothesisStatus, list[HypothesisStatus]] = {
        HypothesisStatus.DRAFT: [HypothesisStatus.ACTIVE, HypothesisStatus.CLOSED],
        HypothesisStatus.ACTIVE: [
            HypothesisStatus.STRENGTHENING, HypothesisStatus.WEAKENING,
            HypothesisStatus.CLOSED,
        ],
        HypothesisStatus.STRENGTHENING: [
            HypothesisStatus.CONFIRMED, HypothesisStatus.WEAKENING, HypothesisStatus.CLOSED,
        ],
        HypothesisStatus.WEAKENING: [HypothesisStatus.AT_RISK, HypothesisStatus.CLOSED],
        HypothesisStatus.AT_RISK: [HypothesisStatus.INVALIDATED, HypothesisStatus.CLOSED],
        HypothesisStatus.CONFIRMED: [HypothesisStatus.CLOSED, HypothesisStatus.WEAKENING],
        HypothesisStatus.INVALIDATED: [HypothesisStatus.CLOSED],
        HypothesisStatus.CLOSED: [],
    }

    def __init__(self):
        super().__init__(self._transitions)

    def close_hypothesis(self, current: HypothesisStatus, cause: str = "",
                         worker: str = "system") -> Transition:
        """Cierre de hipótesis: SOLO desde CONFIRMED o INVALIDATED.

        (SDD-6: CLOSED = caso archivado tras finalización de la oportunidad).
        No se cierra desde WEAKENING/AT_RISK/ACTIVE: cierrar ahí confunde
        'hipótesis archivada' con 'oportunidad cerrada'.
        """
        if current not in (HypothesisStatus.CONFIRMED, HypothesisStatus.INVALIDATED):
            raise StateTransitionError(
                f"No se puede cerrar hipótesis CLOSED desde {current}: "
                "solo CONFIRMED o INVALIDATED pueden cerrarse"
            )
        return Transition(
            from_status=current,
            to_status=HypothesisStatus.CLOSED,
            cause=cause,
            worker=worker,
        )


CASCADE_MAP: dict[HypothesisStatus, OpportunityStatus | None] = {
    # Hipótesis principal invalidada → la tesis rompe → salida total.
    # Lo CASE ccada NO cierra la oportunidad: es solo archivo de la hipótesis.
    HypothesisStatus.INVALIDATED: OpportunityStatus.EXITED,
    HypothesisStatus.CONFIRMED: None,
    HypothesisStatus.CLOSED: None,
}


def apply_hypothesis_cascade(journal_repo: Any, sqlite: Any,
                             ticker: str, opp_id: str,
                             hypothesis: dict[str, Any],
                             is_principal: bool = False) -> dict[str, Any]:
    """Aplica el efecto de una hipótesis sobre la oportunidad.

    - CLOSED de una hipótesis NO cierra la oportunidad (regla de cascade).
    - Solo la hipótesis PRINCIPAL invalidada activa la salida total (EXITED).
    """
    if not is_principal:
        return {"cascade": "none"}

    status = hypothesis.get("status")
    if status != HypothesisStatus.INVALIDATED.value:
        return {"cascade": "none"}

    target = CASCADE_MAP.get(HypothesisStatus.INVALIDATED)
    if target is None:
        return {"cascade": "none"}

    opp = sqlite.get_opportunity(opp_id)
    if not opp:
        return {"cascade": "none"}

    from_status = opp["status"]
    if from_status == target.value:
        return {"cascade": "already_exited"}

    opp["status"] = target.value
    opp["updated_at"] = datetime.now(AR_TZ).isoformat()
    opp["exit_reason"] = "hypothesis_invalidated"
    sqlite.save_opportunity(opp)
    sqlite.record_transition(opp_id, from_status, target.value,
                             cause="hypothesis_invalidated", worker="hypothesis_lifecycle")
    journal_repo.log_event(
        "opportunity:cascade_invalidate",
        {"opp_id": opp_id, "ticker": ticker, "from": from_status, "to": target.value},
        source="hypothesis_lifecycle",
    )
    print(f"[HYP] {ticker} ({opp_id}): hipótesis principal INVALIDATED "
          f"→ oportunidad {from_status} → {target.value}")
    return {"cascade": "exited", "from_status": from_status, "to_status": target.value}