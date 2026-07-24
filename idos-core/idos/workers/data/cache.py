import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Optional
from idos.timezone import AR_TZ

class DataCacheError(Exception):
    pass

class DataCache:
    def __init__(self, db_path: str = "idos.db"):
        self._local = threading.local()
        self._db_path = db_path
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    @contextmanager
    def _write_transaction(self):
        c = self._conn
        try:
            yield c
            c.commit()
        except sqlite3.Error as e:
            c.rollback()
            raise DataCacheError(f"DataCache write failed: {e}") from e

    def _init_db(self):
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS data_cache (
                cache_key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                source TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_expires ON data_cache(expires_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_source ON data_cache(source)")
        conn.commit()
        conn.close()

    def get(self, cache_key: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT data, expires_at FROM data_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        expires = datetime.fromisoformat(row["expires_at"])
        if expires < datetime.now(AR_TZ):
            self._conn.execute("DELETE FROM data_cache WHERE cache_key = ?", (cache_key,))
            self._conn.commit()
            return None
        return json.loads(row["data"])

    def set(
        self,
        cache_key: str,
        data: dict[str, Any],
        source: str,
        ttl_seconds: int = 3600,
    ):
        with self._write_transaction() as c:
            now = datetime.now(AR_TZ)
            expires = now + timedelta(seconds=ttl_seconds)
            c.execute(
                """INSERT OR REPLACE INTO data_cache (cache_key, data, created_at, expires_at, source)
                   VALUES (?, ?, ?, ?, ?)""",
                (cache_key, json.dumps(data), now.isoformat(), expires.isoformat(), source),
            )

    def clear_expired(self):
        with self._write_transaction() as c:
            now = datetime.now(AR_TZ).isoformat()
            c.execute("DELETE FROM data_cache WHERE expires_at < ?", (now,))

    def clear_source(self, source: str, confirm: bool = False):
        if not confirm:
            raise DataCacheError("clear_source requires confirm=True")
        with self._write_transaction() as c:
            c.execute("DELETE FROM data_cache WHERE source = ?", (source,))

    def clear_all(self, confirm: bool = False):
        if not confirm:
            raise DataCacheError("clear_all requires confirm=True")
        with self._write_transaction() as c:
            c.execute("DELETE FROM data_cache")
