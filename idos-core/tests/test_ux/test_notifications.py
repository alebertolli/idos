import pytest
from idos.ux.notifications import NotificationTemplateEngine


class TestNotificationTemplateEngine:
    def test_render_entry_signal(self):
        nte = NotificationTemplateEngine()
        result = nte.render("entry_signal", {"ticker": "AAPL", "price": 150.50, "conviction": 85})
        assert result is not None
        assert "AAPL" in result
        assert "150.50" in result
        assert "85" in result

    def test_render_risk_alert(self):
        nte = NotificationTemplateEngine()
        result = nte.render("risk_alert", {
            "ticker": "AAPL", "alert_type": "STOP_LOSS", "message": "Drawdown exceeded 20%",
        })
        assert result is not None
        assert "STOP_LOSS" in result

    def test_missing_template(self):
        nte = NotificationTemplateEngine()
        result = nte.render("nonexistent", {})
        assert result is None

    def test_missing_context_key(self):
        nte = NotificationTemplateEngine()
        result = nte.render("entry_signal", {"ticker": "AAPL"})
        assert result is None

    def test_register_custom_template(self):
        nte = NotificationTemplateEngine()
        nte.register_template("custom", "Hello {name}!")
        result = nte.render("custom", {"name": "World"})
        assert result == "Hello World!"

    def test_render_or_fallback(self):
        nte = NotificationTemplateEngine()
        result = nte.render_or_fallback("nonexistent", {}, fallback="Default message")
        assert result == "Default message"

    def test_list_templates(self):
        nte = NotificationTemplateEngine()
        templates = nte.list_templates()
        assert "entry_signal" in templates
        assert "exit_signal" in templates
