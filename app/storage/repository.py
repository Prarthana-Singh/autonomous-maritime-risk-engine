import json
import sqlite3
from typing import Any

from app.models.schemas import EventIn


def insert_event(conn: sqlite3.Connection, event: EventIn) -> None:
    """Insert a validated, non-duplicate event. Caller must check for
    duplicates first (see app.domain.deduplication.is_duplicate); the
    event_id PRIMARY KEY constraint is a backstop, not the primary check.
    """
    conn.execute(
        """
        INSERT INTO events (event_id, source, vessel_id, risk_signal, timestamp, confidence_score)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event.event_id,
            event.source.value,
            event.vessel_id,
            event.risk_signal,
            event.timestamp.isoformat(),
            event.confidence_score,
        ),
    )
    conn.commit()


def _row_to_event(row: sqlite3.Row) -> EventIn:
    return EventIn(
        event_id=row["event_id"],
        source=row["source"],
        vessel_id=row["vessel_id"],
        risk_signal=row["risk_signal"],
        timestamp=row["timestamp"],
        confidence_score=row["confidence_score"],
    )


def get_events_for_vessel(conn: sqlite3.Connection, vessel_id: str) -> list[EventIn]:
    """Return a vessel's events in storage/arrival order (rowid order) —
    NOT temporal order. Callers must run this through
    app.domain.temporal.reconstruct_temporal_history to get a correctly
    time-ordered history; arrival order and temporal order are not the
    same thing when events arrive late or out of order.
    """
    cursor = conn.execute(
        "SELECT * FROM events WHERE vessel_id = ? ORDER BY rowid ASC",
        (vessel_id,),
    )
    return [_row_to_event(row) for row in cursor.fetchall()]


def get_event_by_id(conn: sqlite3.Connection, event_id: str) -> sqlite3.Row | None:
    cursor = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
    return cursor.fetchone()


def insert_audit_record(conn: sqlite3.Connection, audit_record: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO audit_records
            (audit_id, vessel_id, event_ids, resolved_risk_signal, resolution_reason, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            audit_record["audit_id"],
            audit_record["vessel_id"],
            json.dumps(audit_record["event_ids"]),
            audit_record["resolved_risk_signal"],
            audit_record["resolution_reason"],
            audit_record["timestamp"],
        ),
    )
    conn.commit()


def _row_to_audit_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "audit_id": row["audit_id"],
        "vessel_id": row["vessel_id"],
        "event_ids": json.loads(row["event_ids"]),
        "resolved_risk_signal": row["resolved_risk_signal"],
        "resolution_reason": row["resolution_reason"],
        "timestamp": row["timestamp"],
    }


def get_audit_records_for_vessel(conn: sqlite3.Connection, vessel_id: str) -> list[dict[str, Any]]:
    cursor = conn.execute(
        "SELECT * FROM audit_records WHERE vessel_id = ? ORDER BY rowid ASC",
        (vessel_id,),
    )
    return [_row_to_audit_record(row) for row in cursor.fetchall()]


def get_all_audited_vessel_ids(conn: sqlite3.Connection) -> list[str]:
    cursor = conn.execute("SELECT DISTINCT vessel_id FROM audit_records ORDER BY vessel_id ASC")
    return [row["vessel_id"] for row in cursor.fetchall()]
