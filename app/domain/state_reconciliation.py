"""Combine temporal ordering and conflict resolution into a per-vessel
RiskState history: exactly one RiskState per processed event.

Two events are considered "conflicting" if they belong to the same
vessel and their risk_signal values differ -- regardless of whether
their timestamps match. Events are walked in chronological order
(reconstruct_temporal_history), tracking a single "current resolved
event" for the vessel. Each new event is compared against it:

  - same risk_signal -> no conflict; the new event is accepted as its
    own state entry, and becomes the new current resolved event (the
    most recent confirming evidence).
  - different risk_signal -> a real conflict; resolve_conflict decides
    the winner between [current_resolved_event, incoming_event]. The
    winner becomes the new current resolved event -- which may still be
    the old one, if it outranks the challenger.

An earlier version of this module grouped events by exact-timestamp
match before resolving conflicts within each group. That undertriggered
on realistic asynchronous data (the PRD's own Weather-HIGH-vs-Regulatory-
LOW example is not described as simultaneous) and has been replaced by
this comparison-against-current-state rule -- documented here, and in
the README, as a revised implementation decision.

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


def _to_risk_state(candidates: list[EventIn]) -> tuple[RiskState, EventIn]:
    resolution = resolve_conflict(candidates)
    winner = resolution.winner
    state = RiskState(
        risk_signal=winner.risk_signal,
        source_reliability=SOURCE_RELIABILITY[winner.source.value],
        timestamp=winner.timestamp,
        reasoning=resolution.explanation,
        event_ids=tuple(e.event_id for e in candidates),
    )
    return state, winner


def resolve_state_sequence(ordered_events: list[EventIn]) -> list[RiskState]:
    """Walk temporally-ordered events, comparing each against the
    vessel's current resolved event by risk_signal. Input MUST already
    be sorted by reconstruct_temporal_history.
    """
    if not ordered_events:
        return []

    state_history: list[RiskState] = []

    first_state, resolved_event = _to_risk_state([ordered_events[0]])
    state_history.append(first_state)

    for event in ordered_events[1:]:
        if event.risk_signal == resolved_event.risk_signal:
            state, resolved_event = _to_risk_state([event])
        else:
            state, resolved_event = _to_risk_state([resolved_event, event])
        state_history.append(state)

    return state_history


def reconstruct_state_history(events: list[EventIn]) -> list[RiskState]:
    ordered = reconstruct_temporal_history(events)
    return resolve_state_sequence(ordered)
