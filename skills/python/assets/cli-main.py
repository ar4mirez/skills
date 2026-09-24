"""The `acme` CLI. Exit codes: 0 ok, 1 some input was invalid, 2 usage error (typer's default).

Commands only parse arguments and format output; every rule lives in acme_core, so the
CLI stays thin and the logic is tested once, in the library.
"""

import json
import sys
from enum import StrEnum
from importlib.metadata import version
from typing import Annotated

import typer

from acme_core import InvalidInputError, new_code, normalize_url, slugify

app = typer.Typer(help="Tools for acme short links.", no_args_is_help=True)


class Format(StrEnum):
    TEXT = "text"
    JSON = "json"


def _version(value: bool) -> None:
    if value:
        typer.echo(f"acme {version('acme-cli')}")
        raise typer.Exit


@app.callback()
def main(
    _version_flag: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="Show the version."),
    ] = False,
) -> None:
    """Tools for acme short links."""


@app.command()
def check(
    urls: Annotated[
        list[str] | None, typer.Argument(help="URLs to check; reads stdin if none.")
    ] = None,
    fmt: Annotated[Format, typer.Option("--format", "-f", help="Output format.")] = Format.TEXT,
) -> None:
    """Validate and normalize URLs. Exits 1 if any URL is invalid."""
    inputs = urls or [line for line in sys.stdin.read().splitlines() if line.strip()]
    results: list[dict[str, str]] = []
    for raw in inputs:
        try:
            results.append({"input": raw, "url": normalize_url(raw)})
        except InvalidInputError as exc:
            results.append({"input": raw, "error": exc.reason})
    if fmt is Format.JSON:
        typer.echo(json.dumps(results, indent=2))
    else:
        for r in results:
            line = f"ok    {r['url']}" if "url" in r else f"error {r['input']!r}: {r['error']}"
            typer.echo(line, err="error" in r)
    if any("error" in r for r in results):
        raise typer.Exit(code=1)


@app.command()
def code(
    length: Annotated[int, typer.Option(min=3, max=32, help="Code length.")] = 7,
    count: Annotated[int, typer.Option(min=1, max=1000, help="How many codes.")] = 1,
) -> None:
    """Generate random short codes."""
    for _ in range(count):
        typer.echo(new_code(length))


@app.command()
def slug(text: Annotated[list[str], typer.Argument(help="Words to slugify.")]) -> None:
    """Turn free text into a URL slug."""
    result = slugify(" ".join(text))
    if not result:
        typer.echo("error: nothing left to slugify", err=True)
        raise typer.Exit(code=1)
    typer.echo(result)
