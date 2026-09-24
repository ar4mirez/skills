"""`acme-api serve | migrate | worker`: one entry point, so the image needs no other tools.

Exit codes: 0 ok, 2 usage error (argparse). Unexpected errors propagate with a traceback.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

import uvicorn
from alembic import command
from alembic.config import Config

from acme_api.config import Settings, get_settings
from acme_api.db import make_engine, make_sessions
from acme_api.jobs import open_jobs
from acme_api.logs import configure_logging, logging_config


def serve(settings: Settings) -> None:
    uvicorn.run(
        "acme_api.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - in a container, listen on all interfaces
        port=settings.port,
        workers=settings.web_concurrency,
        proxy_headers=True,
        forwarded_allow_ips="*",  # only kamal-proxy can reach the container port
        timeout_graceful_shutdown=settings.shutdown_grace_seconds,
        # A dict, not None: uvicorn applies it inside each worker process too; with None,
        # workers spawned by --workers would log with no handlers at all.
        log_config=logging_config(settings.log_level),
    )


def migrate(settings: Settings) -> None:
    """Apply Alembic migrations, then procrastinate's schema on a fresh database."""
    cfg = Config()
    cfg.set_main_option("script_location", "acme_api:migrations")
    # Pass the URL as an attribute, not a main option: ConfigParser would treat a '%'
    # in the password as interpolation syntax.
    cfg.attributes["sqlalchemy_url"] = settings.sqlalchemy_url
    command.upgrade(cfg, "head")
    asyncio.run(_apply_jobs_schema(settings))


async def _apply_jobs_schema(settings: Settings) -> None:
    async with open_jobs(settings.libpq_url, max_size=1) as jobs:
        row = await jobs.connector.execute_query_one_async(
            "SELECT to_regclass('procrastinate_jobs') IS NOT NULL AS present"
        )
        if not row["present"]:
            await jobs.schema_manager.apply_schema_async()


async def work(settings: Settings, *, concurrency: int, wait: bool = True) -> None:
    """Run jobs until SIGTERM (or, with wait=False, until the queue is empty)."""
    engine = make_engine(settings)
    try:
        async with open_jobs(settings.libpq_url, max_size=concurrency + 1) as jobs:
            await jobs.run_worker_async(
                queues=["clicks"],
                concurrency=concurrency,
                wait=wait,
                shutdown_graceful_timeout=settings.shutdown_grace_seconds,
                additional_context={"sessions": make_sessions(engine)},
            )
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acme-api", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the HTTP server")
    sub.add_parser("migrate", help="apply database migrations")
    worker = sub.add_parser("worker", help="run background jobs")
    worker.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    match args.command:
        case "serve":
            serve(settings)
        case "migrate":
            migrate(settings)
        case "worker":
            asyncio.run(work(settings, concurrency=args.concurrency))
    return 0


if __name__ == "__main__":
    sys.exit(main())
