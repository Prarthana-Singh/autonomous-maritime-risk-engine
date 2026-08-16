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


def get_events_for_vessel(conn: sqlite3.Connection, vessel_id: str) -> list[sqlite3.Row]:
    cursor = conn.execute(
        "SELECT * FROM events WHERE vessel_id = ? ORDER BY timestamp ASC, event_id ASC",
        (vessel_id,),
    )
    return cursor.fetchall()


def get_event_by_id(conn: sqlite3.Connection, event_id: str) -> sqlite3.Row | None:
    cursor = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
    return cursor.fetchone()
