"""Send the optional Telegram notification for the monthly pipeline."""

import json
import os
from pathlib import Path

from idos.workers.notifications.telegram import TelegramNotifier


def main() -> int:
    token = os.environ.get("IDOS_TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("IDOS_TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram not configured, skipping notification")
        return 0
    root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    os.chdir(root)
    result_path = Path("cache/pipeline_results.json")
    if not result_path.exists():
        message = "📡 *IDOS Monthly Pipeline*: No results file found"
    else:
        data = json.loads(result_path.read_text(encoding="utf-8"))
        if data.get("status") == "failed":
            message = f"🚨 *IDOS Alert*: Pipeline FAILED\n{data.get('error', 'unknown')}"
        else:
            output = data.get("output", {})
            lines = [
                "📡 *IDOS Monthly Universe Pipeline*",
                "",
                "📊 *Pipeline Results:*",
                f"  Finviz Screening: {output.get('finviz_count', 0)} tickers",
                f"  Operable Filter: {output.get('operable_count', 0)} tickers",
                f"  Data Fetch: {output.get('fetch_new', 0)} new, {output.get('fetch_cached', 0)} cached",
                f"  Scout: {output.get('scout_passed', 0)} passed, {output.get('scout_rejected', 0)} rejected",
            ]
            if output.get("new_watchlist_count", 0):
                lines.extend(["", f"✅ *{output['new_watchlist_count']} new watchlist additions*"])
            if output.get("opportunities_eligible", 0):
                lines.extend([
                    "",
                    f"🎯 *Oportunidades:* {output['opportunities_eligible']} elegibles (score >= threshold)",
                    f"  ✨ Creadas: {output.get('opportunities_created', 0)} | Existentes: {output.get('opportunities_existing', 0)}",
                ])
            if output.get("fetch_errors", 0):
                lines.append(f"⚠️ *{output['fetch_errors']} fetch errors*")
            lines.extend(["", f"Duration: {output.get('duration_seconds', 0):.0f}s"])
            message = "\n".join(lines)
    TelegramNotifier({"bot_token": token, "chat_id": chat}).execute({"message": message})
    print("Telegram notification sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
