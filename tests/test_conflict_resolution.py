import pytest

from app.config import SOURCE_RELIABILITY
from app.domain.conflict_resolution import ResolutionReason, resolve_conflict
from app.models.schemas import EventIn


def event(event_id: str, source: str, risk_signal: str, timestamp: str, confidence: float) -> EventIn:
    return EventIn(
        event_id=event_id,
        source=source,
        vessel_id="vessel-1",
        risk_signal=risk_signal,
        timestamp=timestamp,
        confidence_score=confidence,
    )


def test_source_reliability_config_matches_prd():
    # Weather, Regulatory Compliance, Geopolitical Risk are given explicit
    # values in the PRD. Port Congestion is an undocumented, explicit
    # engineering assumption (see app/config.py).
    assert SOURCE_RELIABILITY["Weather"] == 0.9
    assert SOURCE_RELIABILITY["Regulatory Compliance"] == 0.8
    assert SOURCE_RELIABILITY["Geopolitical Risk"] == 0.7
    assert "Port Congestion" in SOURCE_RELIABILITY


def test_higher_confidence_score_wins():
    weather = event("e1", "Weather", "high", "2026-08-15T12:00:00Z", confidence=0.6)
    regulatory = event("e2", "Regulatory Compliance", "low", "2026-08-15T12:00:00Z", confidence=0.9)

    result = resolve_conflict([weather, regulatory])

    assert result.winner.event_id == "e2"
    assert result.reason == ResolutionReason.CONFIDENCE_SCORE


def test_source_reliability_breaks_confidence_tie():
    # PRD's own example: "high" from Weather vs "low" from Regulatory.
    # Confidence tied -> Weather (0.9) beats Regulatory Compliance (0.8).
    weather = event("e1", "Weather", "high", "2026-08-15T12:00:00Z", confidence=0.8)
    regulatory = event("e2", "Regulatory Compliance", "low", "2026-08-15T12:00:00Z", confidence=0.8)

    result = resolve_conflict([weather, regulatory])

    assert result.winner.event_id == "e1"
    assert result.reason == ResolutionReason.SOURCE_RELIABILITY


def test_earlier_timestamp_breaks_reliability_tie():
    # Both confidence and source_reliability tied (same source) -> earlier timestamp wins.
    earlier = event("e1", "Weather", "high", "2026-08-15T11:00:00Z", confidence=0.8)
    later = event("e2", "Weather", "low", "2026-08-15T12:00:00Z", confidence=0.8)

    result = resolve_conflict([earlier, later])

    assert result.winner.event_id == "e1"
    assert result.reason == ResolutionReason.TIMESTAMP


def test_exact_deterministic_tie_uses_event_id_fallback():
    # Confidence, reliability (same source), and timestamp all identical.
    a = event("z-event", "Weather", "high", "2026-08-15T12:00:00Z", confidence=0.8)
    b = event("a-event", "Weather", "low", "2026-08-15T12:00:00Z", confidence=0.8)

    result = resolve_conflict([a, b])

    assert result.winner.event_id == "a-event"
    assert result.reason == ResolutionReason.DETERMINISTIC_TIEBREAK


def test_deterministic_tie_is_order_independent():
    a = event("z-event", "Weather", "high", "2026-08-15T12:00:00Z", confidence=0.8)
    b = event("a-event", "Weather", "low", "2026-08-15T12:00:00Z", confidence=0.8)

    forward = resolve_conflict([a, b])
    backward = resolve_conflict([b, a])

    assert forward.winner.event_id == backward.winner.event_id == "a-event"


def test_resolution_among_three_candidates():
    low_conf = event("e1", "Weather", "high", "2026-08-15T12:00:00Z", confidence=0.5)
    mid_conf = event("e2", "Regulatory Compliance", "low", "2026-08-15T12:00:00Z", confidence=0.7)
    high_conf = event("e3", "Geopolitical Risk", "medium", "2026-08-15T12:00:00Z", confidence=0.95)

    result = resolve_conflict([low_conf, mid_conf, high_conf])

    assert result.winner.event_id == "e3"
    assert result.reason == ResolutionReason.CONFIDENCE_SCORE


def test_single_candidate_is_not_a_conflict():
    only = event("e1", "Weather", "high", "2026-08-15T12:00:00Z", confidence=0.8)

    result = resolve_conflict([only])

    assert result.winner.event_id == "e1"
    assert result.reason == ResolutionReason.NO_CONFLICT


def test_empty_candidate_list_raises():
    with pytest.raises(ValueError):
        resolve_conflict([])


def test_explanation_is_specific_not_vague():
    weather = event("e1", "Weather", "high", "2026-08-15T12:00:00Z", confidence=0.6)
    regulatory = event("e2", "Regulatory Compliance", "low", "2026-08-15T12:00:00Z", confidence=0.9)

    result = resolve_conflict([weather, regulatory])

    assert "confidence_score" in result.explanation
    assert "0.9" in result.explanation
    assert result.explanation != "risk resolved successfully"
