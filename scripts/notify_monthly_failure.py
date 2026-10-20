"""Send the optional Telegram failure alert."""

import os

from idos.workers.notifications.telegram import TelegramNotifier


def main() -> int:
    token = os.environ.get("IDOS_TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("IDOS_TELEGRAM_CHAT_ID")
    if token and chat:
        TelegramNotifier({"bot_token": token, "chat_id": chat}).execute(
            {"message": "🚨 *IDOS Alert*: Monthly Universe Pipeline workflow FAILED"}
        )
        print("Failure alert sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
