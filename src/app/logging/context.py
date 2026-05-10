"""Correlation context for structured logs.

This module stores only correlation identifiers in context variables so the
same helpers work across FastAPI requests, LiveKit callbacks, and eval jobs.
The helpers are intentionally forgiving and never raise during normal use.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class LogContext:
    trace_id: str
    session_id: str | None = None
    user_id: str | None = None
    turn_id: str | None = None
    turn_index: int | None = None
    learning_module_id: str | None = None
    persona: str | None = None
    region: str | None = None


_log_context: ContextVar[LogContext | None] = ContextVar("log_context", default=None)


def new_trace_id() -> str:
    return uuid4().hex


def get_current_context() -> LogContext | None:
    return _log_context.get()


def get_context_data() -> dict[str, Any]:
    context = get_current_context()
    if context is None:
        return {}
    return {key: value for key, value in asdict(context).items() if value is not None}


def set_context(
    *,
    trace_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    turn_id: str | None = None,
    turn_index: int | None = None,
    learning_module_id: str | None = None,
    persona: str | None = None,
    region: str | None = None,
) -> LogContext:
    current = get_current_context()
    if current is None:
        context = LogContext(
            trace_id=trace_id or new_trace_id(),
            session_id=session_id,
            user_id=user_id,
            turn_id=turn_id,
            turn_index=turn_index,
            learning_module_id=learning_module_id,
            persona=persona,
            region=region,
        )
    else:
        context = replace(
            current,
            trace_id=trace_id or current.trace_id,
            session_id=session_id if session_id is not None else current.session_id,
            user_id=user_id if user_id is not None else current.user_id,
            turn_id=turn_id if turn_id is not None else current.turn_id,
            turn_index=turn_index if turn_index is not None else current.turn_index,
            learning_module_id=(
                learning_module_id if learning_module_id is not None else current.learning_module_id
            ),
            persona=persona if persona is not None else current.persona,
            region=region if region is not None else current.region,
        )

    _log_context.set(context)
    return context


def bind_context(**kwargs: Any) -> LogContext:
    """Alias for set_context to keep the wrapper API ergonomic."""

    return set_context(**kwargs)


def clear_context() -> None:
    _log_context.set(None)


def ensure_trace_id(trace_id: str | None = None) -> str:
    context = get_current_context()
    if trace_id:
        set_context(trace_id=trace_id)
        return trace_id
    if context is not None and context.trace_id:
        return context.trace_id
    generated = new_trace_id()
    set_context(trace_id=generated)
    return generated
