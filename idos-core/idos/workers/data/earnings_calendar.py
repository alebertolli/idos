from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Any
import json
import yaml


EARNINGS_CONFIG_PATH = Path("idos-config/events/earnings.yml")
CACHE_DIR = Path("cache")
STALE_DAYS = 5  # past earnings older than this get auto-marked as triggered


def _load_cache_tickers() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not CACHE_DIR.exists():
        return result
    for f in sorted(CACHE_DIR.glob("*.json")):
        if f.name in ("last_refresh.json", "earnings_trigger.json"):
            continue
        ticker = f.stem.upper()
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        merged = data.get("merged_data", data)
        et = merged.get("next_earnings_date")
        if et:
            result[ticker] = {"next_earnings_date": et, "source_file": f.name}
    return result


def _timestamp_to_date(ts: int | float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _load_existing_config() -> dict[str, Any]:
    if not EARNINGS_CONFIG_PATH.exists():
        return {"tickers": {}}
    try:
        raw = EARNINGS_CONFIG_PATH.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict) or data.get("tickers") is None:
        data = {"tickers": {}}
    data.setdefault("tickers", {})
    return data


def populate_earnings(dry_run: bool = False) -> dict[str, Any]:
    cache_data = _load_cache_tickers()
    config = _load_existing_config()
    existing = config.get("tickers", {})
    added = []
    updated = []
    skipped = []

    for ticker in sorted(cache_data):
        ts = cache_data[ticker]["next_earnings_date"]
        date_str = _timestamp_to_date(ts)
        current = existing.get(ticker, {})
        current_earnings = current.get("earnings_date", "")

        if current_earnings == date_str:
            skipped.append(ticker)
            continue

        if current_earnings:
            updated.append(ticker)
        else:
            added.append(ticker)

        existing.setdefault(ticker, {})
        existing[ticker]["earnings_date"] = date_str
        existing[ticker].setdefault("triggered_at", None)

    today = date.today()
    for ticker in list(existing.keys()):
        info = existing[ticker]
        earnings_str = info.get("earnings_date", "")
        if not earnings_str or info.get("triggered_at"):
            continue
        try:
            ed = datetime.strptime(earnings_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if ed < today - timedelta(days=STALE_DAYS):
            info["triggered_at"] = "auto-skip (stale)"
            skipped.append(f"{ticker}*")

    config["tickers"] = existing

    stale_names = [s.replace("*", "") for s in skipped if s.endswith("*")]
    needs_save = bool(added or updated or stale_names)
    if not dry_run and needs_save:
        EARNINGS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        EARNINGS_CONFIG_PATH.write_text(
            yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    return {
        "tickers_found": len(cache_data),
        "added": added,
        "updated": updated,
        "skipped": [s for s in skipped if not s.endswith("*")],
        "stale_marked": stale_names,
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    result = populate_earnings(dry_run=dry)
    print(f"[EARNINGS] {result['tickers_found']} tickers con earnings_date en cache")
    if result["added"]:
        print(f"[EARNINGS] Añadidos: {', '.join(result['added'])}")
    if result["updated"]:
        print(f"[EARNINGS] Actualizados: {', '.join(result['updated'])}")
    if result["stale_marked"]:
        print(f"[EARNINGS] Marcados como triggered (stale, >{STALE_DAYS}d): {', '.join(result['stale_marked'])}")
    if result["skipped"]:
        print(f"[EARNINGS] Sin cambios: {len(result['skipped'])} tickers")
    if dry:
        print("[EARNINGS] Dry-run mode, no se escribió nada")
