"""LangGraph wiring for the deterministic event-processing pipeline.

    validate -> deduplicate -> load_history -> reconstruct_temporal
        -> resolve_conflicts -> generate_audit -> persist

Each node is small and single-purpose. Rejection (failed validation or a
duplicate event_id) short-circuits via a conditional edge straight to END,
so downstream nodes never see a rejected state. This graph is invoked
identically by live ingestion (POST /events) and replay (POST /replay,
CLI) -- see app.graph.runner -- so there is exactly one processing
implementation for both.

No LLM is used anywhere in this graph: every node is a deterministic
Python function over structured data.
"""

import sqlite3
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import ValidationError

from app.domain.deduplication import is_duplicate
from app.domain.state_reconciliation import resolve_state_sequence
from app.domain.temporal import reconstruct_temporal_history
from app.graph.state import GraphState
from app.models.schemas import EventIn
from app.storage import repository


def validate_node(state: GraphState) -> GraphState:
    try:
        event = EventIn(**state["raw_event"])
    except ValidationError as exc:
        return {**state, "status": "rejected_validation", "error_detail": str(exc)}
    return {**state, "event": event}


def _route_after_validate(state: GraphState) -> str:
    return "rejected" if state.get("status") == "rejected_validation" else "continue"


def make_deduplicate_node(conn: sqlite3.Connection):
    def deduplicate_node(state: GraphState) -> GraphState:
        event = state["event"]
        if is_duplicate(conn, event.event_id):
            return {
                **state,
                "status": "rejected_duplicate",
                "error_detail": f"Duplicate event_id: {event.event_id}",
            }
        return state

    return deduplicate_node


def _route_after_deduplicate(state: GraphState) -> str:
    return "rejected" if state.get("status") == "rejected_duplicate" else "continue"


def make_load_history_node(conn: sqlite3.Connection):
    def load_history_node(state: GraphState) -> GraphState:
        history = repository.get_events_for_vessel(conn, state["event"].vessel_id)
        return {**state, "history_before": history}

    return load_history_node


def reconstruct_temporal_node(state: GraphState) -> GraphState:
    combined = state["history_before"] + [state["event"]]
    ordered = reconstruct_temporal_history(combined)
    return {**state, "temporal_order": ordered}


def resolve_conflicts_node(state: GraphState) -> GraphState:
    state_history = resolve_state_sequence(state["temporal_order"])
    return {**state, "state_history": state_history}


def generate_audit_node(state: GraphState) -> GraphState:
    event = state["event"]
    # state_history[i] is, by construction, the entry produced while
    # incorporating temporal_order[i] -- a 1:1 positional correspondence.
    # A plain "does this entry contain my event_id" search is ambiguous
    # under resolve_state_sequence: an event's id can legitimately appear
    # in its own entry AND, later, as the losing/winning anchor referenced
    # in the NEXT event's entry. Position-based lookup is unambiguous.
    index = next(
        i for i, e in enumerate(state["temporal_order"]) if e.event_id == event.event_id
    )
    affected = state["state_history"][index]
    audit_record: dict[str, Any] = {
        "audit_id": event.event_id,
        "vessel_id": event.vessel_id,
        "event_ids": list(affected.event_ids),
        "resolved_risk_signal": affected.risk_signal,
        "resolution_reason": affected.reasoning,
        "timestamp": affected.timestamp.isoformat(),
    }
    return {**state, "audit_record": audit_record}


def make_persist_node(conn: sqlite3.Connection):
    def persist_node(state: GraphState) -> GraphState:
        repository.insert_event(conn, state["event"])
        repository.insert_audit_record(conn, state["audit_record"])
        return {**state, "status": "accepted"}

    return persist_node


def build_graph(conn: sqlite3.Connection) -> CompiledStateGraph:
    builder = StateGraph(GraphState)

    builder.add_node("validate", validate_node)
    builder.add_node("deduplicate", make_deduplicate_node(conn))
    builder.add_node("load_history", make_load_history_node(conn))
    builder.add_node("reconstruct_temporal", reconstruct_temporal_node)
    builder.add_node("resolve_conflicts", resolve_conflicts_node)
    builder.add_node("generate_audit", generate_audit_node)
    builder.add_node("persist", make_persist_node(conn))

    builder.add_edge(START, "validate")
    builder.add_conditional_edges(
        "validate", _route_after_validate, {"rejected": END, "continue": "deduplicate"}
    )
    builder.add_conditional_edges(
        "deduplicate",
        _route_after_deduplicate,
        {"rejected": END, "continue": "load_history"},
    )
    builder.add_edge("load_history", "reconstruct_temporal")
    builder.add_edge("reconstruct_temporal", "resolve_conflicts")
    builder.add_edge("resolve_conflicts", "generate_audit")
    builder.add_edge("generate_audit", "persist")
    builder.add_edge("persist", END)

    return builder.compile()


def process_event(graph: CompiledStateGraph, raw_event: dict[str, Any]) -> GraphState:
    return graph.invoke({"raw_event": raw_event})
