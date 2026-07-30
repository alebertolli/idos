from datetime import datetime
from pathlib import Path
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


def _format_wyckoff_md(ticker: str, signal: Any) -> str:
    def _val(d: dict | None, *keys: str) -> str:
        for k in keys:
            if d and k in d and d[k] is not None and d[k] != "" and d[k] != 0:
                return str(d[k])
        return "N/A"

    def _float_val(d: dict | None, *keys: str) -> str:
        for k in keys:
            if d and k in d and d[k] is not None and d[k] != 0 and d[k] != "":
                try:
                    return f"{float(d[k]):.2f}"
                except (ValueError, TypeError):
                    return str(d[k])
        return "N/A"

    raw = signal.wyckoff_raw
    ind = signal.wyckoff_indicators

    current_price = _float_val(ind, "current_price")
    ma_50d = _float_val(ind, "ma_50d")
    ma_200d = _float_val(ind, "ma_200d")
    pct_ma50 = _val(ind, "pct_from_ma50")
    pct_ma200 = _val(ind, "pct_from_ma200")
    high_52w = _float_val(ind, "high_52w")
    low_52w = _float_val(ind, "low_52w")
    pct_52w_high = _val(ind, "pct_from_52w_high")
    pct_52w_low = _val(ind, "pct_from_52w_low")
    trend = _val(ind, "recent_trend")
    spread_desc = _val(ind, "bar_spread_description")
    vol_desc = _val(ind, "volume_description")
    support = _val(ind, "support_levels")
    resistance = _val(ind, "resistance_levels")
    algo_phase = _val(ind, "algorithmic_phase")

    eventos = []
    if raw:
        for e in (raw.get("eventos_wyckoff_detectados") or []):
            if isinstance(e, dict):
                eventos.append(f"| {e.get('evento', '?')} | {e.get('descripcion', '')} | {e.get('confianza', '')} |")

    pruebas = []
    pasan = "?"
    total = "?"
    if raw:
        pc = raw.get("pruebas_compra") or {}
        pasan = str(pc.get("pruebas_pasan", "?"))
        total = str(pc.get("total_pruebas", "?"))
        for i in range(1, 10):
            key = f"prueba_{i}_"
            val = next((v for k, v in pc.items() if k.startswith(key)), "N/A")
            emoji = "✅" if val == "Pasa" else "❌" if val == "NoPasa" else "⬜"
            pruebas.append(f"- {emoji} Prueba {i}: {val}")

    stop_loss = _float_val(raw, "stop_loss_sugerido", "precio") if raw else "N/A"
    price_target = "N/A"
    if raw:
        pt = raw.get("precio_objetivo_wyckoff") or {}
        price_target = _float_val(pt, "estimado")

    entry_point = signal.wyckoff_entry_point or "N/A"
    confidence = signal.wyckoff_confidence or _val(raw, "confianza") or "N/A"
    senal_llm = _val(raw, "senal_entrada") if raw else "N/A"

    md = (
        f"# Analisis Wyckoff - {ticker} - {datetime.now(AR_TZ).strftime('%Y-%m-%d')}\n\n"
        f"## Fase detectada: {signal.wyckoff_phase.title()}\n"
        f"## Score: {signal.wyckoff_score}/100\n"
        f"## Confianza: {confidence}\n"
        f"## Senal LLM: {senal_llm}\n\n"
    )

    md += "### Indicadores Tecnicos\n"
    md += f"| Indicador | Valor |\n|-----------|-------|\n"
    md += f"| Precio Actual | ${current_price} |\n"
    md += f"| MA 50d | ${ma_50d} ({pct_ma50}%) |\n"
    md += f"| MA 200d | ${ma_200d} ({pct_ma200}%) |\n"
    md += f"| Max 52 sem | ${high_52w} ({pct_52w_high}%) |\n"
    md += f"| Min 52 sem | ${low_52w} ({pct_52w_low}%) |\n"
    md += f"| Tendencia reciente | {trend} |\n"
    md += f"| Spread de barras | {spread_desc} |\n"
    md += f"| Volumen | {vol_desc} |\n"
    md += f"| Soportes | {support} |\n"
    md += f"| Resistencias | {resistance} |\n"
    md += f"| Fase algoritmica | {algo_phase} |\n\n"

    if eventos:
        md += "### Eventos Wyckoff Detectados\n"
        md += "| Evento | Descripcion | Confianza |\n|--------|-------------|-----------|\n"
        md += "".join(eventos) + "\n"

    if pruebas:
        md += "### Pruebas de Compra\n"
        md += "\n".join(pruebas) + "\n\n"
        md += f"**Pasan:** {pasan}/{total}\n\n"
    else:
        md += "### Pruebas de Compra\nNo disponible (analisis algoritmico)\n\n"

    md += (
        f"### Punto de Entrada: {entry_point}\n"
        f"### Precio Objetivo Wyckoff: {price_target}\n"
        f"### Stop Loss Sugerido: {stop_loss}\n"
        f"### Peso Ajustado: {signal.adjusted_weight:.1f}%\n"
        f"### Precio Actual: ${signal.current_price:.2f}\n"
        f"### Target (Tesis): ${signal.target_price:.2f}\n"
        f"### Margen de Seguridad: {signal.margin_of_safety_pct:.1f}%\n"
    )
    return md


class EntryMonitorWorker(BaseWorker):
    """Monitors APPROVED/ENTRY_PENDING opportunities for entry conditions.

    Triggers: daily schedule or manual CLI.
    Transitions: ENTRY_PENDING -> ACCUMULATING.
    """
    name = "entry_monitor_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        cfg = self.config or {}
        llm_client = cfg.get("llm_service")
        prompt_registry = None
        if not llm_client and cfg.get("provider"):
            llm_client = LLMClient(
                provider=cfg.get("provider", ""),
                api_key=cfg.get("api_key", ""),
                model=cfg.get("model", ""),
                fallback_model=cfg.get("fallback_model", ""),
                fallback_providers=cfg.get("fallback_providers", []),
            )
        if self.config.get("prompts_path"):
            prompt_registry = PromptRegistry(self.config["prompts_path"])

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

        bp = Path(base_path) if base_path else Path.cwd()
        sqlite = SQLiteStore(bp / "idos.db")
        journal = JournalRepository(bp / "idos-journal")

        opp = sqlite.get_opportunity(opp_id)
        if not opp:
            yaml_opp = journal.load_opportunity(ticker, opp_id)
            if yaml_opp:
                sqlite.save_opportunity(yaml_opp)
                opp = sqlite.get_opportunity(opp_id)
                print(f"[ENTRY] {ticker}: restored from journal YAML -> SQLite")
            else:
                return {"ticker": ticker, "opp_id": opp_id, "status": "skipped",
                        "reason": f"Opportunity {opp_id} not found in SQLite or journal"}

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

        wyckoff_paths = self._persist_wyckoff_analysis(ticker, opp_id, signal, bp)

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
            "wyckoff_score": signal.wyckoff_score,
            "wyckoff_confidence": signal.wyckoff_confidence,
            "wyckoff_entry_point": signal.wyckoff_entry_point,
            "wyckoff_stop_loss": signal.wyckoff_stop_loss,
            "wyckoff_price_target": signal.wyckoff_price_target,
            "adjusted_weight": signal.adjusted_weight,
            "wyckoff_journal_path": str(wyckoff_paths.get("journal", "")),
            "wyckoff_knowledge_path": str(wyckoff_paths.get("knowledge_md", "")),
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

    def _persist_wyckoff_analysis(
        self, ticker: str, opp_id: str, signal: Any, base_path: Path
    ) -> dict[str, str]:
        import json
        import yaml
        paths: dict[str, str] = {}
        now = datetime.now(AR_TZ)
        ts = now.strftime("%Y%m%d_%H%M%S")
        date_str = now.strftime("%Y-%m-%d")

        journal_wyckoff_dir = base_path / "idos-journal" / "companies" / ticker / "opportunities" / opp_id / "wyckoff"
        journal_wyckoff_dir.mkdir(parents=True, exist_ok=True)
        journal_file = journal_wyckoff_dir / f"{ts}.yml"

        wyckoff_data = {
            "analyzed_at": now.isoformat(),
            "ticker": ticker,
            "opp_id": opp_id,
            "phase": signal.wyckoff_phase,
            "score": signal.wyckoff_score,
            "confidence": signal.wyckoff_confidence,
            "entry_point": signal.wyckoff_entry_point,
            "stop_loss": signal.wyckoff_stop_loss,
            "price_target": signal.wyckoff_price_target,
            "adjusted_weight": signal.adjusted_weight,
            "llm_response": signal.wyckoff_raw,
            "indicators": signal.wyckoff_indicators,
            "triggered_entry": signal.all_conditions_met,
        }
        with open(journal_file, "w", encoding="utf-8") as f:
            yaml.dump(wyckoff_data, f, default_flow_style=False, allow_unicode=True)
        paths["journal"] = str(journal_file)
        print(f"[ENTRY] {ticker}: Wyckoff analysis saved to {journal_file}")

        knowledge_dir = base_path / "idos-knowledge" / "companies" / ticker / "wyckoff"
        try:
            knowledge_dir.mkdir(parents=True, exist_ok=True)
            md_content = _format_wyckoff_md(ticker, signal)
            md_file = knowledge_dir / f"{date_str}.md"
            md_file.write_text(md_content, encoding="utf-8")
            paths["knowledge_md"] = str(md_file)

            if signal.wyckoff_raw:
                raw_file = knowledge_dir / f"{date_str}.raw.json"
                raw_file.write_text(json.dumps(signal.wyckoff_raw, indent=2, ensure_ascii=False), encoding="utf-8")
                paths["knowledge_raw"] = str(raw_file)

            print(f"[ENTRY] {ticker}: Wyckoff wiki saved to {knowledge_dir}")
        except Exception as e:
            print(f"[ENTRY] {ticker}: Error saving Wyckoff to knowledge: {e}")

        return paths

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
            "wyckoff_score": signal.wyckoff_score,
            "wyckoff_confidence": signal.wyckoff_confidence,
            "wyckoff_entry_point": signal.wyckoff_entry_point,
            "wyckoff_stop_loss": signal.wyckoff_stop_loss,
            "wyckoff_price_target": signal.wyckoff_price_target,
            "adjusted_weight": signal.adjusted_weight,
            "rationale": signal.reason,
            "generated_at": datetime.now(AR_TZ).isoformat(),
        }
        journal.save_decision(ticker, opp_id, decision)
        sqlite.log_event("entry:executed", {
            "opp_id": opp_id, "ticker": ticker,
            "price": signal.current_price,
            "target": signal.target_price,
            "wyckoff": signal.wyckoff_phase,
            "wyckoff_score": signal.wyckoff_score,
        })

        self._notify_entry(ticker, signal)

    def _notify_entry(self, ticker: str, signal: Any):
        sl = f"${signal.wyckoff_stop_loss:.2f}" if signal.wyckoff_stop_loss else "N/A"
        message = (
            f"**{ticker} - Senal de Entrada Ejecutada**\n\n"
            f"- Precio: `${signal.current_price:.2f}`\n"
            f"- Target: `${signal.target_price:.2f}`\n"
            f"- Margen: `{signal.margin_of_safety_pct:.1f}%`\n"
            f"- Wyckoff: `{signal.wyckoff_phase}` (score: `{signal.wyckoff_score}`)\n"
            f"- Confianza: `{signal.wyckoff_confidence}`\n"
            f"- Pto. Entrada: `{signal.wyckoff_entry_point}`\n"
            f"- Stop Loss: `{sl}`\n"
            f"- Peso Ajustado: `{signal.adjusted_weight:.1f}%`\n"
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
