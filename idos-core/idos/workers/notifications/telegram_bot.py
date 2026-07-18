import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from idos.workers.base import BaseWorker, WorkerResult


COMMANDS = {
    "/start": "Muestra esta ayuda",
    "/help": "Muestra esta ayuda",
    "/watchlist": "Muestra la watchlist actual",
    "/dashboard": "Resumen general del sistema",
    "/opp-list": "Lista oportunidades activas",
    "/position-list": "Lista posiciones abiertas",
    "/event-log": "Eventos recientes del sistema",
    "/scout": "Ejecuta screening y muestra resultados",
}


class TelegramBot(BaseWorker):
    name = "telegram_bot"

    def __init__(self, config: dict[str, Any] | None = None):
        config = config if config is not None else {}
        super().__init__(config)
        self.bot_token = config.get("bot_token") or os.getenv("IDOS_TELEGRAM_BOT_TOKEN", "")
        self.chat_id = config.get("chat_id") or os.getenv("IDOS_TELEGRAM_CHAT_ID", "")
        self.last_update_id = config.get("last_update_id", 0)
        self.poll_timeout = int(config.get("poll_timeout", 30))
        self.base_path = config.get("base_path", Path.cwd())

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        single_run = context.get("single_run", False)
        updates = self._get_updates(timeout=self.poll_timeout if not single_run else 5)
        results = []
        for update in updates:
            msg = update.get("message", {}) or update.get("channel_post", {})
            chat_id = msg.get("chat", {}).get("id")
            text = (msg.get("text") or "").strip()
            if not text or not chat_id:
                continue
            if chat_id != self.chat_id:
                continue
            result = self._handle_command(text, chat_id)
            results.append(result)
            self.last_update_id = max(self.last_update_id, update.get("update_id", 0) + 1)
        return {"processed": len(results), "results": results, "last_update_id": self.last_update_id}

    def _get_updates(self, timeout: int = 30) -> list[dict]:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/getUpdates",
                json={
                    "offset": self.last_update_id,
                    "timeout": timeout,
                    "allowed_updates": ["message", "channel_post"],
                },
                timeout=timeout + 5,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", [])
        except Exception as e:
            print(f"[TELEGRAM_BOT] getUpdates error: {e}")
            return []

    def _send(self, chat_id: int | str, text: str, parse_mode: str = "Markdown"):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as e:
            print(f"[TELEGRAM_BOT] sendMessage error: {e}")

    def _handle_command(self, text: str, chat_id: int | str) -> dict:
        cmd = text.split()[0].lower()
        args = text.split()[1:] if len(text.split()) > 1 else []

        handler = {
            "/start": self._cmd_help,
            "/help": self._cmd_help,
            "/watchlist": self._cmd_watchlist,
            "/dashboard": self._cmd_dashboard,
            "/opp-list": self._cmd_opp_list,
            "/position-list": self._cmd_position_list,
            "/event-log": self._cmd_event_log,
            "/scout": self._cmd_scout,
        }.get(cmd)

        if handler:
            try:
                handler(args, chat_id)
                return {"command": cmd, "status": "ok"}
            except Exception as e:
                self._send(chat_id, f"Error ejecutando {cmd}: {e}")
                return {"command": cmd, "status": "error", "error": str(e)}
        else:
            self._send(chat_id, f"Comando no reconocido: {cmd}\n\nUsá /help para ver los comandos disponibles.")
            return {"command": cmd, "status": "unknown"}

    def _cmd_help(self, args: list[str], chat_id: int | str):
        lines = ["*Comandos disponibles:*", ""]
        for cmd, desc in COMMANDS.items():
            lines.append(f"`{cmd}` — {desc}")
        lines.append("")
        lines.append("Enviá cualquier comando y recibís el resultado.")
        self._send(chat_id, "\n".join(lines))

    def _cmd_watchlist(self, args: list[str], chat_id: int | str):
        from idos.data.journal import JournalRepository
        repo = JournalRepository(self.base_path / "idos-journal")
        entries = repo.load_watchlist()
        if not entries:
            self._send(chat_id, "Watchlist vacía.")
            return
        lines = [f"*Watchlist ({len(entries)} entries)*", ""]
        for e in sorted(entries, key=lambda x: x.get("score", 0), reverse=True)[:10]:
            lines.append(f"• {e['ticker']}: {e.get('score', '?')} pts")
        if len(entries) > 10:
            lines.append(f"\n... y {len(entries) - 10} más")
        self._send(chat_id, "\n".join(lines))

    def _cmd_dashboard(self, args: list[str], chat_id: int | str):
        db_path = self.base_path / "idos.db"
        from idos.data.sqlite import SQLiteStore
        store = SQLiteStore(str(db_path))
        opps = store.list_opportunities()
        active = [o for o in opps if o["status"] not in ("ARCHIVED", "EXITED")]
        lines = ["*IDOS Dashboard*", ""]
        lines.append(f"• Oportunidades activas: {len(active)}")
        lines.append(f"• Total oportunidades: {len(opps)}")
        lines.append("")
        lines.append("Usá `/opp-list` para ver detalles o `/watchlist` para screening.")
        self._send(chat_id, "\n".join(lines))

    def _cmd_opp_list(self, args: list[str], chat_id: int | str):
        db_path = self.base_path / "idos.db"
        from idos.data.sqlite import SQLiteStore
        store = SQLiteStore(str(db_path))
        opps = store.list_opportunities()
        if not opps:
            self._send(chat_id, "No hay oportunidades registradas.")
            return
        lines = [f"*Oportunidades ({len(opps)})*", ""]
        for opp in opps[:10]:
            conv = opp.get("conviction", {}).get("overall", "N/A")
            lines.append(f"• {opp['id']} | {opp['ticker']} | {opp['status']} | {conv}")
        if len(opps) > 10:
            lines.append(f"\n... y {len(opps) - 10} más")
        self._send(chat_id, "\n".join(lines))

    def _cmd_position_list(self, args: list[str], chat_id: int | str):
        from idos.data.journal import JournalRepository
        from idos.portfolio.engine import PortfolioEngine
        repo = JournalRepository(self.base_path / "idos-journal")
        engine = PortfolioEngine(repo)
        positions = engine.get_positions()
        if not positions:
            self._send(chat_id, "No hay posiciones abiertas.")
            return
        lines = ["*Posiciones Activas*", ""]
        for p in positions:
            lines.append(f"• {p['ticker']}: {p.get('shares', 0)} shares @ ${p.get('avg_entry_price', 0):.2f}")
        self._send(chat_id, "\n".join(lines))

    def _cmd_event_log(self, args: list[str], chat_id: int | str):
        from idos.events.bus import get_event_bus
        bus = get_event_bus()
        history = bus.get_history()
        if not history:
            self._send(chat_id, "No hay eventos registrados.")
            return
        lines = ["*Eventos Recientes*", ""]
        for e in history[-10:]:
            lines.append(f"• {e.type} | {e.timestamp.isoformat()[:19]}")
        self._send(chat_id, "\n".join(lines))

    def _cmd_scout(self, args: list[str], chat_id: int | str):
        from idos.workers.data.scout_worker import ScoutWorker
        tickers = [t.upper() for t in args if t.upper().isalpha()] if args else []
        config = {
            "universe_path": str(self.base_path / "idos-config/universe/watchlist.md"),
            "journal_path": str(self.base_path / "idos-journal"),
        }
        if tickers:
            config["tickers"] = tickers
        w = ScoutWorker(config)
        r = w.execute({"force_refresh": False, "tickers": tickers or None})
        if r.status == "failed":
            self._send(chat_id, f"Scout falló: {r.error}")
            return
        passed = [res for res in r.output.get("results", []) if res.get("passed")]
        lines = [f"*Scout: {r.output.get('tickers_screened', 0)} evaluados, {len(passed)} pasaron*", ""]
        for res in passed[:10]:
            lines.append(f"• {res['ticker']}: {res.get('scout_score', '?')} pts (#{res.get('rank', '?')})")
        self._send(chat_id, "\n".join(lines))
