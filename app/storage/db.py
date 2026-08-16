"""SQLite connection/schema management.

The events table is append-only and is the single source of truth: state
history and audit trails are derived from it deterministically rather than
stored as separately-mutated rows (see README design notes).
"""

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    vessel_id TEXT NOT NULL,
    risk_signal TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    confidence_score REAL NOT NULL,
    received_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_vessel_id ON events (vessel_id);

CREATE TABLE IF NOT EXISTS audit_records (
    audit_id TEXT PRIMARY KEY,
    vessel_id TEXT NOT NULL,
    event_ids TEXT NOT NULL,
    resolved_risk_signal TEXT NOT NULL,
    resolution_reason TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_vessel_id ON audit_records (vessel_id);
"""


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
