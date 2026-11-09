"""Общие фикстуры: SQLite in-memory БД, TestClient, чистые singleton'ы."""

from __future__ import annotations

import os
import tempfile

# DATABASE_URL должен указывать на SQLite ДО импорта backend.* — иначе
# модульный engine в backend.db потребует драйвер PostgreSQL.
_TEST_DB = os.path.join(tempfile.gettempdir(), "symbio_test_default.db").replace(os.sep, "/")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import get_db
from backend.main import app
from backend.models import Base
from core.symbio_core.confidence import feedback_store
from core.symbio_core.context import ContextMemory
from core.symbio_hive import hive
from engine.coordinator import coordinator
from engine.llm import llm_chain
from engine.observer import observer
from engine.reviewer import reviewer


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(engine):
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = factory()
    yield session
    session.close()


@pytest.fixture()
def session_factory(engine):
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return factory


@pytest.fixture()
def client(db_session):
    """TestClient с подменой зависимости БД на SQLite in-memory."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def clean_singletons():
    """Чистые глобальные состояния перед каждым тестом."""
    hive.reset()
    observer.reset()
    feedback_store.reset()
    reviewer.reset()
    coordinator.reset()
    llm_chain.cost_tracker.reset()
    llm_chain.rate_limiter.reset()
    llm_chain.last_provider = None
    yield
    hive.reset()
    observer.reset()
    feedback_store.reset()


@pytest.fixture()
def memory():
    return ContextMemory()
