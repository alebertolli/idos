from datetime import datetime
from typing import Any

from idos.ai.llm import LLMClient
from idos.ai.prompts import PromptRegistry
from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.models.enums import OpportunityStatus
from idos.portfolio.entry import EntryEngine
from idos.portfolio.wyckoff import WyckoffAnalyzer
from idos.state.machine import OpportunityStateMachine
from idos.workers.base import BaseWorker
from idos.timezone import AR_TZ

class EntryMonitorWorker(BaseWorker):
    """Monitors APPROVED/ENTRY_PENDING opportunities for entry conditions.

    Triggers: daily schedule or manual CLI.
    Transitions: ENTRY_PENDING -> ACCUMULATING.
    """
    name = "entry_monitor_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        llm_client = None
        prompt_registry = None
        if self.config.get("provider"):
            llm_client = LLMClient(
                provider=config.get("provider", ""),
                api_key=config.get("api_key", ""),
                model=config.get("model", ""),
                fallback_model=config.get("fallback_model", ""),
                fallback_providers=config.get("fallback_providers", []),
            )
            prompts_path = config.get("prompts_path", "")
            prompt_registry = PromptRegistry(prompts_path) if prompts_path else None

        wyckoff = WyckoffAnalyzer(llm_client=llm_client, prompt_registry=prompt_registry)
        self.entry_engine = EntryEngine(
            wyckoff_analyzer=wyckoff,
            llm_client=llm_client,
            prompt_registry=prompt_registry,
        )
        self.state_machine = OpportunityStateMachine()

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "").upper().strip()
        opp_id = context.get("opp_id", "")
        base_path = context.get("base_path", "")
        if not ticker or not opp_id:
            msg = "Both ticker and opp_id are required"
            raise ValueError(msg)

        from pathlib import Path
        bp = Path(base_path) if base_path else Path.cwd()
        sqlite = SQLiteStore(bp / "idos.db")
        journal = JournalRepository(bp / "idos-journal")

        opp = sqlite.get_opportunity(opp_id)
        if not opp:
            return {"ticker": ticker, "opp_id": opp_id, "status": "skipped",
                    "reason": f"Opportunity {opp_id} not found in SQLite. Run DDD first."}

        current_status = OpportunityStatus(opp["status"])
        if current_status not in (OpportunityStatus.APPROVED, OpportunityStatus.ENTRY_PENDING):
            return {"ticker": ticker, "opp_id": opp_id, "status": "skipped",
                    "reason": f"Current status {current_status} not monitored for entry"}

        if current_status == OpportunityStatus.APPROVED:
            if not self.state_machine.can_transition(current_status, OpportunityStatus.ENTRY_PENDING):
                return {"ticker": ticker, "opp_id": opp_id, "status": "skipped",
                        "reason": "Cannot transition to ENTRY_PENDING"}
            opp["status"] = OpportunityStatus.ENTRY_PENDING.value
            opp["updated_at"] = datetime.now(AR_TZ).isoformat()
            sqlite.save_opportunity(opp)
            sqlite.record_transition(opp_id, current_status.value, "ENTRY_PENDING",
                                     cause="entry_monitor_activated", worker="entry_monitor_worker")

        entry_context = self._build_entry_context(ticker, opp, sqlite, journal)
        signal = self.entry_engine.evaluate(ticker, entry_context)

        if signal.all_conditions_met:
            new_status = OpportunityStatus.ACCUMULATING
            opp["status"] = new_status.value
            opp["updated_at"] = datetime.now(AR_TZ).isoformat()
            sqlite.save_opportunity(opp)
            sqlite.record_transition(opp_id, "ENTRY_PENDING", "ACCUMULATING",
                                     cause="entry_conditions_met", worker="entry_monitor_worker")

            self._record_entry_decision(ticker, opp_id, signal, journal, sqlite)

        return {
            "ticker": ticker,
            "opp_id": opp_id,
            "status": "entry_signal_generated",
            "all_conditions_met": signal.all_conditions_met,
            "price_in_zone": signal.price_in_zone,
            "wyckoff_confirmed": signal.wyckoff_confirmed,
            "thesis_active": signal.thesis_active,
            "portfolio_fit": signal.portfolio_fit,
            "current_price": signal.current_price,
            "target_price": signal.target_price,
            "margin_of_safety_pct": signal.margin_of_safety_pct,
            "wyckoff_phase": signal.wyckoff_phase,
            "reason": signal.reason,
            "entry_executed": signal.all_conditions_met,
        }

    def _build_entry_context(self, ticker: str, opp: dict[str, Any],
                              sqlite: SQLiteStore, journal: JournalRepository) -> dict[str, Any]:
        import json
        from pathlib import Path

        price_data: list[dict[str, Any]] = []

        db_rows = sqlite.get_price_history(ticker, limit=365)
        if db_rows:
            price_data = [
                {"close": r["close"], "volume": r.get("volume", 0)}
                for r in db_rows if r.get("close")
            ]
            print(f"[ENTRY] {ticker}: {len(price_data)} registros desde price_history")

        if not price_data:
            cache_path = Path("cache") / f"{ticker}.json"
            if cache_path.exists():
                try:
                    raw = json.loads(cache_path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        prices = raw.get("price_history", [])
                        volumes = raw.get("volume_history", [])
                        dates = raw.get("price_history_dates", [])
                        if not prices and "yfinance" in raw:
                            prices = raw["yfinance"].get("price_history", [])
                            volumes = raw["yfinance"].get("volume_history", [])
                            dates = raw["yfinance"].get("price_history_dates", [])
                        if not prices:
                            merged = raw.get("merged_data", {})
                            prices = merged.get("price_history", [])
                            volumes = merged.get("volume_history", [])
                            dates = merged.get("price_history_dates", [])
                        if prices and volumes:
                            min_len = min(len(prices), len(volumes))
                            price_data = [
                                {"close": prices[i], "volume": volumes[i]}
                                for i in range(min_len)
                            ]
                            print(f"[ENTRY] {ticker}: {len(price_data)} registros desde cache/{ticker}.json")
                except Exception as e:
                    print(f"[ENTRY] {ticker}: error leyendo cache: {e}")

        if not price_data:
            print(f"[ENTRY] {ticker}: sin datos de precio disponibles (ni SQLite ni cache)")

        conviction = opp.get("conviction", {})
        return {
            "price_data": price_data,
            "intrinsic_value": opp.get("intrinsic_value") or conviction.get("intrinsic_value", 0),
            "current_price": opp.get("current_price") or conviction.get("current_price", 0),
            "thesis_active": True,
            "portfolio": {"total_weight": 0},
            "proposed_weight": conviction.get("overall", 50) / 100 * 3 if conviction.get("overall") else 1.5,
        }

    def _record_entry_decision(self, ticker: str, opp_id: str, signal: Any,
                                journal: JournalRepository, sqlite: SQLiteStore):
        from uuid import uuid4
        decision_id = f"dec-{uuid4().hex[:8]}"
        decision = {
            "id": decision_id,
            "type": "BUY",
            "ticker": ticker,
            "opp_id": opp_id,
            "status": "EXECUTED",
            "price": signal.current_price,
            "target_price": signal.target_price,
            "margin_of_safety_pct": signal.margin_of_safety_pct,
            "wyckoff_phase": signal.wyckoff_phase,
            "rationale": signal.reason,
            "generated_at": datetime.now(AR_TZ).isoformat(),
        }
        journal.save_decision(ticker, opp_id, decision)
        sqlite.log_event("entry:executed", {
            "opp_id": opp_id, "ticker": ticker,
            "price": signal.current_price,
            "target": signal.target_price,
            "wyckoff": signal.wyckoff_phase,
        })

        self._notify_entry(ticker, signal)

    def _notify_entry(self, ticker: str, signal: Any):
        message = (
            f"**{ticker} - Senal de Entrada Ejecutada**\n\n"
            f"- Precio: `${signal.current_price:.2f}`\n"
            f"- Target: `${signal.target_price:.2f}`\n"
            f"- Margen: `{signal.margin_of_safety_pct:.1f}%`\n"
            f"- Wyckoff: `{signal.wyckoff_phase}`\n"
            f"- Decision: `BUY / {signal.reason}`"
        )
        print(message)
        try:
            from idos.workers.notifications.telegram import TelegramNotifier
            tg = TelegramNotifier()
            result = tg.execute({"message": message[:4000]})
            if result.output.get("status") == "skipped":
                print(f"[ENTRY NOTIFY] {result.output.get('reason', 'sin configurar')}")
                print(f"[ENTRY NOTIFY] {result.output.get('hint', 'configura IDOS_TELEGRAM_BOT_TOKEN y IDOS_TELEGRAM_CHAT_ID')}")
        except Exception as e:
            print(f"[ENTRY NOTIFY] Telegram error: {e}")
