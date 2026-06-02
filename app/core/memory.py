"""Memory subsystem.

Two collaborating classes:

``ConversationMemory``
    Fast in-process rolling window of the latest turns, used to give Gemini
    short-term context without a DB round trip on every message.

``MemoryService``
    Durable, SQLite-backed long-term memory: the user profile, preferences and
    explicit "remember that ..." facts, plus a persisted transcript.
"""

from __future__ import annotations

from collections import deque
from typing import Deque

from app.config.logger import get_logger
from app.config.settings import settings
from app.database.sqlite_manager import SQLiteManager

logger = get_logger(__name__)


class ConversationMemory:
    """Bounded short-term memory of recent conversation turns."""

    def __init__(self, window: int | None = None) -> None:
        self.window = window or settings.conversation_window
        self._turns: Deque[dict[str, str]] = deque(maxlen=self.window)

    def add(self, role: str, content: str) -> None:
        if content:
            self._turns.append({"role": role, "content": content})

    def history(self) -> list[dict[str, str]]:
        return list(self._turns)

    def clear(self) -> None:
        self._turns.clear()

    def seed(self, turns: list[dict[str, str]]) -> None:
        """Pre-fill the window, e.g. from the persisted transcript on startup."""
        for turn in turns[-self.window:]:
            self._turns.append(turn)


class MemoryService:
    """Long-term, persistent memory backed by SQLite."""

    def __init__(self, db: SQLiteManager) -> None:
        self.db = db
        self.user_id = db.ensure_user()

    # -- profile ------------------------------------------------------------
    def set_name(self, name: str) -> None:
        self.db.update_user(self.user_id, name=name)

    def set_work_profile(self, profile: str) -> None:
        self.db.update_user(self.user_id, work_profile=profile)

    def get_profile(self) -> dict[str, str]:
        row = self.db.get_user(self.user_id)
        if not row:
            return {}
        return {
            "name": row["name"] or "",
            "work_profile": row["work_profile"] or "",
        }

    # -- arbitrary facts ----------------------------------------------------
    def remember(self, key: str, value: str, category: str = "general") -> None:
        self.db.upsert_memory(self.user_id, key, value, category)
        logger.info("Remembered %s -> %s", key, value)

    def recall(self, key: str) -> str | None:
        return self.db.get_memory(self.user_id, key)

    def forget(self, key: str) -> bool:
        return self.db.delete_memory(self.user_id, key)

    def all_facts(self) -> dict[str, str]:
        return {row["key"]: row["value"] for row in self.db.all_memories(self.user_id)}

    # -- preferences (stored as namespaced facts) ---------------------------
    def set_preference(self, name: str, value: str) -> None:
        self.remember(f"pref:{name}", value, category="preference")

    def get_preference(self, name: str, default: str | None = None) -> str | None:
        return self.recall(f"pref:{name}") or default

    # -- transcript ---------------------------------------------------------
    def log_turn(self, role: str, content: str, intent: str | None = None) -> None:
        self.db.add_turn(self.user_id, role, content, intent)

    def recent_turns(self, limit: int = 12) -> list[dict[str, str]]:
        return [
            {"role": row["role"], "content": row["content"]}
            for row in self.db.recent_turns(self.user_id, limit)
        ]

    def context_summary(self) -> str:
        """A compact text block describing what we know about the user."""
        profile = self.get_profile()
        facts = self.all_facts()
        lines: list[str] = []
        if profile.get("name"):
            lines.append(f"User name: {profile['name']}")
        if profile.get("work_profile"):
            lines.append(f"Work profile: {profile['work_profile']}")
        for key, value in facts.items():
            pretty = key.replace("pref:", "preference - ")
            lines.append(f"{pretty}: {value}")
        return "\n".join(lines) if lines else "No stored facts yet."
