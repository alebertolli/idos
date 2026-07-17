from datetime import datetime, timezone
from typing import Any

from idos.workers.base import BaseWorker


class DigestWorker(BaseWorker):
    name = "digest_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        scout_results = context.get("scout_results", [])
        risk_alerts = context.get("risk_alerts", [])
        positions = context.get("positions", [])
        opportunities = context.get("opportunities", [])

        lines: list[str] = []
        lines.append(f"# 📊 IDOS Weekly Digest — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
        lines.append("")
        lines.append("## Resumen de la Semana")
        lines.append("")

        passed = [s for s in scout_results if s.get("passed")]
        lines.append(f"- **Oportunidades identificadas:** {len(passed)}")
        lines.append(f"- **Alertas de riesgo activas:** {len(risk_alerts)}")
        lines.append(f"- **Posiciones activas:** {len(positions)}")
        lines.append("")

        if passed:
            lines.append("### Nuevas Oportunidades de Screening")
            lines.append("")
            lines.append("| Ticker | Score | Razón |")
            lines.append("|--------|-------|-------|")
            for s in passed:
                lines.append(f"| {s['ticker']} | {s.get('score', 'N/A')} | {s.get('reason', '')} |")
            lines.append("")

        if risk_alerts:
            lines.append("### Alertas de Riesgo")
            lines.append("")
            for alert in risk_alerts:
                lines.append(f"- 🔴 **{alert.get('ticker')}**: {alert.get('message', '')}")
            lines.append("")

        if opportunities:
            lines.append("### Estado de Oportunidades")
            lines.append("")
            lines.append("| ID | Ticker | Estado | Convicción |")
            lines.append("|-----|--------|--------|------------|")
            for opp in opportunities:
                lines.append(
                    f"| {opp.get('id', '')} | {opp.get('ticker', '')} "
                    f"| {opp.get('status', '')} | {opp.get('conviction', 'N/A')} |"
                )
            lines.append("")

        lines.append("---")
        lines.append("*Generado automáticamente por IDOS*")

        digest_text = "\n".join(lines)
        return {
            "digest": digest_text,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "line_count": len(lines),
            "summary": {
                "opportunities": len(passed),
                "risk_alerts": len(risk_alerts),
                "positions": len(positions),
            },
        }
