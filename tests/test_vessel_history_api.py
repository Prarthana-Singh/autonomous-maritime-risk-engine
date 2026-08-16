from fastapi.testclient import TestClient


def post_event(client: TestClient, **overrides) -> None:
    payload = {
        "event_id": "e1",
        "source": "Weather",
        "vessel_id": "vessel-1",
        "risk_signal": "high",
        "timestamp": "2026-08-15T12:00:00Z",
        "confidence_score": 0.8,
    }
    payload.update(overrides)
    response = client.post("/events", json=payload)
    assert response.status_code == 201, response.text


def test_late_out_of_order_event_reconstructs_correct_history(client: TestClient):
    # Realistic scenario from the spec: 12:00 HIGH, 12:10 MEDIUM arrive live,
    # then 11:50 LOW arrives late (after both).
    post_event(client, event_id="e1", risk_signal="high", timestamp="2026-08-15T12:00:00Z")
    post_event(client, event_id="e2", risk_signal="medium", timestamp="2026-08-15T12:10:00Z")
    post_event(client, event_id="e3", risk_signal="low", timestamp="2026-08-15T11:50:00Z")

    response = client.get("/vessels/vessel-1/history")

    assert response.status_code == 200
    history = response.json()
    assert [item["event_id"] for item in history] == ["e3", "e1", "e2"]
    assert [item["risk_signal"] for item in history] == ["low", "high", "medium"]


def test_multiple_vessels_have_independent_histories(client: TestClient):
    post_event(
        client,
        event_id="a1",
        vessel_id="vessel-A",
        risk_signal="high",
        timestamp="2026-08-15T12:00:00Z",
    )
    post_event(
        client,
        event_id="b1",
        vessel_id="vessel-B",
        risk_signal="low",
        timestamp="2026-08-15T09:00:00Z",
    )
    post_event(
        client,
        event_id="a2",
        vessel_id="vessel-A",
        risk_signal="medium",
        timestamp="2026-08-15T08:00:00Z",  # late arrival for vessel-A
    )

    history_a = client.get("/vessels/vessel-A/history").json()
    history_b = client.get("/vessels/vessel-B/history").json()

    assert [item["event_id"] for item in history_a] == ["a2", "a1"]
    assert [item["event_id"] for item in history_b] == ["b1"]


def test_history_for_unknown_vessel_is_empty(client: TestClient):
    response = client.get("/vessels/no-such-vessel/history")

    assert response.status_code == 200
    assert response.json() == []
