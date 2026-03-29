# Frontend Integration Guide (Current Backend)

## Goal
Build frontend in a separate repo and connect it to this backend for:
1. Register/login
2. Fetch personas
3. Start session with selected persona
4. Join LiveKit room with returned token
5. Talk to agent

## Recommended Repos
1. `voice-agent-backend` (this repo)
2. `voice-agent-frontend` (new React repo)

## Backend Prerequisites (Local)
Run both backend API and worker locally:

```bash
# terminal 1: API
source .venv/bin/activate
PYTHONPATH=src uvicorn app.main:app --reload

# terminal 2: worker
source .venv/bin/activate
PYTHONPATH=src python3 -m app.livekit.agent dev
```

<!-- Default API URL: `http://127.0.0.1:8000` -->

## Backend Prerequisites (Deployed)
API is deployed on Lambda + API Gateway, worker runs on EC2.
- API base URL: `https://fwvekndmn6.execute-api.ap-south-1.amazonaws.com`
- Worker is always-on via systemd on EC2.

## API Contract Used By Frontend

### `POST /auth/register`
Request body:

```json
{
  "name": "Suman",
  "email": "suman@example.com",
  "password": "Password123"
}
```

Response body:

```json
{
  "user_id": "uuid",
  "name": "Suman",
  "email": "suman@example.com",
  "token": "jwt",
  "expires_in": 3600
}
```

### `POST /auth/login`
Request body:

```json
{
  "email": "suman@example.com",
  "password": "Password123"
}
```

Response body:

```json
{
  "user_id": "uuid",
  "name": "Suman",
  "email": "suman@example.com",
  "token": "jwt",
  "expires_in": 3600
}
```

### `GET /personas`
Response body:

```json
[
  {
    "module_key": "school_mentor",
    "module_name": "school_mentor",
    "display_name": "Ms. Ananya Rao",
    "role": "School teacher / Academic mentor",
    "tone": "Encouraging but structured",
    "short_description": "Helps students express thoughts clearly in simple spoken English.",
    "is_active": true,
    "created_at": "2026-03-17T00:00:00Z",
    "updated_at": "2026-03-17T00:00:00Z"
  }
]
```

### `POST /sessions/start` (Bearer token required)
Request body:

```json
{
  "persona": "school_mentor"
}
```

Response body:

```json
{
  "session_id": "uuid",
  "user_id": "uuid",
  "persona": "school_mentor",
  "room_name": "session-uuid",
  "token": "jwt",
  "livekit_url": "wss://....livekit.cloud",
  "status": "active",
  "created_at": "iso-datetime"
}
```

### `GET /sessions` (Bearer token required)
Response body:

```json
[
  {
    "session_id": "uuid",
    "persona": "school_mentor",
    "room_name": "session-uuid",
    "status": "active",
    "created_at": "2026-03-25T12:00:00Z",
    "started_at": "2026-03-25T12:00:00Z",
    "ended_at": null,
    "overall_score": 74,
    "fluency_score": 70,
    "grammar_score": 72,
    "vocabulary_score": 76,
    "clarity_score": 78,
    "report_status": "ready"
  }
]
```

### `GET /sessions/{id}` (Bearer token required)
Response body:

```json
{
  "session_id": "uuid",
  "user_id": "uuid",
  "persona": "school_mentor",
  "room_name": "session-uuid",
  "status": "completed",
  "created_at": "2026-03-25T12:00:00Z",
  "started_at": "2026-03-25T12:00:00Z",
  "ended_at": "2026-03-25T12:10:00Z",
  "overall_score": 74,
  "fluency_score": 70,
  "grammar_score": 72,
  "vocabulary_score": 76,
  "clarity_score": 78,
  "report_status": "ready",
  "summary": {
    "strengths": ["Clear structure", "Good pacing"],
    "improvements": ["Reduce fillers", "Be more concise"],
    "practice_tasks": ["Answer in STAR format"],
    "corrections": [{"original": "...", "suggested": "..."}],
    "notes": "Short summary"
  }
}
```

## Frontend Environment Variables

```env
VITE_BACKEND_URL=http://127.0.0.1:8000
```

## Minimal Frontend Flow
1. User registers or logs in → save JWT
2. Frontend calls `GET /personas` to show persona cards
3. User selects persona
4. Frontend calls `POST /sessions/start` with `Authorization: Bearer <JWT>`
5. Frontend stores `session_id` for UI state
6. Frontend joins LiveKit with `livekit_url + token`
7. Agent joins room automatically and starts voice interaction
8. User clicks “Get Report” → `GET /sessions/{id}` to fetch summary
9. Sessions history → `GET /sessions` for list + scores

## LiveKit Client Setup (React)
Install:

```bash
npm i livekit-client
```

Example:

```ts
import { Room } from "livekit-client";

export async function startAndJoin(persona: string, jwt: string) {
  const res = await fetch(`${import.meta.env.VITE_BACKEND_URL}/sessions/start`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${jwt}`,
    },
    body: JSON.stringify({ persona }),
  });

  if (!res.ok) throw new Error(`start session failed: ${res.status}`);
  const data = await res.json();

  const room = new Room();
  await room.connect(data.livekit_url, data.token);

  // Optional: enable mic after connect
  await room.localParticipant.setMicrophoneEnabled(true);

  return { room, session: data };
}
```

## Suggested UI Screens
1. `Home`: form + “Start Session”
2. `Call`: connected room, mic state, transcript/event placeholders
3. `Report`: fetch `GET /sessions/{id}` for summary + scores
4. `History`: use `GET /sessions` for session list + scores

## Important Notes
1. Use a fresh `/sessions/start` call for each new attempt.
2. Do not reuse old LiveKit room tokens across attempts.
3. If agent does not join, verify worker is running on EC2.
4. Conversation is free-flow; max turns is enforced (default 10).

## Quick Debug Checklist
1. `GET /health` returns 200
2. `GET /personas` returns persona list
3. `POST /sessions/start` returns token and room name (with JWT)
4. Frontend connects with returned token
5. Worker logs show job pickup and agent join
