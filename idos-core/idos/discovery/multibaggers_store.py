"""Append-only storage for strategy-specific discovery snapshots."""
import json
import sqlite3
from pathlib import Path
from typing import Any


class MultibaggersStore:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS discovery_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                strategy_id TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL,
                result_json TEXT NOT NULL,
                intake_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(ticker, strategy_id, snapshot_hash))""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_discovery_strategy ON discovery_snapshots(strategy_id, ticker, created_at DESC)")

    def save(self, result: dict[str, Any], intake: dict[str, Any] | None = None) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute("""INSERT INTO discovery_snapshots
                (ticker, strategy_id, strategy_version, snapshot_hash, result_json, intake_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(ticker,strategy_id,snapshot_hash) DO UPDATE SET intake_json=excluded.intake_json""", (
                result["ticker"], result["strategy_id"], result["strategy_version"], result["snapshot_hash"],
                json.dumps(result, sort_keys=True, default=str), json.dumps(intake or {}, sort_keys=True, default=str),
                result["as_of"],
            ))

    def list(self, ticker: str, strategy_id: str = "MULTIBAGGERS") -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute("SELECT result_json,intake_json,created_at FROM discovery_snapshots WHERE ticker=? AND strategy_id=? ORDER BY created_at", (ticker.upper(), strategy_id.upper())).fetchall()
        return [{"result": json.loads(row[0]), "intake": json.loads(row[1]), "created_at": row[2]} for row in rows]
