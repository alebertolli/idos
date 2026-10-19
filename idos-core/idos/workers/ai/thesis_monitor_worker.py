from datetime import datetime
from pathlib import Path
from typing import Any

from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.workers.base import BaseWorker
from idos.timezone import AR_TZ
from idos.workers.ai.research_worker import ResearchWorker


class ThesisMonitorWorker(BaseWorker):
    """Re-assesses the integrity of an investment thesis (Thesis Exit / Risk Exit).

    Coordinates a thesis review through ResearchWorker and persists its result.
    It does not create an LLM client or perform investment analysis itself.

    Triggers: monthly schedule (re-assessment) + risk triggers (Risk Exit).
    """
    name = "thesis_monitor_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        cfg = config or {}
        self.research = cfg.get("research_worker") or ResearchWorker(cfg)

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "").upper().strip()
        opp_id = context.get("opp_id", "")
        trigger_source = context.get("trigger_source", "manual")
        base_path = context.get("base_path", "")
        if not ticker:
            raise ValueError("ticker required")

        bp = Path(base_path) if base_path else Path.cwd()
        sqlite = SQLiteStore(bp / "idos.db")
        journal = JournalRepository(bp / "idos-journal")

        if not opp_id:
            matching = [o for o in sqlite.list_opportunities()
                        if o.get("ticker") == ticker
                        and o.get("status") in ("MONITORING", "FULL_POSITION", "ACCUMULATING", "REDUCING")]
            if not matching:
                return {"ticker": ticker, "status": "skipped", "reason": "sin posición activa"}
            opp_id = matching[0]["id"]

        opp = sqlite.get_opportunity(opp_id)
        if not opp:
            return {"ticker": ticker, "status": "skipped", "reason": f"oportunidad {opp_id} no encontrada"}

        result = self.evaluate(ticker, opp_id, sqlite, journal, bp, trigger_source)
        if not result:
            return {"ticker": ticker, "opp_id": opp_id, "status": "failed",
                    "reason": "LLM sin respuesta estructurada"}

        thesis_active = bool(result.get("thesis_active", True))
        now_iso = datetime.now(AR_TZ).isoformat()
        opp["thesis_active"] = thesis_active
        if not thesis_active:
            opp["thesis_invalidated_reason"] = result.get("reason", "Tesis invalidada tras re-assessment")
        opp["updated_at"] = now_iso
        opp["last_thesis_assessment_at"] = now_iso
        sqlite.save_opportunity(opp)

        cascade = self._sync_hypotheses_on_invalidation(ticker, opp_id, thesis_active,
                                                        result, sqlite, journal, opp)

        yaml_opp = journal.load_opportunity(ticker, opp_id)
        if yaml_opp:
            yaml_opp["thesis_active"] = thesis_active
            if not thesis_active:
                yaml_opp["thesis_invalidated_reason"] = result.get("reason", "")
            yaml_opp["updated_at"] = now_iso
            yaml_opp["last_thesis_assessment_at"] = now_iso
            journal.save_opportunity(ticker, yaml_opp)

        event_data = {
            "opp_id": opp_id, "ticker": ticker,
            "thesis_active": thesis_active,
            "flags": result.get("flags", []),
            "reason": result.get("reason", ""),
            "risk_level": result.get("risk_level", ""),
            "confidence": result.get("confidence", 0),
            "trigger": trigger_source,
            "cascade": cascade.get("cascade", "none"),
        }
        journal.log_event("thesis:reassessed", event_data, source="thesis_monitor_worker")
        sqlite.log_event("thesis:reassessed", event_data, source="thesis_monitor_worker")

        print(f"[THESIS] {ticker}: thesis_active={thesis_active} trigger={trigger_source} "
              f"flags={result.get('flags', [])} reason={result.get('reason', '')[:120]}")

        return {
            "ticker": ticker,
            "opp_id": opp_id,
            "status": "completed",
            "thesis_active": thesis_active,
            "flags": result.get("flags", []),
            "reason": result.get("reason", ""),
            "risk_level": result.get("risk_level", ""),
            "confidence": result.get("confidence", 0),
            "recommendation": result.get("recommendation", ""),
            "cascade": cascade.get("cascade", "none"),
        }

    def _sync_hypotheses_on_invalidation(self, ticker: str, opp_id: str, thesis_active: bool,
                                        result: dict[str, Any], sqlite: Any,
                                        journal: Any, opp: dict[str, Any]) -> dict[str, Any]:
        """Al invalidarse la tesis, marca hipótesis principales como INVALIDATED
        y aplica la cascade (solo principal → EXITED). CLOSED no cierra oportunidad."""
        if thesis_active:
            return {"cascade": "none"}
        from idos.research.lifecycle import apply_hypothesis_cascade
        hypotheses = journal.load_hypotheses(ticker, opp_id)
        if not hypotheses:
            return {"cascade": "none"}
        cascade = {"cascade": "none"}
        invalidated = []
        for h in hypotheses:
            is_principal = bool(h.get("parent_id") == "" and h.get("status") == "ACTIVE")
            if h.get("status") in ("ACTIVE", "STRENGTHENING", "WEAKENING", "AT_RISK"):
                h["status"] = "INVALIDATED"
                h["updated_at"] = datetime.now(AR_TZ).isoformat()
                h.setdefault("falsification", [])
                h["falsification"].append({
                    "condition": result.get("reason", "Tesis invalidada en re-assessment"),
                    "triggered": True,
                    "triggered_at": datetime.now(AR_TZ).isoformat(),
                })
                journal.save_hypothesis(ticker, opp_id, h)
                invalidated.append(h)
                result_cascade = apply_hypothesis_cascade(
                    journal, sqlite, ticker, opp_id, h, is_principal=is_principal,
                )
                if is_principal and result_cascade.get("cascade") == "exited":
                    cascade = result_cascade
        if invalidated:
            self._notify_hypothesis_invalidated(ticker, opp_id, invalidated, cascade)
        return cascade

    def _notify_hypothesis_invalidated(self, ticker: str, opp_id: str,
                                       invalidated: list[dict[str, Any]],
                                       cascade: dict[str, Any]):
        try:
            from idos.workers.notifications.telegram import TelegramNotifier
            lines = [f"🚨 *Hipótesis INVALIDADA* — {ticker} ({opp_id})"]
            for h in invalidated[:5]:
                lines.append(f"- {h.get('statement', '')[:120]}")
            if cascade.get("cascade") == "exited":
                lines.append(f"\nCascade: oportunidad → EXITED (salida total).")
            tg = TelegramNotifier()
            tg.execute({"message": "\n".join(lines)[:4000]})
        except Exception as e:
            print(f"[HYP NOTIFY] Telegram error: {e}")

    def evaluate(self, ticker: str, opp_id: str, sqlite: SQLiteStore,
                 journal: JournalRepository, base_path: Path,
                 trigger_source: str = "manual") -> dict[str, Any]:
        return self.research.reassess_thesis(
            ticker, opp_id, sqlite, journal, base_path, trigger_source,
        )
