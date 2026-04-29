"""Test fixtures — session-scoped Postgres testcontainer + async FastAPI client.

Usage
-----
Tests that need a DB get ``db_session``.
Tests that need an HTTP client get ``client`` (anonymous) or use ``make_operator``.
Tests that need a WS connection use the raw ``websockets.connect`` helper with
the token from ``POST /auth/socket-token``.

The Redis dependency is replaced with fakeredis so tests never need a live
Redis instance.
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from httpx_ws.transport import ASGIWebSocketTransport
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer

# ── Tell the app we're in test mode (skips wait_for_db) ──────────────────────
os.environ["TESTING"] = "1"

# ── Patch Redis before importing the app ─────────────────────────────────────
import fakeredis.aioredis as fake_aioredis
import app.services.redis as _redis_module

_fake_redis = fake_aioredis.FakeRedis(decode_responses=True)

# Patch eval method since fakeredis doesn't support Lua script evaluation in async mode
# For testing, we'll always allow the token bucket (return 1 = token consumed)
async def _mock_eval(script, numkeys, *args):
    """Mock eval that simulates the token bucket Lua script behavior."""
    # For testing, always return 1 (token consumed, not rate-limited)
    return 1

_fake_redis.eval = _mock_eval
_redis_module.redis_client = _fake_redis  # type: ignore[assignment]

from app.database import Base
from app.core.dependencies import get_db
from app.main import app

# ── Session-scoped Postgres testcontainer ─────────────────────────────────────

@pytest.fixture(scope="session")
def pg_container() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def db_engine(pg_container: PostgresContainer):
    url = pg_container.get_connection_url()
    engine = create_engine(url)
    # Create all tables directly (no alembic needed in tests).
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine) -> Generator[Session, None, None]:
    """Function-scoped DB session that rolls back after each test."""
    connection = db_engine.connect()
    transaction = connection.begin()
    TestSession = sessionmaker(bind=connection)
    session = TestSession()

    # Override the FastAPI dependency
    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield session
    session.close()
    transaction.rollback()
    connection.close()
    app.dependency_overrides.pop(get_db, None)


# ── Async HTTP client ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGIWebSocketTransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ── Helper factories ──────────────────────────────────────────────────────────

async def register_and_login(client: AsyncClient, email: str, password: str = "correct-horse-battery") -> str:
    """Register an operator and return their access token."""
    await client.post("/auth/register", json={"email": email, "password": password})
    r = await client.post("/auth/login", json={"email": email, "password": password})
    return r.json()["access_token"]


@pytest.fixture()
def make_token(client):
    """Return a factory that registers + logs in an operator and yields their token."""
    async def _factory(email: str, password: str = "correct-horse-battery") -> str:
        return await register_and_login(client, email, password)
    return _factory
