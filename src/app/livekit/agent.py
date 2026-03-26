import asyncio
import logging
import urllib.request
from dataclasses import dataclass

from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession
from livekit.agents.metrics import LLMMetrics, RealtimeModelMetrics
from livekit.agents.voice.events import ConversationItemAddedEvent, MetricsCollectedEvent

from app.config import get_settings, validate_required_env
from app.curricula.loader import load_curriculum
from app.eval.fast_metrics import compute_fast_metrics
from app.services.session_service import (
    SessionServiceError,
    add_turn_usage,
    create_turn,
    get_session_by_room_name,
    next_turn_index,
    update_turn_fast_metrics,
    update_turn_user_transcript,
)

try:
    from livekit.plugins import cartesia, deepgram, google, sarvam
except ImportError as exc:  # pragma: no cover - surfaced at runtime
    raise RuntimeError(
        "Required plugins not installed. Run: pip install livekit-plugins-deepgram livekit-plugins-cartesia livekit-plugins-sarvam"
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
    intro_sent: bool = False
    intro_logged: bool = False
    pending_turn_index: int | None = None
    assistant_ts: float | None = None
    last_assistant_index: int | None = None
    finalize_called: bool = False


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


def _build_sarvam_tts(speaker: str):
    return sarvam.TTS(
        target_language_code="hi-IN",
        model="bulbul:v3",
        speaker=speaker,
        pace=1.0,
        temperature=0.6,
        output_audio_bitrate="128k",
        min_buffer_size=50,
        max_chunk_length=150,
    )


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
    # if persona_tts.startswith("sarvam:"):
    #     tts_engine = _build_sarvam_tts(persona_tts.removeprefix("sarvam:"))
    # else:
    #     tts_engine = _build_cartesia_tts(persona_tts)
    session = AgentSession(
        # stt=sarvam.STT(
        #         language="en-IN",
        #         model="saaras:v3",
        #         mode="transcribe",  # default
        #     ),
        # stt=deepgram.STT(
        #     model="nova-3",
        #     language="en",
        #         )
        # stt=_build_deepgram_stt(settings.agent_stt),
        stt=deepgram.STTv2(
                model="flux-general-en",
                eager_eot_threshold=0.4,
                ),
        llm=google.LLM(
        model="gemini-3-flash-preview",
        ),
        tts=_build_cartesia_tts(persona_tts),
    )

    async def _finalize_session(reason: str) -> None:
        if not turn_tracker:
            return
        if not settings.backend_base_url:
            logging.warning("Finalize skipped (%s): BACKEND_BASE_URL not set", reason)
            return
        url = f"{settings.backend_base_url.rstrip('/')}/sessions/{turn_tracker.session_id}/finalize"
        headers = {"Content-Type": "application/json"}
        if settings.internal_api_key:
            headers["X-Internal-Key"] = settings.internal_api_key

        def _do_request() -> None:
            req = urllib.request.Request(url, method="POST", headers=headers)
            with urllib.request.urlopen(req, timeout=30):
                return

        try:
            await asyncio.to_thread(_do_request)
        except Exception:
            logging.exception("Finalize call failed (%s)", reason)

    def _schedule_finalize(reason: str) -> None:
        if not turn_tracker or turn_tracker.finalize_called:
            return
        turn_tracker.finalize_called = True
        asyncio.create_task(_finalize_session(reason))

    def on_conversation_item_added(ev: ConversationItemAddedEvent) -> None:
        if not turn_tracker:
            return
        if turn_tracker.closed:
            return
        item = ev.item
        if getattr(item, "type", None) != "message":
            return
        if not turn_tracker.intro_sent and item.role == "user":
            return

        text = item.text_content or ""
        if not text.strip():
            return

        if item.role == "assistant":
            idx = turn_tracker.next_index
            turn_tracker.next_index += 1
            question_text = turn_tracker.question_text if not turn_tracker.intro_logged else ""
            create_turn(
                session_id=turn_tracker.session_id,
                turn_index=idx,
                question_text=question_text,
                user_transcript="",
                agent_reply=text,
            )
            turn_tracker.pending_turn_index = idx
            turn_tracker.assistant_ts = ev.created_at
            turn_tracker.last_assistant_index = idx
            if not turn_tracker.intro_logged:
                turn_tracker.intro_sent = True
                turn_tracker.intro_logged = True
            return

        if item.role == "user" and turn_tracker.pending_turn_index is not None:
            idx = turn_tracker.pending_turn_index
            duration_ms: int | None = None
            if turn_tracker.assistant_ts:
                duration_ms = int(max(0.0, ev.created_at - turn_tracker.assistant_ts) * 1000)
            update_turn_user_transcript(
                session_id=turn_tracker.session_id,
                turn_index=idx,
                user_transcript=text,
                duration_ms=duration_ms,
            )
            turn_tracker.pending_turn_index = None
            turn_tracker.assistant_ts = None
            async def _persist_fast_metrics() -> None:
                try:
                    metrics = compute_fast_metrics(text)
                    update_turn_fast_metrics(
                        session_id=turn_tracker.session_id,
                        turn_index=idx,
                        metrics={
                            "word_count": metrics.word_count,
                            "filler_count": metrics.filler_count,
                            "filler_ratio": metrics.filler_ratio,
                            "sentence_count": metrics.sentence_count,
                            "avg_words_per_sentence": metrics.avg_words_per_sentence,
                        },
                    )
                except Exception:  # pragma: no cover - runtime logging
                    logging.exception("fast metrics write failed")
            asyncio.create_task(_persist_fast_metrics())
            if idx >= turn_tracker.max_turns:
                turn_tracker.closed = True
                closing = curriculum.prompts.get(
                    "closing_prompt",
                    "Thanks for sharing. I will prepare your summary now.",
                )
                asyncio.create_task(session.generate_reply(instructions=closing))
                _schedule_finalize("max_turns")

    def on_metrics_collected(ev: MetricsCollectedEvent) -> None:
        if not turn_tracker:
            return
        turn_index = turn_tracker.last_assistant_index or (turn_tracker.next_index - 1)
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

    def on_participant_disconnected(_participant) -> None:
        if not turn_tracker or turn_tracker.closed:
            return
        turn_tracker.closed = True
        _schedule_finalize("participant_disconnected")

    ctx.room.on("participant_disconnected", on_participant_disconnected)

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
