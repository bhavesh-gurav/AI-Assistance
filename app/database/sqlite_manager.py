"""Thread-safe SQLite access layer for JARVIS.

Owns the database connection and schema. Higher level services
(``MemoryService``) build on top of the small CRUD helpers exposed here.

Schema
------
- ``users``         : the person(s) using the assistant + work profile
- ``memories``      : arbitrary key/value facts ("remember that ...")
- ``conversations`` : rolling transcript of user/assistant turns
- ``settings``      : persisted preferences (theme, default editor, ...)
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.config.logger import get_logger

logger = get_logger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    work_profile  TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    category    TEXT DEFAULT 'general',
    created_at  TEXT NOT NULL,
    UNIQUE(user_id, key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    role        TEXT NOT NULL,          -- 'user' | 'assistant'
    content     TEXT NOT NULL,
    intent      TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_created
    ON conversations (created_at);
CREATE INDEX IF NOT EXISTS idx_memories_key
    ON memories (key);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteManager:
    """A small, thread-safe wrapper around a single SQLite connection."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # check_same_thread=False because the assistant touches the DB from
        # background worker threads; the RLock serialises all access.
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._create_schema()
        logger.info("SQLite ready at %s", self.db_path)

    # -- low level helpers --------------------------------------------------
    def _create_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def execute(self, query: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(query, tuple(params))
            self._conn.commit()
            return cursor

    def query_one(self, query: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(query, tuple(params)).fetchone()

    def query_all(self, query: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(query, tuple(params)).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- users --------------------------------------------------------------
    def ensure_user(self, name: str = "User") -> int:
        row = self.query_one("SELECT id FROM users ORDER BY id LIMIT 1")
        if row is not None:
            return int(row["id"])
        cursor = self.execute(
            "INSERT INTO users (name, created_at, updated_at) VALUES (?, ?, ?)",
            (name, _now(), _now()),
        )
        return int(cursor.lastrowid)

    def update_user(self, user_id: int, *, name: str | None = None, work_profile: str | None = None) -> None:
        fields, params = [], []
        if name is not None:
            fields.append("name = ?")
            params.append(name)
        if work_profile is not None:
            fields.append("work_profile = ?")
            params.append(work_profile)
        if not fields:
            return
        fields.append("updated_at = ?")
        params.extend([_now(), user_id])
        self.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", params)

    def get_user(self, user_id: int) -> sqlite3.Row | None:
        return self.query_one("SELECT * FROM users WHERE id = ?", (user_id,))

    # -- memories -----------------------------------------------------------
    def upsert_memory(self, user_id: int, key: str, value: str, category: str = "general") -> None:
        self.execute(
            """
            INSERT INTO memories (user_id, key, value, category, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET
                value = excluded.value,
                category = excluded.category,
                created_at = excluded.created_at
            """,
            (user_id, key.strip().lower(), value, category, _now()),
        )

    def get_memory(self, user_id: int, key: str) -> str | None:
        row = self.query_one(
            "SELECT value FROM memories WHERE user_id = ? AND key = ?",
            (user_id, key.strip().lower()),
        )
        return str(row["value"]) if row else None

    def all_memories(self, user_id: int) -> list[sqlite3.Row]:
        return self.query_all(
            "SELECT key, value, category FROM memories WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )

    def delete_memory(self, user_id: int, key: str) -> bool:
        cursor = self.execute(
            "DELETE FROM memories WHERE user_id = ? AND key = ?",
            (user_id, key.strip().lower()),
        )
        return cursor.rowcount > 0

    # -- conversations ------------------------------------------------------
    def add_turn(self, user_id: int, role: str, content: str, intent: str | None = None) -> None:
        self.execute(
            "INSERT INTO conversations (user_id, role, content, intent, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, role, content, intent, _now()),
        )

    def recent_turns(self, user_id: int, limit: int = 12) -> list[sqlite3.Row]:
        rows = self.query_all(
            "SELECT role, content FROM conversations WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        return list(reversed(rows))

    # -- settings -----------------------------------------------------------
    def set_setting(self, key: str, value: str) -> None:
        self.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, _now()),
        )

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return str(row["value"]) if row else default
