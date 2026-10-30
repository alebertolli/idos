from scripts import notify_ddd_failure


def test_failure_message_reports_batch_state_and_run_link():
    message = notify_ddd_failure.build_failure_message(
        {
            "total": 3,
            "processed": [{"status": "completed"}],
            "errors": [{"status": "ddd_failed"}],
        },
        {
            "pause_reason": "GROQ 429; Gemini timeout",
            "last_successful_batch_size": 2,
            "last_failure": {"safe_batch_size": 2},
        },
        "https://github.com/alebertolli/idos/actions/runs/123",
    )

    assert "lote: 3" in message.lower()
    assert "completos: 1" in message.lower()
    assert "tamaño al reanudar: 2" in message.lower()
    assert "GROQ 429" in message
    assert "https://github.com/alebertolli/idos/actions/runs/123" in message


def test_failure_alert_uses_each_configured_private_channel(monkeypatch):
    sent = []

    class FakeTelegramNotifier:
        def __init__(self, config):
            sent.append(("telegram-configured", config["chat_id"]))

        def execute(self, context):
            sent.append(("telegram", context["message"], context["parse_mode"]))
            return {"status": "sent"}

    class FakeEmailNotifier:
        def __init__(self, config):
            sent.append(("email-configured", config["to_addr"]))

        def execute(self, context):
            sent.append(("email", context["subject"], context["body"]))
            return {"status": "sent"}

    monkeypatch.setattr("idos.workers.notifications.telegram.TelegramNotifier", FakeTelegramNotifier)
    monkeypatch.setattr("idos.workers.notifications.email_notifier.EmailNotifier", FakeEmailNotifier)

    channels = notify_ddd_failure.send_alert(
        "Research stopped", {
            "IDOS_TELEGRAM_BOT_TOKEN": "test-token",
            "IDOS_TELEGRAM_CHAT_ID": "test-chat",
            "IDOS_SMTP_HOST": "smtp.example.test",
            "IDOS_SMTP_PORT": "587",
            "IDOS_SMTP_USER": "sender@example.test",
            "IDOS_SMTP_PASS": "test-password",
            "IDOS_FROM_ADDR": "sender@example.test",
            "IDOS_TO_ADDR": "owner@example.test",
        }
    )

    assert channels == ["telegram", "email"]
    assert ("telegram", "Research stopped", None) in sent
    assert any(item[0] == "email" and item[2] == "Research stopped" for item in sent)


def test_failure_alert_without_channel_reports_no_delivery():
    assert notify_ddd_failure.send_alert("Research stopped", {}) == []
