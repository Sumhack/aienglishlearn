from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import get_settings


def _db_path() -> Path:
    settings = get_settings()
    db_path = Path(settings.sqlite_db_path).expanduser()
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


@contextmanager
def get_sqlite_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path(), detect_types=sqlite3.PARSE_DECLTYPES)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        yield conn
    finally:
        conn.close()


def init_sqlite_db() -> None:
    schema_path = Path(__file__).resolve().parent / "schema_sqlite.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with get_sqlite_connection() as conn:
        conn.executescript(sql)
        _apply_incremental_migrations(conn)
        conn.commit()


def _apply_incremental_migrations(conn: sqlite3.Connection) -> None:
    _drop_sessions_user_fk(conn)
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(turns)").fetchall()
    }
    migrations = [
        ("prompt_tokens", "ALTER TABLE turns ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0"),
        (
            "completion_tokens",
            "ALTER TABLE turns ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0",
        ),
        ("total_tokens", "ALTER TABLE turns ADD COLUMN total_tokens INTEGER NOT NULL DEFAULT 0"),
        ("model_name", "ALTER TABLE turns ADD COLUMN model_name TEXT"),
        (
            "estimated_cost_usd",
            "ALTER TABLE turns ADD COLUMN estimated_cost_usd REAL NOT NULL DEFAULT 0.0",
        ),
    ]
    for name, statement in migrations:
        if name not in columns:
            conn.execute(statement)


def _drop_sessions_user_fk(conn: sqlite3.Connection) -> None:
    fk_rows = conn.execute("PRAGMA foreign_key_list(sessions)").fetchall()
    has_user_fk = any(row["table"] == "registered_users" for row in fk_rows)
    if not has_user_fk:
        return
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("ALTER TABLE sessions RENAME TO sessions_old;")
    conn.executescript(
        """
        CREATE TABLE sessions (
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
        INSERT INTO sessions (id, user_id, learning_module_id, room_name, statuses, created_at, started_at, ended_at)
        SELECT id, user_id, learning_module_id, room_name, statuses, created_at, started_at, ended_at
        FROM sessions_old;
        DROP TABLE sessions_old;
        """
    )
    conn.execute("PRAGMA foreign_keys = ON;")
