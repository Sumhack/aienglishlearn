import asyncio
import logging
from dataclasses import dataclass

from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession
from livekit.agents.metrics import LLMMetrics, RealtimeModelMetrics
from livekit.agents.voice.events import ConversationItemAddedEvent, MetricsCollectedEvent

from app.config import get_settings, validate_required_env
from app.curricula.loader import load_curriculum
from app.services.session_service import (
    SessionServiceError,
    add_turn_usage,
    create_turn,
    get_session_by_room_name,
    next_turn_index,
    update_turn_reply,
)

try:
    from livekit.plugins import cartesia, deepgram,google
except ImportError as exc:  # pragma: no cover - surfaced at runtime
    raise RuntimeError(
        "Required plugins not installed. Run: pip install livekit-plugins-deepgram livekit-plugins-cartesia"
    ) from exc

class Assistant(Agent):
    def __init__(self, instructions: str) -> None:
        super().__init__(
            instructions=instructions,
        )


@dataclass
class TurnTracker:
    session_id: str
    question_text: str
    next_index: int
    max_turns: int
    closed: bool = False
    pending_turn_index: int | None = None
    user_ts: float | None = None


server = AgentServer()


def _build_deepgram_stt(model_spec: str):
    if not model_spec.startswith("deepgram/"):
        return deepgram.STT()
    payload = model_spec.removeprefix("deepgram/")
    if ":" in payload:
        model_name, language = payload.split(":", 1)
        return deepgram.STT(model=model_name, language=language)
    return deepgram.STT(model=payload)


def _build_cartesia_tts(model_spec: str):
    if not model_spec.startswith("cartesia/"):
        return cartesia.TTS(model="sonic-3")
    payload = model_spec.removeprefix("cartesia/")
    if ":" in payload:
        model_name, voice_id = payload.split(":", 1)
        return cartesia.TTS(model=model_name, voice=voice_id)
    return cartesia.TTS(model=payload)


@server.rtc_session()
async def my_agent(ctx: agents.JobContext) -> None:
    settings = get_settings()
    session_row = get_session_by_room_name(ctx.room.name)
    persona = session_row.persona if session_row else "school_mentor"
    curriculum = load_curriculum(persona)
    assistant_prompt = curriculum.prompts.get(
        "assistant_system_prompt",
        "You are a helpful voice AI assistant.",
    )
    intro_prompt = curriculum.prompts.get(
        "session_intro_prompt",
        "Greet the learner and explain the session.",
    )
    questions = curriculum.questions.get("questions", [])
    first_question = questions[0]["text"] if questions else "Tell me about yourself."
    max_turns = curriculum.questions.get("max_turns", 10)
    turn_tracker: TurnTracker | None = None
    if session_row:
        turn_tracker = TurnTracker(
            session_id=session_row.session_id,
            question_text=first_question,
            next_index=next_turn_index(session_row.session_id),
            max_turns=max_turns,
        )

    persona_tts = curriculum.prompts.get("tts_voice") or settings.agent_tts
    session = AgentSession(
        stt=deepgram.STTv2(
                model="flux-general-en",
                eager_eot_threshold=0.4,
                ),
        # stt=_build_deepgram_stt(settings.agent_stt),
        llm=google.LLM(
        model="gemini-3-flash-preview",
        ),
        tts=_build_cartesia_tts(persona_tts),
    )

    def on_conversation_item_added(ev: ConversationItemAddedEvent) -> None:
        if not turn_tracker:
            return
        if turn_tracker.closed:
            return
        item = ev.item
        if getattr(item, "type", None) != "message":
            return

        text = item.text_content or ""
        if not text.strip():
            return

        if item.role == "user":
            idx = turn_tracker.next_index
            turn_tracker.next_index += 1
            create_turn(
                session_id=turn_tracker.session_id,
                turn_index=idx,
                question_text=turn_tracker.question_text,
                user_transcript=text,
            )
            turn_tracker.pending_turn_index = idx
            turn_tracker.user_ts = ev.created_at
            if idx >= turn_tracker.max_turns:
                turn_tracker.closed = True
                closing = curriculum.prompts.get(
                    "closing_prompt",
                    "Thanks for sharing. I will prepare your summary now.",
                )
                asyncio.create_task(session.generate_reply(instructions=closing))
        elif item.role == "assistant" and turn_tracker.pending_turn_index is not None:
            duration_ms: int | None = None
            if turn_tracker.user_ts:
                duration_ms = int(max(0.0, ev.created_at - turn_tracker.user_ts) * 1000)
            update_turn_reply(
                session_id=turn_tracker.session_id,
                turn_index=turn_tracker.pending_turn_index,
                agent_reply=text,
                duration_ms=duration_ms,
            )
            turn_tracker.pending_turn_index = None
            turn_tracker.user_ts = None

    def on_metrics_collected(ev: MetricsCollectedEvent) -> None:
        if not turn_tracker:
            return
        turn_index = turn_tracker.pending_turn_index or (turn_tracker.next_index - 1)
        if turn_index < 1:
            return

        metrics = ev.metrics
        if isinstance(metrics, LLMMetrics):
            add_turn_usage(
                session_id=turn_tracker.session_id,
                turn_index=turn_index,
                prompt_tokens=metrics.prompt_tokens,
                completion_tokens=metrics.completion_tokens,
                total_tokens=metrics.total_tokens,
                model_name=metrics.metadata.model_name if metrics.metadata else None,
            )
        elif isinstance(metrics, RealtimeModelMetrics):
            add_turn_usage(
                session_id=turn_tracker.session_id,
                turn_index=turn_index,
                prompt_tokens=metrics.input_tokens,
                completion_tokens=metrics.output_tokens,
                total_tokens=metrics.total_tokens,
                model_name=metrics.metadata.model_name if metrics.metadata else None,
            )

    session.on("conversation_item_added", on_conversation_item_added)
    session.on("metrics_collected", on_metrics_collected)

    await session.start(
        room=ctx.room,
        agent=Assistant(instructions=assistant_prompt),
    )

    await session.generate_reply(
        instructions=(
            f"{intro_prompt} "
            f"Then ask the first interview question exactly: '{first_question}'"
        ),
    )


def main() -> None:
    validate_required_env(["livekit", "models"])
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    try:
        agents.cli.run_app(server)
    except SessionServiceError:
        logging.exception("session persistence failure in worker")
        raise


if __name__ == "__main__":
    main()
