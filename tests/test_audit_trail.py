import json

from fastapi.testclient import TestClient

from app.domain.audit_export import export_all_audit_trails, export_audit_trail_for_vessel
from app.graph.pipeline import build_graph, process_event
from app.storage import db, repository


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


def test_accepted_event_persists_an_audit_record():
    conn = db.connect(":memory:")
    graph = build_graph(conn)

    process_event(graph, make_raw_event())

    records = repository.get_audit_records_for_vessel(conn, "vessel-1")
    assert len(records) == 1
    record = records[0]
    assert record["vessel_id"] == "vessel-1"
    assert record["event_ids"] == ["e1"]
    assert record["resolved_risk_signal"] == "high"
    assert record["resolution_reason"] != "risk resolved successfully"
    assert record["timestamp"] == "2026-08-15T12:00:00+00:00"


def test_each_accepted_event_gets_its_own_audit_record():
    conn = db.connect(":memory:")
    graph = build_graph(conn)

    weather = make_raw_event(event_id="w1", source="Weather", risk_signal="high")
    regulatory = make_raw_event(
        event_id="r1", source="Regulatory Compliance", risk_signal="low"
    )
    process_event(graph, weather)
    process_event(graph, regulatory)

    records = {r["audit_id"]: r for r in repository.get_audit_records_for_vessel(conn, "vessel-1")}

    assert set(records.keys()) == {"w1", "r1"}
    # w1's audit reflects the world when it was processed: no conflict yet,
    # since r1 didn't exist. r1's audit reflects both events, now in
    # conflict, resolved by source_reliability.
    assert records["w1"]["event_ids"] == ["w1"]
    assert set(records["r1"]["event_ids"]) == {"w1", "r1"}
    assert records["w1"]["resolved_risk_signal"] == "high"
    assert records["r1"]["resolved_risk_signal"] == "high"


def test_rejected_event_does_not_create_an_audit_record():
    conn = db.connect(":memory:")
    graph = build_graph(conn)

    process_event(graph, make_raw_event())
    process_event(graph, make_raw_event())  # duplicate

    records = repository.get_audit_records_for_vessel(conn, "vessel-1")
    assert len(records) == 1


def test_resolution_reason_is_specific_for_each_tier():
    conn = db.connect(":memory:")
    graph = build_graph(conn)

    # Confidence tier
    process_event(graph, make_raw_event(
        event_id="a1", source="Weather", risk_signal="high",
        timestamp="2026-08-15T09:00:00Z", confidence_score=0.9,
    ))
    process_event(graph, make_raw_event(
        event_id="a2", source="Regulatory Compliance", risk_signal="low",
        timestamp="2026-08-15T09:00:00Z", confidence_score=0.3,
    ))

    records = {r["audit_id"]: r for r in repository.get_audit_records_for_vessel(conn, "vessel-1")}
    assert "confidence_score" in records["a2"]["resolution_reason"]


def test_audit_retrievable_via_api():
    from app.main import create_app

    app = create_app(db_path=":memory:")
    client = TestClient(app)

    client.post("/events", json=make_raw_event())

    response = client.get("/vessels/vessel-1/audit")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["resolved_risk_signal"] == "high"


def test_audit_retrieval_for_unknown_vessel_is_empty():
    from app.main import create_app

    app = create_app(db_path=":memory:")
    client = TestClient(app)

    response = client.get("/vessels/no-such-vessel/audit")

    assert response.status_code == 200
    assert response.json() == []


def test_export_audit_trail_writes_matching_json_file(tmp_path):
    conn = db.connect(":memory:")
    graph = build_graph(conn)
    process_event(graph, make_raw_event())

    path = export_audit_trail_for_vessel(conn, "vessel-1", tmp_path)

    assert path.exists()
    exported = json.loads(path.read_text(encoding="utf-8"))
    db_records = repository.get_audit_records_for_vessel(conn, "vessel-1")
    assert exported == db_records


def test_export_all_audit_trails_covers_every_vessel(tmp_path):
    conn = db.connect(":memory:")
    graph = build_graph(conn)
    process_event(graph, make_raw_event(event_id="a1", vessel_id="vessel-A"))
    process_event(graph, make_raw_event(event_id="b1", vessel_id="vessel-B"))

    paths = export_all_audit_trails(conn, tmp_path)

    names = {p.name for p in paths}
    assert names == {"vessel-A_audit_trace.json", "vessel-B_audit_trace.json"}


def test_export_is_deterministic_across_runs(tmp_path):
    def run(outputs_dir):
        conn = db.connect(":memory:")
        graph = build_graph(conn)
        process_event(graph, make_raw_event(event_id="w1", source="Weather", risk_signal="high"))
        process_event(
            graph,
            make_raw_event(event_id="r1", source="Regulatory Compliance", risk_signal="low"),
        )
        path = export_audit_trail_for_vessel(conn, "vessel-1", outputs_dir)
        return path.read_text(encoding="utf-8")

    first = run(tmp_path / "run1")
    second = run(tmp_path / "run2")

    assert first == second
