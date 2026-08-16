import sqlite3

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
