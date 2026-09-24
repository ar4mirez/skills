"""The FastAPI application factory. `create_app(settings)` is what tests and uvicorn call."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from acme_api.config import Settings, get_settings
from acme_api.db import make_engine, make_sessions
from acme_api.jobs import open_jobs
from acme_api.routes import router
from acme_core import ConflictError, InvalidInputError, LinkError, NotFoundError

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Startup: one engine and one small job-deferral pool per process.
        engine = make_engine(settings)
        app.state.engine = engine
        app.state.sessions = make_sessions(engine)
        try:
            async with open_jobs(settings.libpq_url):
                yield
        finally:
            # Shutdown (after uvicorn has drained in-flight requests).
            await engine.dispose()

    app = FastAPI(title="acme", version="0.1.0", lifespan=lifespan)
    app.include_router(router)

    @app.get("/up", response_class=PlainTextResponse, include_in_schema=False)
    async def up(request: Request) -> PlainTextResponse:
        """Health check for kamal-proxy: 200 only when the database answers."""
        try:
            async with request.app.state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except SQLAlchemyError, OSError:
            log.exception("health check failed")
            return PlainTextResponse("db unavailable", status.HTTP_503_SERVICE_UNAVAILABLE)
        return PlainTextResponse("ok")

    @app.exception_handler(LinkError)
    async def acme_error(_request: Request, exc: Exception) -> JSONResponse:
        match exc:
            case NotFoundError():
                code = status.HTTP_404_NOT_FOUND
            case ConflictError():
                code = status.HTTP_409_CONFLICT
            case InvalidInputError():
                code = status.HTTP_422_UNPROCESSABLE_CONTENT
            case _:
                code = status.HTTP_400_BAD_REQUEST
        return JSONResponse({"detail": str(exc)}, status_code=code)

    return app
