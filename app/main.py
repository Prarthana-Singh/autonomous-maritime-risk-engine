from pathlib import Path

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import events as events_api
from app.api import vessels as vessels_api
from app.graph.pipeline import build_graph
from app.storage import db as db_module


def create_app(db_path: str | Path = db_module.DEFAULT_DB_PATH) -> FastAPI:
    app = FastAPI(title="Autonomous Maritime Risk Assessment Engine")
    app.state.db = db_module.connect(db_path)
    app.state.graph = build_graph(app.state.db)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request, exc: RequestValidationError
    ) -> JSONResponse:
        # PRD requires malformed/invalid events to be rejected with 400;
        # FastAPI's default for request validation failures is 422.
        return JSONResponse(
            status_code=400, content=jsonable_encoder({"detail": exc.errors()})
        )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(events_api.router)
    app.include_router(vessels_api.router)
    return app


app = create_app()
