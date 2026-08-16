from app.graph.pipeline import build_graph, process_event
from app.storage import db


def make_graph():
    conn = db.connect(":memory:")
    return build_graph(conn), conn


def make_raw_event(**overrides) -> dict:
    payload = {
        "event_id": "e1",
        "source": "Weather",
        "vessel_id": "vessel-1",
        "risk_signal": "high",
        "timestamp": "2026-08-15T12:00:00Z",
        "confidence_score": 0.8,
    }
    payload.update(overrides)
    return payload


def test_graph_is_deterministic_across_independent_runs():
    events = [
        make_raw_event(
            event_id="e1", source="Weather", risk_signal="high",
            timestamp="2026-08-15T12:00:00Z", confidence_score=0.8,
        ),
        make_raw_event(
            event_id="e2", source="Regulatory Compliance", risk_signal="low",
            timestamp="2026-08-15T12:00:00Z", confidence_score=0.8,
        ),
        make_raw_event(
            event_id="e3", source="Geopolitical Risk", risk_signal="medium",
            timestamp="2026-08-15T11:00:00Z", confidence_score=0.6,
        ),
    ]

    def run_all():
        graph, _conn = make_graph()
        return [process_event(graph, event)["audit_record"] for event in events]

    run1 = run_all()
    run2 = run_all()

    assert run1 == run2


def test_malformed_event_rejected_without_side_effects():
    graph, conn = make_graph()
    bad = {"event_id": "e1", "source": "Weather", "vessel_id": "vessel-1"}  # missing fields

    result = process_event(graph, bad)

    assert result["status"] == "rejected_validation"
    assert "error_detail" in result
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_duplicate_event_rejected_without_second_persist():
    graph, conn = make_graph()
    payload = make_raw_event()

    first = process_event(graph, payload)
    second = process_event(graph, payload)

    assert first["status"] == "accepted"
    assert second["status"] == "rejected_duplicate"
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_replaying_same_event_twice_leaves_state_history_unchanged():
    graph, _conn = make_graph()
    payload = make_raw_event()

    first = process_event(graph, payload)
    process_event(graph, payload)  # duplicate, should have no effect
    third = process_event(graph, {**payload, "event_id": "e2", "timestamp": "2026-08-15T13:00:00Z"})

    # The first event's resolved state must be identical before and after
    # the rejected duplicate attempt.
    first_state = next(rs for rs in first["state_history"] if "e1" in rs.event_ids)
    still_there = next(rs for rs in third["state_history"] if "e1" in rs.event_ids)
    assert first_state == still_there


def test_generate_audit_reflects_conflict_resolution_reason():
    graph, _conn = make_graph()
    # Distinct (but close) timestamps: two sources reporting moments apart,
    # not literally simultaneously -- the realistic case this rule targets.
    weather = make_raw_event(
        event_id="w1", source="Weather", risk_signal="high",
        timestamp="2026-08-15T12:00:00Z", confidence_score=0.8,
    )
    regulatory = make_raw_event(
        event_id="r1", source="Regulatory Compliance", risk_signal="low",
        timestamp="2026-08-15T12:05:00Z", confidence_score=0.8,
    )

    process_event(graph, weather)
    result = process_event(graph, regulatory)

    audit = result["audit_record"]
    assert audit["resolved_risk_signal"] == "high"  # Weather (0.9) beats Regulatory (0.8)
    assert audit["vessel_id"] == "vessel-1"
    assert set(audit["event_ids"]) == {"w1", "r1"}
    assert "source_reliability" in audit["resolution_reason"]


def test_late_out_of_order_events_produce_correct_state_history():
    # Under the current-vs-incoming conflict rule, every distinct signal
    # is a real conflict against whatever is currently resolved, so each
    # later report needs to actually outrank the previous one to win --
    # confidence rises with time here so the win/win/win chain is
    # unambiguous, while still proving the late arrival is slotted into
    # its correct chronological position first (not appended last).
    graph, _conn = make_graph()
    high = make_raw_event(
        event_id="e1", risk_signal="high", timestamp="2026-08-15T12:00:00Z", confidence_score=0.7
    )
    medium = make_raw_event(
        event_id="e2", risk_signal="medium", timestamp="2026-08-15T12:10:00Z", confidence_score=0.9
    )
    low_late = make_raw_event(
        event_id="e3", risk_signal="low", timestamp="2026-08-15T11:50:00Z", confidence_score=0.5
    )

    process_event(graph, high)
    process_event(graph, medium)
    result = process_event(graph, low_late)

    assert [rs.risk_signal for rs in result["state_history"]] == ["low", "high", "medium"]
