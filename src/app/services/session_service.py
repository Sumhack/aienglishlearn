from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key
from livekit import api

from app.config import get_settings


class SessionServiceError(Exception):
    pass


@dataclass(frozen=True)
class SessionStartPayload:
    user_id: str
    name: str
    persona: str


@dataclass(frozen=True)
class SessionStartResult:
    session_id: str
    user_id: str
    persona: str
    room_name: str
    token: str
    livekit_url: str
    status: str
    created_at: str


@dataclass(frozen=True)
class SessionLookupResult:
    session_id: str
    room_name: str
    persona: str


@dataclass(frozen=True)
class SessionDetail:
    session_id: str
    user_id: str
    persona: str
    room_name: str
    status: str
    created_at: str
    started_at: str | None
    ended_at: str | None


@dataclass(frozen=True)
class TurnDetail:
    session_id: str
    turn_index: int
    question_text: str
    user_transcript: str
    agent_reply: str
    duration_ms: int | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model_name: str | None
    estimated_cost_usd: Decimal
    created_at: str


@dataclass(frozen=True)
class SessionListItem:
    session_id: str
    user_id: str
    persona: str
    room_name: str
    status: str
    created_at: str
    started_at: str | None
    ended_at: str | None


@dataclass(frozen=True)
class PersonaItem:
    module_key: str
    module_name: str
    display_name: str
    role: str
    tone: str
    short_description: str
    is_active: bool
    created_at: str | None
    updated_at: str | None


def _first_row(response: object) -> dict | None:
    if response is None:
        return None
    return dict(response)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _d(value: float | int) -> Decimal:
    # DynamoDB requires Decimal for non-integer numbers
    return Decimal(str(value))


def _dynamo_resource():
    settings = get_settings()
    # if settings.aws_access_key_id and settings.aws_secret_access_key:
    #     return boto3.resource(
    #         "dynamodb",
    #         region_name=settings.aws_region,
    #         aws_access_key_id=settings.aws_access_key_id,
    #         aws_secret_access_key=settings.aws_secret_access_key,
    #     )
    return boto3.resource(
        "dynamodb",
        region_name= "ap-south-1",
    )


def _sessions_table():
    return _dynamo_resource().Table(get_settings().aws_sessions_table)


def _turns_table():
    return _dynamo_resource().Table(get_settings().aws_turns_table)


def _modules_table():
    return _dynamo_resource().Table(get_settings().aws_modules_table)


def _get_learning_module(*, persona: str) -> dict:
    table = _modules_table()
    item = table.get_item(Key={"module_key": persona}).get("Item")
    if not item:
        raise SessionServiceError(f"Persona '{persona}' not found in learning_modules")
    return item


def _create_session(*, user_id: str, persona: str, learning_module_id: str) -> dict:
    session_id = str(uuid4())
    room_name = f"session-{session_id}"
    now = _now_utc()
    item = {
        "session_id": session_id,
        "user_id": user_id,
        "learning_module_id": learning_module_id,
        "persona": persona,
        "room_name": room_name,
        "status": "active",
        "created_at": now,
        "started_at": now,
        "ended_at": None,
    }
    _sessions_table().put_item(Item=item)
    return item


def _build_room_token(*, room_name: str, identity: str, name: str, session_id: str) -> str:
    settings = get_settings()
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(name)
        .with_metadata(f'{{"session_id":"{session_id}"}}')
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
            )
        )
        .to_jwt()
    )
    return token


def create_session(payload: SessionStartPayload) -> SessionStartResult:
    module = _get_learning_module(persona=payload.persona)
    session = _create_session(
        user_id=payload.user_id,
        persona=payload.persona,
        learning_module_id=module["module_key"],
    )
    token = _build_room_token(
        room_name=session["room_name"],
        identity=f"user-{payload.user_id}",
        name=payload.name,
        session_id=session["session_id"],
    )
    settings = get_settings()
    return SessionStartResult(
        session_id=session["session_id"],
        user_id=payload.user_id,
        persona=payload.persona,
        room_name=session["room_name"],
        token=token,
        livekit_url=settings.livekit_url,
        status=session["status"],
        created_at=session["created_at"],
    )


def get_session_by_room_name(room_name: str) -> SessionLookupResult | None:
    if not room_name.startswith("session-"):
        return None
    session_id = room_name.removeprefix("session-")
    item = _sessions_table().get_item(Key={"session_id": session_id}).get("Item")
    if not item:
        return None
    return SessionLookupResult(
        session_id=item["session_id"],
        room_name=item["room_name"],
        persona=item.get("persona", ""),
    )


def get_session_by_id(session_id: str) -> SessionDetail | None:
    item = _sessions_table().get_item(Key={"session_id": session_id}).get("Item")
    if not item:
        return None
    return SessionDetail(
        session_id=item["session_id"],
        user_id=item["user_id"],
        persona=item.get("persona", ""),
        room_name=item["room_name"],
        status=item["status"],
        created_at=item.get("created_at"),
        started_at=item.get("started_at"),
        ended_at=item.get("ended_at"),
    )


def list_turns_for_session(session_id: str) -> list[TurnDetail]:
    table = _turns_table()
    response = table.query(
        KeyConditionExpression=Key("session_id").eq(session_id),
        ScanIndexForward=True,
    )
    items = response.get("Items", [])
    turns: list[TurnDetail] = []
    for item in items:
        turns.append(
            TurnDetail(
                session_id=item["session_id"],
                turn_index=int(item["turn_index"]),
                question_text=item.get("question_text", ""),
                user_transcript=item.get("user_transcript", ""),
                agent_reply=item.get("agent_reply", ""),
                duration_ms=item.get("duration_ms"),
                prompt_tokens=int(item.get("prompt_tokens", 0)),
                completion_tokens=int(item.get("completion_tokens", 0)),
                total_tokens=int(item.get("total_tokens", 0)),
                model_name=item.get("model_name"),
                estimated_cost_usd=Decimal(str(item.get("estimated_cost_usd", 0))),
                created_at=item.get("created_at", ""),
            )
        )
    return turns


def list_turn_items(session_id: str) -> list[dict]:
    table = _turns_table()
    response = table.query(
        KeyConditionExpression=Key("session_id").eq(session_id),
        ScanIndexForward=True,
    )
    return response.get("Items", [])


def list_sessions_for_user(user_id: str, limit: int = 50) -> list[SessionListItem]:
    table = _sessions_table()
    response = table.query(
        IndexName="user_id_index",
        KeyConditionExpression=Key("user_id").eq(user_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    items = response.get("Items", [])
    sessions: list[SessionListItem] = []
    for item in items:
        sessions.append(
            SessionListItem(
                session_id=item["session_id"],
                user_id=item["user_id"],
                persona=item.get("persona", ""),
                room_name=item.get("room_name", ""),
                status=item.get("status", ""),
                created_at=item.get("created_at", ""),
                started_at=item.get("started_at"),
                ended_at=item.get("ended_at"),
            )
        )
    return sessions


def list_personas(active_only: bool = True) -> list[PersonaItem]:
    table = _modules_table()
    response = table.scan()
    items = response.get("Items", [])
    personas: list[PersonaItem] = []
    for item in items:
        if active_only and not item.get("is_active", True):
            continue
        personas.append(
            PersonaItem(
                module_key=item.get("module_key", ""),
                module_name=item.get("module_name", ""),
                display_name=item.get("display_name", ""),
                role=item.get("role", ""),
                tone=item.get("tone", ""),
                short_description=item.get("short_description", ""),
                is_active=bool(item.get("is_active", True)),
                created_at=item.get("created_at"),
                updated_at=item.get("updated_at"),
            )
        )
    return personas


def next_turn_index(session_id: str) -> int:
    table = _turns_table()
    response = table.query(
        KeyConditionExpression=Key("session_id").eq(session_id),
        ScanIndexForward=False,
        Limit=1,
    )
    items = response.get("Items", [])
    if not items:
        return 1
    return int(items[0]["turn_index"]) + 1


def create_turn(
    *,
    session_id: str,
    turn_index: int,
    question_text: str,
    user_transcript: str,
    agent_reply: str = "",
    duration_ms: int | None = None,
) -> None:
    turn_id = str(uuid4())
    item = {
        "session_id": session_id,
        "turn_index": turn_index,
        "turn_id": turn_id,
        "question_text": question_text,
        "user_transcript": user_transcript,
        "agent_reply": agent_reply,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": _d(0),
        "created_at": _now_utc(),
    }
    if duration_ms is not None:
        item["duration_ms"] = int(duration_ms)
    _turns_table().put_item(Item=item)


def update_turn_reply(
    *,
    session_id: str,
    turn_index: int,
    agent_reply: str,
    duration_ms: int | None = None,
) -> None:
    table = _turns_table()
    expr = "SET agent_reply = :reply"
    values = {":reply": agent_reply}
    if duration_ms is not None:
        expr += ", duration_ms = :dur"
        values[":dur"] = duration_ms
    table.update_item(
        Key={"session_id": session_id, "turn_index": turn_index},
        UpdateExpression=expr,
        ExpressionAttributeValues=values,
    )


def update_turn_user_transcript(
    *,
    session_id: str,
    turn_index: int,
    user_transcript: str,
    duration_ms: int | None = None,
) -> None:
    table = _turns_table()
    expr = "SET user_transcript = :txt"
    values = {":txt": user_transcript}
    if duration_ms is not None:
        expr += ", duration_ms = :dur"
        values[":dur"] = duration_ms
    table.update_item(
        Key={"session_id": session_id, "turn_index": turn_index},
        UpdateExpression=expr,
        ExpressionAttributeValues=values,
    )


def update_turn_fast_metrics(
    *,
    session_id: str,
    turn_index: int,
    metrics: dict,
) -> None:
    converted: dict = {}
    for key, value in metrics.items():
        if isinstance(value, float):
            converted[key] = _d(value)
        else:
            converted[key] = value
    table = _turns_table()
    table.update_item(
        Key={"session_id": session_id, "turn_index": turn_index},
        UpdateExpression="SET fast_metrics_json = :m",
        ExpressionAttributeValues={":m": converted},
    )


def add_turn_usage(
    *,
    session_id: str,
    turn_index: int,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    model_name: str | None,
) -> None:
    settings = get_settings()
    estimated_cost = (
        (prompt_tokens / 1000.0) * settings.llm_input_cost_per_1k_tokens
        + (completion_tokens / 1000.0) * settings.llm_output_cost_per_1k_tokens
    )
    table = _turns_table()
    table.update_item(
        Key={"session_id": session_id, "turn_index": turn_index},
        UpdateExpression=(
            "SET prompt_tokens = if_not_exists(prompt_tokens, :zero) + :p, "
            "completion_tokens = if_not_exists(completion_tokens, :zero) + :c, "
            "total_tokens = if_not_exists(total_tokens, :zero) + :t, "
            "estimated_cost_usd = if_not_exists(estimated_cost_usd, :zero) + :cost, "
            "model_name = if_not_exists(model_name, :model)"
        ),
        ExpressionAttributeValues={
            ":p": prompt_tokens,
            ":c": completion_tokens,
            ":t": total_tokens,
            ":cost": _d(estimated_cost),
            ":model": model_name,
            ":zero": _d(0),
        },
    )


def update_session_summary(
    *,
    session_id: str,
    scores: dict[str, float],
    summary: dict,
    report_status: str,
) -> None:
    table = _sessions_table()
    table.update_item(
        Key={"session_id": session_id},
        UpdateExpression=(
            "SET overall_score = :overall, "
            "fluency_score = :fluency, "
            "grammar_score = :grammar, "
            "vocabulary_score = :vocab, "
            "clarity_score = :clarity, "
            "summary_json = :summary, "
            "report_status = :status"
        ),
        ExpressionAttributeValues={
            ":overall": _d(scores.get("overall", 0)),
            ":fluency": _d(scores.get("fluency", 0)),
            ":grammar": _d(scores.get("grammar", 0)),
            ":vocab": _d(scores.get("vocabulary", 0)),
            ":clarity": _d(scores.get("clarity", 0)),
            ":summary": summary,
            ":status": report_status,
        },
    )
