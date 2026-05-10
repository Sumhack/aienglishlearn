"""Structured logging contract for v1.

This module documents the shape of log records and provides lightweight,
non-throwing helpers for filling defaults. It must not be used as a strict
runtime validator in production request paths.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Final


SCHEMA_VERSION: Final[str] = "v1"

LOG_LEVELS: Final[frozenset[str]] = frozenset({"DEBUG", "INFO", "WARN", "ERROR"})
STATUS_VALUES: Final[frozenset[str]] = frozenset(
    {"started", "completed", "failed", "success"}
)
ERROR_TYPES: Final[frozenset[str]] = frozenset(
    {"validation", "auth", "timeout", "dependency", "not_found", "rate_limit", "internal"}
)
ERROR_STAGES: Final[frozenset[str]] = frozenset(
    {"ingest", "session_start", "turn_infer", "tool_call", "persist", "evaluation", "auth", "db"}
)
SEVERITY_VALUES: Final[frozenset[str]] = frozenset({"low", "medium", "high", "critical"})

REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "timestamp",
    "schema_version",
    "event",
    "status",
    "level",
    "service",
    "source",
    "trace_id",
)

OPTIONAL_FIELDS: Final[tuple[str, ...]] = (
    "method",
    "path",
    "status_code",
    "session_id",
    "user_id",
    "turn_id",
    "turn_index",
    "learning_module_id",
    "persona",
    "region",
    "environment",
    "model_name",
    "latency_ms",
    "duration_ms",
    "error_type",
    "error_stage",
    "severity",
    "message",
    "error_message",
    "metadata",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def normalize_log_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a best-effort normalized copy of a record.

    This helper never raises. It fills defaults for missing contract fields and
    leaves unknown keys untouched so logging remains best-effort.
    """

    normalized = dict(record)
    normalized.setdefault("timestamp", utc_now_iso())
    normalized.setdefault("schema_version", SCHEMA_VERSION)
    normalized.setdefault("level", "INFO")
    normalized.setdefault("service", "app")
    normalized.setdefault("source", normalized.get("service", "app"))
    normalized.setdefault("trace_id", "unknown")
    normalized.setdefault("metadata", {})

    return normalized
