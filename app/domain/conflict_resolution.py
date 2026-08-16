"""Deterministic conflict resolution between candidate events.

Given a set of candidate events describing the same vessel that disagree
on risk_signal, pick exactly one winner using the PRD priority order:

    1. Higher confidence_score
    2. If tied, higher source_reliability
    3. If tied, earlier timestamp

If all three are identical, fall back to a stable deterministic tiebreak
(lexicographically smallest event_id). This fourth tier is NOT specified
by the PRD -- it is an implementation detail, documented here and in the
README, needed only because the PRD's own priority chain does not cover
a fully-tied case.

Whether a given set of events actually "conflicts" (e.g. differing
risk_signal) is decided by the caller (Phase 6 pipeline wiring); this
module only ranks whatever candidates it is given.
"""

from dataclasses import dataclass
from enum import Enum

from app.config import SOURCE_RELIABILITY
from app.models.schemas import EventIn


class ResolutionReason(str, Enum):
    NO_CONFLICT = "no_conflict"
    CONFIDENCE_SCORE = "confidence_score"
    SOURCE_RELIABILITY = "source_reliability"
    TIMESTAMP = "timestamp"
    DETERMINISTIC_TIEBREAK = "deterministic_tiebreak"


@dataclass(frozen=True)
class ConflictResolution:
    winner: EventIn
    reason: ResolutionReason
    explanation: str


def _reliability(event: EventIn) -> float:
    return SOURCE_RELIABILITY[event.source.value]


def resolve_conflict(events: list[EventIn]) -> ConflictResolution:
    if not events:
        raise ValueError("resolve_conflict requires at least one candidate event")

    if len(events) == 1:
        only = events[0]
        return ConflictResolution(
            winner=only,
            reason=ResolutionReason.NO_CONFLICT,
            explanation=f"Only one candidate event ({only.event_id}); no conflict to resolve.",
        )

    max_confidence = max(e.confidence_score for e in events)
    by_confidence = [e for e in events if e.confidence_score == max_confidence]
    if len(by_confidence) == 1:
        winner = by_confidence[0]
        return ConflictResolution(
            winner=winner,
            reason=ResolutionReason.CONFIDENCE_SCORE,
            explanation=(
                f"{winner.source.value} ({winner.event_id}) selected: confidence_score "
                f"{winner.confidence_score} is the highest among {len(events)} candidates."
            ),
        )

    max_reliability = max(_reliability(e) for e in by_confidence)
    by_reliability = [e for e in by_confidence if _reliability(e) == max_reliability]
    if len(by_reliability) == 1:
        winner = by_reliability[0]
        return ConflictResolution(
            winner=winner,
            reason=ResolutionReason.SOURCE_RELIABILITY,
            explanation=(
                f"{winner.source.value} ({winner.event_id}) selected: confidence_score tied "
                f"at {winner.confidence_score} among {len(by_confidence)} candidates; "
                f"source_reliability {max_reliability} is the highest among them."
            ),
        )

    earliest_timestamp = min(e.timestamp for e in by_reliability)
    by_timestamp = [e for e in by_reliability if e.timestamp == earliest_timestamp]
    if len(by_timestamp) == 1:
        winner = by_timestamp[0]
        return ConflictResolution(
            winner=winner,
            reason=ResolutionReason.TIMESTAMP,
            explanation=(
                f"{winner.source.value} ({winner.event_id}) selected: confidence_score and "
                f"source_reliability tied among {len(by_reliability)} candidates; "
                f"timestamp {winner.timestamp.isoformat()} is the earliest among them."
            ),
        )

    winner = min(by_timestamp, key=lambda e: e.event_id)
    return ConflictResolution(
        winner=winner,
        reason=ResolutionReason.DETERMINISTIC_TIEBREAK,
        explanation=(
            f"{winner.source.value} ({winner.event_id}) selected: confidence_score, "
            f"source_reliability, and timestamp are all tied among {len(by_timestamp)} "
            f"candidates; event_id is used as a stable deterministic tiebreak "
            f"(lexicographically smallest, not a PRD rule)."
        ),
    )
