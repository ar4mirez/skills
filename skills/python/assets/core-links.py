"""Short-link domain rules: pure functions and immutable values, no I/O.

Validation happens once, at the boundary: ``parse_code`` and ``normalize_url`` either
return a value you can trust or raise ``InvalidInputError``.
"""

import re
import secrets
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import NewType
from urllib.parse import urlsplit, urlunsplit

from acme_core.errors import InvalidInputError

Code = NewType("Code", str)
"""A validated short code. Only ``parse_code`` and ``new_code`` produce one."""

CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i: easy to read aloud
_CODE_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,31}")
_MAX_URL = 2048
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def parse_code(raw: str) -> Code:
    """Validate a user-supplied code: 3-32 chars of a-z, 0-9, and '-'."""
    code = raw.strip().lower()
    if not _CODE_RE.fullmatch(code):
        raise InvalidInputError("code", "must be 3-32 characters of a-z, 0-9, or '-'")
    return Code(code)


def new_code(length: int = 7) -> Code:
    """Generate a random, unguessable code (``secrets``, never ``random``)."""
    if not 3 <= length <= 32:
        raise InvalidInputError("length", "must be between 3 and 32")
    return Code("".join(secrets.choice(CODE_ALPHABET) for _ in range(length)))


def normalize_url(raw: str) -> str:
    """Return a canonical absolute http(s) URL, or raise ``InvalidInputError``."""
    text = raw.strip()
    if not text or len(text) > _MAX_URL:
        raise InvalidInputError("url", f"must be 1-{_MAX_URL} characters")
    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise InvalidInputError("url", "scheme must be http or https")
    if not parts.hostname:
        raise InvalidInputError("url", "must include a host")
    if parts.username or parts.password:
        raise InvalidInputError("url", "must not embed credentials")
    netloc = parts.netloc.lower()
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def slugify(text: str, *, max_length: int = 32) -> str:
    """ASCII-fold and hyphenate free text: 'Crème Brûlée!' -> 'creme-brulee'."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:max_length].rstrip("-")


@dataclass(frozen=True, slots=True, kw_only=True)
class Link:
    """A stored short link. Frozen: build a new one instead of mutating."""

    code: Code
    url: str
    created_at: datetime
    clicks: int = 0


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of results plus an opaque cursor for the next page (None at the end)."""

    items: tuple[T, ...]
    next_cursor: str | None = None

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


def paginate[T](items: Iterable[T], *, limit: int, cursor_of: Callable[[T], str]) -> Page[T]:
    """Build a ``Page`` from up to ``limit + 1`` fetched rows (the extra row means "more")."""
    rows = list(items)
    if len(rows) <= limit:
        return Page(tuple(rows))
    kept = tuple(rows[:limit])
    return Page(kept, cursor_of(kept[-1]))
