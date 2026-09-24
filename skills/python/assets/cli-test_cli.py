import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from acme_cli.main import app

runner = CliRunner()


def test_check_valid_urls_exit_0() -> None:
    result = runner.invoke(app, ["check", "https://Example.com", "http://a.test/x"])
    assert result.exit_code == 0, result.output
    assert "ok    https://example.com/" in result.stdout


def test_check_invalid_url_exits_1_and_reports_on_stderr() -> None:
    result = runner.invoke(app, ["check", "https://ok.test", "ftp://nope.test"])
    assert result.exit_code == 1
    assert "scheme must be http or https" in result.stderr


def test_check_reads_stdin_and_emits_json() -> None:
    result = runner.invoke(app, ["check", "--format", "json"], input="https://a.test\n\nnope\n")
    assert result.exit_code == 1
    assert json.loads(result.stdout) == [
        {"input": "https://a.test", "url": "https://a.test/"},
        {"input": "nope", "error": "scheme must be http or https"},
    ]


def test_code_generates_count_codes() -> None:
    result = runner.invoke(app, ["code", "--length", "5", "--count", "3"])
    assert result.exit_code == 0
    codes = result.stdout.split()
    assert len(codes) == 3
    assert all(len(c) == 5 for c in codes)


@pytest.mark.parametrize(
    "args", [["code", "--length", "2"], ["check", "--format", "xml"], ["nope"]]
)
def test_usage_errors_exit_2(args: list[str]) -> None:
    assert runner.invoke(app, args).exit_code == 2


def test_slug() -> None:
    assert runner.invoke(app, ["slug", "Hello,", "World!"]).stdout == "hello-world\n"
    assert runner.invoke(app, ["slug", "!!!"]).exit_code == 1


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("acme 0.1.0")


def test_module_entry_point_runs() -> None:
    # One real subprocess run proves `python -m acme_cli` and the installed metadata work.
    proc = subprocess.run(
        [sys.executable, "-m", "acme_cli", "slug", "Hi There"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert proc.stdout == "hi-there\n"
