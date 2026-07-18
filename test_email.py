"""Test email notification via Gmail SMTP"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "idos-core"))

from idos.workers.notifications.email_notifier import EmailNotifier

# Use env vars or prompt
os.environ.setdefault("IDOS_SMTP_HOST", input("SMTP Host (smtp.gmail.com): ") or "smtp.gmail.com")
os.environ.setdefault("IDOS_SMTP_PORT", input("Port (587): ") or "587")
os.environ.setdefault("IDOS_SMTP_USER", input("Gmail user: "))
os.environ.setdefault("IDOS_SMTP_PASS", input("App Password: "))
os.environ.setdefault("IDOS_FROM_ADDR", os.environ["IDOS_SMTP_USER"])
os.environ.setdefault("IDOS_TO_ADDR", input("Send to: "))

n = EmailNotifier()
r = n.execute({"subject": "IDOS Test", "body": "Email configurado correctamente ✅"})
print(r)
