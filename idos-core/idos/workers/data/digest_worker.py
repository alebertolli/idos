from datetime import datetime
from typing import Any

from idos.workers.base import BaseWorker
from idos.timezone import AR_TZ

class DigestWorker(BaseWorker):
    name = "digest_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        scout_results = context.get("scout_results", [])
        risk_alerts = context.get("risk_alerts", [])
        positions = context.get("positions", [])
        opportunities = context.get("opportunities", [])

        print(f"[DIGEST] Generating digest: {len(scout_results)} scout results, {len(risk_alerts)} alerts, {len(positions)} positions, {len(opportunities)} opportunities")

        now = datetime.now(AR_TZ)
        week_start = now.strftime("%Y-%m-%d")
        lines: list[str] = []
        lines.append(f"# 📊 IDOS Weekly Digest — {week_start}")
        lines.append("")
        lines.append(f"_Generado: {now.strftime('%Y-%m-%d %H:%M GMT-3')}_")
        lines.append("")

        passed = [s for s in scout_results if s.get("passed")]
        lines.append("## Resumen de la Semana")
        lines.append("")
        lines.append(f"- 🟢 **Oportunidades identificadas:** {len(passed)}")
        lines.append(f"- 🟡 **Alertas de riesgo activas:** {len(risk_alerts)}")
        lines.append(f"- 🔵 **Posiciones activas:** {len(positions)}")
        lines.append(f"- 🔍 **Tickers evaluados:** {len(scout_results)}")
        lines.append("")

        if passed:
            lines.append("### 🟢 Nuevas Oportunidades de Screening")
            lines.append("")
            lines.append("| # | Ticker | Score | Rank | Razón |")
            lines.append("|---|--------|-------|------|-------|")
            for s in sorted(passed, key=lambda x: x.get("rank", 99)):
                score = s.get("scout_score") or s.get("score", "N/A")
                lines.append(f"| {s.get('rank', '-')} | **{s['ticker']}** | {score} | #{s.get('rank', '-')} | {s.get('reason', '')} |")
            lines.append("")

        if not passed and len(scout_results) > 0:
            lines.append("### ℹ️ Screening Completado")
            lines.append("")
            lines.append("Se evaluaron todos los tickers pero ninguno superó el umbral mínimo de score.")
            lines.append("")

        if risk_alerts:
            lines.append("### 🟡 Alertas de Riesgo")
            lines.append("")
            for alert in risk_alerts:
                lines.append(f"- 🔴 **{alert.get('ticker')}**: {alert.get('message', '')}")
            lines.append("")

        if opportunities:
            lines.append("### 📌 Estado de Oportunidades")
            lines.append("")
            lines.append("| ID | Ticker | Estado | Convicción |")
            lines.append("|-----|--------|--------|------------|")
            for opp in opportunities:
                lines.append(
                    f"| {opp.get('id', '')} | **{opp.get('ticker', '')}** "
                    f"| {opp.get('status', '')} | {opp.get('conviction', 'N/A')} |"
                )
            lines.append("")

        if positions:
            lines.append("### 📊 Cartera Activa")
            lines.append("")
            lines.append("| Ticker | Peso | P/L |")
            lines.append("|--------|------|-----|")
            for p in positions:
                lines.append(f"| **{p.get('ticker', '')}** | {p.get('weight', 'N/A')}% | {p.get('pnl_pct', 'N/A')}% |")
            lines.append("")

        lines.append("")
        lines.append("---")
        lines.append(f"*🤖 Generado automáticamente por IDOS — {now.strftime('%Y-%m-%d %H:%M GMT-3')}*")

        digest_text = "\n".join(lines)
        return {
            "digest": digest_text,
            "generated_at": now.isoformat(),
            "line_count": len(lines),
            "summary": {
                "opportunities": len(passed),
                "risk_alerts": len(risk_alerts),
                "positions": len(positions),
            },
        }
