from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from acme_core import (
    CODE_ALPHABET,
    InvalidInputError,
    Link,
    LinkError,
    Page,
    new_code,
    normalize_url,
    paginate,
    parse_code,
    slugify,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("abc", "abc"),
        ("  Launch-2026 ", "launch-2026"),
        ("a" * 32, "a" * 32),
    ],
)
def test_parse_code_accepts(raw: str, expected: str) -> None:
    assert parse_code(raw) == expected


@pytest.mark.parametrize("raw", ["", "ab", "-abc", "a" * 33, "has space", "emoji-🙂", "semi;colon"])
def test_parse_code_rejects(raw: str) -> None:
    with pytest.raises(InvalidInputError, match="code") as exc:
        parse_code(raw)
    assert isinstance(exc.value, ValueError)  # generic callers can still catch ValueError
    assert isinstance(exc.value, LinkError)
    assert exc.value.field == "code"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Example.COM", "https://example.com/"),
        ("HTTP://example.com/a?b=1#frag", "http://example.com/a?b=1"),
        (" https://example.com:8443/x ", "https://example.com:8443/x"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "example.com",
        "ftp://example.com",
        "javascript:alert(1)",
        "https://",
        "https://user:pw@example.com",
        "https://example.com/" + "a" * 2048,
    ],
)
def test_normalize_url_rejects(raw: str) -> None:
    with pytest.raises(InvalidInputError, match="url"):
        normalize_url(raw)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Crème Brûlée!", "creme-brulee"), ("  --Hello,   World--  ", "hello-world"), ("日本", "")],
)
def test_slugify(text: str, expected: str) -> None:
    assert slugify(text) == expected


def test_new_code_uses_alphabet_and_length() -> None:
    code = new_code(10)
    assert len(code) == 10
    assert set(code) <= set(CODE_ALPHABET)
    assert parse_code(code) == code


@pytest.mark.parametrize("length", [2, 33])
def test_new_code_rejects_bad_length(length: int) -> None:
    with pytest.raises(InvalidInputError, match="length"):
        new_code(length)


def test_link_is_frozen() -> None:
    link = Link(code=parse_code("abc"), url="https://example.com/", created_at=datetime.now(UTC))
    with pytest.raises(AttributeError):
        link.url = "https://evil.example/"  # type: ignore[misc]


def test_paginate() -> None:
    first = paginate(range(5), limit=3, cursor_of=str)
    assert first == Page((0, 1, 2), "2")
    assert list(first) == [0, 1, 2]
    assert len(first) == 3
    assert paginate([1, 2], limit=3, cursor_of=str) == Page((1, 2))


# Property tests: invariants over generated input, not hand-picked examples.


@given(st.text())
def test_slugify_output_is_always_a_valid_slug(text: str) -> None:
    slug = slugify(text)
    assert len(slug) <= 32
    assert slug == slug.strip("-")
    assert all(c.isascii() and (c.isalnum() or c == "-") for c in slug)
    assert slugify(slug) == slug  # idempotent


@given(st.text())
def test_parse_code_never_raises_anything_but_invalid_input(raw: str) -> None:
    try:
        code = parse_code(raw)
    except InvalidInputError:
        return
    assert parse_code(code) == code


@given(st.integers(min_value=3, max_value=32))
def test_new_code_round_trips(length: int) -> None:
    code = new_code(length)
    assert len(code) == length
    assert parse_code(code) == code
