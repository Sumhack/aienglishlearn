from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Attr, Key
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
    display_name: str
    coach_type: str
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
    summary_json: dict | None
    # recordings_json: dict | None


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


@dataclass(frozen=True)
class PersonaItem:
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


@dataclass(frozen=True)
class PersonaV1Item:
    module_key: str
    coach_category: str
    coach_type: str
    display_name: str
    short_description: str
    tone: str


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
    # Allow the same codebase to run in multiple regions (India + US) by
    # respecting `AWS_REGION` from env/config. Keep a safe default for local use.
    region_name = settings.aws_region
    #or "ap-south-1"
    # if settings.aws_access_key_id and settings.aws_secret_access_key:
    #     return boto3.resource(
    #         "dynamodb",
    #         region_nazme=region_name,
    #         aws_access_key_id=settings.aws_access_key_id,
    #         aws_secret_access_key=settings.aws_secret_access_key,
    #     )
    return boto3.resource("dynamodb", region_name=region_name)


def _sessions_table():
    return _dynamo_resource().Table(get_settings().aws_sessions_table)


def _turns_table():
    return _dynamo_resource().Table(get_settings().aws_turns_table)


def _modules_table():
    return _dynamo_resource().Table(get_settings().aws_modules_table)


def _personas_table():
    return _dynamo_resource().Table(get_settings().aws_personas_table)


def _get_learning_module(*, persona: str) -> dict:
    table = _personas_table()
    # personas table uses composite PK (coach_type, module_key),
    # so look up by module_key via scan for now.
    item = None
    scan_kwargs = {"FilterExpression": Attr("module_key").eq(persona)}
    response = table.scan(**scan_kwargs)
    items = response.get("Items", [])
    if items:
        item = items[0]
    while not item and response.get("LastEvaluatedKey"):
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"], **scan_kwargs)
        items = response.get("Items", [])
        if items:
            item = items[0]
    if not item:
        raise SessionServiceError(f"Persona '{persona}' not found in learning_modules")
    return item


def _get_learning_module_meta(*, persona: str) -> tuple[str, str]:
    module = _get_learning_module(persona=persona)
    display_name = module.get("display_name") or module.get("module_name") or persona
    coach_type = module.get("coach_type") or ""
    return display_name, coach_type


def _create_session(
    *,
    user_id: str,
    persona: str,
    learning_module_id: str,
    display_name: str,
    coach_type: str,
) -> dict:
    session_id = str(uuid4())
    room_name = f"session-{session_id}"
    now = _now_utc()
    item = {
        "session_id": session_id,
        "user_id": user_id,
        "learning_module_id": learning_module_id,
        "persona": persona,
        "display_name": display_name,
        "coach_type": coach_type,
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
    display_name = module.get("display_name") or module.get("module_name") or payload.persona
    coach_type = module.get("coach_type") or ""
    session = _create_session(
        user_id=payload.user_id,
        persona=payload.persona,
        learning_module_id=module["module_key"],
        display_name=display_name,
        coach_type=coach_type,
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
        display_name=display_name,
        coach_type=coach_type,
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
    display_name, coach_type = _get_learning_module_meta(persona=item.get("persona", ""))
    return SessionDetail(
        session_id=item["session_id"],
        user_id=item["user_id"],
        persona=item.get("persona", ""),
        display_name=display_name,
        coach_type=coach_type,
        room_name=item["room_name"],
        status=item["status"],
        created_at=item.get("created_at"),
        started_at=item.get("started_at"),
        ended_at=item.get("ended_at"),
        overall_score=float(item.get("overall_score", 0)) if item.get("overall_score") is not None else None,
        fluency_score=float(item.get("fluency_score", 0)) if item.get("fluency_score") is not None else None,
        grammar_score=float(item.get("grammar_score", 0)) if item.get("grammar_score") is not None else None,
        vocabulary_score=float(item.get("vocabulary_score", 0)) if item.get("vocabulary_score") is not None else None,
        clarity_score=float(item.get("clarity_score", 0)) if item.get("clarity_score") is not None else None,
        relevance_score=float(item.get("relevance_score", 0)) if item.get("relevance_score") is not None else None,
        report_status=item.get("report_status"),
        summary_json=item.get("summary_json"),
        # recordings_json=item.get("recordings_json"),
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


def list_sessions_for_user(user_id: str, limit: int = 200) -> list[SessionListItem]:
    table = _sessions_table()
    response = table.query(
        IndexName="user_id_index",
        KeyConditionExpression=Key("user_id").eq(user_id),
        FilterExpression=Attr("relevance_score").gt(_d(0)),
        ScanIndexForward=False,
        # Limit=limit,
    )
    items = response.get("Items", [])
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    sessions: list[SessionListItem] = []
    for item in items:
        sessions.append(
            SessionListItem(
                session_id=item["session_id"],
                user_id=item["user_id"],
                persona=item.get("persona", ""),
                display_name=item.get("display_name", ""),
                coach_type=item.get("coach_type", ""),
                room_name=item.get("room_name", ""),
                status=item.get("status", ""),
                created_at=item.get("created_at", ""),
                started_at=item.get("started_at"),
                ended_at=item.get("ended_at"),
                overall_score=float(item.get("overall_score", 0)) if item.get("overall_score") is not None else None,
                fluency_score=float(item.get("fluency_score", 0)) if item.get("fluency_score") is not None else None,
                grammar_score=float(item.get("grammar_score", 0)) if item.get("grammar_score") is not None else None,
                vocabulary_score=float(item.get("vocabulary_score", 0)) if item.get("vocabulary_score") is not None else None,
                clarity_score=float(item.get("clarity_score", 0)) if item.get("clarity_score") is not None else None,
                relevance_score=float(item.get("relevance_score", 0)) if item.get("relevance_score") is not None else None,
                report_status=item.get("report_status"),
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
                coach_type=item.get("coach_type", ""),
                role=item.get("role", ""),
                tone=item.get("tone", ""),
                short_description=item.get("short_description", ""),
                is_active=bool(item.get("is_active", True)),
                created_at=item.get("created_at"),
                updated_at=item.get("updated_at"),
            )
        )
    return personas


def list_personas_v1() -> list[PersonaV1Item]:
    table = _personas_table()
    response = table.scan()
    items = response.get("Items", [])
    personas: list[PersonaV1Item] = []
    for item in items:
        personas.append(
            PersonaV1Item(
                module_key=item.get("module_key", ""),
                coach_category=item.get("coach_category", ""),
                coach_type=item.get("coach_type", ""),
                display_name=item.get("display_name", ""),
                short_description=item.get("short_description", ""),
                tone=item.get("tone", ""),
            )
        )
    personas.sort(
        key=lambda item: (
            item.coach_category.lower(),
            item.display_name.lower(),
            item.module_key.lower(),
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
            "relevance_score = :relevance, "
            "summary_json = :summary, "
            "report_status = :status"
        ),
        ExpressionAttributeValues={
            ":overall": _d(scores.get("overall", 0)),
            ":fluency": _d(scores.get("fluency", 0)),
            ":grammar": _d(scores.get("grammar", 0)),
            ":vocab": _d(scores.get("vocabulary", 0)),
            ":clarity": _d(scores.get("clarity", 0)),
            ":relevance": _d(scores.get("relevance", 0)),
            ":summary": summary,
            ":status": report_status,
        },
    )


def update_session_recording(
    *,
    session_id: str,
    key: str,
    value: str,
) -> None:
    table = _sessions_table()
    # DynamoDB does not allow setting a parent and child path in the same update.
    table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #r = if_not_exists(#r, :empty)",
        ExpressionAttributeNames={"#r": "recordings_json"},
        ExpressionAttributeValues={":empty": {}},
    )
    table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #r.#k = :v",
        ExpressionAttributeNames={"#r": "recordings_json", "#k": key},
        ExpressionAttributeValues={":v": value},
    )
