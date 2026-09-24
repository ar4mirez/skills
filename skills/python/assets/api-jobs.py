"""Background jobs on Postgres with procrastinate: no Redis, and jobs commit with your data.

The web process only defers jobs; `acme-api worker` runs them. Importing this module never
touches the environment or the network: `open_jobs` attaches a fresh connector (which owns
its pool) for the lifetime of a context, so the app can be opened and closed repeatedly
(tests, one-off commands) without reusing a closed pool.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from procrastinate import App, JobContext, PsycopgConnector, RetryStrategy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from acme_api.store import increment_clicks
from acme_core import Code

log = logging.getLogger(__name__)

jobs = App(connector=PsycopgConnector())


@asynccontextmanager
async def open_jobs(conninfo: str, *, max_size: int = 4) -> AsyncIterator[App]:
    connector = PsycopgConnector(conninfo=conninfo, min_size=1, max_size=max_size)
    with jobs.replace_connector(connector):
        async with jobs.open_async():
            yield jobs


@jobs.task(
    queue="clicks", pass_context=True, retry=RetryStrategy(max_attempts=5, exponential_wait=2)
)
async def record_click(context: JobContext, code: str) -> None:
    sessions: async_sessionmaker[AsyncSession] = context.additional_context["sessions"]
    async with sessions.begin() as session:  # commits on success, rolls back on error
        await increment_clicks(session, Code(code))
    log.info("click recorded", extra={"code": code, "job_id": context.job.id})
