"""Integration fixtures: a real Postgres (TEST_DATABASE_URL), migrated once per session.

Without TEST_DATABASE_URL the database tests are skipped locally and fail in CI (where
CI=true), so a misconfigured pipeline can't pass silently.
"""

import os
from collections.abc import AsyncIterator, Iterator

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from acme_api.__main__ import migrate
from acme_api.app import create_app
from acme_api.config import Settings

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"  # psycopg's async mode and procrastinate need asyncio, not trio


@pytest.fixture(scope="session")
def settings() -> Settings:
    if not TEST_DATABASE_URL:
        if os.environ.get("CI"):
            pytest.fail("TEST_DATABASE_URL must be set in CI")
        pytest.skip("set TEST_DATABASE_URL to run database tests")
    return Settings(database_url=SecretStr(TEST_DATABASE_URL), db_pool_size=2)


@pytest.fixture(scope="session")
def migrated(settings: Settings) -> Settings:
    with psycopg.connect(settings.libpq_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    migrate(settings)  # the same code path production runs
    migrate(settings)  # and it's idempotent
    return settings


@pytest.fixture
def clean_db(migrated: Settings) -> Iterator[Settings]:
    yield migrated
    with psycopg.connect(migrated.libpq_url, autocommit=True) as conn:
        conn.execute("TRUNCATE links, procrastinate_jobs RESTART IDENTITY CASCADE")


@pytest.fixture
async def app(clean_db: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(clean_db)
    # httpx's ASGITransport does not run lifespan events; enter the lifespan ourselves.
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
