"""Shared pytest fixtures for FreightPulse AI test suite.

Provides an isolated in-memory SQLite database per test so integration tests
never touch the development database.
"""
import sys
from pathlib import Path

# --- Path shim: ensure the project root is importable -----------------------
# conftest.py files are loaded by pytest BEFORE test collection adds paths,
# so we guarantee it here regardless of pytest.ini configuration.
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# ----------------------------------------------------------------------------

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai.database import Base


@pytest.fixture()
def test_session_factory(monkeypatch):
    """Create an isolated in-memory DB and redirect ai.tasks.SessionLocal to it.

    StaticPool ensures every connection reuses the same in-memory database,
    so tables created here are visible to all sessions within one test.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    import ai.tasks as tasks_module

    monkeypatch.setattr(tasks_module, "SessionLocal", TestingSessionLocal)

    yield TestingSessionLocal

    Base.metadata.drop_all(bind=engine)
    engine.dispose()