"""Structured JSON logs with the standard library: one line per record, on stdout.

Libraries call ``logging.getLogger(__name__)`` and never configure logging; only the
process entry point does, with ``configure_logging`` (or by handing ``logging_config`` to
uvicorn, which re-applies it inside every worker process).
"""

import json
import logging
import logging.config
from datetime import UTC, datetime
from typing import Any, override

# Attributes every LogRecord has; anything else came from `extra=` and is emitted as a field.
# uvicorn adds `color_message` (ANSI-coloured duplicate of msg) to its records: drop it.
_SKIP = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "taskName",
    "color_message",
}


class JsonFormatter(logging.Formatter):
    @override
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update({k: v for k, v in vars(record).items() if k not in _SKIP})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def logging_config(level: str = "INFO") -> dict[str, Any]:
    """A dictConfig that routes everything (including uvicorn's loggers) to JSON on stdout."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": JsonFormatter}},
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "stream": "ext://sys.stdout",
            }
        },
        "root": {"handlers": ["stdout"], "level": level},
        "loggers": {
            # Let uvicorn's loggers propagate to root instead of using their own handlers.
            name: {"handlers": [], "propagate": True}
            for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
        },
    }


def configure_logging(level: str = "INFO") -> None:
    logging.config.dictConfig(logging_config(level))
