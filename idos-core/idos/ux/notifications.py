from typing import Any


class NotificationTemplateEngine:
    def __init__(self):
        self._templates: dict[str, str] = {
            "entry_signal": "BUY SIGNAL: {ticker} - Price ${price:.2f}, Conviction {conviction}/100",
            "exit_signal": "EXIT SIGNAL: {ticker} - Reason: {reason}, Urgency: {urgency}",
            "risk_alert": "RISK ALERT: {ticker} - {alert_type}: {message}",
            "weekly_summary": "WEEKLY SUMMARY: {positions} positions, P&L {pnl:+.1f}%, Cash {cash_pct:.1f}%",
            "watchlist_alert": "WATCHLIST: {ticker} - {reason}",
            "portfolio_rebalance": "REBALANCE: Position {ticker} - {action} ({reason})",
            "decision_ready": "DECISION READY: {ticker} - {verdict} (Conviction: {conviction}/100)",
        }

    def register_template(self, name: str, template: str):
        self._templates[name] = template

    def render(self, template_name: str, context: dict[str, Any]) -> str | None:
        template = self._templates.get(template_name)
        if not template:
            return None
        try:
            return template.format(**context)
        except KeyError:
            return None

    def render_or_fallback(self, template_name: str, context: dict[str, Any],
                           fallback: str = "") -> str:
        result = self.render(template_name, context)
        return result or fallback

    def list_templates(self) -> list[str]:
        return list(self._templates.keys())
