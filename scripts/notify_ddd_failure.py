"""Send concise Research failure alerts through configured private channels."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def build_failure_message(
    results: dict[str, Any], ramp: dict[str, Any], run_url: str
) -> str:
    processed = results.get("processed") or []
    errors = results.get("errors") or []
    completed = sum(item.get("status") == "completed" for item in processed if isinstance(item, dict))
    total = results.get("total", len(processed))
    batch = ramp.get("last_failure") or {}
    safe_size = batch.get("safe_batch_size", ramp.get("last_successful_batch_size", 0))
    resume_size = safe_size or 1
    first_error = errors[0] if errors and isinstance(errors[0], dict) else {}
    reason = (
        ramp.get("pause_reason")
        or first_error.get("error")
        or "El workflow terminó con un error; revisar el log del run."
    )
    reason = " ".join(str(reason).replace("`", "'").split())[:350]
    title = (
        "🚨 IDOS Research pausó la rampa horaria"
        if ramp.get("paused")
        else "🚨 Falló el workflow DDD de IDOS"
    )
    message = (
        f"{title}\n"
        f"Lote: {total}; completos: {completed}; errores registrados: {len(errors)}\n"
        f"Último lote completado: {safe_size}; tamaño al reanudar: {resume_size}\n"
        f"Motivo: {reason}\n"
        f"Run: {run_url}"
    )
    return message


def send_alert(message: str, env: dict[str, str] | None = None) -> list[str]:
    env = env or os.environ
    sent: list[str] = []
    token = env.get("IDOS_TELEGRAM_BOT_TOKEN", "")
    chat = env.get("IDOS_TELEGRAM_CHAT_ID", "")
    if token and chat:
        try:
            from idos.workers.notifications.telegram import TelegramNotifier

            result = TelegramNotifier({"bot_token": token, "chat_id": chat}).execute(
                {"message": message, "parse_mode": None}
            )
            if result.get("status") == "sent":
                sent.append("telegram")
            else:
                print("Telegram alert was not sent: {}".format(result.get("reason", "unknown")))
        except Exception as exc:
            print("Telegram alert failed: {}".format(str(exc)[:250]))

    smtp_host = env.get("IDOS_SMTP_HOST", "")
    to_addr = env.get("IDOS_TO_ADDR", "")
    if smtp_host and to_addr:
        try:
            from idos.workers.notifications.email_notifier import EmailNotifier

            result = EmailNotifier({
                "smtp_host": smtp_host,
                "smtp_port": env.get("IDOS_SMTP_PORT", "587"),
                "smtp_user": env.get("IDOS_SMTP_USER", ""),
                "smtp_pass": env.get("IDOS_SMTP_PASS", ""),
                "from_addr": env.get("IDOS_FROM_ADDR", ""),
                "to_addr": to_addr,
            }).execute({
                "subject": "IDOS Research: rampa horaria pausada",
                "body": message,
            })
            if result.get("status") == "sent":
                sent.append("email")
            else:
                print("Email alert was not sent: {}".format(result.get("reason", result.get("error", "unknown"))))
        except Exception as exc:
            print("Email alert failed: {}".format(str(exc)[:250]))
    return sent


def main() -> int:
    message = build_failure_message(
        _read_json(Path("cache/ddd_results.json")),
        _read_json(Path("cache/ddd_research_capacity.json")),
        os.environ.get("GITHUB_RUN_URL", ""),
    )
    sent = send_alert(message)
    print("Research failure alert sent via: {}".format(", ".join(sent) if sent else "no configured channel"))
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())

\n