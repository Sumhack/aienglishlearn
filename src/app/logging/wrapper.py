"""Application-facing structured logging helpers.

This module is the preferred way for app code to emit logs. It keeps the
event contract centralized, merges correlation context, and degrades safely
if logging fails.
"""

from __future__ import annotations

import sys
from typing import Any

from app.logging.context import bind_context, clear_context, get_context_data
from app.logging.events import ALL_EVENTS, is_valid_event
from app.logging.logger import get_logger
from app.logging.schema import normalize_log_record


def _build_record(
    *,
    event: str,
    status: str,
    level: str = "INFO",
    message: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "event": event,
        "status": status,
        "level": level,
    }
    if message is not None:
        record["message"] = message
    record.update(get_context_data())
    record.update(fields)
    return normalize_log_record(record)


def _emit(logger: Any, method: str, record: dict[str, Any]) -> None:
    getattr(logger, method)(**record)


def log_event(
    *,
    event: str,
    status: str,
    level: str = "INFO",
    message: str | None = None,
    **fields: Any,
) -> None:
    """Emit a structured log event without raising on failure."""

    try:
        emit_event = event
        if not is_valid_event(event):
            fields = dict(fields)
            fields["invalid_event"] = emit_event
            event = "invalid.event"

        record = _build_record(
            event=event,
            status=status,
            level=level,
            message=message,
            **fields,
        )
        logger = get_logger()
        if level.upper() == "ERROR":
            _emit(logger, "error", record)
        elif level.upper() in {"WARN", "WARNING"}:
            _emit(logger, "warning", record)
        else:
            _emit(logger, "info", record)
    except Exception:
        print(f"logging failed: event={event}", file=sys.stderr)
        return


def log_error(
    *,
    event: str,
    status: str = "failed",
    message: str | None = None,
    **fields: Any,
) -> None:
    log_event(event=event, status=status, level="ERROR", message=message, **fields)


def log_boundary(
    *,
    event: str,
    message: str | None = None,
    level: str = "INFO",
    status: str = "started",
    **fields: Any,
) -> None:
    log_event(event=event, status=status, level=level, message=message, **fields)


__all__ = [
    "ALL_EVENTS",
    "bind_context",
    "clear_context",
    "log_boundary",
    "log_error",
    "log_event",
]
