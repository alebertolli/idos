from datetime import datetime
from pathlib import Path
from typing import Any
from statistics import mean

from idos.timezone import AR_TZ
from idos.portfolio.ledger import TradeLedger


def generate_monthly_report(ledger: TradeLedger, paper_trader, bankroll: float, report_date: str) -> str:
    positions = paper_trader.current_positions()
    all_trades = ledger.history()
    buys = [t for t in all_trades if t.type == "BUY"]
    sells = [t for t in all_trades if t.type == "SELL"]

    total_invested = sum(p["total_invested"] for p in positions)
    total_value = sum(p.get("current_value", p["total_invested"]) for p in positions)
    unrealized_pnl = total_value - total_invested
    cash = bankroll - total_invested
    cash_pct = round(cash / bankroll * 100, 1) if bankroll else 0

    closed_pnl = sum(t.pnl for t in sells)
    total_pnl = closed_pnl + unrealized_pnl
    total_pnl_pct = round((total_pnl / bankroll) * 100, 2)
    invested_pct = round(total_invested / bankroll * 100, 1) if bankroll else 0

    wins = [t for t in sells if t.pnl > 0]
    losses = [t for t in sells if t.pnl <= 0]
    win_rate = round(len(wins) / (len(wins) + len(losses)) * 100, 1) if sells else 0
    avg_win = round(mean(t.pnl for t in wins), 2) if wins else 0
    avg_loss = round(mean(t.pnl for t in losses), 2) if losses else 0
    profit_factor = round(abs(sum(t.pnl for t in wins) / sum(t.pnl for t in losses)), 2) if losses and sum(t.pnl for t in losses) != 0 else float("inf")

    total_volume = sum(t.value for t in all_trades)
    total_fees = sum(t.fee for t in all_trades)

    lines = []
    lines.append(f"# IDOS Paper Portfolio Report")
    lines.append(f"")
    lines.append(f"_Generado: {report_date}_")
    lines.append(f"")
    lines.append("## Resumen")
    lines.append(f"")
    lines.append(f"| Métrica | Valor |")
    lines.append(f"|---------|-------|")
    lines.append(f"| Bankroll | ${bankroll:,.0f} |")
    lines.append(f"| Total Invertido | ${total_invested:,.2f} ({invested_pct}%) |")
    lines.append(f"| Cash Disponible | ${cash:,.2f} ({cash_pct}%) |")
    lines.append(f"| Valor del Portfolio | ${total_value + cash:,.2f} |")
    lines.append(f"| P&L Realizado (Cerrado) | ${closed_pnl:+,.2f} |")
    lines.append(f"| P&L No Realizado (Abierto) | ${unrealized_pnl:+,.2f} |")
    lines.append(f"| P&L Total | ${total_pnl:+,.2f} ({total_pnl_pct:+.2f}%) |")
    lines.append(f"| Comisiones Pagadas | ${total_fees:,.2f} |")
    lines.append(f"| Volumen Total Operado | ${total_volume:,.2f} |")

    lines.append("")
    lines.append("## Performance")
    lines.append("")
    lines.append(f"| Métrica | Valor |")
    lines.append(f"|---------|-------|")
    lines.append(f"| Operaciones Cerradas | {len(sells)} |")
    lines.append(f"| Operaciones Ganadas | {len(wins)} |")
    lines.append(f"| Operaciones Perdidas | {len(losses)} |")
    lines.append(f"| Win Rate | {win_rate}% |")
    lines.append(f"| Avg Win | ${avg_win:+,.2f} |")
    lines.append(f"| Avg Loss | ${avg_loss:+,.2f} |")
    lines.append(f"| Profit Factor | {profit_factor if profit_factor != float('inf') else '∞'} |")

    if sells:
        total_gain_pct = sum(((t.value - t.fee) / _cost_basis(sells, t) - 1) * 100 for t in sells if _cost_basis(sells, t) > 0)
        avg_return = round(total_gain_pct / len(sells), 2) if sells else 0
        lines.append(f"| Retorno Promedio por Operación | {avg_return:+.2f}% |")

    lines.append("")
    lines.append("## Posiciones Activas")
    lines.append("")
    if positions:
        lines.append("| Ticker | Entry | Actual | P&L | P&L% | Weight | Stop Loss | Target | Días |")
        lines.append("|--------|-------|--------|-----|------|--------|-----------|--------|------|")
        for pos in positions:
            ticker = pos["ticker"]
            ep = pos.get("entry_price", 0)
            qty = pos.get("quantity", 0)
            invested = pos.get("total_invested", 0)
            sl = pos.get("stop_loss", 0)
            target = pos.get("target_price", 0)
            entry_date = pos.get("entry_date", "")
            cv = pos.get("current_value", invested)
            pnl = cv - invested
            pnl_pct = round((pnl / invested) * 100, 2) if invested else 0
            weight = round(invested / bankroll * 100, 1) if bankroll else 0
            days = (datetime.now(AR_TZ) - datetime.fromisoformat(entry_date)).days if entry_date else 0
            lines.append(f"| {ticker} | ${ep:.2f} | ${cv:.2f} | ${pnl:+,.2f} | {pnl_pct:+.2f}% | {weight}% | ${sl:.2f} | ${target:.2f} | {days} |")
    else:
        lines.append("_Sin posiciones activas._")

    lines.append("")
    lines.append("## Historial de Operaciones")
    lines.append("")
    if all_trades:
        lines.append("| Fecha | Ticker | Tipo | Precio | Cant | Valor | Comisión | Razón | P&L |")
        lines.append("|-------|--------|------|--------|------|-------|----------|-------|-----|")
        for t in sorted(all_trades, key=lambda x: x.date, reverse=True):
            d = datetime.fromisoformat(t.date).strftime("%Y-%m-%d %H:%M") if t.date else ""
            pnl_str = f"${t.pnl:+,.2f}" if t.type == "SELL" else "-"
            lines.append(f"| {d} | {t.ticker} | {t.type} | ${t.price:.2f} | {t.quantity} | ${t.value:.2f} | ${t.fee:.2f} | {t.reason} | {pnl_str} |")
    else:
        lines.append("_Sin operaciones registradas._")

    return "\n".join(lines)


def _cost_basis(sells: list, trade) -> float:
    for s in sells:
        if s.trade_id == trade.trade_id:
            return s.pnl
    return 0


def save_report(report: str, journal, report_date: str):
    report_dir = Path(str(journal.base_path)) / "paper" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    dt = datetime.fromisoformat(report_date) if report_date else datetime.now(AR_TZ)
    filename = dt.strftime("%Y-%m") + ".md"
    path = report_dir / filename
    path.write_text(report, encoding="utf-8")
    print(f"[REPORT] Saved to {path}")
    return path
