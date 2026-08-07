import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from typing import Any
from idos.timezone import AR_TZ

class DatabaseError(Exception):
    pass

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
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    @contextmanager
    def _write_transaction(self):
        c = self.conn
        try:
            yield c
            c.commit()
        except sqlite3.Error as e:
            c.rollback()
            raise DatabaseError(f"SQLite write failed: {e}") from e

    def _init_db(self):
        c = self.conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS opportunities (
                id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'DISCOVERED',
                conviction_json TEXT DEFAULT '{}',
                current_price REAL DEFAULT 0,
                intrinsic_value REAL DEFAULT 0,
                thesis_active INTEGER DEFAULT 1,
                thesis_invalidated_reason TEXT DEFAULT '',
                exit_reason TEXT DEFAULT '',
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

            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL DEFAULT 0,
                high REAL DEFAULT 0,
                low REAL DEFAULT 0,
                close REAL DEFAULT 0,
                volume REAL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(ticker, date)
            );

            CREATE TABLE IF NOT EXISTS hypotheses (
                id TEXT PRIMARY KEY,
                opportunity_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                statement TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'DRAFT',
                priority TEXT DEFAULT 'important',
                version INTEGER DEFAULT 1,
                probability REAL DEFAULT 0.5,
                confidence REAL DEFAULT 0.0,
                parent_id TEXT DEFAULT '',
                hypotheses_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_hyp_status ON hypotheses(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_hyp_opp ON hypotheses(opportunity_id);
            CREATE INDEX IF NOT EXISTS idx_hyp_ticker ON hypotheses(ticker);

            CREATE INDEX IF NOT EXISTS idx_price_history_ticker ON price_history(ticker, date DESC);
            CREATE INDEX IF NOT EXISTS idx_opp_status ON opportunities(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_opp_ticker ON opportunities(ticker);
            CREATE INDEX IF NOT EXISTS idx_transitions_opp ON state_transitions(opportunity_id, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_transitions_status ON state_transitions(from_status, to_status);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events_log(event_type, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_events_source ON events_log(source);
            CREATE INDEX IF NOT EXISTS idx_events_correlation ON events_log(correlation_id);
            CREATE INDEX IF NOT EXISTS idx_telemetry_run ON telemetry_traces(run_id);
            CREATE INDEX IF NOT EXISTS idx_telemetry_ts ON telemetry_traces(timestamp);
            CREATE INDEX IF NOT EXISTS idx_telemetry_worker ON telemetry_traces(worker, step);
            CREATE INDEX IF NOT EXISTS idx_provenance_target ON provenance_chain(target_id);
            CREATE INDEX IF NOT EXISTS idx_provenance_evidence ON provenance_chain(evidence_id);
            CREATE INDEX IF NOT EXISTS idx_commits_status ON pending_commits(status);
        """)
        # migrations for existing databases
        try:
            c.execute("ALTER TABLE opportunities ADD COLUMN current_price REAL DEFAULT 0")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE opportunities ADD COLUMN intrinsic_value REAL DEFAULT 0")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE opportunities ADD COLUMN thesis_active INTEGER DEFAULT 1")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE opportunities ADD COLUMN thesis_invalidated_reason TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE opportunities ADD COLUMN exit_reason TEXT DEFAULT ''")
        except Exception:
            pass

    def save_opportunity(self, opp: dict[str, Any]):
        with self._write_transaction() as c:
            c.execute("""
                INSERT OR REPLACE INTO opportunities (id, ticker, status, conviction_json, current_price, intrinsic_value, thesis_active, thesis_invalidated_reason, exit_reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                opp["id"], opp["ticker"], opp["status"],
                json.dumps(opp.get("conviction", {})),
                opp.get("current_price") or opp.get("conviction", {}).get("current_price", 0),
                opp.get("intrinsic_value") or opp.get("conviction", {}).get("intrinsic_value", 0),
                1 if opp.get("thesis_active", True) else 0,
                opp.get("thesis_invalidated_reason", ""),
                opp.get("exit_reason", ""),
                opp.get("created_at", datetime.now(AR_TZ).isoformat()),
                opp.get("updated_at", datetime.now(AR_TZ).isoformat()),
            ))

    def get_opportunity(self, opp_id: str) -> dict[str, Any] | None:
        c = self.conn
        row = c.execute("SELECT * FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["conviction"] = json.loads(result.pop("conviction_json", "{}"))
        result["thesis_active"] = bool(result.get("thesis_active", 1))
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
            r["thesis_active"] = bool(r.get("thesis_active", 1))
            results.append(r)
        return results

    def record_transition(self, opp_id: str, from_status: str, to_status: str, cause: str = "", worker: str = "system"):
        with self._write_transaction() as c:
            c.execute("""
                INSERT INTO state_transitions (opportunity_id, from_status, to_status, cause, worker, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (opp_id, from_status, to_status, cause, worker, datetime.now(AR_TZ).isoformat()))

    def enqueue_commit(self, repo: str, file_path: str, content: str, message: str = ""):
        with self._write_transaction() as c:
            c.execute("""
                INSERT INTO pending_commits (repo, file_path, content, message, status, created_at)
                VALUES (?, ?, ?, ?, 'PENDING', ?)
            """, (repo, file_path, content, message, datetime.now(AR_TZ).isoformat()))

    def get_pending_commits(self, limit: int = 10) -> list[dict[str, Any]]:
        c = self.conn
        rows = c.execute("SELECT * FROM pending_commits WHERE status = 'PENDING' ORDER BY id ASC LIMIT ?", (limit,))
        return [dict(r) for r in rows.fetchall()]

    def mark_commit_done(self, commit_id: int):
        with self._write_transaction() as c:
            c.execute("UPDATE pending_commits SET status = 'DONE' WHERE id = ?", (commit_id,))

    def trace(self, run_id: str, worker: str, step: str, status: str,
              provider: str = "", prompt_id: str = "", tokens_in: int = 0,
              tokens_out: int = 0, latency_ms: int = 0, detail: str = ""):
        with self._write_transaction() as c:
            c.execute("""
                INSERT INTO telemetry_traces (run_id, worker, step, provider, prompt_id,
                    tokens_in, tokens_out, latency_ms, status, detail, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, worker, step, provider, prompt_id,
                  tokens_in, tokens_out, latency_ms, status, detail,
                  datetime.now(AR_TZ).isoformat()))

    def log_event(self, event_type: str, data: dict, source: str = "system", correlation_id: str = ""):
        with self._write_transaction() as c:
            c.execute("""
                INSERT INTO events_log (event_type, data_json, source, correlation_id, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (event_type, json.dumps(data), source, correlation_id, datetime.now(AR_TZ).isoformat()))

    def save_price_history(self, ticker: str, rows: list[dict[str, Any]]):
        with self._write_transaction() as c:
            now = datetime.now(AR_TZ).isoformat()
            valid_rows = [
                (ticker.upper(), r.get("date", ""), r.get("open", 0), r.get("high", 0),
                 r.get("low", 0), r.get("close", 0), r.get("volume", 0), now)
                for r in rows if r.get("date")
            ]
            c.executemany("""
                INSERT OR REPLACE INTO price_history (ticker, date, open, high, low, close, volume, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, valid_rows)

    def get_price_history(self, ticker: str, limit: int = 365) -> list[dict[str, Any]]:
        c = self.conn
        rows = c.execute("""
            SELECT date, open, high, low, close, volume
            FROM price_history
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT ?
        """, (ticker.upper(), limit))
        results = []
        for row in rows.fetchall():
            r = dict(row)
            if r.get("close"):
                results.append(r)
        results.reverse()
        return results

    def get_last_price_date(self, ticker: str) -> str | None:
        c = self.conn
        row = c.execute("""
            SELECT date FROM price_history
            WHERE ticker = ?
            ORDER BY date DESC LIMIT 1
        """, (ticker.upper(),)).fetchone()
        return row["date"] if row else None

    def save_hypothesis(self, hyp: dict[str, Any]):
        hyp_json = dict(hyp)
        hyp_json.pop("status", None)
        with self._write_transaction() as c:
            c.execute("""
                INSERT INTO hypotheses (id, opportunity_id, ticker, statement, status, priority,
                    version, probability, confidence, parent_id, hypotheses_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                hyp["id"], hyp["opportunity_id"], hyp["ticker"], hyp.get("statement", ""),
                hyp.get("status", "DRAFT"), hyp.get("priority", "important"),
                hyp.get("version", 1), hyp.get("probability", 0.5), hyp.get("confidence", 0.0),
                hyp.get("parent_id", ""), json.dumps(hyp_json, default=str),
                hyp.get("created_at", datetime.now(AR_TZ).isoformat()),
                hyp.get("updated_at", datetime.now(AR_TZ).isoformat()),
            ))

    def get_hypothesis(self, hyp_id: str) -> dict[str, Any] | None:
        c = self.conn
        row = c.execute("SELECT * FROM hypotheses WHERE id = ?", (hyp_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        stored = json.loads(result.pop("hypotheses_json", "{}"))
        if isinstance(stored, dict):
            result = {**stored, **result}
        return result

    def list_hypotheses(self, opp_id: str | None = None,
                        status: str | None = None) -> list[dict[str, Any]]:
        c = self.conn
        where = []
        params = []
        if opp_id:
            where.append("opportunity_id = ?")
            params.append(opp_id)
        if status:
            where.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM hypotheses"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC"
        rows = c.execute(sql, params)
        results = []
        for row in rows.fetchall():
            r = dict(row)
            stored = json.loads(r.pop("hypotheses_json", "{}"))
            if isinstance(stored, dict):
                r = {**stored, **r}
            results.append(r)
        return results

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
