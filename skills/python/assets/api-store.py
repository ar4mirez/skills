"""Queries. Functions take a session and return domain objects, never ORM rows.

Driver errors are translated to acme_core errors here, so routes and jobs never import
psycopg or SQLAlchemy exception types.
"""

from psycopg.errors import UniqueViolation
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from acme_api.db import LinkRow
from acme_core import Code, ConflictError, Link, NotFoundError, Page, paginate


async def create_link(session: AsyncSession, *, code: Code, url: str) -> Link:
    row = LinkRow(code=code, url=url)
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if isinstance(exc.orig, UniqueViolation):
            raise ConflictError(f"code {code!r} is already taken") from exc
        raise
    await session.refresh(row)  # load server defaults (created_at, clicks)
    return row.to_domain()


async def get_link(session: AsyncSession, code: Code) -> Link:
    row = await session.scalar(select(LinkRow).where(LinkRow.code == code))
    if row is None:
        raise NotFoundError(f"no link with code {code!r}")
    return row.to_domain()


async def list_links(session: AsyncSession, *, limit: int, after: str | None) -> Page[Link]:
    """Keyset pagination on the unique code: stable under inserts, no OFFSET scans."""
    query = select(LinkRow).order_by(LinkRow.code).limit(limit + 1)
    if after is not None:
        query = query.where(LinkRow.code > after)
    rows = await session.scalars(query)
    return paginate((r.to_domain() for r in rows), limit=limit, cursor_of=lambda link: link.code)


async def increment_clicks(session: AsyncSession, code: Code) -> None:
    # One atomic UPDATE; never read-modify-write a counter in Python.
    await session.execute(
        update(LinkRow).where(LinkRow.code == code).values(clicks=LinkRow.clicks + 1)
    )
