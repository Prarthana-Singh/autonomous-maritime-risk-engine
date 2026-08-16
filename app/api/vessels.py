import sqlite3

from fastapi import APIRouter, Depends, Request

from app.domain.temporal import reconstruct_temporal_history
from app.storage import repository

router = APIRouter()


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


@router.get("/vessels/{vessel_id}/history")
def get_vessel_history(vessel_id: str, db: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    events = repository.get_events_for_vessel(db, vessel_id)
    ordered = reconstruct_temporal_history(events)
    return [event.model_dump(mode="json") for event in ordered]
