# Development Progress

## 2026-02-21

### Task 1: Backend skeleton structure
- Created initial backend layout under `src/app/` with folders for `livekit`, `db`, `eval`, `services`, and `curricula`.
- Added placeholder files for planned modules:
  - API entrypoint (`src/app/main.py`)
  - Worker entrypoint (`src/app/livekit/agent.py`)
  - Config (`src/app/config.py`)
  - DB client/schema placeholders (`src/app/db/*`)
  - Evaluation placeholders (`src/app/eval/*`)
  - Service placeholders (`src/app/services/*`)
  - Curriculum loader and v1 curriculum files (`src/app/curricula/*`)

Why:
- Establishes a clean base that matches the agreed architecture and lets us implement features incrementally without reorganizing later.

### Task 2: Config foundation and env template
- Implemented central settings module in `src/app/config.py`:
  - Loads `.env` using `python-dotenv`
  - Defines a typed `Settings` dataclass
  - Adds `missing_env_vars(scopes)` and `validate_required_env(scopes)` helpers for startup validation
  - Adds cached `get_settings()` accessor
- Added `.env.example` with required variables for LiveKit, Supabase, and model providers.

Why:
- Keeps environment handling in one place and avoids silent runtime errors from missing keys.
- Makes onboarding/deployment clearer by documenting required env vars.

### Task 3: API scaffold for incremental backend build
- Implemented FastAPI app scaffold in `src/app/main.py` with:
  - `GET /health`
  - `POST /sessions/start` (stub response model)
  - `GET /sessions/{session_id}` (stub response model)
- Added typed request/response models for session bootstrap and health checks.
- Added startup validation for required API env scopes: `livekit` and `supabase`.
- Added API runtime dependencies to `requirements.txt`:
  - `fastapi`
  - `uvicorn`

Why:
- Establishes a runnable API surface early so frontend/backend contracts are explicit before full implementation.
- Keeps failures explicit by validating required environment at startup instead of failing mid-request.

### Task 4: LiveKit worker scaffold with Google model alignment
- Implemented worker entrypoint in `src/app/livekit/agent.py` by porting the baseline flow from `setup_agent.py`:
  - `AgentServer` initialization
  - `@server.rtc_session()` handler
  - `AgentSession` startup and initial greeting
- Wired worker model config through central settings (`agent_stt`, `agent_llm`, `agent_tts`) instead of hardcoding.
- Added worker startup guard: `validate_required_env(["livekit", "models"])`.
- Updated `src/app/config.py` model scope and settings to use:
  - `GOOGLE_API_KEY` (instead of `OPENAI_API_KEY`)
  - env-configurable agent model IDs (`AGENT_STT`, `AGENT_LLM`, `AGENT_TTS`)
- Recreated a clean `.env.example` with the updated Google-based key set and model config variables.

Why:
- Keeps model/provider choices configurable per environment while preserving the same worker runtime pattern.
- Aligns backend config with your decision to use Google models going forward.

### Task 5: Curriculum loader and v1 behavioral content
- Implemented `src/app/curricula/loader.py`:
  - Added `CurriculumPack` dataclass
  - Added `load_curriculum(persona, mode)` entrypoint
  - Added file loading with validation and fallback to default `professional/behavioral_interview`
- Populated v1 curriculum files under `src/app/curricula/professional/behavioral_interview/`:
  - `questions.json` with 5 core behavioral questions + follow-up policy/examples
  - `prompts.json` with system/intro/turn/closing guidance
  - `scoring.json` with weighted dimensions, fast metric seed list, and report output contract

Why:
- Establishes a content-pack architecture so interview behavior and scoring can evolve without changing core orchestration code.
- Unblocks next steps where the agent loop and evaluation pipeline need standardized curriculum inputs.

### Task 6: Worker uses curriculum prompts and first question
- Updated `src/app/livekit/agent.py` to load curriculum content via:
  - `load_curriculum("professional", "behavioral_interview")`
- Replaced hardcoded assistant instructions with `assistant_system_prompt` from `prompts.json`.
- Replaced hardcoded greeting call with curriculum-based intro plus first interview question from `questions.json`.
- Updated `Assistant` class signature to accept instructions dynamically.

Why:
- Ensures agent behavior is controlled by curriculum content-pack files, enabling mode/persona expansion without changing orchestration code.
- Moves us from static demo behavior toward the intended interview workflow contract.

### Task 7: Core DB schema finalized for users, modules, sessions, and turns
- Implemented agreed schema in `src/app/db/schema.sql` with four tables:
  - `users`
  - `learning_modules`
  - `sessions`
  - `turns`
- Kept `sessions` with both `created_at` and `started_at`, plus `ended_at`.
- Kept `learning_modules.config_json` for module configuration and question content in v1.
- Added primary keys, foreign keys, status/check constraints, and essential indexes for session/turn lookups.

Why:
- Establishes a stable data contract before implementing `/sessions/start` and turn persistence logic.
- Keeps v1 implementation simple while preserving future extensibility.

### Task 8: Real session bootstrap service and API integration
- Implemented Supabase client factory in `src/app/db/supabase_client.py`.
- Implemented `src/app/services/session_service.py` with end-to-end session bootstrap:
  - upsert `registered_users`
  - get/create `learning_modules`
  - create `sessions`
  - mint LiveKit room token
- Replaced `/sessions/start` stub in `src/app/main.py` with real service call and expanded response contract:
  - `session_id`, `user_id`, `learning_module_id`, `room_name`, `token`, `livekit_url`, `status`, `created_at`
- Updated request contract to include `email`, `module_name`, and `level`.
- Updated dependencies in `requirements.txt`:
  - `supabase`
  - `email-validator`
- Fixed schema consistency in `src/app/db/schema.sql` for your renamed columns:
  - `sessions.user_id` now references `registered_users(id)`
  - status index now points to `sessions.statuses`

Why:
- Enables full API-based session bootstrap and token generation without frontend dependency.
- Aligns runtime code with your renamed schema/table choices so Postman testing is now possible.

### Task 9: Local SQLite migration for API persistence
- Migrated API persistence layer from Supabase REST to SQLite for local development:
  - Added `src/app/db/sqlite_client.py` with connection helper and schema initializer.
  - Added `src/app/db/schema_sqlite.sql` with SQLite-compatible tables/indexes:
    - `registered_users`
    - `learning_modules`
    - `sessions`
    - `turns`
- Reworked `src/app/services/session_service.py` to use SQLite queries/transactions for:
  - user upsert
  - module get/create
  - session creation
  - existing LiveKit token mint flow (unchanged)
- Updated API startup in `src/app/main.py`:
  - validates `livekit` + `sqlite` env scopes
  - auto-initializes SQLite schema on app startup
- Updated config/env/deps:
  - `src/app/config.py` now uses `SQLITE_DB_PATH` instead of Supabase env vars
  - `.env.example` now documents `SQLITE_DB_PATH`
  - removed `supabase` dependency from `requirements.txt`
  - left `src/app/db/supabase_client.py` as an explicit disabled stub for clarity

Why:
- Removes dependency on Supabase network availability and unblocks end-to-end local testing now.
- Keeps the API contract stable so frontend and later cloud DB migration remain straightforward.

### Task 10: Turn persistence and token/cost tracking scaffold
- Extended SQLite turns schema with usage fields in `src/app/db/schema_sqlite.sql`:
  - `prompt_tokens`, `completion_tokens`, `total_tokens`, `model_name`, `estimated_cost_usd`
- Added incremental migration logic in `src/app/db/sqlite_client.py` so existing local DB files are auto-upgraded on startup.
- Added token pricing settings in `src/app/config.py`:
  - `LLM_INPUT_COST_PER_1K_TOKENS`
  - `LLM_OUTPUT_COST_PER_1K_TOKENS`
- Added turn persistence helpers in `src/app/services/session_service.py`:
  - `get_session_by_room_name`
  - `next_turn_index`
  - `create_turn`
  - `update_turn_reply`
  - `add_turn_usage`
- Wired worker event callbacks in `src/app/livekit/agent.py`:
  - listens to `conversation_item_added` and stores user/assistant turns
  - listens to `metrics_collected` and accumulates token usage + estimated cost
  - associates room activity to session rows using `room_name`

Why:
- Enables immediate visibility into what happened in each conversation turn.
- Provides a practical v1 basis for per-session usage and cost monitoring before full billing-grade metering is added.

### Task 11: DynamoDB-backed auth endpoints
- Added `src/app/auth/jwt_utils.py` for JWT creation/verification.
- Added `src/app/auth/user_store.py` for DynamoDB user storage:
  - GSI lookup by `email`
  - bcrypt password hashing
- Added `/auth/register` and `/auth/login` endpoints in `src/app/main.py`.
- Added auth environment requirements in `src/app/config.py`:
  - `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_USERS_TABLE`, `JWT_SECRET`
- Added dependencies in `requirements.txt`:
  - `boto3`
  - `passlib[bcrypt]`
  - `pyjwt`
- Documented new env vars in `.example`.

Why:
- Enables a minimal registration/login flow suitable for demos.
- Keeps authentication decoupled so it can later be swapped for Cognito/Auth0 without major refactors.

### Task 12: JWT-protected session start
- Updated `POST /sessions/start` to require `Authorization: Bearer <token>`.
- Session creation now uses `name` and `email` from JWT claims instead of request body.
- Simplified request body to only include:
  - `contact`, `module_name`, `level`

Why:
- Ensures sessions are tied to authenticated users without re-sending identity fields.

### Task 13: Remove contact and SQLite user upsert from session start
- Removed `contact` from `SessionStartRequest` and session payload.
- Session creation now uses `user_id` from JWT (`sub` claim).
- Removed SQLite `registered_users` upsert from `create_session`.
- Dropped the `sessions.user_id` foreign key to `registered_users` in SQLite schema.
- Added a migration to rebuild the `sessions` table without the user FK.

Why:
- Session creation should be tied to authenticated users and not re-upsert local user records.
- Keeps SQLite as session storage without duplicating user identity data.

### Task 14: Lambda handler scaffolding for API
- Added `src/app/lambda/handler.py` with a Mangum adapter for FastAPI.
- Added `mangum` to `requirements.txt`.

Why:
- Enables deployment of the same FastAPI API to AWS Lambda behind API Gateway.

### Task 15: Switch sessions/turns/modules to DynamoDB
- Removed SQLite dependency from API startup (`init_sqlite_db`).
- Updated `src/app/services/session_service.py` to use DynamoDB tables:
  - `sessions` (PK: `session_id`)
  - `turns` (PK: `session_id`, SK: `turn_index`)
  - `learning_modules` (PK: `module_key`)
- Implemented DynamoDB access helpers and updated turn persistence to use `UpdateItem`.
- Updated `src/app/config.py` to require:
  - `AWS_SESSIONS_TABLE`, `AWS_TURNS_TABLE`, `AWS_MODULES_TABLE`
  - Removed `SQLITE_DB_PATH` requirement

Why:
- Aligns runtime persistence with your AWS DynamoDB plan.
- Removes local SQLite dependency for production deployment.

### Task 16: Authenticated session retrieval with turns
- Implemented `GET /sessions/{session_id}` to return session + turns from DynamoDB.
- Enforced JWT authentication and user ownership check (403 if not owner).
- Added `list_turns_for_session` and `get_session_by_id` in `session_service.py`.

Why:
- Enables user-specific session retrieval for frontend and reporting.

### Task 17: List sessions for current user
- Added `list_sessions_for_user` in `session_service.py` using `user_id_index`.
- Added `GET /sessions` endpoint with JWT auth and optional `limit`.

Why:
- Enables frontend to show a session history list before drilling into session detail.
