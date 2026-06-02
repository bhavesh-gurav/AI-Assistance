"""The JARVIS orchestrator.

Wires together speech, the intent engine, memory and all automation
controllers, and exposes a single :meth:`process_text` pipeline used by both the
voice loop and the UI:

    text -> intent routing -> (confirmation) -> action execution -> speech

The class is transport-agnostic: it never touches the microphone directly so it
can be driven by typed input, the tray UI, or the voice loop.
"""

from __future__ import annotations

import re
import threading
from typing import Any, Callable

from app.ai.model_router import ModelRouter
from app.ai.prompt_manager import PromptManager
from app.automation.browser_controller import BrowserController
from app.automation.cursor_controller import CursorController
from app.automation.desktop_controller import DesktopController
from app.automation.file_manager import FileManager
from app.automation.system_controller import SystemController
from app.config.logger import get_logger
from app.config.settings import settings
from app.core.intent_engine import IntentEngine
from app.core.memory import ConversationMemory, MemoryService
from app.database.sqlite_manager import SQLiteManager

logger = get_logger(__name__)

_AFFIRMATIVE = re.compile(r"\b(yes|yeah|yep|sure|do it|confirm|go ahead|please do|okay|ok)\b", re.I)
_NEGATIVE = re.compile(r"\b(no|nope|cancel|stop|don't|do not|abort|nevermind|never mind)\b", re.I)


class Assistant:
    """High-level assistant brain + executor."""

    def __init__(self) -> None:
        # AI + persistence
        self.prompts = PromptManager()
        self.router = ModelRouter(self.prompts)
        self.db = SQLiteManager(settings.database_path)
        self.memory = MemoryService(self.db)
        self.conversation = ConversationMemory()
        self.conversation.seed(self.memory.recent_turns(settings.conversation_window))

        # Routing + controllers
        self.intent_engine = IntentEngine(self.router)
        self.desktop = DesktopController()
        self.system = SystemController()
        self.browser = BrowserController()
        self.cursor = CursorController()
        self.files = FileManager()

        # Pending dangerous action awaiting "yes".
        self._pending: dict[str, Any] | None = None
        self._lock = threading.Lock()

        # action name -> handler
        self._actions: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "open_application": self.desktop.open_application,
            "close_application": self.desktop.close_application,
            "minimize_all": self.desktop.minimize_all,
            "system_power": self.system.power,
            "volume": self.system.volume,
            "brightness": self.system.brightness,
            "create_folder": self.files.create_folder,
            "create_file": self.files.create_file,
            "rename_path": self.files.rename_path,
            "delete_path": self.files.delete_path,
            "move_path": self.files.move_path,
            "search_files": self.files.search_files,
            "open_path": self.files.open_path,
            "web_search": self.browser.web_search,
            "open_url": self.browser.open_url,
            "remember": self._remember,
            "recall": self._recall,
            "forget": self._forget,
            "generate_code": self._generate_code,
        }

    # -- main pipeline ------------------------------------------------------
    def process_text(self, text: str) -> dict[str, Any]:
        """Run one full turn and return a result dict including a 'speech' field."""
        text = (text or "").strip()
        if not text:
            return {"status": "noop", "speech": ""}
        with self._lock:
            return self._process_locked(text)

    def _process_locked(self, text: str) -> dict[str, Any]:
        # Resolve a pending confirmation first.
        if self._pending is not None:
            return self._resolve_pending(text)

        self.conversation.add("user", text)
        self.memory.log_turn("user", text)

        intent = self.intent_engine.route(
            text, self.conversation.history(), self.memory.context_summary()
        )

        # Dangerous actions: ask before doing.
        if settings.require_confirmation and IntentEngine.needs_confirmation(intent):
            self._pending = intent
            question = intent.get("speech") or "Are you sure?"
            if not question.lower().startswith(("are you", "do you")):
                question = f"Are you sure? {question}"
            self._say_internal(question)
            return {"status": "needs_confirmation", "speech": question, "intent": intent}

        return self._execute(intent)

    def _resolve_pending(self, text: str) -> dict[str, Any]:
        pending, self._pending = self._pending, None
        assert pending is not None
        if _NEGATIVE.search(text) and not _AFFIRMATIVE.search(text):
            speech = "Okay, cancelled."
            self._say_internal(speech)
            return {"status": "cancelled", "speech": speech}
        if _AFFIRMATIVE.search(text):
            return self._execute(pending)
        # Ambiguous reply -> re-ask once by restoring pending state.
        self._pending = pending
        speech = "I need a yes or no. Should I go ahead?"
        self._say_internal(speech)
        return {"status": "needs_confirmation", "speech": speech}

    def _execute(self, intent: dict[str, Any]) -> dict[str, Any]:
        action = intent.get("action")
        params = intent.get("parameters") or {}
        speech = intent.get("speech") or ""

        result: dict[str, Any]
        if action and action in self._actions:
            try:
                exec_result = self._actions[action](self._with_code(intent, params))
            except Exception as exc:  # defensive: never crash the loop
                logger.exception("Action %s failed", action)
                exec_result = {"status": "error", "message": f"That failed: {exc}"}
            # Prefer the model's friendly speech, fall back to the action message.
            spoken = speech or exec_result.get("message", "")
            result = {**exec_result, "speech": spoken, "intent": intent.get("intent")}
        else:
            # GeneralQuestion / chat
            result = {"status": "ok", "speech": speech, "intent": intent.get("intent", "GeneralQuestion")}

        self.conversation.add("assistant", result.get("speech", ""))
        self.memory.log_turn("assistant", result.get("speech", ""), intent.get("intent"))
        self._say_internal(result.get("speech", ""))
        return result

    @staticmethod
    def _with_code(intent: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Inject the model's 'code' block into generate_code parameters."""
        if intent.get("action") == "generate_code" and isinstance(intent.get("code"), dict):
            merged = dict(params)
            merged.setdefault("language", intent["code"].get("language", "python"))
            merged.setdefault("filename", intent["code"].get("filename"))
            merged["content"] = intent["code"].get("content", "")
            return merged
        return params

    # -- coding handler -----------------------------------------------------
    def _generate_code(self, params: dict[str, Any]) -> dict[str, Any]:
        language = str(params.get("language", "python"))
        code = str(params.get("content", "")).strip()
        filename = params.get("filename")
        to_cursor = bool(params.get("to_cursor", True))
        save_file = bool(params.get("save_file", True))

        if not code:
            return {"status": "error", "message": "No code was generated."}

        if to_cursor:
            return self.cursor.write_code(
                code, language=language, filename=filename,
                save_file=save_file, type_into_editor=True,
            )

        # Just save to disk.
        result = self.cursor.write_code(
            code, language=language, filename=filename, save_file=True, type_into_editor=False,
        )
        return result

    # -- memory handlers ----------------------------------------------------
    def _remember(self, params: dict[str, Any]) -> dict[str, Any]:
        key = str(params.get("key", "")).strip()
        value = str(params.get("value", "")).strip()
        if not key or not value:
            return {"status": "error", "message": "I need both what to remember and its value."}
        # Map a couple of well-known keys onto the profile.
        if key.lower() in {"name", "my name"}:
            self.memory.set_name(value)
        elif key.lower() in {"company", "company name", "work", "work profile"}:
            self.memory.set_work_profile(value)
        else:
            self.memory.remember(key, value)
        return {"status": "ok", "message": f"Got it. I'll remember that {key} is {value}."}

    def _recall(self, params: dict[str, Any]) -> dict[str, Any]:
        key = str(params.get("key", "")).strip()
        value = self.memory.recall(key)
        if value is None:
            return {"status": "ok", "message": f"I don't have anything stored for {key}."}
        return {"status": "ok", "message": f"{key} is {value}."}

    def _forget(self, params: dict[str, Any]) -> dict[str, Any]:
        key = str(params.get("key", "")).strip()
        removed = self.memory.forget(key)
        msg = f"Forgotten {key}." if removed else f"I had nothing stored for {key}."
        return {"status": "ok", "message": msg}

    # -- speech hook --------------------------------------------------------
    # The voice loop sets this to the TTS callback; UI may override it too.
    on_speak: Callable[[str], None] | None = None

    def _say_internal(self, text: str) -> None:
        if text and self.on_speak:
            try:
                self.on_speak(text)
            except Exception:
                logger.exception("on_speak callback failed")

    def shutdown(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass
