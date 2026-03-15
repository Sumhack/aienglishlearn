create extension if not exists pgcrypto;

create table if not exists public.registered_users (
    id uuid primary key default gen_random_uuid(),
    fullname text not null,
    email text not null unique,
    contact text not null unique,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.learning_modules (
    id uuid primary key default gen_random_uuid(),
    module_name text not null,
    levels text not null,
    descriptions text,
    is_active boolean not null default true,
    config_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.sessions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.registered_users(id) on delete cascade,
    learning_module_id uuid not null references public.learning_modules(id),
    room_name text not null,
    statuses text not null check (statuses in ('active', 'completed', 'failed')),
    created_at timestamptz not null default now(),
    started_at timestamptz,
    ended_at timestamptz
);

create table if not exists public.turns (
    id uuid primary key default gen_random_uuid(),
    session_id uuid not null references public.sessions(id) on delete cascade,
    turn_index int not null check (turn_index >= 1),
    question_text text not null,
    user_transcript text not null,
    agent_reply text not null,
    duration_ms int check (duration_ms >= 0),
    created_at timestamptz not null default now(),
    unique (session_id, turn_index)
);

create index if not exists idx_sessions_user_id on public.sessions(user_id);
create index if not exists idx_sessions_learning_module_id on public.sessions(learning_module_id);
create index if not exists idx_sessions_status on public.sessions(statuses);
create index if not exists idx_turns_session_turn on public.turns(session_id, turn_index);
