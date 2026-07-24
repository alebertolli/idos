import os
import tempfile
import time

from idos.workers.data.cache import DataCache


def test_cache_set_and_get():
    cache = DataCache()
    cache.set("test_key", {"value": 42}, source="test", ttl_seconds=60)
    result = cache.get("test_key")
    assert result is not None
    assert result["value"] == 42


def test_cache_expired():
    cache = DataCache()
    cache.set("expire_key", {"x": 1}, source="test", ttl_seconds=0)
    result = cache.get("expire_key")
    assert result is None


def test_cache_miss():
    cache = DataCache()
    result = cache.get("nonexistent")
    assert result is None


def test_cache_clear_source():
    cache = DataCache()
    cache.set("a1", {"val": 1}, source="src1", ttl_seconds=60)
    cache.set("a2", {"val": 2}, source="src1", ttl_seconds=60)
    cache.set("b1", {"val": 3}, source="src2", ttl_seconds=60)

    cache.clear_source("src1", confirm=True)
    assert cache.get("a1") is None
    assert cache.get("a2") is None
    assert cache.get("b1") is not None


def test_cache_clear_all():
    cache = DataCache()
    cache.set("k1", {"v": 1}, source="s", ttl_seconds=60)
    cache.set("k2", {"v": 2}, source="s", ttl_seconds=60)
    cache.clear_all(confirm=True)
    assert cache.get("k1") is None
    assert cache.get("k2") is None


def test_cache_overwrite():
    cache = DataCache()
    cache.set("overwrite", {"v": 1}, source="s", ttl_seconds=60)
    cache.set("overwrite", {"v": 2}, source="s", ttl_seconds=60)
    result = cache.get("overwrite")
    assert result["v"] == 2


def test_cache_clear_expired():
    cache = DataCache()
    cache.set("fresh", {"v": 1}, source="s", ttl_seconds=60)
    cache.set("stale", {"v": 2}, source="s", ttl_seconds=-1)
    cache.clear_expired()
    assert cache.get("fresh") is not None
    assert cache.get("stale") is None
