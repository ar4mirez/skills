"""Typed settings, read once from the environment at startup.

Fail fast: a missing or malformed variable stops the process before it serves traffic.
Secrets are ``SecretStr`` so they never show up in reprs, logs, or tracebacks.
"""

from functools import cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, extra="ignore")

    # libpq form (postgresql://user:pass@host:5432/db); psycopg and procrastinate use it
    # as-is, SQLAlchemy gets the +psycopg dialect added in `sqlalchemy_url`.
    database_url: SecretStr
    db_pool_size: int = Field(default=5, ge=1, le=100)
    port: int = Field(default=8000, ge=1, le=65535)
    web_concurrency: int = Field(default=1, ge=1, le=64)
    log_level: LogLevel = "INFO"
    shutdown_grace_seconds: int = Field(default=8, ge=0, le=60)

    @field_validator("database_url")
    @classmethod
    def _postgres_only(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        for prefix in ("postgres://", "postgresql+psycopg://"):
            if raw.startswith(prefix):
                raw = "postgresql://" + raw.removeprefix(prefix)
        if not raw.startswith("postgresql://"):
            msg = "must be a postgresql:// URL"
            raise ValueError(msg)
        return SecretStr(raw)

    @property
    def libpq_url(self) -> str:
        return self.database_url.get_secret_value()

    @property
    def sqlalchemy_url(self) -> str:
        return "postgresql+psycopg://" + self.libpq_url.removeprefix("postgresql://")


@cache
def get_settings() -> Settings:
    """The process-wide settings. Tests build ``Settings(...)`` directly instead."""
    return Settings()  # fields come from the environment (the pydantic mypy plugin knows)
