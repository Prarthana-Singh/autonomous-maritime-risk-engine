import copy
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

VALID_EVENT = {
    "event_id": "evt-001",
    "source": "Weather",
    "vessel_id": "vessel-123",
    "risk_signal": "high",
    "timestamp": "2026-08-15T12:00:00Z",
    "confidence_score": 0.85,
}


def make_event(**overrides) -> dict:
    event = copy.deepcopy(VALID_EVENT)
    event.update(overrides)
    return event


def test_valid_event_is_accepted(client: TestClient):
    response = client.post("/events", json=VALID_EVENT)

    assert response.status_code == 201
    assert response.json() == {"event_id": "evt-001", "status": "accepted"}


def test_valid_event_is_persisted(client: TestClient, app: FastAPI):
    client.post("/events", json=VALID_EVENT)

    row = app.state.db.execute(
        "SELECT * FROM events WHERE event_id = ?", ("evt-001",)
    ).fetchone()

    assert row is not None
    assert row["source"] == "Weather"
    assert row["risk_signal"] == "high"


def test_event_timestamped_exactly_7_days_in_the_past_is_accepted(client: TestClient):
    # PRD NFR: "must handle events with timestamps up to 7 days in the past."
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    event = make_event(timestamp=seven_days_ago.isoformat())

    response = client.post("/events", json=event)

    assert response.status_code == 201


def test_event_timestamped_far_outside_a_week_is_still_accepted(client: TestClient):
    # No upper bound on event age is enforced (see README design notes):
    # the PRD states a capability guarantee ("must handle up to 7 days"),
    # not a validation rule that rejects anything older.
    over_a_year_ago = datetime.now(timezone.utc) - timedelta(days=400)
    event = make_event(timestamp=over_a_year_ago.isoformat())

    response = client.post("/events", json=event)

    assert response.status_code == 201


def test_malformed_event_missing_field_returns_400(client: TestClient):
    event = make_event()
    del event["vessel_id"]

    response = client.post("/events", json=event)

    assert response.status_code == 400


def test_non_object_json_body_returns_400(client: TestClient):
    response = client.post("/events", json=[1, 2, 3])

    assert response.status_code == 400


def test_unparseable_json_body_returns_400(client: TestClient):
    response = client.post(
        "/events", content="not json at all", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 400


def test_malformed_event_wrong_type_returns_400(client: TestClient):
    event = make_event(confidence_score="not-a-number")

    response = client.post("/events", json=event)

    assert response.status_code == 400


def test_invalid_risk_signal_returns_400(client: TestClient):
    event = make_event(risk_signal="critical")

    response = client.post("/events", json=event)

    assert response.status_code == 400


def test_risk_signal_is_case_insensitive(client: TestClient):
    event = make_event(risk_signal="HIGH")

    response = client.post("/events", json=event)

    assert response.status_code == 201


def test_invalid_source_returns_400(client: TestClient):
    event = make_event(source="Piracy")

    response = client.post("/events", json=event)

    assert response.status_code == 400


def test_confidence_score_out_of_range_returns_400(client: TestClient):
    event = make_event(confidence_score=1.5)

    response = client.post("/events", json=event)

    assert response.status_code == 400


def test_confidence_score_negative_returns_400(client: TestClient):
    event = make_event(confidence_score=-0.1)

    response = client.post("/events", json=event)

    assert response.status_code == 400


def test_duplicate_event_id_returns_409(client: TestClient):
    first = client.post("/events", json=VALID_EVENT)
    second = client.post("/events", json=VALID_EVENT)

    assert first.status_code == 201
    assert second.status_code == 409


def test_duplicate_event_does_not_alter_stored_state(client: TestClient, app: FastAPI):
    client.post("/events", json=VALID_EVENT)
    client.post("/events", json=VALID_EVENT)

    rows = app.state.db.execute(
        "SELECT * FROM events WHERE event_id = ?", ("evt-001",)
    ).fetchall()

    assert len(rows) == 1


def test_duplicate_event_id_with_different_payload_still_rejected(client: TestClient):
    client.post("/events", json=VALID_EVENT)
    conflicting = make_event(risk_signal="low", confidence_score=0.1)

    response = client.post("/events", json=conflicting)

    assert response.status_code == 409
