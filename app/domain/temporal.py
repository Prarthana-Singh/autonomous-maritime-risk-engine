"""Deterministic per-vessel temporal ordering of events.

Events may arrive late or out of order (see PRD). The reconstructed
history must always reflect chronological order (event timestamp), not
arrival order. Ties on timestamp are broken by event_id, lexicographically,
as a stable deterministic fallback -- this tiebreak is an implementation
detail, not a PRD rule (see README design notes).

Note: this module only orders events chronologically. It does not decide
which signal "wins" among same-timestamp conflicts -- that is conflict
resolution (Phase 5).
"""

from app.models.schemas import EventIn


def reconstruct_temporal_history(events: list[EventIn]) -> list[EventIn]:
    """Return events sorted chronologically (timestamp, then event_id),
    regardless of the order they were passed in (i.e. arrival order).
    """
    return sorted(events, key=lambda event: (event.timestamp, event.event_id))
