"""Exit Decision Engine - daily monitor.

Evaluates the 4 exit rules for every active paper position and executes the
appropriate action. Spec v2:

- Thesis Exit (100%): thesis_active == False -> full liquidation -> EXITED.
- Risk Exit (100%): quantitative risk triggers (drawdown, etc.) launch a thesis
  reassessment (LLM); if the thesis changed -> full liquidation -> EXITED.
- Valuation Exit (partial): overvaluation = price/intrinsic - 1 >= threshold ->
  partial trim (exit_pct_on_valuation) -> REDUCING. Never 100%.
- Portfolio Exit (proposal): CapitalCompetitionEngine.should_replace AND current
  asymmetry < min_asymmetry_ratio -> proposal + notification, no auto-liquidation
  (total replacement requires explicit CLI decision).

Technical signals (stop loss / trailing stop) are NOT used for exits.
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.portfolio.competition import CapitalCompetitionEngine
from idos.portfolio.exit import ExitEngine, ExitReason, ExitSignal
from idos.portfolio.paper import PaperTrader
from idos.timezone import AR_TZ
from idos.workers.base import BaseWorker


class ExitMonitorWorker(BaseWorker):
    name = "exit_monitor_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        cfg = config or {}
        exit_cfg = cfg.get("exit", {}) or {}
        self.valuation_overvaluation_pct = float(exit_cfg.get("valuation_overvaluation_pct", 25))
        self.exit_pct_on_valuation = float(exit_cfg.get("exit_pct_on_valuation", 50))
        self.exit_pct_on_drawdown = float(exit_cfg.get("exit_pct_on_drawdown", 50))
        self.replacement_conviction_multiple = float(exit_cfg.get("replacement_conviction_multiple", 1.3))
        self.min_asymmetry_ratio = float(exit_cfg.get("min_asymmetry_ratio", 3))
        self.notify = bool(exit_cfg.get("notify", True))
        risk_cfg = cfg.get("risk", {}) or {}
        self.max_drawdown_pct = float(risk_cfg.get("max_drawdown_pct", 15.0))
        self.risk_reassessment_cooldown_days = int(cfg.get("risk_reassessment_cooldown_days", 7))
        self._llm_service = cfg.get("llm_service")

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        base_path = context.get("base_path", "")
        bp = Path(base_path) if base_path else Path.cwd()
        journal = JournalRepository(bp / "idos-journal")
        sqlite = SQLiteStore(bp / "idos.db")

        exit_engine = ExitEngine({
            "valuation_overvaluation_pct": self.valuation_overvaluation_pct,
            "exit_pct_on_valuation": self.exit_pct_on_valuation,
        })
        portfolio_config = self._load_portfolio_config(bp)
        trader = PaperTrader(portfolio_config, journal)

        positions = trader.current_positions()
        exits: list[dict[str, Any]] = []
        proposals: list[dict[str, Any]] = []

        for pos in positions:
            ticker = pos.get("ticker", "")
            if not ticker:
                continue
            price = self._current_price(sqlite, ticker)
            if not price:
                print(f"[EXIT] {ticker}: sin precio disponible, skip")
                continue

            opp = self._load_opp(sqlite, journal, ticker, pos.get("opp_id", ""))
            if not opp:
                print(f"[EXIT] {ticker}: sin oportunidad, skip")
                continue

            signal = self._decide(ticker, pos, opp, price, exit_engine, sqlite, journal, bp)

            if signal is None:
                continue

            if signal.reason == ExitReason.PORTFOLIO_REPLACEMENT:
                proposal = self._build_proposal(ticker, pos, opp, signal)
                proposals.append(proposal)
                if self.notify:
                    self._notify_proposal(proposal)
                continue

            result = self._execute_exit(ticker, pos, opp, price, signal, trader, journal, sqlite)
            exits.append(result)
            if self.notify:
                self._notify_exit(result)

        self._write_exit_signals(bp, exits, proposals)

        return {
            "status": "completed",
            "positions_checked": len(positions),
            "exits_executed": len(exits),
            "proposals_generated": len(proposals),
            "exits": exits,
            "proposals": proposals,
        }

    # ── decision ────────────────────────────────────────────────────────────

    def _decide(self, ticker: str, pos: dict[str, Any], opp: dict[str, Any],
                price: float, exit_engine: ExitEngine, sqlite: SQLiteStore,
                journal: JournalRepository, bp: Path) -> ExitSignal | None:
        conviction = opp.get("conviction", {}).get("overall", 0)
        intrinsic = opp.get("intrinsic_value", 0) or 0

        # 1) Thesis Exit (100%)
        if not opp.get("thesis_active", True):
            return exit_engine.evaluate_thesis_exit(ticker, thesis_active=False)

        # 2) Risk Exit: risk trigger -> thesis reassessment
        risk_triggered = self._risk_triggered(pos, price)
        if risk_triggered:
            thesis_changed = self._reassess_thesis(ticker, pos, opp, journal, sqlite, bp)
            if thesis_changed:
                return exit_engine.evaluate_risk_exit(
                    ticker, thesis_intact=False,
                    details=f"Tesis cambiada tras re-assessment (trigger drawdown {self._drawdown(pos, price):.1f}%)")
            else:
                print(f"[EXIT] {ticker}: trigger de riesgo sin cambio de tesis - solo alerta")

        # 3) Valuation Exit (partial, never 100%)
        val_signal = exit_engine.evaluate_valuation_margin_exit(ticker, price, intrinsic)
        if val_signal:
            return val_signal

        # 4) Portfolio Exit (proposal only)
        if self._portfolio_proposal(ticker, pos, opp, conviction, bp):
            worst_asymmetry = self._asymmetry(pos, intrinsic)
            if worst_asymmetry is not None and worst_asymmetry < self.min_asymmetry_ratio:
                return exit_engine.evaluate_portfolio_exit(
                    ticker,
                    replacement_score=self._best_candidate(ticker, bp),
                    current_conviction=conviction,
                )

        return None

    def _risk_triggered(self, pos: dict[str, Any], price: float) -> bool:
        dd = self._drawdown(pos, price)
        return dd is not None and dd > self.max_drawdown_pct

    @staticmethod
    def _drawdown(pos: dict[str, Any], price: float) -> float | None:
        entry = pos.get("entry_price", 0) or 0
        if entry <= 0 or price <= 0:
            return None
        return (entry - price) / entry * 100

    def _reassess_thesis(self, ticker: str, pos: dict[str, Any], opp: dict[str, Any],
                         journal: JournalRepository, sqlite: SQLiteStore, bp: Path) -> bool:
        last = pos.get("thesis_last_reassessed", "")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if datetime.now(AR_TZ) - last_dt < timedelta(days=self.risk_reassessment_cooldown_days):
                    return not opp.get("thesis_active", True)
            except (ValueError, TypeError):
                pass
        try:
            from idos.workers.ai.thesis_monitor_worker import ThesisMonitorWorker
            worker = ThesisMonitorWorker({"llm_service": self._llm_service})
            result = worker.run({
                "ticker": ticker,
                "opp_id": opp.get("id", ""),
                "trigger_source": "risk",
                "base_path": str(bp),
            })
            if result.get("status") == "completed":
                self._update_position_thesis_ts(ticker, pos, journal)
                return not result.get("thesis_active", True)
        except Exception as e:
            print(f"[EXIT] {ticker}: error en re-assessment de tesis: {e}")
        return False

    def _update_position_thesis_ts(self, ticker: str, pos: dict[str, Any], journal: JournalRepository):
        path = journal.base / "paper" / "positions" / f"{ticker}.yml"
        if path.exists():
            import yaml
            try:
                pos["thesis_last_reassessed"] = datetime.now(AR_TZ).isoformat()
                path.write_text(yaml.dump(pos, default_flow_style=False, allow_unicode=True), encoding="utf-8")
            except Exception:
                pass

    @staticmethod
    def _asymmetry(pos: dict[str, Any], intrinsic: float) -> float | None:
        entry = pos.get("entry_price", 0) or 0
        stop = pos.get("stop_loss", 0) or 0
        if entry <= 0 or stop <= 0 or intrinsic <= 0 or entry <= stop:
            return None
        risk = (entry - stop) / entry
        upside = (intrinsic - entry) / entry
        if risk <= 0:
            return None
        return upside / risk

    def _portfolio_proposal(self, ticker: str, pos: dict[str, Any], opp: dict[str, Any],
                            conviction: int, bp: Path) -> bool:
        return self._best_candidate(ticker, bp) > conviction * self.replacement_conviction_multiple

    def _best_candidate(self, held_ticker: str, bp: Path) -> int:
        candidates = self._load_buylist(bp)
        best = 0
        for c in candidates:
            if c.get("ticker", "").upper() == held_ticker.upper():
                continue
            best = max(best, int(c.get("conviction_score", 0) or 0))
        return best

    def _load_buylist(self, bp: Path) -> list[dict[str, Any]]:
        import yaml
        bl_path = bp / "idos-journal" / "portfolio" / "buylist.yml"
        if not bl_path.exists():
            return []
        try:
            data = yaml.safe_load(bl_path.read_text(encoding="utf-8")) or {}
            return data.get("entries", []) or []
        except Exception:
            return []

    # ── execution ───────────────────────────────────────────────────────────

    def _execute_exit(self, ticker: str, pos: dict[str, Any], opp: dict[str, Any],
                      price: float, signal: ExitSignal, trader: PaperTrader,
                      journal: JournalRepository, sqlite: SQLiteStore) -> dict[str, Any]:
        exit_pct = signal.exit_pct / 100.0
        result = trader.sell(ticker, price, signal.reason.value, exit_pct=exit_pct)
        status = result.get("status", "error")
        print(f"[EXIT] {ticker}: {signal.reason.value} exit_pct={exit_pct*100:.0f}% -> {status}")
        if status == "executed":
            if result.get("closed") or exit_pct >= 1.0:
                new_status = "EXITED"
                opp["exit_reason"] = signal.reason.value
            else:
                new_status = "REDUCING" if opp.get("status") not in ("REDUCING",) else "REDUCING"
            self._transition_opp(opp, new_status, signal, journal, sqlite)

        return {
            "ticker": ticker,
            "opp_id": opp.get("id", ""),
            "reason": signal.reason.value,
            "exit_pct": exit_pct,
            "price": price,
            "status": status,
            "closed": result.get("closed", False),
            "quantity": result.get("quantity", 0),
            "pnl": result.get("pnl", 0),
            "new_status": new_status,
            "urgency": signal.urgency,
            "details": signal.details,
            "generated_at": datetime.now(AR_TZ).isoformat(),
        }

    def _transition_opp(self, opp: dict[str, Any], new_status: str, signal: ExitSignal,
                        journal: JournalRepository, sqlite: SQLiteStore):
        old_status = opp.get("status", "")
        if old_status == new_status:
            return
        opp["status"] = new_status
        opp["updated_at"] = datetime.now(AR_TZ).isoformat()
        sqlite.save_opportunity(opp)
        sqlite.record_transition(opp["id"], old_status, new_status,
                                 cause=signal.reason.value, worker="exit_monitor_worker")
        decision = {
            "id": f"dec-{uuid4().hex[:8]}",
            "type": "SELL",
            "ticker": opp.get("ticker", ""),
            "opp_id": opp["id"],
            "status": "EXECUTED",
            "reason": signal.reason.value,
            "exit_pct": signal.exit_pct,
            "urgency": signal.urgency,
            "rationale": signal.details,
            "generated_at": datetime.now(AR_TZ).isoformat(),
        }
        journal.save_decision(opp.get("ticker", ""), opp["id"], decision)
        journal.log_event("position:exited" if new_status == "EXITED" else "position:reduced", {
            "opp_id": opp["id"], "ticker": opp.get("ticker", ""),
            "from": old_status, "to": new_status, "reason": signal.reason.value,
            "exit_pct": signal.exit_pct,
        }, source="exit_monitor_worker")
        sqlite.log_event("exit:executed", {
            "opp_id": opp["id"], "ticker": opp.get("ticker", ""),
            "from": old_status, "to": new_status, "reason": signal.reason.value,
            "exit_pct": signal.exit_pct,
        }, source="exit_monitor_worker")

    def _build_proposal(self, ticker: str, pos: dict[str, Any], opp: dict[str, Any],
                        signal: ExitSignal) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "opp_id": opp.get("id", ""),
            "reason": signal.reason.value,
            "conviction": opp.get("conviction", {}).get("overall", 0),
            "best_candidate_score": signal.conviction_after,
            "asymmetry": self._asymmetry(pos, opp.get("intrinsic_value", 0) or 0),
            "action": "proposal",
            "execution": "run: idos position-exit <TICKER> --reason portfolio_rebalance",
            "generated_at": datetime.now(AR_TZ).isoformat(),
        }

    # ── helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _load_portfolio_config(bp: Path) -> dict[str, Any]:
        from idos.config import load_config
        cfg = load_config(bp / "idos-config" / "portfolio.yml") or {}
        return {
            "bankroll": cfg.get("bankroll", 100000),
            "max_position_pct": cfg.get("max_position_pct", 3.0),
            "fee_pct": cfg.get("fee_pct", 0.1),
            "stop_loss_asymmetry_divisor": cfg.get("stop_loss_asymmetry_divisor", 3),
        }

    @staticmethod
    def _current_price(sqlite: SQLiteStore, ticker: str) -> float:
        rows = sqlite.get_price_history(ticker, limit=1)
        return float(rows[-1]["close"]) if rows else 0.0

    @staticmethod
    def _load_opp(sqlite: SQLiteStore, journal: JournalRepository, ticker: str, opp_id: str) -> dict[str, Any] | None:
        if opp_id:
            opp = sqlite.get_opportunity(opp_id)
            if opp:
                return opp
        matching = [o for o in sqlite.list_opportunities()
                    if o.get("ticker") == ticker.upper()
                    and o.get("status") in ("ACCUMULATING", "FULL_POSITION", "MONITORING", "REDUCING")]
        if matching:
            return matching[0]
        return None

    @staticmethod
    def _write_exit_signals(bp: Path, exits: list[dict[str, Any]], proposals: list[dict[str, Any]]):
        cache_dir = bp / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        import json
        payload = {"exits": exits, "proposals": proposals,
                   "generated_at": datetime.now(AR_TZ).isoformat()}
        (cache_dir / "exit_signals.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _notify_exit(self, result: dict[str, Any]):
        ticker = result["ticker"]
        reason = result["reason"]
        exit_pct = result.get("exit_pct", 1.0)
        message = (
            f"**{ticker} - Salida Ejecutada**\n\n"
            f"- Razón: `{reason}`\n"
            f"- % Vendido: `{exit_pct*100:.0f}%`\n"
            f"- Precio: `${result.get('price', 0):.2f}`\n"
            f"- Nuevo estado: `{result.get('new_status', '')}`\n"
            f"- Detalle: `{result.get('details', '')[:200]}`"
        )
        print(message)
        self._send_notification(ticker, f"IDOS - Salida Ejecutada {ticker}", message)

    def _notify_proposal(self, proposal: dict[str, Any]):
        message = (
            f"**{proposal['ticker']} - Propuesta de Sustitución**\n\n"
            f"- Convicción actual: `{proposal.get('conviction', 0)}`\n"
            f"- Mejor candidato: `{proposal.get('best_candidate_score', 0)}`\n"
            f"- Asimetría actual: `{proposal.get('asymmetry', 'N/A')}`\n"
            f"- La liquidación total requiere decisión explícita:\n"
            f"  `idos position-exit {proposal['ticker']} --reason portfolio_rebalance`"
        )
        print(message)
        self._send_notification(proposal["ticker"], f"IDOS - Propuesta de Sustitución {proposal['ticker']}", message)

    def _send_notification(self, ticker: str, subject: str, message: str):
        try:
            from idos.workers.notifications.telegram import TelegramNotifier
            tg = TelegramNotifier()
            r = tg.execute({"message": message[:4000]})
            if r.output.get("status") == "skipped":
                print(f"[EXIT NOTIFY] Telegram: {r.output.get('reason', 'sin configurar')}")
        except Exception as e:
            print(f"[EXIT NOTIFY] Telegram error: {e}")
        try:
            from idos.workers.notifications.email_notifier import EmailNotifier
            en = EmailNotifier()
            en.execute({"subject": subject, "body": message})
        except Exception as e:
            print(f"[EXIT NOTIFY] Email error: {e}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    os.chdir(os.environ.get("GITHUB_WORKSPACE", "."))
    bp = Path(os.environ.get("GITHUB_WORKSPACE", "."))
    w = ExitMonitorWorker()
    result = w.execute({"base_path": str(bp)})
    r = result.output if hasattr(result, "output") else result
    print(f"[EXIT] positions_checked={r.get('positions_checked', 0)} "
          f"exits={r.get('exits_executed', 0)} proposals={r.get('proposals_generated', 0)}")
    for ex in r.get("exits", []):
        print(f"  [EXIT] {ex['ticker']}: {ex['reason']} pct={ex.get('exit_pct', 0)*100:.0f}% -> {ex.get('new_status', '')}")
    for pr in r.get("proposals", []):
        print(f"  [PROP] {pr['ticker']}: sustitución propuesta (no liquidada)")
