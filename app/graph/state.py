from typing import Any, TypedDict

from app.domain.state_reconciliation import RiskState
from app.models.schemas import EventIn


class GraphState(TypedDict, total=False):
    raw_event: dict[str, Any]
    event: EventIn
    history_before: list[EventIn]
    temporal_groups: list[list[EventIn]]
    state_history: list[RiskState]
    audit_record: dict[str, Any]
    status: str  # "accepted" | "rejected_validation" | "rejected_duplicate"
    error_detail: str
