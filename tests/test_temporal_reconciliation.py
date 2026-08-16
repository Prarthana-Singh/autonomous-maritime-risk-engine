from app.domain.temporal import reconstruct_temporal_history
from app.models.schemas import EventIn


def event(event_id: str, risk_signal: str, timestamp: str, **overrides) -> EventIn:
    payload = {
        "event_id": event_id,
        "source": "Weather",
        "vessel_id": "vessel-1",
        "risk_signal": risk_signal,
        "timestamp": timestamp,
        "confidence_score": 0.8,
    }
    payload.update(overrides)
    return EventIn(**payload)


def test_events_are_ordered_by_timestamp_not_arrival_order():
    # Arrival order: HIGH (12:00), MEDIUM (12:10), then LOW (11:50) arrives late.
    arrival_order = [
        event("e1", "high", "2026-08-15T12:00:00Z"),
        event("e2", "medium", "2026-08-15T12:10:00Z"),
        event("e3", "low", "2026-08-15T11:50:00Z"),
    ]

    result = reconstruct_temporal_history(arrival_order)

    assert [e.event_id for e in result] == ["e3", "e1", "e2"]
    assert [e.risk_signal for e in result] == ["low", "high", "medium"]


def test_out_of_order_batch_reconstructs_chronologically():
    shuffled = [
        event("b", "medium", "2026-08-15T12:10:00Z"),
        event("c", "low", "2026-08-15T11:50:00Z"),
        event("a", "high", "2026-08-15T12:00:00Z"),
    ]

    result = reconstruct_temporal_history(shuffled)

    assert [e.timestamp.isoformat() for e in result] == [
        "2026-08-15T11:50:00+00:00",
        "2026-08-15T12:00:00+00:00",
        "2026-08-15T12:10:00+00:00",
    ]


def test_tie_on_timestamp_broken_deterministically_by_event_id():
    same_timestamp = "2026-08-15T12:00:00Z"
    events = [
        event("z-event", "high", same_timestamp),
        event("a-event", "low", same_timestamp),
        event("m-event", "medium", same_timestamp),
    ]

    result = reconstruct_temporal_history(events)

    assert [e.event_id for e in result] == ["a-event", "m-event", "z-event"]


def test_reconstruction_is_deterministic_regardless_of_input_order():
    events = [
        event("e1", "high", "2026-08-15T12:00:00Z"),
        event("e2", "medium", "2026-08-15T12:10:00Z"),
        event("e3", "low", "2026-08-15T11:50:00Z"),
        event("e4", "high", "2026-08-15T11:55:00Z"),
    ]

    forward = reconstruct_temporal_history(events)
    reversed_input = reconstruct_temporal_history(list(reversed(events)))

    assert [e.event_id for e in forward] == [e.event_id for e in reversed_input]


def test_empty_history_returns_empty_list():
    assert reconstruct_temporal_history([]) == []
