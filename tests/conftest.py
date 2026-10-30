"""Shared fixtures for thronos-edupresence tests."""
import os

os.environ["DATABASE_URL"] = "sqlite:///test_edupresence.db"
os.environ["AUTH_REQUIRED"] = "false"
os.environ["AUTO_SEED_DEMO"] = "false"
os.environ["SMS_PROVIDER"] = "mock"
os.environ["L2E_ENABLED"] = "false"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app

from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path):
    db_path = tmp_path / "test.db"
    url = f"sqlite:///{db_path}"
    test_engine = create_engine(url, connect_args={"check_same_thread": False})
    TestSession = sessionmaker(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield TestSession
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session(_fresh_db):
    session = _fresh_db()
    try:
        yield session
    finally:
        session.close()
