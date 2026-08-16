"""Shared event-sequence runner used by POST /replay, the CLI, and live
processing comparisons in tests.

run_event_sequence drives a list of raw events through the exact same
graph as live processing (app.graph.pipeline.build_graph) -- there is no
separate replay implementation. By default it binds to a fresh, isolated
in-memory store rather than the live database (see README design notes):
this is what lets replay reprocess already-ingested events without 409
collisions, and what makes replay output a pure function of the event
list alone.
"""

import sqlite3
from dataclasses import dataclass
from typing import Any

from app.domain.state_reconciliation import reconstruct_state_history
from app.graph.pipeline import build_graph, process_event
from app.storage import db, repository


@dataclass
class EventOutcome:
    event_id: str | None
    status: str
    detail: str | None = None


@dataclass
class ReplayResult:
    outcomes: list[EventOutcome]
    conn: sqlite3.Connection


def _event_outcome(raw_event: dict[str, Any], result: dict[str, Any]) -> EventOutcome:
    event_obj = result.get("event")
    event_id = event_obj.event_id if event_obj is not None else raw_event.get("event_id")
    return EventOutcome(
        event_id=event_id,
        status=result.get("status", "rejected_validation"),
        detail=result.get("error_detail"),
    )


def run_event_sequence(
    raw_events: list[dict[str, Any]], conn: sqlite3.Connection | None = None
) -> ReplayResult:
    if conn is None:
        conn = db.connect(":memory:")
    graph = build_graph(conn)
    outcomes = [_event_outcome(raw_event, process_event(graph, raw_event)) for raw_event in raw_events]
    return ReplayResult(outcomes=outcomes, conn=conn)


def build_vessel_snapshot(conn: sqlite3.Connection, vessel_id: str) -> dict[str, Any]:
    events = repository.get_events_for_vessel(conn, vessel_id)
    state_history = reconstruct_state_history(events)
    return {
        "state_history": [
            {
                "risk_signal": s.risk_signal,
                "source_reliability": s.source_reliability,
                "timestamp": s.timestamp.isoformat(),
                "reasoning": s.reasoning,
                "event_ids": list(s.event_ids),
            }
            for s in state_history
        ],
        "audit_trail": repository.get_audit_records_for_vessel(conn, vessel_id),
    }


def snapshot_all_vessels(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        vessel_id: build_vessel_snapshot(conn, vessel_id)
        for vessel_id in repository.get_all_audited_vessel_ids(conn)
    }


def replay_response(raw_events: list[dict[str, Any]]) -> dict[str, Any]:
    """Full replay of raw_events against a fresh isolated store, shaped
    as the POST /replay and CLI response body."""
    result = run_event_sequence(raw_events)
    return {
        "processed": [
            {
                "event_id": outcome.event_id,
                "status": outcome.status,
                **({"detail": outcome.detail} if outcome.detail else {}),
            }
            for outcome in result.outcomes
        ],
        "vessels": snapshot_all_vessels(result.conn),
    }
