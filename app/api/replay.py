from typing import Any

from fastapi import APIRouter, Body, status

from app.graph.runner import replay_response

router = APIRouter()


@router.post("/replay", status_code=status.HTTP_200_OK)
def replay_events(payload: list[dict[str, Any]] = Body(...)) -> dict:
    return replay_response(payload)
