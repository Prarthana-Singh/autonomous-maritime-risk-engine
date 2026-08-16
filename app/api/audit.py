import sqlite3

from fastapi import APIRouter, Depends, Request

from app.storage import repository

router = APIRouter()


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


@router.get("/vessels/{vessel_id}/audit")
def get_vessel_audit(vessel_id: str, db: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    return repository.get_audit_records_for_vessel(db, vessel_id)
