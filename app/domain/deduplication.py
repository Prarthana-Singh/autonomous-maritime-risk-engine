import sqlite3


def is_duplicate(conn: sqlite3.Connection, event_id: str) -> bool:
    """True if an event with this event_id has already been ingested.

    event_id alone is the uniqueness key (per PRD functional requirement:
    "Events with duplicate event_id are rejected with 409 Conflict"),
    kept as its own function since the LangGraph pipeline (Phase 6) uses
    it as a standalone "deduplicate" node.
    """
    row = conn.execute("SELECT 1 FROM events WHERE event_id = ?", (event_id,)).fetchone()
    return row is not None
