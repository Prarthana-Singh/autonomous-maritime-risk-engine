import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app() -> FastAPI:
    return create_app(db_path=":memory:")


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)
