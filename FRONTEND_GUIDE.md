# Frontend Integration Guide

## Goal
Build frontend in a separate repo and connect it to this backend for:
1. Start session via API
2. Join LiveKit room with returned token
3. Talk to agent

## Recommended Repos
1. `voice-agent-backend` (this repo)
2. `voice-agent-frontend` (new React repo)

## Backend Prerequisites
Run both backend API and worker:

```bash
# terminal 1: API
source .venv/bin/activate
PYTHONPATH=src uvicorn app.main:app --reload

# terminal 2: worker
source .venv/bin/activate
PYTHONPATH=src python3 -m app.livekit.agent dev
```

Default API URL: `http://127.0.0.1:8000`

## API Contract Used By Frontend

### `POST /sessions/start`
Request body:

```json
{
  "name": "Suman",
  "email": "suman@example.com",
  "contact": "+919999999999",
  "module_name": "behavioral_interview",
  "level": "intermediate"
}
```

Response body:

```json
{
  "session_id": "uuid",
  "user_id": "uuid",
  "learning_module_id": "uuid",
  "room_name": "session-uuid",
  "token": "jwt",
  "livekit_url": "wss://....livekit.cloud",
  "status": "active",
  "created_at": "iso-datetime"
}
```

## Frontend Environment Variables

```env
VITE_BACKEND_URL=http://127.0.0.1:8000
```

## Minimal Frontend Flow
1. User fills form (`name`, `email`, `contact`, `level`, optional `module_name`)
2. Frontend calls `POST /sessions/start`
3. Frontend stores `session_id` for UI state
4. Frontend joins LiveKit with `livekit_url + token`
5. Agent joins room automatically and starts voice interaction

## LiveKit Client Setup (React)
Install:

```bash
npm i livekit-client
```

Example:

```ts
import { Room } from "livekit-client";

export async function startAndJoin(form: {
  name: string;
  email: string;
  contact: string;
  level: string;
  module_name?: string;
}) {
  const res = await fetch(`${import.meta.env.VITE_BACKEND_URL}/sessions/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...form,
      module_name: form.module_name ?? "behavioral_interview",
    }),
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
3. `Report` (later): final score/feedback

## Important Notes
1. Use a fresh `/sessions/start` call for each new attempt.
2. Do not reuse old tokens across attempts.
3. If agent does not join, verify worker terminal is running.
4. Conversation currently starts and works, but strict 5-question sequencing is not implemented yet.

## Quick Debug Checklist
1. `GET /health` returns 200
2. `POST /sessions/start` returns token and room name
3. Frontend connects with returned token
4. Worker logs show job pickup and agent join
