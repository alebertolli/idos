import os
import smtplib
from email.mime.text import MIMEText
from typing import Any

from idos.workers.base import BaseWorker


class EmailNotifier(BaseWorker):
    name = "email"

    def __init__(self, config: dict[str, Any] | None = None):
        config = config if config is not None else {}
        super().__init__(config)
        self.smtp_host = config.get("smtp_host") or os.getenv("IDOS_SMTP_HOST", "")
        self.smtp_port = int(config.get("smtp_port") or os.getenv("IDOS_SMTP_PORT", "587"))
        self.smtp_user = config.get("smtp_user") or os.getenv("IDOS_SMTP_USER", "")
        self.smtp_pass = config.get("smtp_pass") or os.getenv("IDOS_SMTP_PASS", "")
        self.from_addr = config.get("from_addr") or os.getenv("IDOS_FROM_ADDR", "")
        self.to_addr = config.get("to_addr") or os.getenv("IDOS_TO_ADDR", "")

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        subject = context.get("subject", "IDOS Notification")
        body = context.get("body", "")
        to = context.get("to") or self.to_addr

        if not body:
            msg = "No body provided"
            raise ValueError(msg)
        if not to:
            return {
                "status": "skipped",
                "reason": "IDOS_TO_ADDR no configurado",
                "hint": "Configura IDOS_SMTP_HOST, IDOS_SMTP_USER, IDOS_SMTP_PASS, IDOS_TO_ADDR",
            }

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self.from_addr or self.smtp_user
        msg["To"] = to

        if not self.smtp_host:
            # Modo offline: guardar a archivo
            from pathlib import Path
            out_dir = Path("idos-journal/notifications")
            out_dir.mkdir(parents=True, exist_ok=True)
            fname = f"email_{subject[:20]}_{len(os.listdir(out_dir))}.txt"
            (out_dir / fname).write_text(body, encoding="utf-8")
            return {"status": "saved_to_file", "file": str(out_dir / fname)}

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
            return {"status": "sent", "to": to, "subject": subject}
        except Exception as e:
            return {"status": "failed", "error": str(e)}
