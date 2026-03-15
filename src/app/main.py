from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.config import validate_required_env
from app.auth.jwt_utils import create_jwt_token, decode_jwt_token
from app.auth.user_store import AuthUserError, create_user, verify_user
from app.services.session_service import (
    SessionServiceError,
    SessionStartPayload,
    create_session,
    get_session_by_id,
    list_sessions_for_user,
    list_turns_for_session,
)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    timestamp_utc: str


class SessionStartRequest(BaseModel):
    module_name: str = Field(default="behavioral_interview", min_length=1, max_length=120)
    level: str = Field(default="intermediate", min_length=1, max_length=40)


class SessionStartResponse(BaseModel):
    session_id: str
    user_id: str
    learning_module_id: str
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
    learning_module_id: str
    room_name: str
    status: str
    created_at: str
    started_at: str | None
    ended_at: str | None
    turns: list[TurnResponse]


class SessionListItemResponse(BaseModel):
    session_id: str
    learning_module_id: str
    room_name: str
    status: str
    created_at: str
    started_at: str | None
    ended_at: str | None


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = decode_jwt_token(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user_id = claims.get("sub")
    name = claims.get("name")
    if not user_id or not name:
        raise HTTPException(status_code=401, detail="Token missing user details")

    try:
        result = create_session(
            SessionStartPayload(
                user_id=user_id,
                name=name,
                module_name=payload.module_name,
                level=payload.level,
            )
        )
    except SessionServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return SessionStartResponse(
        session_id=result.session_id,
        user_id=result.user_id,
        learning_module_id=result.learning_module_id,
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
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    token, expires_in = create_jwt_token(
        user_id=user.user_id,
        email=user.email,
        name=user.name,
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
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    token, expires_in = create_jwt_token(
        user_id=user.user_id,
        email=user.email,
        name=user.name,
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
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = decode_jwt_token(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing user details")

    session = get_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    turns = list_turns_for_session(session_id)
    return SessionDetailResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        learning_module_id=session.learning_module_id,
        room_name=session.room_name,
        status=session.status,
        created_at=session.created_at,
        started_at=session.started_at,
        ended_at=session.ended_at,
        turns=[
            TurnResponse(
                turn_index=t.turn_index,
                question_text=t.question_text,
                user_transcript=t.user_transcript,
                agent_reply=t.agent_reply,
                duration_ms=t.duration_ms,
                prompt_tokens=t.prompt_tokens,
                completion_tokens=t.completion_tokens,
                total_tokens=t.total_tokens,
                model_name=t.model_name,
                estimated_cost_usd=float(t.estimated_cost_usd),
                created_at=t.created_at,
            )
            for t in turns
        ],
    )


@app.get("/sessions", response_model=list[SessionListItemResponse])
async def list_sessions(
    authorization: str | None = Header(default=None),
    limit: int = 50,
) -> list[SessionListItemResponse]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = decode_jwt_token(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing user details")

    sessions = list_sessions_for_user(user_id, limit=limit)
    return [
        SessionListItemResponse(
            session_id=s.session_id,
            learning_module_id=s.learning_module_id,
            room_name=s.room_name,
            status=s.status,
            created_at=s.created_at,
            started_at=s.started_at,
            ended_at=s.ended_at,
        )
        for s in sessions
    ]
