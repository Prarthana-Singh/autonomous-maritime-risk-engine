import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.domain.deduplication import is_duplicate
from app.models.schemas import EventIn
from app.storage import repository

router = APIRouter()


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


@router.post("/events", status_code=status.HTTP_201_CREATED)
def create_event(payload: EventIn, db: sqlite3.Connection = Depends(get_db)) -> dict:
    if is_duplicate(db, payload.event_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Duplicate event_id: {payload.event_id}",
        )

    repository.insert_event(db, payload)
    return {"event_id": payload.event_id, "status": "accepted"}
