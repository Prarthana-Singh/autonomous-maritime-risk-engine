"""Combine temporal ordering and conflict resolution into a per-vessel
RiskState history: exactly one RiskState per distinct event timestamp.

Two events are considered "conflicting" if they belong to the same vessel
and share the exact same timestamp. This grouping rule is the simplest
defensible reading of the PRD (which describes near-simultaneous
contradictory reports but does not define a time window); it is
documented here and in the README as an implementation detail. It is
independent of the priority chain itself, which lives in
conflict_resolution.py. Groups of size 1 trivially resolve via
resolve_conflict's NO_CONFLICT case.

reconstruct_state_history is a pure function of the full event set: given
the same events, it always produces the same state history regardless of
processing order. This is what makes replay deterministic (Phase 8).
"""

from dataclasses import dataclass
from datetime import datetime

from app.config import SOURCE_RELIABILITY
from app.domain.conflict_resolution import resolve_conflict
from app.domain.temporal import reconstruct_temporal_history
from app.models.schemas import EventIn


@dataclass(frozen=True)
class RiskState:
    risk_signal: str
    source_reliability: float
    timestamp: datetime
    reasoning: str
    event_ids: tuple[str, ...]


def group_by_timestamp(ordered_events: list[EventIn]) -> list[list[EventIn]]:
    """Group temporally-ordered events into consecutive runs sharing the
    exact same timestamp. Input MUST already be sorted by
    reconstruct_temporal_history -- grouping by consecutive runs is only
    correct on sorted input.
    """
    groups: list[list[EventIn]] = []
    for event in ordered_events:
        if groups and groups[-1][-1].timestamp == event.timestamp:
            groups[-1].append(event)
        else:
            groups.append([event])
    return groups


def resolve_state_groups(groups: list[list[EventIn]]) -> list[RiskState]:
    states = []
    for group in groups:
        resolution = resolve_conflict(group)
        winner = resolution.winner
        states.append(
            RiskState(
                risk_signal=winner.risk_signal,
                source_reliability=SOURCE_RELIABILITY[winner.source.value],
                timestamp=winner.timestamp,
                reasoning=resolution.explanation,
                event_ids=tuple(e.event_id for e in group),
            )
        )
    return states


def reconstruct_state_history(events: list[EventIn]) -> list[RiskState]:
    ordered = reconstruct_temporal_history(events)
    groups = group_by_timestamp(ordered)
    return resolve_state_groups(groups)
