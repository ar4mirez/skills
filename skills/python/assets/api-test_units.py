"""Fast tests that need no database: settings, logging, and the command-line entry point."""

import json
import logging
import sys

import pytest
from pydantic import SecretStr, ValidationError

from acme_api import __main__ as cli
from acme_api.config import Settings, get_settings
from acme_api.logs import JsonFormatter, configure_logging


@pytest.mark.parametrize(
    "url",
    ["postgres://u:p@db/x", "postgresql://u:p@db/x", "postgresql+psycopg://u:p@db/x"],
)
def test_database_url_forms_normalize(url: str) -> None:
    settings = Settings(database_url=SecretStr(url))
    assert settings.libpq_url == "postgresql://u:p@db/x"
    assert settings.sqlalchemy_url == "postgresql+psycopg://u:p@db/x"
    assert "u:p" not in repr(settings)  # SecretStr keeps the password out of logs


@pytest.mark.parametrize(
    "overrides",
    [{"database_url": "mysql://db/x"}, {"port": "0"}, {"log_level": "LOUD"}],
)
def test_bad_settings_fail_fast(monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str]) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://db/x")
    for key, value in overrides.items():
        monkeypatch.setenv(key.upper(), value)
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()
    get_settings.cache_clear()


def test_json_formatter_includes_extra_and_exceptions() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
    record = logging.LogRecord("acme", logging.ERROR, __file__, 1, "failed %s", ("x",), exc_info)
    record.code = "abc"
    line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == "failed x"
    assert line["code"] == "abc"
    assert line["level"] == "ERROR"
    assert "ValueError: boom" in line["exc"]


def test_configure_logging_replaces_root_handlers() -> None:
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        configure_logging("WARNING")
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        assert root.level == logging.WARNING
    finally:
        root.handlers[:], _ = saved
        root.setLevel(saved[1])


def test_usage_error_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["bogus"])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_serve_runs_uvicorn_with_production_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.append({"app": app, **kw}))
    monkeypatch.setattr(cli, "configure_logging", lambda _level: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://db/x")
    monkeypatch.setenv("WEB_CONCURRENCY", "3")
    get_settings.cache_clear()
    try:
        assert cli.main(["serve"]) == 0
    finally:
        get_settings.cache_clear()
    [call] = calls
    assert call["app"] == "acme_api.app:create_app"
    assert call["factory"] is True
    assert call["workers"] == 3
    assert call["timeout_graceful_shutdown"] == 8
    assert call["log_config"]["root"]["handlers"] == ["stdout"]  # type: ignore[index]
