from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from idos.models.enums import OpportunityStatus
from idos.core.errors import StateTransitionError
from idos.timezone import AR_TZ

GuardFn = Callable[[dict[str, Any]], tuple[bool, str]]

@dataclass
class Transition:
    from_status: OpportunityStatus
    to_status: OpportunityStatus
    timestamp: datetime = field(default_factory=lambda: datetime.now(AR_TZ))
    cause: str = ""
    worker: str = "system"

class StateMachine:
    def __init__(self, allowed_transitions: dict[OpportunityStatus, list[OpportunityStatus]]):
        self._allowed = allowed_transitions

    def can_transition(self, current: OpportunityStatus, target: OpportunityStatus) -> bool:
        return target in self._allowed.get(current, [])

    def transition(self, current: OpportunityStatus, target: OpportunityStatus, cause: str = "", worker: str = "system") -> Transition:
        if not self.can_transition(current, target):
            raise StateTransitionError(f"Cannot transition from {current} to {target}")
        return Transition(
            from_status=current,
            to_status=target,
            cause=cause,
            worker=worker,
        )

def _combined_guard(ctx: dict, checks: list) -> tuple[bool, str]:
    for key, expected, msg in checks:
        val = ctx.get(key)
        if callable(expected):
            if not expected(val):
                return False, msg
        elif val != expected:
            return False, msg
    return True, "All guards passed"


class OpportunityStateMachine(StateMachine):
    _transitions: dict[OpportunityStatus, list[OpportunityStatus]] = {
        OpportunityStatus.DISCOVERED: [OpportunityStatus.SCREENED],
        OpportunityStatus.SCREENED: [OpportunityStatus.WATCHLIST, OpportunityStatus.ARCHIVED],
        OpportunityStatus.WATCHLIST: [OpportunityStatus.UNDER_RESEARCH, OpportunityStatus.ARCHIVED],
        OpportunityStatus.UNDER_RESEARCH: [OpportunityStatus.UNDER_RESEARCH, OpportunityStatus.WATCHLIST],
        OpportunityStatus.UNDER_DEEP_DD: [OpportunityStatus.APPROVED, OpportunityStatus.WATCHLIST],
        OpportunityStatus.APPROVED: [OpportunityStatus.ENTRY_PENDING, OpportunityStatus.WATCHLIST],
        OpportunityStatus.ENTRY_PENDING: [OpportunityStatus.ACCUMULATING, OpportunityStatus.WATCHLIST],
        OpportunityStatus.ACCUMULATING: [OpportunityStatus.FULL_POSITION, OpportunityStatus.EXITED, OpportunityStatus.MONITORING],
        OpportunityStatus.FULL_POSITION: [OpportunityStatus.MONITORING, OpportunityStatus.REDUCING],
        OpportunityStatus.MONITORING: [OpportunityStatus.REDUCING, OpportunityStatus.EXITED, OpportunityStatus.FULL_POSITION],
        OpportunityStatus.REDUCING: [OpportunityStatus.EXITED, OpportunityStatus.MONITORING],
        OpportunityStatus.EXITED: [OpportunityStatus.POST_MORTEM],
        OpportunityStatus.POST_MORTEM: [OpportunityStatus.ARCHIVED],
        OpportunityStatus.ARCHIVED: [],
    }

    def __init__(self):
        super().__init__(self._transitions)
        self._guards: dict[tuple[OpportunityStatus, OpportunityStatus], GuardFn] = {}
        self._register_default_guards()

    def _register_default_guards(self):
        self.register_guard(
            OpportunityStatus.DISCOVERED, OpportunityStatus.SCREENED,
            lambda ctx: (bool(ctx.get("metrics")), "No basic metrics available"),
        )
        self.register_guard(
            OpportunityStatus.SCREENED, OpportunityStatus.WATCHLIST,
            lambda ctx: (ctx.get("screen_score", 0) >= 30, f"Screen score {ctx.get('screen_score', 0)} < 30"),
        )
        self.register_guard(
            OpportunityStatus.WATCHLIST, OpportunityStatus.UNDER_RESEARCH,
            lambda ctx: (ctx.get("conviction", 0) >= 20, f"Conviction {ctx.get('conviction', 0)} < 20"),
        )
        self.register_guard(
            OpportunityStatus.UNDER_RESEARCH, OpportunityStatus.UNDER_DEEP_DD,
            lambda ctx: (ctx.get("conviction", 0) >= 40, f"Conviction {ctx.get('conviction', 0)} < 40"),
        )
        self.register_guard(
            OpportunityStatus.UNDER_DEEP_DD, OpportunityStatus.APPROVED,
            lambda ctx: _combined_guard(ctx, [
                ("case_file_exists", True, "Principio 1 violado: No existe Case File documentado"),
                ("hypotheses_count", lambda v: v >= 1, "Principio 1 violado: No hay árbol de hipótesis estructurado"),
                ("assessments_complete", True, "No todas las evaluaciones completadas (business, technical, valuation)"),
            ]),
        )
        def _entry_guard(ctx: dict) -> tuple[bool, str]:
            base_passed, base_msg = _combined_guard(ctx, [
                ("thesis_active", True, "Tesis no esta activa"),
                ("price_in_zone", True, "Precio fuera de zona de margen de seguridad"),
                ("wyckoff_confirmed", True, "Estructura tecnica no confirmada"),
                ("is_averaging_down", False, "Principio 3 violado: No promediar a la baja sin reevaluacion"),
            ])
            if not base_passed:
                return base_passed, base_msg
            score = ctx.get("wyckoff_score", 100)
            min_score = int(ctx.get("min_wyckoff_score", 45))
            if score < min_score:
                return False, f"Score tecnicidad {score} < {min_score}"
            return True, "All guards passed"

        self.register_guard(
            OpportunityStatus.ENTRY_PENDING, OpportunityStatus.ACCUMULATING,
            _entry_guard,
        )
        self.register_guard(
            OpportunityStatus.EXITED, OpportunityStatus.POST_MORTEM,
            lambda ctx: (
                ctx.get("post_mortem_ready", False),
                "Post-mortem document not completed",
            ),
        )

    def register_guard(self, from_status: OpportunityStatus, to_status: OpportunityStatus, guard_fn: GuardFn):
        self._guards[(from_status, to_status)] = guard_fn

    def transition(self, current: OpportunityStatus, target: OpportunityStatus,
                   cause: str = "", worker: str = "system",
                   context: dict[str, Any] | None = None) -> Transition:
        if not self.can_transition(current, target):
            raise StateTransitionError(f"Cannot transition from {current} to {target}")

        guard = self._guards.get((current, target))
        if guard:
            passed, reason = guard(context or {})
            if not passed:
                raise StateTransitionError(f"Guard blocked: {reason}")

        return Transition(
            from_status=current,
            to_status=target,
            cause=cause,
            worker=worker,
        )

    def get_next_states(self, current: OpportunityStatus) -> list[OpportunityStatus]:
        return self._allowed.get(current, [])
