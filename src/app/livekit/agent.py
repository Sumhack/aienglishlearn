import asyncio
import time
import urllib.request
from dataclasses import dataclass, field

from livekit import agents, rtc
from livekit.agents import Agent, AgentServer, AgentSession
from livekit.agents.llm import ChatContext
from livekit.agents.metrics import LLMMetrics, RealtimeModelMetrics
from livekit.agents.voice.events import ConversationItemAddedEvent, MetricsCollectedEvent
# from livekit.agents import TurnHandlingOptions
# from livekit.agents.turn_handling import TurnHandlingOptions
# from livekit.plugins.turn_detector.multilingual import MultilingualModel
# from livekit.plugins import silero
# from livekit.plugins.turn_detector.multilingual import MultilingualModel
# from livekit.plugins import silero
from app.config import get_settings, validate_required_env
from app.curricula.loader import load_curriculum
from app.eval.fast_metrics import compute_fast_metrics
from app.logging.events import (
    AGENT_SESSION_CONFIGURED,
    DB_WRITE_FAILED,
    LLM_FAILED,
    LLM_REQUEST,
    LLM_RESPONSE,
    PARTICIPANT_CONNECTED,
    SESSION_COMPLETED,
    SESSION_FINALIZATION_COMPLETED,
    SESSION_FINALIZATION_FAILED,
    SESSION_FINALIZATION_STARTED,
    SESSION_FAILED,
    SESSION_STARTED,
    STT_FAILED,
    STT_STARTED,
    TRACK_EGRESS_FAILED,
    TRACK_PUBLISHED,
    TURN_COMPLETED,
    TURN_FAILED,
    TURN_STARTED,
    TTS_FAILED,
    TTS_STARTED,
    WARMUP_COMPLETED,
    WARMUP_FAILED,
    WARMUP_STARTED,
)
from app.logging.context import ensure_trace_id
from app.logging.wrapper import bind_context, log_boundary, log_error
from app.services.session_service import (
    SessionServiceError,
    add_turn_usage,
    create_turn,
    get_session_by_room_name,
    get_session_by_id,
    next_turn_index,
    update_turn_fast_metrics,
    update_turn_user_transcript,
    update_session_recording,
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
    egress_track_ids: set[str] = field(default_factory=set)

# server = AgentServer()

_warmup_done = False
_warmup_lock = asyncio.Lock()


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


async def _warmup_models(llm_engine: object, tts_engine: object) -> None:
    global _warmup_done
    if _warmup_done:
        return
    async with _warmup_lock:
        if _warmup_done:
            return
        try:
            log_boundary(
                event=WARMUP_STARTED,
                status="started",
                message="Warmup started",
                component="livekit.agent",
                operation="warmup",
            )
            if hasattr(llm_engine, "chat"):
                ctx = ChatContext()
                ctx.add_message(role="user", content="Say OK.")
                await llm_engine.chat(chat_ctx=ctx).collect()
            if hasattr(tts_engine, "synthesize"):
                async for _chunk in tts_engine.synthesize("OK"):
                    pass
            _warmup_done = True
            log_boundary(
                event=WARMUP_COMPLETED,
                status="completed",
                message="Warmup completed",
                component="livekit.agent",
                operation="warmup",
            )
        except Exception as exc:
            log_error(
                event=WARMUP_FAILED,
                status="failed",
                message="Warmup failed",
                component="livekit.agent",
                operation="warmup",
                error_type="internal",
                error_stage="tool_call",
                severity="medium",
                error_message=str(exc),
            )


server = AgentServer(num_idle_processes=1)


@server.rtc_session()
async def my_agent(ctx: agents.JobContext) -> None:
    settings = get_settings()
    start_ts = time.monotonic()
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
    # questions = curriculum.questions.get("questions", [])
    # first_question = questions[0]["text"] if questions else "Tell me about yourself."
    first_question = "Tell me about yourself."
    max_turns = curriculum.questions.get("max_turns", 10)
    turn_tracker: TurnTracker | None = None
    if session_row:
        turn_tracker = TurnTracker(
            session_id=session_row.session_id,
            question_text=first_question,
            next_index=next_turn_index(session_row.session_id),
            max_turns=max_turns,
        )
        bind_context(
            trace_id=ensure_trace_id(),
            session_id=turn_tracker.session_id,
            persona=persona,
        )
        log_boundary(
            event=SESSION_STARTED,
            status="started",
            message="Worker joined session",
            session_id=turn_tracker.session_id,
            persona=persona,
            duration_ms=0,
        )

    persona_tts = curriculum.prompts.get("tts_voice") or settings.agent_tts
    # if persona_tts.startswith("sarvam:"):
    #     tts_engine = _build_sarvam_tts(persona_tts.removeprefix("sarvam:"))
    # else:
    #     tts_engine = _build_cartesia_tts(persona_tts)
    llm_engine = google.LLM(
        model="gemini-3-flash-preview",
    )
    tts_engine = _build_cartesia_tts(persona_tts)
    # await _warmup_models(llm_engine, tts_engine)
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
        llm=llm_engine,
        # llm=aws.LLM(
        # model="amazon.nova-pro-v1:0",
        # temperature=0.8,
        # ),
        # llm = aws.LLM(),
        tts=tts_engine,
        preemptive_generation=True,
        use_tts_aligned_transcript=True,

        # vad=silero.VAD.load(),

        # turn_handling={
        # "turn_detection": MultilingualModel(),
    # },
    )
    # asyncio.create_task(_warmup_models(llm_engine, tts_engine))
    log_boundary(
        event=AGENT_SESSION_CONFIGURED,
        status="started",
        message="Agent session configured",
        session_id=turn_tracker.session_id if turn_tracker else None,
        persona=persona,
        model_name="deepgram/flux-general-en",
    )

    async def _finalize_session(reason: str) -> None:
        if not turn_tracker:
            return
        if not settings.backend_base_url:
            log_error(
                event=SESSION_FAILED,
                status="failed",
                message="Finalize skipped because BACKEND_BASE_URL is not set",
                session_id=turn_tracker.session_id,
                error_type="dependency",
                error_stage="persist",
                severity="medium",
                reason=reason,
            )
            return
        log_boundary(
            event=SESSION_FINALIZATION_STARTED,
            status="started",
            message="Finalize request started",
            session_id=turn_tracker.session_id,
            reason=reason,
        )
        url = f"{settings.backend_base_url.rstrip('/')}/sessions/{turn_tracker.session_id}/finalize"
        headers = {"Content-Type": "application/json"}
        if settings.internal_api_key:
            headers["X-Internal-Key"] = settings.internal_api_key

        def _do_request() -> None:
            req = urllib.request.Request(url, method="POST", headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                log_boundary(
                    event=SESSION_FINALIZATION_COMPLETED,
                    status="completed",
                    message="Session finalize completed",
                    session_id=turn_tracker.session_id,
                    reason=reason,
                    status_code=getattr(resp, "status", "unknown"),
                )
                log_boundary(
                    event=SESSION_COMPLETED,
                    status="completed",
                    message="Session completed",
                    session_id=turn_tracker.session_id,
                    reason=reason,
                )
                return

        try:
            await asyncio.to_thread(_do_request)
        except Exception as exc:
            log_error(
                event=SESSION_FINALIZATION_FAILED,
                status="failed",
                message="Finalize request failed",
                session_id=turn_tracker.session_id,
                reason=reason,
                error_type="dependency",
                error_stage="persist",
                severity="high",
                error_message=str(exc),
            )

    def _schedule_finalize(reason: str) -> None:
        if not turn_tracker or turn_tracker.finalize_called:
            return
        turn_tracker.finalize_called = True
        log_boundary(
            event=SESSION_FINALIZATION_STARTED,
            status="started",
            message="Finalize scheduled",
            session_id=turn_tracker.session_id,
            reason=reason,
        )
        asyncio.create_task(_finalize_session(reason))

    async def _start_track_egress(track_id: str, key: str, user_id: str) -> None:
        if not turn_tracker:
            return
        if track_id in turn_tracker.egress_track_ids:
            return
        turn_tracker.egress_track_ids.add(track_id)
        if not (
            settings.egress_s3_access_key
            and settings.egress_s3_secret_key
            and settings.egress_s3_bucket
            and settings.egress_s3_region
        ):
            return
        try:
            from livekit import api
            from livekit.protocol import egress as lk_egress

            s3 = lk_egress.S3Upload(
                access_key=settings.egress_s3_access_key,
                secret=settings.egress_s3_secret_key,
                bucket=settings.egress_s3_bucket,
                region=settings.egress_s3_region,
            )
            filepath = (
                f"users/{user_id}/sessions/{turn_tracker.session_id}/{key}-{{track_id}}.ogg"
            )
            resolved_path = (
                f"users/{user_id}/sessions/{turn_tracker.session_id}/{key}-{track_id}.ogg"
            )
            file_output = lk_egress.DirectFileOutput(
                filepath=filepath,
                s3=s3,
            )
            req = lk_egress.TrackEgressRequest(
                room_name=ctx.room.name,
                track_id=track_id,
                file=file_output,
            )
            lkapi = api.LiveKitAPI(
                url=settings.livekit_url,
                api_key=settings.livekit_api_key,
                api_secret=settings.livekit_api_secret,
            )
            try:
                await lkapi.egress.start_track_egress(req)
            finally:
                await lkapi.aclose()

            update_session_recording(
                session_id=turn_tracker.session_id,
                key=key,
                value=f"s3://{settings.egress_s3_bucket}/{resolved_path}",
            )
        except Exception as exc:
            log_error(
                event=TRACK_EGRESS_FAILED,
                status="failed",
                message="Failed to start egress",
                session_id=turn_tracker.session_id,
                error_type="dependency",
                error_stage="persist",
                severity="medium",
                key=key,
                error_message=str(exc),
            )

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
            log_boundary(
                event=TURN_STARTED,
                status="started",
                message="Assistant turn started",
                session_id=turn_tracker.session_id,
                turn_index=idx,
                duration_ms=0,
            )
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
                log_boundary(
                    event=LLM_RESPONSE,
                    status="completed",
                    message="First assistant message created",
                    session_id=turn_tracker.session_id,
                    turn_index=idx,
                    latency_ms=int((time.monotonic() - start_ts) * 1000),
                )
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
            log_boundary(
                event=TURN_COMPLETED,
                status="completed",
                message="User transcript captured",
                session_id=turn_tracker.session_id,
                turn_index=idx,
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
                except Exception as exc:  # pragma: no cover - runtime logging
                    log_error(
                        event=DB_WRITE_FAILED,
                        status="failed",
                        message="Fast metrics write failed",
                        session_id=turn_tracker.session_id,
                        turn_index=idx,
                        error_type="dependency",
                        error_stage="persist",
                        severity="medium",
                        error_message=str(exc),
                    )
                
            asyncio.create_task(_persist_fast_metrics())
            # if idx >= turn_tracker.max_turns:
            #     # Finalize on disconnect only for now.
            #     turn_tracker.closed = True
            #     closing = curriculum.prompts.get(
            #         "closing_prompt",
            #         "Thanks for sharing. I will prepare your summary now.",
            #     )
            #     asyncio.create_task(session.generate_reply(instructions=closing))

    def on_metrics_collected(ev: MetricsCollectedEvent) -> None:
        if not turn_tracker:
            return
        turn_index = turn_tracker.last_assistant_index or (turn_tracker.next_index - 1)
        if turn_index < 1:
            return

        metrics = ev.metrics
        if isinstance(metrics, LLMMetrics):
            log_boundary(
                event=LLM_REQUEST,
                status="started",
                message="LLM metrics collected",
                session_id=turn_tracker.session_id,
                turn_index=turn_index,
                model_name=metrics.metadata.model_name if metrics.metadata else None,
            )
            add_turn_usage(
                session_id=turn_tracker.session_id,
                turn_index=turn_index,
                prompt_tokens=metrics.prompt_tokens,
                completion_tokens=metrics.completion_tokens,
                total_tokens=metrics.total_tokens,
                model_name=metrics.metadata.model_name if metrics.metadata else None,
            )
            log_boundary(
                event=LLM_RESPONSE,
                status="completed",
                message="LLM response recorded",
                session_id=turn_tracker.session_id,
                turn_index=turn_index,
                latency_ms=0,
            )
        elif isinstance(metrics, RealtimeModelMetrics):
            log_boundary(
                event=STT_STARTED,
                status="started",
                message="Realtime metrics collected",
                session_id=turn_tracker.session_id,
                turn_index=turn_index,
                model_name=metrics.metadata.model_name if metrics.metadata else None,
            )
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
        # record=True,
    )
    log_boundary(
        event=SESSION_STARTED,
        status="completed",
        message="Session start completed",
        session_id=turn_tracker.session_id if turn_tracker else None,
        latency_ms=int((time.monotonic() - start_ts) * 1000),
    )
    if turn_tracker:
        session_detail = get_session_by_id(turn_tracker.session_id)
        if session_detail:
            def _start_agent_for_publication(publication) -> None:
                if publication.kind != rtc.TrackKind.KIND_AUDIO:
                    return
                asyncio.create_task(
                    _start_track_egress(
                        track_id=publication.sid,
                        key="agent",
                        user_id=session_detail.user_id,
                    )
                )

            def on_local_track_published(publication, _track) -> None:
                _start_agent_for_publication(publication)

            for publication in ctx.room.local_participant.track_publications.values():
                _start_agent_for_publication(publication)

            ctx.room.on("local_track_published", on_local_track_published)

    def _start_user_for_publication(publication, participant) -> None:
        if publication.kind != rtc.TrackKind.KIND_AUDIO:
            return
        identity = getattr(participant, "identity", "")
        if not identity.startswith("user-"):
            return
        user_id = identity.removeprefix("user-")
        asyncio.create_task(
            _start_track_egress(
                track_id=publication.sid,
                key="user",
                user_id=user_id,
            )
        )

    def on_track_published(publication, remote_participant) -> None:
        if not turn_tracker or turn_tracker.closed:
            return
        log_boundary(
            event=TRACK_PUBLISHED,
            status="started",
            message="Track published",
            session_id=turn_tracker.session_id,
            metadata={
                "turn_index": turn_tracker.last_assistant_index,
                "track_sid": publication.sid,
                "participant_identity": getattr(remote_participant, "identity", ""),
            },
        )
        _start_user_for_publication(publication, remote_participant)

    def on_participant_connected(participant) -> None:
        if not turn_tracker or turn_tracker.closed:
            return
        log_boundary(
            event=PARTICIPANT_CONNECTED,
            status="started",
            message="Participant connected",
            session_id=turn_tracker.session_id,
            metadata={
                "participant_identity": getattr(participant, "identity", ""),
                "track_count": len(participant.track_publications),
            },
        )
        for publication in participant.track_publications.values():
            _start_user_for_publication(publication, participant)

    ctx.room.on("track_published", on_track_published)
    ctx.room.on("participant_connected", on_participant_connected)

    log_boundary(
        event=LLM_REQUEST,
        status="started",
        message="Initial generate_reply started",
        session_id=turn_tracker.session_id if turn_tracker else None,
        latency_ms=int((time.monotonic() - start_ts) * 1000),
    )
    await session.generate_reply(
        instructions=(
            f"{intro_prompt} "
            f"Then ask the first interview question exactly: '{first_question}'"
        ),
    )
    log_boundary(
        event=LLM_RESPONSE,
        status="completed",
        message="Initial generate_reply completed",
        session_id=turn_tracker.session_id if turn_tracker else None,
        latency_ms=int((time.monotonic() - start_ts) * 1000),
    )

    if turn_tracker:
        for participant in ctx.room.remote_participants.values():
            on_participant_connected(participant)


def main() -> None:
    validate_required_env(["livekit", "models"])
    get_settings()
    try:
        agents.cli.run_app(server)
    except SessionServiceError:
        log_error(
            event=SESSION_FAILED,
            status="failed",
            message="Session persistence failure in worker",
            error_type="dependency",
            error_stage="persist",
            severity="high",
        )
        raise


if __name__ == "__main__":
    main()
