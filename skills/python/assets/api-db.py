"""SQLAlchemy 2.0 typed ORM models and the async engine/session factory."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, String, Text, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from acme_api.config import Settings
from acme_core import Code, Link


class Base(DeclarativeBase):
    pass


class LinkRow(Base):
    __tablename__ = "links"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    url: Mapped[str] = mapped_column(Text)
    clicks: Mapped[int] = mapped_column(BigInteger, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def to_domain(self) -> Link:
        return Link(
            code=Code(self.code), url=self.url, created_at=self.created_at, clicks=self.clicks
        )


def make_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.sqlalchemy_url,
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,  # survive Postgres restarts and idle-connection reaping
    )


def make_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: attributes stay loaded after commit, so no lazy refresh
    # (which in async code would raise MissingGreenlet) when building the response.
    return async_sessionmaker(engine, expire_on_commit=False)
