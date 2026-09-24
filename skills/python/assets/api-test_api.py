import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from acme_api.__main__ import work
from acme_api.config import Settings

pytestmark = pytest.mark.anyio


async def test_up(client: httpx.AsyncClient) -> None:
    response = await client.get("/up")
    assert response.status_code == 200
    assert response.text == "ok"


async def test_create_get_and_list(client: httpx.AsyncClient) -> None:
    created = await client.post("/links", json={"url": "https://Example.com/a", "code": "Launch"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["code"] == "launch"
    assert body["url"] == "https://example.com/a"
    assert body["clicks"] == 0

    fetched = await client.get("/links/launch")
    assert fetched.json() == body

    generated = await client.post("/links", json={"url": "https://example.com/b"})
    assert len(generated.json()["code"]) == 7

    page = (await client.get("/links", params={"limit": 1})).json()
    assert len(page["items"]) == 1
    rest = (await client.get("/links", params={"limit": 5, "cursor": page["next_cursor"]})).json()
    assert len(rest["items"]) == 1
    assert rest["next_cursor"] is None


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"url": "ftp://example.com"}, "url"),
        ({"url": "https://example.com", "code": "x"}, "code"),
        ({"url": "https://example.com", "extra": 1}, "extra"),
        ({}, "url"),
    ],
)
async def test_create_rejects_invalid_input(
    client: httpx.AsyncClient, payload: dict[str, object], field: str
) -> None:
    response = await client.post("/links", json=payload)
    assert response.status_code == 422
    assert field in response.text


async def test_duplicate_code_conflicts(client: httpx.AsyncClient) -> None:
    payload = {"url": "https://example.com", "code": "dupe"}
    assert (await client.post("/links", json=payload)).status_code == 201
    response = await client.post("/links", json=payload)
    assert response.status_code == 409
    assert "already taken" in response.json()["detail"]


async def test_unknown_and_malformed_codes(client: httpx.AsyncClient) -> None:
    assert (await client.get("/links/missing")).status_code == 404
    assert (await client.get("/links/x")).status_code == 422
    assert (await client.get("/r/missing")).status_code == 404


async def test_redirect_defers_a_click_job_the_worker_runs(
    client: httpx.AsyncClient, app: FastAPI, clean_db: Settings
) -> None:
    await client.post("/links", json={"url": "https://example.com/go", "code": "go-now"})
    response = await client.get("/r/go-now")
    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/go"
    assert (await client.get("/links/go-now")).json()["clicks"] == 0  # not counted in-request

    # Drain the queue once with a real worker, then stop (wait=False).
    await work(clean_db, concurrency=1, wait=False)
    assert (await client.get("/links/go-now")).json()["clicks"] == 1


async def test_up_returns_503_when_the_database_is_unreachable(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    healthy = app.state.engine
    app.state.engine = create_async_engine("postgresql+psycopg://nobody@127.0.0.1:1/none")
    try:
        response = await client.get("/up")
    finally:
        await app.state.engine.dispose()
        app.state.engine = healthy
    assert response.status_code == 503
