"""Stage only public market data produced by Daily Refresh."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Callable


_SAFE_TICKER = re.compile(r"[A-Z0-9.^=_-]{1,32}\Z")


def public_market_cache_paths(cache_dir: Path) -> list[Path]:
    """Whitelist the refresh summary and market cache for its listed tickers."""
    if cache_dir.is_symlink():
        raise ValueError(f"Cache directory must not be a symlink: {cache_dir}")
    summary_path = cache_dir / "last_refresh.json"
    if not summary_path.is_file():
        return []
    if summary_path.is_symlink():
        raise ValueError(f"Refresh summary must not be a symlink: {summary_path}")

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid refresh summary: {summary_path}") from exc
    if not isinstance(summary, dict) or not isinstance(summary.get("tickers"), list):
        raise ValueError(f"Refresh summary must contain a ticker list: {summary_path}")

    paths = [summary_path]
    seen: set[str] = set()
    for value in summary["tickers"]:
        if not isinstance(value, str):
            raise ValueError("Refresh summary contains a non-string ticker")
        ticker = value.strip().upper()
        if not _SAFE_TICKER.fullmatch(ticker):
            raise ValueError(f"Unsafe ticker in refresh summary: {value!r}")
        if ticker in seen:
            continue
        seen.add(ticker)
        market_cache = cache_dir / f"{ticker}.json"
        if market_cache.is_file() and not market_cache.is_symlink():
            if market_cache.resolve().parent != cache_dir.resolve():
                raise ValueError(f"Market cache resolves outside cache directory: {market_cache}")
            paths.append(market_cache)
    return paths


def stage_public_market_cache(
    repo_root: Path,
    *,
    run: Callable[..., object] = subprocess.run,
) -> list[Path]:
    """Git-stage only allowlisted market data files; portfolio signals are excluded."""
    root = repo_root.resolve()
    paths = public_market_cache_paths(root / "cache")
    relative_paths = [path.relative_to(root).as_posix() for path in paths]
    if relative_paths:
        run(["git", "add", "--", *relative_paths], cwd=root, check=True)
    return paths


def main() -> int:
    root = Path.cwd()
    paths = stage_public_market_cache(root)
    print(f"[PUBLIC-CACHE] Staged {len(paths)} refresh summary/market-data files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
