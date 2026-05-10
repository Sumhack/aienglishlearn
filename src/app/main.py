from datetime import datetime, timezone
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, field_validator
from app.auth.google import router as google_router
from app.config import get_settings, validate_required_env
from app.auth.jwt_utils import create_jwt_token, decode_jwt_token
from app.auth.user_store import AuthUserError, create_user, verify_user
from app.eval.deep_eval_worker import run_deep_eval
from app.eval.prompts import build_session_eval_prompt
from app.logging.events import (
    AUTH_FAILED,
    AUTH_SUCCESS,
    EVALUATION_COMPLETED,
    EVALUATION_FAILED,
    EVALUATION_STARTED,
    SESSION_FAILED,
    SESSION_STARTED,
)
from app.logging.logger import configure_logging
from app.logging.wrapper import bind_context, log_boundary, log_error
from app.middleware.logging_middleware import LoggingMiddleware
from app.services.session_service import (
    SessionServiceError,
    SessionStartPayload,
    create_session,
    get_session_by_id,
    list_sessions_for_user,
    list_personas,
    list_personas_v1,
    list_turn_items,
    update_session_summary,
)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    timestamp_utc: str


class SessionStartRequest(BaseModel):
    persona: str = Field(min_length=1, max_length=120)


class SessionStartResponse(BaseModel):
    session_id: str
    user_id: str
    persona: str
    display_name: str
    coach_type: str
    room_name: str
    token: str
    livekit_url: str
    status: Literal["active", "completed", "failed"]
    created_at: str


class TurnResponse(BaseModel):
    turn_index: int
    question_text: str
    user_transcript: str
    agent_reply: str
    duration_ms: int | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model_name: str | None
    estimated_cost_usd: float
    created_at: str


class SessionDetailResponse(BaseModel):
    session_id: str
    user_id: str
    persona: str
    display_name: str
    coach_type: str
    room_name: str
    status: str
    created_at: str
    started_at: str | None
    ended_at: str | None
    overall_score: float | None
    fluency_score: float | None
    grammar_score: float | None
    vocabulary_score: float | None
    clarity_score: float | None
    relevance_score: float | None
    report_status: str | None
    summary: dict | None
    # recordings: dict | None


class SessionListItemResponse(BaseModel):
    session_id: str
    persona: str
    display_name: str
    coach_type: str
    room_name: str
    status: str
    created_at: str
    started_at: str | None
    ended_at: str | None
    overall_score: float | None
    fluency_score: float | None
    grammar_score: float | None
    vocabulary_score: float | None
    clarity_score: float | None
    relevance_score: float | None
    report_status: str | None


class PersonaResponse(BaseModel):
    module_key: str
    module_name: str
    display_name: str
    coach_type: str
    role: str
    tone: str
    short_description: str
    is_active: bool
    created_at: str | None
    updated_at: str | None


class PersonaV1Response(BaseModel):
    module_key: str
    coach_category: str
    coach_type: str
    display_name: str
    short_description: str
    tone: str


class SessionFinalizeResponse(BaseModel):
    session_id: str
    report_status: str
    scores: dict[str, float]
    summary: dict


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def password_max_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password cannot be longer than 72 bytes")
        return value


class AuthResponse(BaseModel):
    user_id: str
    name: str
    email: EmailStr
    token: str
    expires_in: int


app = FastAPI(title="Voice Agent Backend", version="0.1.0")
configure_logging()
app.add_middleware(LoggingMiddleware)
app.include_router(google_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "https://www.speakaura.tech",],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.on_event("startup")
async def startup_checks() -> None:
    # API needs LiveKit (room/token creation) and DynamoDB (auth + sessions).
    validate_required_env(["livekit", "auth"])


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="voice-agent-backend",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/sessions/start", response_model=SessionStartResponse)
async def start_session(
    payload: SessionStartRequest,
    authorization: str | None = Header(default=None),
) -> SessionStartResponse:
    start_ts = time.monotonic()
    if not authorization or not authorization.startswith("Bearer "):
        log_error(
            event=AUTH_FAILED,
            status="failed",
            message="Missing or invalid Authorization header",
            error_type="auth",
            error_stage="auth",
            severity="medium",
            status_code=401,
            error_message="Missing or invalid Authorization header",
        )
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = decode_jwt_token(token)
    except Exception as exc:
        log_error(
            event=AUTH_FAILED,
            status="failed",
            message="Invalid token",
            error_type="auth",
            error_stage="auth",
            severity="medium",
            status_code=401,
            error_message=str(exc),
        )
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user_id = claims.get("sub")
    name = claims.get("name")
    if not user_id or not name:
        log_error(
            event=AUTH_FAILED,
            status="failed",
            message="Token missing user details",
            error_type="auth",
            error_stage="auth",
            severity="medium",
            status_code=401,
            error_message="Token missing user details",
        )
        raise HTTPException(status_code=401, detail="Token missing user details")
    bind_context(user_id=user_id)

    try:
        result = create_session(
            SessionStartPayload(
                user_id=user_id,
                name=name,
                persona=payload.persona,
            )
        )
    except SessionServiceError as exc:
        log_error(
            event=SESSION_FAILED,
            status="failed",
            message="Session start failed",
            error_type="dependency",
            error_stage="session_start",
            severity="high",
            error_message=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    bind_context(session_id=result.session_id, persona=result.persona)

    log_boundary(
        event=SESSION_STARTED,
        status="started",
        message="Session created",
        session_id=result.session_id,
        user_id=result.user_id,
        persona=result.persona,
        duration_ms=int((time.monotonic() - start_ts) * 1000),
    )

    return SessionStartResponse(
        session_id=result.session_id,
        user_id=result.user_id,
        persona=result.persona,
        display_name=result.display_name,
        coach_type=result.coach_type,
        room_name=result.room_name,
        token=result.token,
        livekit_url=result.livekit_url,
        status=result.status,  # type: ignore[arg-type]
        created_at=result.created_at,
    )


@app.post("/auth/register", response_model=AuthResponse)
async def register(payload: RegisterRequest) -> AuthResponse:
    try:
        user = create_user(name=payload.name, email=payload.email, password=payload.password)
    except AuthUserError as exc:
        log_error(
            event=AUTH_FAILED,
            status="failed",
            message="Registration failed",
            error_type="validation",
            error_stage="auth",
            severity="medium",
            error_message=str(exc),
            status_code=409,
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    token, expires_in = create_jwt_token(
        user_id=user.user_id,
        email=user.email,
        name=user.name,
    )
    log_boundary(
        event=AUTH_SUCCESS,
        status="success",
        message="Registration succeeded",
        user_id=user.user_id,
    )
    return AuthResponse(
        user_id=user.user_id,
        name=user.name,
        email=user.email,
        token=token,
        expires_in=expires_in,
    )


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def login_password_max_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password cannot be longer than 72 bytes")
        return value


@app.post("/auth/login", response_model=AuthResponse)
async def login(payload: LoginRequest) -> AuthResponse:
    try:
        user = verify_user(email=payload.email, password=payload.password)
    except AuthUserError as exc:
        log_error(
            event=AUTH_FAILED,
            status="failed",
            message="Login failed",
            error_type="auth",
            error_stage="auth",
            severity="medium",
            error_message=str(exc),
            status_code=401,
        )
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    token, expires_in = create_jwt_token(
        user_id=user.user_id,
        email=user.email,
        name=user.name,
    )
    log_boundary(
        event=AUTH_SUCCESS,
        status="success",
        message="Login succeeded",
        user_id=user.user_id,
    )
    return AuthResponse(
        user_id=user.user_id,
        name=user.name,
        email=user.email,
        token=token,
        expires_in=expires_in,
    )


@app.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: str,
    authorization: str | None = Header(default=None),
) -> SessionDetailResponse:
    if not authorization or not authorization.startswith("Bearer "):
        log_error(
            event=AUTH_FAILED,
            status="failed",
            message="Missing or invalid Authorization header",
            error_type="auth",
            error_stage="auth",
            severity="medium",
            status_code=401,
            error_message="Missing or invalid Authorization header",
        )
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = decode_jwt_token(token)
    except Exception as exc:
        log_error(
            event=AUTH_FAILED,
            status="failed",
            message="Invalid token",
            error_type="auth",
            error_stage="auth",
            severity="medium",
            status_code=401,
            error_message=str(exc),
        )
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user_id = claims.get("sub")
    if not user_id:
        log_error(
            event=AUTH_FAILED,
            status="failed",
            message="Token missing user details",
            error_type="auth",
            error_stage="auth",
            severity="medium",
            status_code=401,
            error_message="Token missing user details",
        )
        raise HTTPException(status_code=401, detail="Token missing user details")
    bind_context(user_id=user_id, session_id=session_id)

    session = get_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != user_id:
        log_error(
            event=AUTH_FAILED,
            status="failed",
            message="Forbidden access to session",
            error_type="auth",
            error_stage="auth",
            severity="medium",
            status_code=403,
            error_message="Forbidden",
            session_id=session_id,
            user_id=user_id,
        )
        raise HTTPException(status_code=403, detail="Forbidden")
    bind_context(persona=session.persona)

    return SessionDetailResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        persona=session.persona,
        display_name=session.display_name,
        coach_type=session.coach_type,
        room_name=session.room_name,
        status=session.status,
        created_at=session.created_at,
        started_at=session.started_at,
        ended_at=session.ended_at,
        overall_score=float(session.overall_score) if session.overall_score is not None else None,
        fluency_score=float(session.fluency_score) if session.fluency_score is not None else None,
        grammar_score=float(session.grammar_score) if session.grammar_score is not None else None,
        vocabulary_score=float(session.vocabulary_score) if session.vocabulary_score is not None else None,
        clarity_score=float(session.clarity_score) if session.clarity_score is not None else None,
        relevance_score=float(session.relevance_score) if session.relevance_score is not None else None,
        report_status=session.report_status,
        summary=session.summary_json,
        # recordings=session.recordings_json,
    )


@app.get("/sessions", response_model=list[SessionListItemResponse])
async def list_sessions(
    authorization: str | None = Header(default=None),
    limit: int = 50,
) -> list[SessionListItemResponse]:
    if not authorization or not authorization.startswith("Bearer "):
        log_error(
            event=AUTH_FAILED,
            status="failed",
            message="Missing or invalid Authorization header",
            error_type="auth",
            error_stage="auth",
            severity="medium",
            status_code=401,
            error_message="Missing or invalid Authorization header",
        )
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = decode_jwt_token(token)
    except Exception as exc:
        log_error(
            event=AUTH_FAILED,
            status="failed",
            message="Invalid token",
            error_type="auth",
            error_stage="auth",
            severity="medium",
            status_code=401,
            error_message=str(exc),
        )
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user_id = claims.get("sub")
    if not user_id:
        log_error(
            event=AUTH_FAILED,
            status="failed",
            message="Token missing user details",
            error_type="auth",
            error_stage="auth",
            severity="medium",
            status_code=401,
            error_message="Token missing user details",
        )
        raise HTTPException(status_code=401, detail="Token missing user details")
    bind_context(user_id=user_id)

    sessions = list_sessions_for_user(user_id, limit=limit)
    return [
        SessionListItemResponse(
            session_id=s.session_id,
            persona=s.persona,
            display_name=s.display_name,
            coach_type=s.coach_type,
            room_name=s.room_name,
            status=s.status,
            created_at=s.created_at,
            started_at=s.started_at,
            ended_at=s.ended_at,
            overall_score=s.overall_score,
            fluency_score=s.fluency_score,
            grammar_score=s.grammar_score,
            vocabulary_score=s.vocabulary_score,
            clarity_score=s.clarity_score,
            relevance_score=s.relevance_score,
            report_status=s.report_status,
        )
        for s in sessions
    ]


@app.get("/personas", response_model=list[PersonaResponse])
async def get_personas(active_only: bool = True) -> list[PersonaResponse]:
    personas = list_personas(active_only=active_only)
    return [
        PersonaResponse(
            module_key=p.module_key,
            module_name=p.module_name,
            display_name=p.display_name,
            coach_type=p.coach_type,
            role=p.role,
            tone=p.tone,
            short_description=p.short_description,
            is_active=p.is_active,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in personas
    ]


@app.get("/personas_v1", response_model=list[PersonaV1Response])
async def get_personas_v1() -> list[PersonaV1Response]:
    personas = list_personas_v1()
    return [
        PersonaV1Response(
            module_key=p.module_key,
            coach_category=p.coach_category,
            coach_type=p.coach_type,
            display_name=p.display_name,
            short_description=p.short_description,
            tone=p.tone,
        )
        for p in personas
    ]


@app.post("/sessions/{session_id}/finalize", response_model=SessionFinalizeResponse)
async def finalize_session(
    session_id: str,
    authorization: str | None = Header(default=None),
    x_internal_key: str | None = Header(default=None),
) -> SessionFinalizeResponse:
    eval_start_ts = time.monotonic()
    settings = get_settings()
    user_id: str | None = None
    if settings.internal_api_key and x_internal_key == settings.internal_api_key:
        user_id = "internal"
        bind_context(user_id=user_id, session_id=session_id)
    else:
        if not authorization or not authorization.startswith("Bearer "):
            log_error(
                event=AUTH_FAILED,
                status="failed",
                message="Missing or invalid Authorization header",
                error_type="auth",
                error_stage="auth",
                severity="medium",
                status_code=401,
                error_message="Missing or invalid Authorization header",
                session_id=session_id,
            )
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            claims = decode_jwt_token(token)
        except Exception as exc:
            log_error(
                event=AUTH_FAILED,
                status="failed",
                message="Invalid token",
                error_type="auth",
                error_stage="auth",
                severity="medium",
                status_code=401,
                error_message=str(exc),
                session_id=session_id,
            )
            raise HTTPException(status_code=401, detail="Invalid token") from exc

        user_id = claims.get("sub")
        if not user_id:
            log_error(
                event=AUTH_FAILED,
                status="failed",
                message="Token missing user details",
                error_type="auth",
                error_stage="auth",
                severity="medium",
                status_code=401,
                error_message="Token missing user details",
                session_id=session_id,
            )
            raise HTTPException(status_code=401, detail="Token missing user details")
        bind_context(user_id=user_id, session_id=session_id)

    session = get_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if user_id != "internal" and session.user_id != user_id:
        log_error(
            event=AUTH_FAILED,
            status="failed",
            message="Forbidden access to finalize session",
            error_type="auth",
            error_stage="auth",
            severity="medium",
            status_code=403,
            error_message="Forbidden",
            session_id=session_id,
            user_id=user_id,
        )
        raise HTTPException(status_code=403, detail="Forbidden")
    bind_context(persona=session.persona)

    try:
        turn_items = list_turn_items(session_id)
        log_boundary(
            event=EVALUATION_STARTED,
            status="started",
            message="Session evaluation started",
            session_id=session_id,
            user_id=user_id,
        )
        prompt = build_session_eval_prompt(session.persona, turn_items)
        result = run_deep_eval(prompt)
        summary = {
            "strengths": result.strengths,
            "improvements": result.improvements,
            "content_improvements": result.content_improvements,
            "practice_tasks": result.practice_tasks,
            "corrections": result.corrections,
            "notes": result.notes,
        }
        update_session_summary(
            session_id=session_id,
            scores=result.scores,
            summary=summary,
            report_status="ready",
        )
        log_boundary(
            event=EVALUATION_COMPLETED,
            status="completed",
            message="Session evaluation completed",
            session_id=session_id,
            user_id=user_id,
            duration_ms=int((time.monotonic() - eval_start_ts) * 1000),
        )
    except Exception as exc:
        log_error(
            event=EVALUATION_FAILED,
            status="failed",
            message="Session evaluation failed",
            session_id=session_id,
            user_id=user_id,
            error_type="internal",
            error_stage="evaluation",
            severity="high",
            error_message=str(exc),
        )
        update_session_summary(
            session_id=session_id,
            scores={
                "overall": 0,
                "fluency": 0,
                "grammar": 0,
                "vocabulary": 0,
                "clarity": 0,
                "relevance": 0,
            },
            summary={"error": str(exc)},
            report_status="failed",
        )
        raise HTTPException(status_code=500, detail=f"Deep eval failed: {exc}") from exc

    return SessionFinalizeResponse(
        session_id=session_id,
        report_status="ready",
        scores=result.scores,
        summary=summary,
    )
