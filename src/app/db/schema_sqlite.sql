CREATE TABLE IF NOT EXISTS registered_users (
    id TEXT PRIMARY KEY,
    fullname TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    contact TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learning_modules (
    id TEXT PRIMARY KEY,
    module_name TEXT NOT NULL,
    levels TEXT NOT NULL,
    descriptions TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    learning_module_id TEXT NOT NULL,
    room_name TEXT NOT NULL,
    statuses TEXT NOT NULL CHECK (statuses IN ('active', 'completed', 'failed')),
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    FOREIGN KEY (learning_module_id) REFERENCES learning_modules(id)
);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL CHECK (turn_index >= 1),
    question_text TEXT NOT NULL,
    user_transcript TEXT NOT NULL,
    agent_reply TEXT NOT NULL,
    duration_ms INTEGER CHECK (duration_ms >= 0),
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    model_name TEXT,
    estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, turn_index),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_learning_module_id ON sessions(learning_module_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(statuses);
CREATE INDEX IF NOT EXISTS idx_turns_session_turn ON turns(session_id, turn_index);
