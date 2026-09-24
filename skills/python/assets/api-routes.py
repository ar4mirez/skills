"""HTTP routes. Handlers only translate: validate input, call the store, shape output."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import AfterValidator, BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from acme_api import store
from acme_api.jobs import record_click
from acme_core import Code, Link, new_code, normalize_url, parse_code

router = APIRouter()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessions: async_sessionmaker[AsyncSession] = request.app.state.sessions
    async with sessions() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]
# Path codes go through the same validator as request bodies (422 on bad input).
PathCode = Annotated[Code, AfterValidator(parse_code)]


class CreateLink(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown fields are a client bug: reject them

    url: Annotated[str, AfterValidator(normalize_url)]
    code: Annotated[str, AfterValidator(parse_code)] | None = None


class LinkOut(BaseModel):
    code: str
    url: str
    clicks: int
    created_at: datetime

    @classmethod
    def of(cls, link: Link) -> LinkOut:
        return cls(code=link.code, url=link.url, clicks=link.clicks, created_at=link.created_at)


class LinkPage(BaseModel):
    items: list[LinkOut]
    next_cursor: str | None


@router.post("/links", status_code=status.HTTP_201_CREATED)
async def create_link(body: CreateLink, session: Session) -> LinkOut:
    code = Code(body.code) if body.code else new_code()
    return LinkOut.of(await store.create_link(session, code=code, url=body.url))


@router.get("/links")
async def list_links(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=32)] = None,
) -> LinkPage:
    page = await store.list_links(session, limit=limit, after=cursor)
    return LinkPage(items=[LinkOut.of(link) for link in page], next_cursor=page.next_cursor)


@router.get("/links/{code}")
async def get_link(code: PathCode, session: Session) -> LinkOut:
    return LinkOut.of(await store.get_link(session, code))


@router.get("/r/{code}", response_class=RedirectResponse, status_code=status.HTTP_302_FOUND)
async def follow(code: PathCode, session: Session) -> str:
    link = await store.get_link(session, code)
    await record_click.defer_async(code=link.code)  # counted by the worker, not in-request
    return link.url
