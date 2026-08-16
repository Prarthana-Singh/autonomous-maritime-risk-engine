import json

import replay_cli
from app.graph.runner import build_vessel_snapshot, replay_response
from app.main import create_app
from fastapi.testclient import TestClient


def event(**overrides) -> dict:
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


CONFLICT_SCENARIO = [
    event(event_id="w1", source="Weather", risk_signal="high",
          timestamp="2026-08-15T12:00:00Z", confidence_score=0.8),
    event(event_id="r1", source="Regulatory Compliance", risk_signal="low",
          timestamp="2026-08-15T12:00:00Z", confidence_score=0.8),
    event(event_id="g1", source="Geopolitical Risk", risk_signal="medium",
          timestamp="2026-08-15T11:00:00Z", confidence_score=0.6),
]


def test_replay_reports_status_per_event_in_submitted_order():
    batch = [
        event(event_id="e1"),
        {"event_id": "bad"},  # malformed
        event(event_id="e1"),  # duplicate of the first
    ]

    result = replay_response(batch)

    statuses = [item["status"] for item in result["processed"]]
    assert statuses == ["accepted", "rejected_validation", "rejected_duplicate"]


def test_live_vs_replay_produce_identical_final_state_and_audit():
    app = create_app(db_path=":memory:")
    client = TestClient(app)
    for raw_event in CONFLICT_SCENARIO:
        response = client.post("/events", json=raw_event)
        assert response.status_code == 201, response.text

    live_snapshot = build_vessel_snapshot(app.state.db, "vessel-1")
    replay_result = replay_response(CONFLICT_SCENARIO)
    replay_snapshot = replay_result["vessels"]["vessel-1"]

    assert live_snapshot == replay_snapshot


def test_replay_does_not_mutate_the_live_database():
    app = create_app(db_path=":memory:")
    client = TestClient(app)

    replay_response(CONFLICT_SCENARIO)

    history = client.get("/vessels/vessel-1/history").json()
    assert history == []


def test_replay_endpoint_is_isolated_from_live_database():
    app = create_app(db_path=":memory:")
    client = TestClient(app)

    response = client.post("/replay", json=CONFLICT_SCENARIO)

    assert response.status_code == 200
    assert response.json()["vessels"]["vessel-1"]["state_history"]
    # Isolated store: nothing should have been written to the live app db.
    assert client.get("/vessels/vessel-1/history").json() == []


def test_duplicate_within_a_single_replay_batch_is_idempotent():
    batch = [event(event_id="e1"), event(event_id="e1")]

    result = replay_response(batch)

    statuses = [item["status"] for item in result["processed"]]
    assert statuses == ["accepted", "rejected_duplicate"]
    assert result["vessels"]["vessel-1"]["state_history"][0]["event_ids"] == ["e1"]


def test_replaying_the_same_batch_twice_produces_identical_output():
    first = replay_response(CONFLICT_SCENARIO)
    second = replay_response(CONFLICT_SCENARIO)

    assert first == second


def test_replay_handles_late_out_of_order_batch():
    # Submitted out of order within the replay batch itself. Confidence
    # rises with time so each later report legitimately wins its conflict
    # against the previous one, giving an unambiguous expected chain
    # while still proving the late (11:50) event is resolved first.
    scrambled = [
        event(event_id="e2", risk_signal="medium", timestamp="2026-08-15T12:10:00Z", confidence_score=0.9),
        event(event_id="e3", risk_signal="low", timestamp="2026-08-15T11:50:00Z", confidence_score=0.5),
        event(event_id="e1", risk_signal="high", timestamp="2026-08-15T12:00:00Z", confidence_score=0.7),
    ]

    result = replay_response(scrambled)

    signals = [s["risk_signal"] for s in result["vessels"]["vessel-1"]["state_history"]]
    assert signals == ["low", "high", "medium"]


def test_cli_replay_matches_api_replay_output(tmp_path, capsys):
    events_file = tmp_path / "events.json"
    events_file.write_text(json.dumps(CONFLICT_SCENARIO), encoding="utf-8")
    output_file = tmp_path / "result.json"

    exit_code = replay_cli.main([str(events_file), "--output", str(output_file)])

    assert exit_code == 0
    cli_result = json.loads(output_file.read_text(encoding="utf-8"))
    api_result = replay_response(CONFLICT_SCENARIO)
    assert cli_result == api_result
