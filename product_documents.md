# Product Requirements Document (PRD)

## 1. Product Overview

### Product Name
AI Conversational Avatar Backend (v1)

### Vision
Provide a real-time voice interview practice backend where a learner can start a session, talk to an AI interviewer over LiveKit, and have session/turn data persisted for analysis and reporting.

### Current Scope
This codebase currently implements:
1. Session bootstrap API (`/sessions/start`) with LiveKit token issuance
2. LiveKit voice worker (STT -> LLM -> TTS)
3. Curriculum loading from JSON packs
4. SQLite persistence for users, modules, sessions, and turns
5. Turn-level token usage and estimated cost tracking

---

## 2. Current System Architecture

### High-Level Components
1. **FastAPI service** (`src/app/main.py`)
2. **LiveKit worker service** (`src/app/livekit/agent.py`)
3. **Session/data service layer** (`src/app/services/session_service.py`)
4. **SQLite storage** (`src/app/db/sqlite_client.py`, `src/app/db/schema_sqlite.sql`)
5. **Curriculum/content packs** (`src/app/curricula/**`)

### Runtime Interaction
1. Frontend calls backend `POST /sessions/start`
2. Backend upserts user/module, creates session, returns `room_name + token + livekit_url`
3. Frontend joins LiveKit room with token
4. Worker (already connected to LiveKit) receives job and joins room
5. Conversation events are captured and persisted in `turns`

---

## 3. In-Scope Functionalities (Implemented)

### 3.1 Session Bootstrap
Implemented in:
- `src/app/main.py`
- `src/app/services/session_service.py`

Capabilities:
1. Upsert `registered_users` by `email/contact`
2. Upsert `learning_modules` by `module_name + level`
3. Create `sessions` row with `active` status
4. Mint participant JWT with room-join grants
5. Return payload required by frontend to connect LiveKit

### 3.2 Voice Agent Runtime
Implemented in:
- `src/app/livekit/agent.py`

Capabilities:
1. Loads prompts/questions via curriculum loader
2. Starts `AgentSession` with configurable `stt/llm/tts` models
3. Sends intro + first question
4. Subscribes to LiveKit agent events:
   - `conversation_item_added`
   - `metrics_collected`
5. Persists user/assistant turn text and duration
6. Persists token usage and estimated cost

### 3.3 Curriculum System
Implemented in:
- `src/app/curricula/loader.py`
- `src/app/curricula/professional/behavioral_interview/*.json`

Capabilities:
1. Loads prompt/question/scoring packs by `persona/mode`
2. Fallback to default `professional/behavioral_interview`
3. Provides configurable content without hardcoding in worker logic

### 3.4 Local Persistence
Implemented in:
- `src/app/db/sqlite_client.py`
- `src/app/db/schema_sqlite.sql`

Capabilities:
1. Auto-initialize SQLite schema at API startup
2. Apply incremental migration for newer `turns` usage columns
3. Store:
   - users
   - modules
   - sessions
   - turns with usage/cost metrics

---

## 4. API Endpoints

## 4.1 `GET /health`
Purpose:
- Service health probe

Response:
- `status`
- `service`
- `timestamp_utc`

## 4.2 `POST /sessions/start`
Purpose:
- Start interview session and return LiveKit credentials for room join

Request body:
1. `name` (string)
2. `email` (email)
3. `contact` (string)
4. `module_name` (string, default `behavioral_interview`)
5. `level` (string, default `intermediate`)

Response body:
1. `session_id`
2. `user_id`
3. `learning_module_id`
4. `room_name`
5. `token`
6. `livekit_url`
7. `status`
8. `created_at`

## 4.3 `GET /sessions/{session_id}`
Status:
- Currently scaffold/stub only (not implemented with DB fetch yet)

---

## 5. Data Model (Current SQLite)

### `registered_users`
1. `id`
2. `fullname`
3. `email`
4. `contact`
5. `created_at`
6. `updated_at`

### `learning_modules`
1. `id`
2. `module_name`
3. `levels`
4. `descriptions`
5. `is_active`
6. `config_json`
7. `created_at`
8. `updated_at`

### `sessions`
1. `id`
2. `user_id`
3. `learning_module_id`
4. `room_name`
5. `statuses`
6. `created_at`
7. `started_at`
8. `ended_at`

### `turns`
1. `id`
2. `session_id`
3. `turn_index`
4. `question_text`
5. `user_transcript`
6. `agent_reply`
7. `duration_ms`
8. `prompt_tokens`
9. `completion_tokens`
10. `total_tokens`
11. `model_name`
12. `estimated_cost_usd`
13. `created_at`

---

## 6. Configuration & Environment

Core env variables (current):
1. `LIVEKIT_URL`
2. `LIVEKIT_API_KEY`
3. `LIVEKIT_API_SECRET`
4. `SQLITE_DB_PATH`
5. `GOOGLE_API_KEY`
6. `DEEPGRAM_API_KEY`
7. `CARTESIA_API_KEY`
8. `AGENT_STT`
9. `AGENT_LLM`
10. `AGENT_TTS`
11. `LLM_INPUT_COST_PER_1K_TOKENS`
12. `LLM_OUTPUT_COST_PER_1K_TOKENS`
13. `LOG_LEVEL`

---

## 7. Known Current Limitations

1. Interview loop is not strict yet (only intro + first question are explicitly driven)
2. `GET /sessions/{session_id}` is still stub
3. No final report generation pipeline yet
4. No async deep evaluation worker implementation yet
5. Session completion state transitions (`completed`, `ended_at`) are not fully wired
6. No frontend repository included in this backend repo

---

## 8. Future Possibilities / Roadmap

### Phase 1 (Immediate)
1. Implement strict 5-question progression with optional 1 follow-up per question
2. Implement `GET /sessions/{session_id}` with session + turns payload
3. Mark sessions completed and persist `ended_at`

### Phase 2 (Evaluation)
1. Implement fast metrics module (`word_count`, fillers, pace hints)
2. Implement async deep evaluation worker (`fluency/grammar/vocab/confidence`)
3. Persist evaluation outputs per turn and session aggregate

### Phase 3 (Reporting & UX)
1. Generate final report payload and save summary fields
2. Add event timeline (`listening`, `eval_queued`, `eval_completed`, etc.)
3. Add frontend report screen and historical session views

### Phase 4 (Productionization)
1. Migrate SQLite to managed Postgres
2. Add proper migrations framework
3. Add observability (structured logs, metrics, traces)
4. Add auth/rate-limits and production hardening

### Phase 5 (Extensibility)
1. Add additional modules (`HR`, `technical_interview`, etc.)
2. Add persona-mode matrix via curriculum packs
3. Add configurable evaluation methods per module/version

---

## 9. Operational Runbook (Current)

### Start API
```bash
source .venv/bin/activate
PYTHONPATH=src uvicorn app.main:app --reload
```

### Start Worker
```bash
source .venv/bin/activate
PYTHONPATH=src python3 -m app.livekit.agent dev
```

### Session Start Test
```bash
curl -X POST http://127.0.0.1:8000/sessions/start \
  -H "Content-Type: application/json" \
  -d '{
    "name":"Suman",
    "email":"suman@example.com",
    "contact":"+919999999999",
    "module_name":"behavioral_interview",
    "level":"intermediate"
  }'
```

---

## 10. Summary
The codebase has a working backend foundation for real-time interview conversations:
1. API-driven session start
2. LiveKit-integrated voice worker
3. Curriculum-backed prompts/questions
4. Turn-level storage with usage/cost metadata

Major next milestone is to complete interview orchestration and evaluation/reporting so the system transitions from conversational prototype to full interview assessment product.
