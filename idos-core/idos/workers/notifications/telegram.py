import os
from typing import Any

import requests

from idos.workers.base import BaseWorker


class TelegramNotifier(BaseWorker):
    name = "telegram"

    def __init__(self, config: dict[str, Any] | None = None):
        config = config if config is not None else {}
        super().__init__(config)
        self.bot_token = config.get("bot_token") or os.getenv("IDOS_TELEGRAM_BOT_TOKEN", "")
        self.chat_id = config.get("chat_id") or os.getenv("IDOS_TELEGRAM_CHAT_ID", "")

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        message = context.get("message", "")
        parse_mode = context.get("parse_mode", "Markdown")
        if not message:
            msg = "No message provided"
            raise ValueError(msg)
        if not self.bot_token or not self.chat_id:
            return {
                "status": "skipped",
                "reason": "TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados",
                "hint": "Crea un bot con @BotFather en Telegram y configura las env vars",
            }
        resp = requests.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "status": "sent",
            "message_id": data.get("result", {}).get("message_id"),
            "chat_id": self.chat_id,
        }
