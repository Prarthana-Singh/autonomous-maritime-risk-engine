import json
from pathlib import Path

import pytest

from app.graph.runner import build_vessel_snapshot, replay_response
from app.main import create_app
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "fixtures"
OUTPUTS_DIR = REPO_ROOT / "outputs"


def load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


FIXTURE_FILES = sorted(p.name for p in FIXTURES_DIR.glob("*.json"))


def test_five_fixtures_exist():
    assert FIXTURE_FILES == [
        "01_duplicate_event.json",
        "02_late_out_of_order.json",
        "03_conflicting_signals.json",
        "04_replay_consistency.json",
        "05_multiple_vessels.json",
    ]


@pytest.mark.parametrize("name", FIXTURE_FILES)
def test_fixture_replays_without_error_and_matches_committed_output(name):
    events = load_fixture(name)

    result = replay_response(events)

    output_path = OUTPUTS_DIR / f"{Path(name).stem}_result.json"
    assert output_path.exists(), f"missing committed decision-trace output for {name}"
    committed = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == committed


def test_duplicate_event_fixture_rejects_second_occurrence():
    events = load_fixture("01_duplicate_event.json")

    result = replay_response(events)

    statuses = [item["status"] for item in result["processed"]]
    assert statuses == ["accepted", "rejected_duplicate"]
    assert len(result["vessels"]["MV-Atlas"]["state_history"]) == 1


def test_late_out_of_order_fixture_reconstructs_chronological_order():
    events = load_fixture("02_late_out_of_order.json")

    result = replay_response(events)

    signals = [s["risk_signal"] for s in result["vessels"]["MV-Atlas"]["state_history"]]
    assert signals == ["low", "high", "medium"]


def test_conflicting_signals_fixture_resolves_by_reliability():
    events = load_fixture("03_conflicting_signals.json")

    result = replay_response(events)

    # evt-4001 (Weather, HIGH, 0.8) is introduced first (no conflict yet).
    # evt-4002 (Regulatory, LOW, 0.8) then conflicts with it: confidence
    # tied, so source_reliability decides -- Weather (0.9) beats
    # Regulatory (0.8), HIGH persists. evt-4003 (Geopolitical, MEDIUM,
    # 0.6) then also conflicts, but loses on confidence_score (0.8 > 0.6),
    # so HIGH persists a third time -- a later, weaker report does not
    # get to become its own independent state anymore.
    state_history = result["vessels"]["MV-Borealis"]["state_history"]
    assert state_history[0]["risk_signal"] == "high"
    assert "no conflict" in state_history[0]["reasoning"].lower()
    assert state_history[1]["risk_signal"] == "high"
    assert "source_reliability" in state_history[1]["reasoning"]
    assert state_history[2]["risk_signal"] == "high"
    assert "confidence_score" in state_history[2]["reasoning"]


def test_replay_consistency_fixture_matches_live_processing():
    events = load_fixture("04_replay_consistency.json")

    app = create_app(db_path=":memory:")
    client = TestClient(app)
    for raw_event in events:
        response = client.post("/events", json=raw_event)
        assert response.status_code == 201, response.text

    live_snapshot = build_vessel_snapshot(app.state.db, "MV-Celeste")
    replay_snapshot = replay_response(events)["vessels"]["MV-Celeste"]

    assert live_snapshot == replay_snapshot


def test_multiple_vessels_fixture_keeps_vessels_independent():
    events = load_fixture("05_multiple_vessels.json")

    result = replay_response(events)

    assert set(result["vessels"].keys()) == {"MV-Atlas", "MV-Borealis"}
    atlas_signals = [s["risk_signal"] for s in result["vessels"]["MV-Atlas"]["state_history"]]
    borealis_signals = [s["risk_signal"] for s in result["vessels"]["MV-Borealis"]["state_history"]]
    # evt-6001 (HIGH, 0.85) is challenged by evt-6003 (MEDIUM, 0.55) but
    # wins on confidence_score, so HIGH persists rather than MEDIUM
    # becoming its own independent state.
    assert atlas_signals == ["high", "high"]
    # evt-6004 (06:00) arrives late relative to evt-6002 (07:05) but is
    # timestamped earlier, so it must be reconstructed first. It then
    # wins its conflict against evt-6002 (0.7 > 0.6 confidence), so
    # MEDIUM persists rather than LOW replacing it.
    assert borealis_signals == ["medium", "medium"]
