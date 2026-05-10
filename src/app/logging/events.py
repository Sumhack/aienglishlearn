"""Strict event registry for structured logs.

This module defines the allowed event names only. Production code should use
these constants instead of ad-hoc strings so logs stay queryable and stable.
"""

from __future__ import annotations

from typing import Final


SESSION_STARTED: Final[str] = "session.started"
SESSION_COMPLETED: Final[str] = "session.completed"
SESSION_FAILED: Final[str] = "session.failed"

TURN_STARTED: Final[str] = "turn.started"
TURN_COMPLETED: Final[str] = "turn.completed"
TURN_FAILED: Final[str] = "turn.failed"

STT_STARTED: Final[str] = "stt.started"
STT_COMPLETED: Final[str] = "stt.completed"
STT_FAILED: Final[str] = "stt.failed"

LLM_REQUEST: Final[str] = "llm.request"
LLM_RESPONSE: Final[str] = "llm.response"
LLM_FAILED: Final[str] = "llm.failed"

TTS_STARTED: Final[str] = "tts.started"
TTS_COMPLETED: Final[str] = "tts.completed"
TTS_FAILED: Final[str] = "tts.failed"

EVALUATION_STARTED: Final[str] = "evaluation.started"
EVALUATION_COMPLETED: Final[str] = "evaluation.completed"
EVALUATION_FAILED: Final[str] = "evaluation.failed"

DB_READ_STARTED: Final[str] = "db.read.started"
DB_READ_COMPLETED: Final[str] = "db.read.completed"
DB_READ_FAILED: Final[str] = "db.read.failed"

DB_WRITE_STARTED: Final[str] = "db.write.started"
DB_WRITE_COMPLETED: Final[str] = "db.write.completed"
DB_WRITE_FAILED: Final[str] = "db.write.failed"

AUTH_SUCCESS: Final[str] = "auth.success"
AUTH_FAILED: Final[str] = "auth.failed"

REQUEST_STARTED: Final[str] = "request.started"
REQUEST_COMPLETED: Final[str] = "request.completed"
REQUEST_FAILED: Final[str] = "request.failed"

WARMUP_STARTED: Final[str] = "warmup.started"
WARMUP_COMPLETED: Final[str] = "warmup.completed"
WARMUP_FAILED: Final[str] = "warmup.failed"

SESSION_FINALIZATION_STARTED: Final[str] = "session.finalization.started"
SESSION_FINALIZATION_COMPLETED: Final[str] = "session.finalization.completed"
SESSION_FINALIZATION_FAILED: Final[str] = "session.finalization.failed"

AGENT_SESSION_CONFIGURED: Final[str] = "agent.session.configured"
PARTICIPANT_CONNECTED: Final[str] = "participant.connected"
TRACK_PUBLISHED: Final[str] = "track.published"
TRACK_EGRESS_FAILED: Final[str] = "track.egress.failed"

ALL_EVENTS: Final[frozenset[str]] = frozenset(
    {
        SESSION_STARTED,
        SESSION_COMPLETED,
        SESSION_FAILED,
        TURN_STARTED,
        TURN_COMPLETED,
        TURN_FAILED,
        STT_STARTED,
        STT_COMPLETED,
        STT_FAILED,
        LLM_REQUEST,
        LLM_RESPONSE,
        LLM_FAILED,
        TTS_STARTED,
        TTS_COMPLETED,
        TTS_FAILED,
        EVALUATION_STARTED,
        EVALUATION_COMPLETED,
        EVALUATION_FAILED,
        DB_READ_STARTED,
        DB_READ_COMPLETED,
        DB_READ_FAILED,
        DB_WRITE_STARTED,
        DB_WRITE_COMPLETED,
        DB_WRITE_FAILED,
        AUTH_SUCCESS,
        AUTH_FAILED,
        REQUEST_STARTED,
        REQUEST_COMPLETED,
        REQUEST_FAILED,
        WARMUP_STARTED,
        WARMUP_COMPLETED,
        WARMUP_FAILED,
        SESSION_FINALIZATION_STARTED,
        SESSION_FINALIZATION_COMPLETED,
        SESSION_FINALIZATION_FAILED,
        AGENT_SESSION_CONFIGURED,
        PARTICIPANT_CONNECTED,
        TRACK_PUBLISHED,
        TRACK_EGRESS_FAILED,
    }
)

SESSION_EVENTS: Final[frozenset[str]] = frozenset(
    {SESSION_STARTED, SESSION_COMPLETED, SESSION_FAILED}
)
TURN_EVENTS: Final[frozenset[str]] = frozenset({TURN_STARTED, TURN_COMPLETED, TURN_FAILED})
STT_EVENTS: Final[frozenset[str]] = frozenset({STT_STARTED, STT_COMPLETED, STT_FAILED})
LLM_EVENTS: Final[frozenset[str]] = frozenset({LLM_REQUEST, LLM_RESPONSE, LLM_FAILED})
TTS_EVENTS: Final[frozenset[str]] = frozenset({TTS_STARTED, TTS_COMPLETED, TTS_FAILED})
EVALUATION_EVENTS: Final[frozenset[str]] = frozenset(
    {EVALUATION_STARTED, EVALUATION_COMPLETED, EVALUATION_FAILED}
)
DB_EVENTS: Final[frozenset[str]] = frozenset(
    {
        DB_READ_STARTED,
        DB_READ_COMPLETED,
        DB_READ_FAILED,
        DB_WRITE_STARTED,
        DB_WRITE_COMPLETED,
        DB_WRITE_FAILED,
    }
)
AUTH_EVENTS: Final[frozenset[str]] = frozenset({AUTH_SUCCESS, AUTH_FAILED})
REQUEST_EVENTS: Final[frozenset[str]] = frozenset(
    {REQUEST_STARTED, REQUEST_COMPLETED, REQUEST_FAILED}
)
WARMUP_EVENTS: Final[frozenset[str]] = frozenset(
    {WARMUP_STARTED, WARMUP_COMPLETED, WARMUP_FAILED}
)
SESSION_FINALIZATION_EVENTS: Final[frozenset[str]] = frozenset(
    {
        SESSION_FINALIZATION_STARTED,
        SESSION_FINALIZATION_COMPLETED,
        SESSION_FINALIZATION_FAILED,
    }
)


def is_valid_event(event: str) -> bool:
    return event in ALL_EVENTS
