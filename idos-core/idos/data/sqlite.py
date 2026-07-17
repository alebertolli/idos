import sqlite3
import json
from pathlib import Path
from datetime import datetime, UTC
from typing import Any


class SQLiteStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _init_db(self):
        c = self.conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS opportunities (
                id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'DISCOVERED',
                conviction_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS state_transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id TEXT NOT NULL,
                from_status TEXT NOT NULL,
                to_status TEXT NOT NULL,
                cause TEXT DEFAULT '',
                worker TEXT DEFAULT 'system',
                timestamp TEXT NOT NULL,
                FOREIGN KEY (opportunity_id) REFERENCES opportunities(id)
            );

            CREATE TABLE IF NOT EXISTS pending_commits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo TEXT NOT NULL,
                file_path TEXT NOT NULL,
                content TEXT NOT NULL,
                message TEXT DEFAULT '',
                status TEXT DEFAULT 'PENDING',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS telemetry_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                worker TEXT NOT NULL,
                step TEXT NOT NULL,
                provider TEXT DEFAULT '',
                prompt_id TEXT DEFAULT '',
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                latency_ms INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                detail TEXT DEFAULT '',
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS provenance_chain (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id TEXT NOT NULL,
                target_field TEXT NOT NULL,
                source TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                data_json TEXT DEFAULT '{}',
                source TEXT DEFAULT 'system',
                correlation_id TEXT DEFAULT '',
                timestamp TEXT NOT NULL
            );
        """)
        c.commit()

    def save_opportunity(self, opp: dict[str, Any]):
        c = self.conn
        c.execute("""
            INSERT OR REPLACE INTO opportunities (id, ticker, status, conviction_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            opp["id"], opp["ticker"], opp["status"],
            json.dumps(opp.get("conviction", {})),
            opp.get("created_at", datetime.now(UTC).isoformat()),
            opp.get("updated_at", datetime.now(UTC).isoformat()),
        ))
        c.commit()

    def get_opportunity(self, opp_id: str) -> dict[str, Any] | None:
        c = self.conn
        row = c.execute("SELECT * FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["conviction"] = json.loads(result.pop("conviction_json", "{}"))
        return result

    def list_opportunities(self, status: str | None = None) -> list[dict[str, Any]]:
        c = self.conn
        if status:
            rows = c.execute("SELECT * FROM opportunities WHERE status = ? ORDER BY updated_at DESC", (status,))
        else:
            rows = c.execute("SELECT * FROM opportunities ORDER BY updated_at DESC")
        results = []
        for row in rows.fetchall():
            r = dict(row)
            r["conviction"] = json.loads(r.pop("conviction_json", "{}"))
            results.append(r)
        return results

    def record_transition(self, opp_id: str, from_status: str, to_status: str, cause: str = "", worker: str = "system"):
        c = self.conn
        c.execute("""
            INSERT INTO state_transitions (opportunity_id, from_status, to_status, cause, worker, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (opp_id, from_status, to_status, cause, worker, datetime.now(UTC).isoformat()))
        c.commit()

    def enqueue_commit(self, repo: str, file_path: str, content: str, message: str = ""):
        c = self.conn
        c.execute("""
            INSERT INTO pending_commits (repo, file_path, content, message, status, created_at)
            VALUES (?, ?, ?, ?, 'PENDING', ?)
        """, (repo, file_path, content, message, datetime.now(UTC).isoformat()))
        c.commit()

    def get_pending_commits(self) -> list[dict[str, Any]]:
        c = self.conn
        rows = c.execute("SELECT * FROM pending_commits WHERE status = 'PENDING' ORDER BY id ASC")
        return [dict(r) for r in rows.fetchall()]

    def mark_commit_done(self, commit_id: int):
        c = self.conn
        c.execute("UPDATE pending_commits SET status = 'DONE' WHERE id = ?", (commit_id,))
        c.commit()

    def trace(self, run_id: str, worker: str, step: str, status: str,
              provider: str = "", prompt_id: str = "", tokens_in: int = 0,
              tokens_out: int = 0, latency_ms: int = 0, detail: str = ""):
        c = self.conn
        c.execute("""
            INSERT INTO telemetry_traces (run_id, worker, step, provider, prompt_id,
                tokens_in, tokens_out, latency_ms, status, detail, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_id, worker, step, provider, prompt_id,
              tokens_in, tokens_out, latency_ms, status, detail,
              datetime.now(UTC).isoformat()))
        c.commit()

    def log_event(self, event_type: str, data: dict, source: str = "system", correlation_id: str = ""):
        c = self.conn
        c.execute("""
            INSERT INTO events_log (event_type, data_json, source, correlation_id, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (event_type, json.dumps(data), source, correlation_id, datetime.now(UTC).isoformat()))
        c.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
