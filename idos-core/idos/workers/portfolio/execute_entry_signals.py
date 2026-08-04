"""Execute pending entry signals from cache/entry_signals.json.

Replaces the inline `python -c` block in daily-refresh.yml which broke on
f-strings containing `$` under bash double-quote processing.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from idos.config import load_config
from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.timezone import AR_TZ
from idos.workers.portfolio.paper_trader_worker import PaperTraderWorker


def _build_telegram_message(ticker, quantity, price, value, s):
    return (
        f"**{ticker} - Compra Ejecutada**\n\n"
        f"- Cantidad: `{quantity}`\n"
        f"- Precio: `${price:.2f}`\n"
        f"- Valor: `${value:.2f}`\n"
        f"- Target: `${s.get('target_price', 0):.2f}`\n"
        f"- Margen: `{s.get('margin_of_safety_pct', 0):.1f}%`\n"
        f"- Wyckoff: `{s.get('wyckoff_phase')}` (score: `{s.get('wyckoff_score')}`)\n"
        f"- Confianza: `{s.get('wyckoff_confidence')}`\n"
        f"- Peso: `{s.get('adjusted_weight', 0):.1f}%`\n"
        f"- Razón: `{s.get('reason', '')}`"
    )


def _notify_telegram(ticker, quantity, price, value, s):
    try:
        from idos.workers.notifications.telegram import TelegramNotifier
        message = _build_telegram_message(ticker, quantity, price, value, s)
        tg = TelegramNotifier()
        tg_result = tg.execute({"message": message[:4000]})
        if tg_result.output.get("status") == "skipped":
            print(f'[PAPER NOTIFY] Telegram: {tg_result.output.get("reason", "sin configurar")}')
    except Exception as e:
        print(f"[PAPER NOTIFY] Telegram error: {e}")


def _notify_email(ticker, quantity, price, value, s):
    try:
        from idos.workers.notifications.email_notifier import EmailNotifier
        smtp_host = os.environ.get("IDOS_SMTP_HOST", "")
        if not smtp_host:
            print("[PAPER NOTIFY] Email: SMTP no configurado")
            return
        run_url = (
            f"{os.environ.get('GITHUB_SERVER_URL', '')}/"
            f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/"
            f"{os.environ.get('GITHUB_RUN_ID', '')}"
        )
        email_body = (
            f"IDOS - Compra Ejecutada\n\n"
            f"Ticker: {ticker}\n"
            f"Cantidad: {quantity}\n"
            f"Precio: ${price:.2f}\n"
            f"Valor: ${value:.2f}\n"
            f"Target: ${s.get('target_price', 0):.2f}\n"
            f"Margen: {s.get('margin_of_safety_pct', 0):.1f}%\n"
            f"Wyckoff: {s.get('wyckoff_phase')} (score: {s.get('wyckoff_score')})\n"
            f"Confianza: {s.get('wyckoff_confidence')}\n"
            f"Peso Ajustado: {s.get('adjusted_weight', 0):.1f}%\n"
            f"Razon: {s.get('reason', '')}\n\n"
            f"Run: {run_url}"
        )
        en = EmailNotifier()
        en.execute({"subject": f"IDOS - Compra Ejecutada {ticker}", "body": email_body})
        print("[PAPER NOTIFY] Email sent")
    except Exception as e:
        print(f"[PAPER NOTIFY] Email error: {e}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    os.chdir(os.environ.get("GITHUB_WORKSPACE", "."))
    bp = Path(os.environ.get("GITHUB_WORKSPACE", "."))

    signals_file = bp / "cache" / "entry_signals.json"
    if not signals_file.exists():
        print("[PAPER] No entry signals found")
        return 0
    data = json.loads(signals_file.read_text(encoding="utf-8"))
    signals = data.get("signals", [])
    if not signals:
        print("[PAPER] No entry signals to execute")
        return 0

    journal = JournalRepository(bp / "idos-journal")
    db = SQLiteStore(bp / "idos.db")
    cfg = load_config(bp / "idos-config" / "portfolio.yml") or {}
    pw = PaperTraderWorker(cfg)

    for s in signals:
        ticker = s["ticker"]
        opp_id = s["opp_id"]
        print(f"[PAPER] {ticker}: intentando comprar...")

        opp_yaml = journal.load_opportunity(ticker, opp_id)
        if not opp_yaml:
            print(f"[PAPER] {ticker}: sin oportunidad en journal, skip")
            continue
        intrinsic = opp_yaml.get("intrinsic_value", 0)
        conviction = opp_yaml.get("conviction", {}).get("overall", 50)

        pr = pw.execute({
            "action": "buy",
            "ticker": ticker,
            "opp_id": opp_id,
            "price": s.get("current_price", 0),
            "conviction": conviction,
            "intrinsic_value": intrinsic,
            "base_path": str(bp),
        })
        r = pr.output if hasattr(pr, "output") else pr
        print(f"[PAPER] {ticker}: {r.get('status')} - {r.get('reason', '')}")

        if r.get("status") == "executed":
            quantity = r.get("quantity", 0)
            price = r.get("price", 0)
            value = r.get("value", 0)
            print(f"[PAPER] {ticker}: {quantity} shares @ ${price:.2f} = ${value:.2f}")

            opp = db.get_opportunity(opp_id)
            if opp:
                opp["status"] = "ACCUMULATING"
                opp["updated_at"] = datetime.now(AR_TZ).isoformat()
                db.save_opportunity(opp)
                db.record_transition(opp_id, "ENTRY_PENDING", "ACCUMULATING",
                                     cause="entry_executed", worker="paper_trader_worker")

            decision = {
                "id": f"dec-{opp_id.lower()}",
                "type": "BUY",
                "ticker": ticker,
                "opp_id": opp_id,
                "status": "EXECUTED",
                "price": price,
                "target_price": s.get("target_price"),
                "margin_of_safety_pct": s.get("margin_of_safety_pct"),
                "wyckoff_phase": s.get("wyckoff_phase"),
                "wyckoff_score": s.get("wyckoff_score"),
                "wyckoff_confidence": s.get("wyckoff_confidence"),
                "wyckoff_price_target": s.get("wyckoff_price_target"),
                "adjusted_weight": s.get("adjusted_weight"),
                "rationale": s.get("reason", ""),
                "generated_at": datetime.now(AR_TZ).isoformat(),
            }
            journal.save_decision(ticker, opp_id, decision)
            db.log_event("entry:executed", {
                "opp_id": opp_id, "ticker": ticker,
                "price": price, "target": s.get("target_price"),
                "wyckoff": s.get("wyckoff_phase"),
                "wyckoff_score": s.get("wyckoff_score"),
            })

            print(_build_telegram_message(ticker, quantity, price, value, s))
            _notify_telegram(ticker, quantity, price, value, s)
            _notify_email(ticker, quantity, price, value, s)
        elif r.get("status") == "skipped":
            print(f'[PAPER] {ticker}: {r.get("reason", "ya en cartera")} — no se transiciona, se reintenta mañana')
        else:
            print(f"[PAPER] {ticker}: error en compra — no se transiciona, se reintenta mañana")

    return 0


if __name__ == "__main__":
    sys.exit(main())
