"""Monthly DDD Re-Assessment Worker.

Runs once per month (first weekday). Performs three tasks:

1. **Thesis Re-assessment**: Calls ThesisMonitorWorker for due opportunities
   to re-evaluate thesis integrity via LLM; skips reviews before their cadence.
2. **Conviction Recalibration**: Adjusts conviction scores for all active
   opportunities based on overvaluation/undervaluation, thesis status,
   and risk drawdown.
3. **Portfolio Review (Decision Orchestrator)**: Uses CapitalCompetitionEngine
   to identify positions that should be replaced by better candidates.

Every significant change is notified via Telegram + Email.
"""
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.portfolio.competition import CapitalCompetitionEngine
from idos.portfolio.exit import ExitEngine
from idos.research.thesis_schedule import schedule_for_opportunity
from idos.strategy.catalog import StrategyCatalog
from idos.timezone import AR_TZ
from idos.workers.base import BaseWorker


class MonthlyReassessmentWorker(BaseWorker):
    name = "monthly_reassessment_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        cfg = config or {}
        self.thesis_cfg = cfg.get("thesis", {})
        self.conviction_cfg = cfg.get("conviction", {})
        self.portfolio_cfg = cfg.get("portfolio", {})
        self.notify = bool(cfg.get("notify", True))
        self.llm_service = cfg.get("llm_service")

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        base_path = context.get("base_path", "")
        bp = Path(base_path) if base_path else Path.cwd()
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")
        from idos.config import load_config
        configured_portfolio = load_config(bp / "idos-config" / "portfolio.yml") or {}
        self.portfolio_cfg = {**configured_portfolio, **self.portfolio_cfg}

        requested_tickers = {
            str(ticker).strip().upper()
            for ticker in context.get("tickers", [])
            if str(ticker).strip()
        }
        opportunities = self._active_opportunities(sqlite, requested_tickers or None)
        position_map = self._load_paper_positions(journal)

        for opp in opportunities:
            ticker = opp.get("ticker", "")
            pos = position_map.get(ticker.upper(), {})
            opp.setdefault("entry_price", pos.get("entry_price", 0))
            opp.setdefault("stop_loss", pos.get("stop_loss", 0))

        thesis_results = self._reassess_theses(opportunities, sqlite, journal, bp)
        completed_thesis_reviews = [r for r in thesis_results if r.get("status") == "completed"]
        conviction_results = self._recalibrate_conviction(opportunities, sqlite, journal)
        skip_portfolio_review = context.get("skip_portfolio_review", False) is True
        portfolio_runtime_enabled = bool(self.portfolio_cfg.get("runtime_enabled", False))
        portfolio_review_enabled = portfolio_runtime_enabled and not skip_portfolio_review
        portfolio_results = (
            self._review_portfolio(opportunities, sqlite, journal, bp)
            if portfolio_review_enabled else []
        )
        portfolio_review_status = (
            "skipped_for_run" if skip_portfolio_review
            else "completed" if portfolio_runtime_enabled
            else "disabled"
        )

        summary = {
            "date": datetime.now(AR_TZ).isoformat(),
            "total_active": len(opportunities),
            "thesis_reassessed": len(completed_thesis_reviews),
            "thesis_skipped_not_due": sum(1 for r in thesis_results if r.get("reason") == "review_not_due"),
            "thesis_failed": sum(1 for r in thesis_results if r.get("status") == "failed"),
            "thesis_changed": sum(1 for r in completed_thesis_reviews if r.get("thesis_changed")),
            "conviction_recalibrated": len(conviction_results),
            "portfolio_reviewed": len(portfolio_results),
            "portfolio_review_status": portfolio_review_status,
            "proposals": [r for r in portfolio_results if r.get("proposal")],
            "exit_proposals": [r["exit_proposal"] for r in thesis_results if r.get("exit_proposal")],
        }

        self._write_cache(bp, summary, thesis_results, conviction_results, portfolio_results)

        if self.notify and (summary["thesis_changed"] or summary["proposals"] or summary["exit_proposals"]):
            self._notify(summary, bp)

        return {"status": "completed", **summary}

    # ── thesis re-assessment ────────────────────────────────────────────

    def _active_opportunities(self, sqlite: SQLiteStore,
                              tickers: set[str] | None = None) -> list[dict[str, Any]]:
        opportunities = [
            o for o in sqlite.list_opportunities()
            if o.get("status") in ("ACCUMULATING", "FULL_POSITION", "MONITORING", "REDUCING")
        ]
        if tickers is not None:
            opportunities = [o for o in opportunities if str(o.get("ticker", "")).upper() in tickers]
        return opportunities

    @staticmethod
    def _load_paper_positions(journal: JournalRepository) -> dict[str, dict[str, Any]]:
        import yaml
        positions = {}
        pos_dir = journal.base / "paper" / "positions"
        if pos_dir.exists():
            for f in sorted(pos_dir.iterdir()):
                if f.suffix == ".yml":
                    try:
                        p = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                        if p.get("ticker"):
                            positions[p["ticker"].upper()] = p
                    except Exception:
                        pass
        return positions

    def _reassess_theses(self, opportunities: list[dict[str, Any]], sqlite: SQLiteStore,
                           journal: JournalRepository, bp: Path) -> list[dict[str, Any]]:
        results = []
        catalog = StrategyCatalog(bp / "idos-config" / "strategies.yml")
        now = datetime.now(AR_TZ)
        for opp in opportunities:
            ticker = opp.get("ticker", "")
            opp_id = opp.get("id", "")
            if not ticker:
                continue
            try:
                if str(opp.get("research_profile", "")).lower() == "systematic":
                    results.append({
                        "ticker": ticker,
                        "opp_id": opp_id,
                        "status": "skipped",
                        "reason": "systematic_strategy",
                    })
                    continue
                profile = catalog.get(opp.get("strategy_id") or "COMPOUNDER")
                schedule = schedule_for_opportunity(opp, profile, now)
                if schedule.interval_days is None:
                    results.append({
                        "ticker": ticker,
                        "opp_id": opp_id,
                        "status": "skipped",
                        "reason": schedule.reason,
                    })
                    continue
                if not schedule.due:
                    results.append({
                        "ticker": ticker,
                        "opp_id": opp_id,
                        "status": "skipped",
                        "reason": schedule.reason,
                        "next_thesis_review_at": schedule.next_review_at.isoformat(),
                    })
                    continue

                from idos.workers.ai.thesis_monitor_worker import ThesisMonitorWorker
                worker = ThesisMonitorWorker({"llm_service": self.llm_service})
                result = worker.run({
                    "ticker": ticker,
                    "opp_id": opp_id,
                    "trigger_source": "monthly",
                    "base_path": str(bp),
                })
                if result.get("status") == "completed":
                    thesis_active = result.get("thesis_active", True)
                    changed = thesis_active != opp.get("thesis_active", True)
                    exit_proposal = None
                    reviewed_at = datetime.now(AR_TZ)
                    next_review = (reviewed_at + timedelta(days=schedule.interval_days)).isoformat()
                    opp["last_thesis_assessment_at"] = reviewed_at.isoformat()
                    opp["next_thesis_review_at"] = next_review
                    persisted_opp = sqlite.get_opportunity(opp_id) or dict(opp)
                    persisted_opp["last_thesis_assessment_at"] = reviewed_at.isoformat()
                    persisted_opp["next_thesis_review_at"] = next_review
                    sqlite.save_opportunity(persisted_opp)
                    journal_opp = journal.load_opportunity(ticker, opp_id) or dict(persisted_opp)
                    journal_opp["last_thesis_assessment_at"] = reviewed_at.isoformat()
                    journal_opp["next_thesis_review_at"] = next_review
                    journal.save_opportunity(ticker, journal_opp)
                    results.append({
                        "ticker": ticker,
                        "opp_id": opp_id,
                        "status": "completed",
                        "thesis_active": thesis_active,
                        "thesis_changed": changed,
                        "exit_proposal": None,
                        "reason": result.get("reason", ""),
                        "flags": result.get("flags", []),
                        "confidence": result.get("confidence", 0),
                        "review_interval_days": schedule.interval_days,
                        "last_thesis_assessment_at": reviewed_at.isoformat(),
                        "next_thesis_review_at": next_review,
                    })
                    if changed:
                        self._update_opp_thesis(opp, result, sqlite, journal)
                        if not thesis_active:
                            exit_proposal = self._build_thesis_exit_proposal(opp, result, reviewed_at)
                            results[-1]["exit_proposal"] = exit_proposal
                            sqlite.log_event("decision:exit_proposed", exit_proposal,
                                             source="monthly_reassessment_worker")
                else:
                    results.append({
                        "ticker": ticker,
                        "opp_id": opp_id,
                        "status": "failed",
                        "reason": result.get("reason", "thesis_monitor_failed"),
                    })
            except Exception as e:
                print(f"[MONTHLY] {ticker}: error en re-assessment: {e}")
                results.append({
                    "ticker": ticker,
                    "opp_id": opp_id,
                    "status": "failed",
                    "thesis_active": opp.get("thesis_active", True),
                    "thesis_changed": False,
                    "exit_proposal": None,
                    "error": str(e),
                })
        return results

    @staticmethod
    def _build_thesis_exit_proposal(opp: dict[str, Any], result: dict[str, Any],
                                    proposed_at: datetime) -> dict[str, Any]:
        return {
            "id": f"dec-{uuid4().hex[:8]}",
            "type": "SELL",
            "ticker": opp.get("ticker", ""),
            "opp_id": opp.get("id", ""),
            "status": "PENDING_REVIEW",
            "reason": "thesis_invalidated",
            "exit_pct": 100.0,
            "urgency": "high",
            "rationale": result.get("reason", "La revisión de Research marcó la tesis como inválida"),
            "flags": result.get("flags", []),
            "confidence": result.get("confidence"),
            "proposed_at": proposed_at.isoformat(),
            "human_approval_required": True,
        }

    def _update_opp_thesis(self, opp: dict[str, Any], result: dict[str, Any],
                           sqlite: SQLiteStore, journal: JournalRepository):
        opp["thesis_active"] = result.get("thesis_active", True)
        if not opp["thesis_active"]:
            opp["thesis_invalidated_reason"] = result.get("reason", "Tesis invalidada en re-assessment")
        opp["updated_at"] = datetime.now(AR_TZ).isoformat()
        sqlite.save_opportunity(opp)
        journal_opp = journal.load_opportunity(opp.get("ticker", ""), opp["id"]) or dict(opp)
        journal_opp.update({
            "thesis_active": opp["thesis_active"],
            "updated_at": opp["updated_at"],
        })
        if opp.get("thesis_invalidated_reason"):
            journal_opp["thesis_invalidated_reason"] = opp["thesis_invalidated_reason"]
        journal.save_opportunity(opp.get("ticker", ""), journal_opp)
        journal.log_event("thesis:reassessed_monthly", {
            "opp_id": opp["id"], "ticker": opp.get("ticker", ""),
            "thesis_active": opp["thesis_active"],
            "flags": result.get("flags", []),
        }, source="monthly_reassessment_worker")
        print(f"[MONTHLY] {opp.get('ticker')}: tesis re-assessed, active={opp['thesis_active']}")

    # ── conviction recalibration ────────────────────────────────────────

    def _recalibrate_conviction(self, opportunities: list[dict[str, Any]],
                                  sqlite: SQLiteStore, journal: JournalRepository) -> list[dict[str, Any]]:
        results = []
        max_conviction = self.conviction_cfg.get("max", 100)
        min_conviction = self.conviction_cfg.get("min", 10)
        overvaluation_weight = self.conviction_cfg.get("overvaluation_weight", 0.3)
        thesis_weight = self.conviction_cfg.get("thesis_weight", 0.4)
        risk_weight = self.conviction_cfg.get("risk_weight", 0.3)

        for opp in opportunities:
            ticker = opp.get("ticker", "")
            opp_id = opp.get("id", "")
            current = opp.get("conviction", {}).get("overall", 50)
            intrinsic = opp.get("intrinsic_value", 0) or 0
            price = opp.get("current_price", 0) or 0

            # Overvaluation component (0-100, higher = more overvalued = lower conviction)
            overval_score = 0
            if intrinsic > 0 and price > 0:
                overvaluation = (price / intrinsic - 1) * 100
                if overvaluation > 0:
                    overval_score = min(overvaluation / 50, 1.0)  # 50%+ overvaluation = max penalty
                else:
                    overval_score = max(overvaluation / 50, -1.0)  # undervaluation bonus

            # Thesis component
            thesis_score = 1.0 if opp.get("thesis_active", True) else 0.0

            # Risk component (drawdown from entry)
            risk_score = 1.0
            entry = opp.get("entry_price", 0) or price
            if entry > 0 and price > 0:
                dd = (entry - price) / entry
                if dd > 0.15:
                    risk_score = max(1.0 - (dd - 0.15) * 2, 0.0)

            # Weighted new conviction
            new_conviction = (
                (1 - overval_score) * overvaluation_weight +
                thesis_score * thesis_weight +
                risk_score * risk_weight
            ) * max_conviction
            new_conviction = max(min_conviction, min(max_conviction, round(new_conviction)))

            changed = abs(new_conviction - current) > 5
            if changed:
                opp["conviction"] = opp.get("conviction", {})
                opp["conviction"]["overall"] = new_conviction
                opp["conviction"]["monthly_recalibrated"] = datetime.now(AR_TZ).isoformat()
                opp["updated_at"] = datetime.now(AR_TZ).isoformat()
                sqlite.save_opportunity(opp)
                journal.log_event("conviction:recalibrated", {
                    "opp_id": opp_id, "ticker": ticker,
                    "from": current, "to": new_conviction,
                }, source="monthly_reassessment_worker")

            results.append({
                "ticker": ticker,
                "opp_id": opp_id,
                "conviction_before": current,
                "conviction_after": new_conviction,
                "changed": changed,
            })
        return results

    # ── portfolio review (Decision Orchestrator) ────────────────────────

    def _review_portfolio(self, opportunities: list[dict[str, Any]], sqlite: SQLiteStore,
                            journal: JournalRepository, bp: Path) -> list[dict[str, Any]]:
        results = []
        engine = CapitalCompetitionEngine(
            replacement_threshold=self.portfolio_cfg.get("replacement_conviction_multiple", 1.3),
        )
        for opp in opportunities:
            ticker = opp.get("ticker", "")
            conviction = opp.get("conviction", {}).get("overall", 50)
            intrinsic = opp.get("intrinsic_value", 0) or 0
            entry = opp.get("entry_price", 0) or 0
            stop = opp.get("stop_loss", 0) or 0

            asymmetry = self._asymmetry(entry, stop, intrinsic)
            best_candidate = self._best_candidate_score(ticker, bp)

            proposal = False
            if best_candidate > conviction * engine.threshold:
                if asymmetry is not None and asymmetry < 3:
                    proposal = True

            results.append({
                "ticker": ticker,
                "opp_id": opp.get("id", ""),
                "conviction": conviction,
                "best_candidate_score": best_candidate,
                "asymmetry": asymmetry,
                "proposal": proposal,
            })
        return results

    @staticmethod
    def _asymmetry(entry: float, stop: float, intrinsic: float) -> float | None:
        if entry <= 0 or stop <= 0 or intrinsic <= 0 or entry <= stop:
            return None
        risk = (entry - stop) / entry
        upside = (intrinsic - entry) / entry
        if risk <= 0:
            return None
        return upside / risk

    def _best_candidate_score(self, held_ticker: str, bp: Path) -> int:
        bl_path = bp / "idos-journal" / "portfolio" / "buylist.yml"
        if not bl_path.exists():
            return 0
        try:
            import yaml
            data = yaml.safe_load(bl_path.read_text(encoding="utf-8")) or {}
            best = 0
            for e in data.get("entries", []):
                if e.get("ticker", "").upper() == held_ticker.upper():
                    continue
                best = max(best, int(e.get("conviction_score", 0) or 0))
            return best
        except Exception:
            return 0

    # ── cache & notifications ───────────────────────────────────────────

    def _write_cache(self, bp: Path, summary: dict[str, Any], thesis_results: list,
                     conviction_results: list, portfolio_results: list):
        import json
        cache_dir = bp / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "summary": summary,
            "thesis_results": thesis_results,
            "conviction_results": conviction_results,
            "portfolio_results": portfolio_results,
            "generated_at": datetime.now(AR_TZ).isoformat(),
        }
        (cache_dir / "monthly_reassessment.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _notify(self, summary: dict[str, Any], bp: Path):
        lines = [f"**Re-Assessment Mensual IDOS**", ""]
        lines.append(f"Oportunidades activas: {summary['total_active']}")
        lines.append(f"Tesis re-assessadas: {summary['thesis_reassessed']}")
        lines.append(f"Tesis cambiadas: {summary['thesis_changed']}")
        lines.append(f"Conviction recalibrado: {summary['conviction_recalibrated']}")
        lines.append(f"Propuestas de reemplazo: {len(summary['proposals'])}")
        if summary["exit_proposals"]:
            lines.append(f"Propuestas SELL pendientes de revisión: {len(summary['exit_proposals'])}")
            for proposal in summary["exit_proposals"]:
                lines.append(f"  - {proposal['ticker']}: {proposal.get('reason', '')}")
        for pr in summary["proposals"]:
            lines.append(f"  Propuesta: {pr['ticker']} (asimetría {pr.get('asymmetry', 'N/A')})")
        message = "\n".join(lines)

        try:
            from idos.workers.notifications.telegram import TelegramNotifier
            tg = TelegramNotifier()
            tg.execute({"message": message[:4000]})
        except Exception as e:
            print(f"[MONTHLY] Telegram error: {e}")
        try:
            from idos.workers.notifications.email_notifier import EmailNotifier
            en = EmailNotifier()
            en.execute({"subject": "IDOS - Re-Assessment Mensual", "body": message})
        except Exception as e:
            print(f"[MONTHLY] Email error: {e}")


if __name__ == "__main__":
    import os
    import sys
    from pathlib import Path
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    os.chdir(os.environ.get("GITHUB_WORKSPACE", "."))
    bp = Path(os.environ.get("GITHUB_WORKSPACE", "."))
    from idos.ai.service import LLMService
    _mp = Path("idos-config/models.yml")
    _llm_svc = LLMService(str(_mp)) if _mp.exists() else LLMService()
    w = MonthlyReassessmentWorker({"llm_service": _llm_svc, "prompts_path": "idos-config/prompts"})
    result = w.execute({"base_path": str(bp)})
    r = result.output if hasattr(result, "output") else result
    print(f"[MONTHLY] active={r.get('total_active')} thesis_reassessed={r.get('thesis_reassessed')} "
          f"changed={r.get('thesis_changed')} conviction={r.get('conviction_recalibrated')} "
          f"proposals={len(r.get('proposals', []))} exit_proposals={len(r.get('exit_proposals', []))}")
