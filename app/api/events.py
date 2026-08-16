from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request, status

from app.graph.pipeline import process_event

router = APIRouter()


def get_graph(request: Request):
    return request.app.state.graph


@router.post("/events", status_code=status.HTTP_201_CREATED)
def create_event(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    graph = get_graph(request)
    result = process_event(graph, payload)

    status_value = result.get("status")
    if status_value == "rejected_validation":
        raise HTTPException(status_code=400, detail=result["error_detail"])
    if status_value == "rejected_duplicate":
        raise HTTPException(status_code=409, detail=result["error_detail"])

    return {"event_id": result["event"].event_id, "status": "accepted"}
