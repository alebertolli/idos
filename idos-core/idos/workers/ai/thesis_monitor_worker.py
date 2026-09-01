from datetime import datetime
from pathlib import Path
from typing import Any

from idos.ai.llm import LLMClient
from idos.ai.prompts import PromptRegistry
from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.workers.base import BaseWorker
from idos.timezone import AR_TZ


class ThesisMonitorWorker(BaseWorker):
    """Re-assesses the integrity of an investment thesis (Thesis Exit / Risk Exit).

    Evaluates the 9 fundamental events via LLM and persists `thesis_active` on
    the opportunity. Total liquidation happens downstream in ExitMonitorWorker
    when thesis_active becomes false.

    Triggers: monthly schedule (re-assessment) + risk triggers (Risk Exit).
    """
    name = "thesis_monitor_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.llm = config.get("llm_service") or LLMClient(
            provider=config.get("provider", ""),
            api_key=config.get("api_key", ""),
            model=config.get("model", ""),
            fallback_model=config.get("fallback_model", ""),
            fallback_providers=config.get("fallback_providers", []),
        )
        prompts_path = config.get("prompts_path", "")
        self.registry = PromptRegistry(prompts_path) if prompts_path else PromptRegistry()

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
        thesis_statement = ""
        case_summary = ""
        ddd_file = journal.opportunity_path(ticker, opp_id) / "ddd_report.yml"
        if ddd_file.exists():
            import yaml
            try:
                report = yaml.safe_load(ddd_file.read_text(encoding="utf-8")) or {}
                thesis_statement = report.get("tesis_inversion", "")
                integridad = report.get("integridad_tesis", {}) or {}
                if integridad.get("thesis_active") is not None and trigger_source == "manual":
                    case_summary = f"Evaluación DDD previa: {integridad.get('reason', 'sin detalle')}"
            except Exception:
                pass

        case_file = journal.load_case_file(ticker)
        if case_file:
            case_summary = (case_summary + "\n" if case_summary else "") + \
                f"Case file: {case_file.get('last_updated', '')} con {len(case_file.get('opportunities', []))} oportunidades"

        financial = self._load_financial_summary(ticker, sqlite, base_path)
        conviction = 0
        opp = sqlite.get_opportunity(opp_id)
        if opp:
            conviction = opp.get("conviction", {}).get("overall", 0)

        template = self.registry.get("thesis_monitor", category="research")
        if not template:
            return {}
        system = self.registry.get_system("thesis_monitor", category="research") or ""
        formatted = template.format(**{
            "ticker": ticker,
            "name": ticker,
            "thesis_statement": thesis_statement or "No disponible",
            "financial_summary": financial,
            "recent_events": "",
            "case_file_summary": case_summary or "Sin conocimiento acumulado",
            "conviction": conviction,
            "trigger_source": trigger_source,
        })
        return self.llm.generate_structured(prompt=formatted, system_prompt=system, temperature=0.1)

    def _load_financial_summary(self, ticker: str, sqlite: SQLiteStore, base_path: Path) -> str:
        import json
        data: dict[str, Any] = {}
        try:
            for row in sqlite.conn.execute(
                "SELECT data_json FROM events_log WHERE event_type LIKE ? AND data_json LIKE ? ORDER BY timestamp DESC LIMIT 1",
                (f"%{ticker}%", f"%{ticker}%"),
            ):
                try:
                    data = json.loads(row[0])
                    break
                except (json.JSONDecodeError, IndexError):
                    pass
        except Exception:
            pass
        if not data:
            cache_file = base_path / "cache" / f"{ticker}.json"
            if cache_file.exists():
                try:
                    raw = json.loads(cache_file.read_text(encoding="utf-8"))
                    if isinstance(raw, dict) and "merged_data" in raw:
                        data = raw["merged_data"]
                    elif isinstance(raw, dict):
                        data = raw
                except Exception:
                    pass
        if not data:
            return "Sin datos financieros disponibles"
        keys = ["revenue_ttm", "revenue_growth_pct", "operating_margin_pct", "roic_pct",
                "debt_equity_ratio", "fcf_adjusted", "pe_ratio", "interest_coverage_ratio"]
        parts = []
        for k in keys:
            v = data.get(k)
            if v is not None and v != "":
                if isinstance(v, float):
                    parts.append(f"{k}={v:.1f}")
                else:
                    parts.append(f"{k}={v}")
        return ", ".join(parts) or "Sin datos financieros disponibles"
