import json
import os
from pathlib import Path

import pytest

from idos.market.public_cache import public_market_cache_paths, stage_public_market_cache


def test_public_cache_stages_refresh_summary_and_only_listed_market_tickers(tmp_path: Path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "last_refresh.json").write_text(
        json.dumps({"tickers": ["AAPL", "QQQ", "AAPL"], "errors": []}), encoding="utf-8"
    )
    market_and_private_caches = (
        "AAPL.json",
        "QQQ.json",
        "entry_signals.json",
        "exit_signals.json",
        "rebalance_result.json",
        "NVDA.json",
    )
    for name in market_and_private_caches:
        (cache / name).write_text("{}", encoding="utf-8")

    paths = public_market_cache_paths(cache)

    assert [path.name for path in paths] == ["last_refresh.json", "AAPL.json", "QQQ.json"]


def test_public_cache_rejects_path_like_tickers(tmp_path: Path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "last_refresh.json").write_text(
        json.dumps({"tickers": ["../../private"]}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Unsafe ticker"):
        public_market_cache_paths(cache)


def test_public_cache_rejects_symlinked_refresh_summary(tmp_path: Path):
    cache = tmp_path / "cache"
    cache.mkdir()
    external_summary = tmp_path / "external.json"
    external_summary.write_text(json.dumps({"tickers": ["AAPL"]}), encoding="utf-8")
    try:
        os.symlink(external_summary, cache / "last_refresh.json")
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable in this environment")

    with pytest.raises(ValueError, match="must not be a symlink"):
        public_market_cache_paths(cache)


def test_stage_public_market_cache_adds_only_allowlisted_paths(tmp_path: Path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "last_refresh.json").write_text(json.dumps({"tickers": ["AAPL"]}), encoding="utf-8")
    (cache / "AAPL.json").write_text("{}", encoding="utf-8")
    (cache / "entry_signals.json").write_text("{}", encoding="utf-8")
    calls = []

    paths = stage_public_market_cache(
        tmp_path,
        run=lambda args, **kwargs: calls.append((args, kwargs)),
    )

    assert [path.name for path in paths] == ["last_refresh.json", "AAPL.json"]
    assert calls[0][0] == ["git", "add", "--", "cache/last_refresh.json", "cache/AAPL.json"]
