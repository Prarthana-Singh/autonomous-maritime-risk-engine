from app.domain.state_reconciliation import reconstruct_state_history
from app.models.schemas import EventIn


def event(**overrides) -> EventIn:
    payload = {
        "event_id": "e1",
        "source": "Weather",
        "vessel_id": "vessel-1",
        "risk_signal": "high",
        "timestamp": "2026-08-15T12:00:00Z",
        "confidence_score": 0.8,
    }
    payload.update(overrides)
    return EventIn(**payload)


def test_differing_timestamps_and_signals_trigger_conflict_resolution():
    # Not simultaneous -- 45 minutes apart -- and not tied on any field.
    # Under the old exact-timestamp grouping rule these would never have
    # been compared at all, and both would have silently become their
    # own independent, non-conflicting states.
    earlier = event(
        event_id="w1", source="Weather", risk_signal="high",
        timestamp="2026-08-15T09:00:00Z", confidence_score=0.6,
    )
    later = event(
        event_id="r1", source="Regulatory Compliance", risk_signal="low",
        timestamp="2026-08-15T09:45:00Z", confidence_score=0.9,
    )

    state_history = reconstruct_state_history([earlier, later])

    assert len(state_history) == 2
    # The second entry must show an actual resolution between both
    # events, not a standalone acceptance of the later one.
    assert set(state_history[1].event_ids) == {"w1", "r1"}
    assert state_history[1].risk_signal == "low"  # higher confidence_score wins
    assert "confidence_score" in state_history[1].reasoning


def test_a_weaker_later_conflicting_report_does_not_silently_replace_state():
    # A later report with a differing signal but lower confidence and
    # lower source_reliability should lose its conflict outright -- the
    # resolved signal must not simply track "whatever arrived most
    # recently."
    strong_early = event(
        event_id="w1", source="Weather", risk_signal="high",
        timestamp="2026-08-15T09:00:00Z", confidence_score=0.9,
    )
    weak_later = event(
        event_id="p1", source="Port Congestion", risk_signal="low",
        timestamp="2026-08-15T14:00:00Z", confidence_score=0.3,
    )

    state_history = reconstruct_state_history([strong_early, weak_later])

    assert len(state_history) == 2
    assert state_history[1].risk_signal == "high"
    assert set(state_history[1].event_ids) == {"w1", "p1"}
    assert "confidence_score" in state_history[1].reasoning
