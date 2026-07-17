import json
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from typing import Any, Optional


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
        return self._local.conn

    def _init_db(self):
        conn = sqlite3.connect(self._db_path)
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
        if expires < datetime.now(timezone.utc):
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
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl_seconds)
        self._conn.execute(
            """INSERT OR REPLACE INTO data_cache (cache_key, data, created_at, expires_at, source)
               VALUES (?, ?, ?, ?, ?)""",
            (cache_key, json.dumps(data), now.isoformat(), expires.isoformat(), source),
        )
        self._conn.commit()

    def clear_expired(self):
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute("DELETE FROM data_cache WHERE expires_at < ?", (now,))
        self._conn.commit()

    def clear_source(self, source: str):
        self._conn.execute("DELETE FROM data_cache WHERE source = ?", (source,))
        self._conn.commit()

    def clear_all(self):
        self._conn.execute("DELETE FROM data_cache")
        self._conn.commit()
