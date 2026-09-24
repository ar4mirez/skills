"""Alembic environment: async engine, URL from Settings, metadata from acme_api.db."""

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from acme_api.config import get_settings
from acme_api.db import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # `acme-api migrate` passes the URL in attributes; the alembic CLI falls back to env.
    url = config.attributes.get("sqlalchemy_url")
    return url if isinstance(url, str) else get_settings().sqlalchemy_url


def _include_name(name: str | None, type_: str, _parents: object) -> bool:
    # Only diff tables this app owns: autogenerate would otherwise propose dropping the
    # procrastinate_* tables, which procrastinate manages itself.
    return type_ != "table" or name in target_metadata.tables


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, include_name=_include_name
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    # asyncio.run: migrations run from sync code (the CLI or `acme-api migrate`), never
    # from inside a running event loop such as the app's lifespan.
    asyncio.run(_run_async())
