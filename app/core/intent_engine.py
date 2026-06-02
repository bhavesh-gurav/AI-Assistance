"""Smart command routing.

Turns a raw user utterance into a structured intent dict of the shape:

    {
        "intent": "<category>",
        "action": "<action name or None>",
        "parameters": { ... },
        "speech": "<what to say>",
        "code": { ... }            # only for CodingTask
    }

Strategy: try cheap, deterministic local rules first (instant, no API cost) for
the most common commands. Anything else is delegated to Gemini, which is far
better at nuance, coding requests and open questions.
"""

from __future__ import annotations

import re
from typing import Any

from app.ai.model_router import ModelRouter
from app.ai.providers import LLMError
from app.config.logger import get_logger

logger = get_logger(__name__)


# Actions that must be confirmed before execution.
DANGEROUS_ACTIONS = {"delete_path"}
DANGEROUS_POWER = {"shutdown", "restart"}

# Quick app-name lookups for local "open/close X" matching.
_KNOWN_APPS = [
    "chrome", "edge", "vs code", "vscode", "cursor", "notepad", "calculator",
    "calc", "file explorer", "explorer", "spotify", "discord", "whatsapp",
]


class IntentEngine:
    """Classifies utterances and produces routable intent dicts."""

    def __init__(self, router: ModelRouter) -> None:
        self.router = router

    def route(
        self,
        text: str,
        history: list[dict[str, str]] | None = None,
        memory_context: str = "",
    ) -> dict[str, Any]:
        text = text.strip()
        if not text:
            return self._chat("I didn't catch that.")

        local = self._local_match(text)
        if local is not None:
            logger.debug("Local rule matched: %s", local.get("action"))
            return local

        # No AI model configured at all -> stay in local/offline mode.
        if not self.router.any_available:
            logger.info("No AI model configured; using local-only handling.")
            return self._chat(
                "I don't have an AI model connected right now, so I'm running in local mode. "
                "I can still open apps, control the system, search the web and manage files. "
                "Add a Gemini, OpenAI or DeepSeek API key to your .env to enable full answers."
            )

        # Fall back to the LLM brain (tries each configured model in order).
        try:
            result = self.router.route(text, history or [], memory_context)
            return self._normalise(result)
        except LLMError as exc:
            logger.warning("All AI models unavailable: %s", exc)
            return self._chat(
                "My AI models are all unavailable right now, so I've switched to local mode. "
                "I can still open apps, control the system, search the web and manage files."
            )

    # -- local fast path ----------------------------------------------------
    def _local_match(self, text: str) -> dict[str, Any] | None:
        lowered = text.lower()

        # minimize all windows
        if re.search(r"minimi[sz]e (all|everything)|show desktop", lowered):
            return self._intent("ApplicationControl", "minimize_all", {}, "Minimising all windows.")

        # open / close application
        m = re.match(r"(open|launch|start|close|quit|kill)\s+(.+)", lowered)
        if m:
            verb, rest = m.group(1), m.group(2).strip()
            app = self._find_app(rest)
            if app:
                if verb in {"close", "quit", "kill"}:
                    return self._intent("ApplicationControl", "close_application", {"name": app}, f"Closing {app}.")
                return self._intent("ApplicationControl", "open_application", {"name": app}, f"Opening {app}.")

        # system power
        if re.search(r"\b(shut\s?down|power off)\b", lowered):
            return self._intent("SystemControl", "system_power", {"command": "shutdown"}, "Do you want me to shut down the PC?")
        if re.search(r"\brestart|reboot\b", lowered):
            return self._intent("SystemControl", "system_power", {"command": "restart"}, "Do you want me to restart the PC?")
        if re.search(r"\block( the)? (screen|pc|computer)\b|lock it", lowered):
            return self._intent("SystemControl", "system_power", {"command": "lock"}, "Locking your screen.")
        if re.search(r"\b(sleep|hibernate)\b", lowered):
            return self._intent("SystemControl", "system_power", {"command": "sleep"}, "Going to sleep.")

        # volume
        if re.search(r"volume up|louder|increase volume", lowered):
            return self._intent("SystemControl", "volume", {"command": "up", "amount": 5}, "Volume up.")
        if re.search(r"volume down|quieter|lower volume|decrease volume", lowered):
            return self._intent("SystemControl", "volume", {"command": "down", "amount": 5}, "Volume down.")
        if re.search(r"\b(unmute)\b", lowered):
            return self._intent("SystemControl", "volume", {"command": "unmute"}, "Unmuted.")
        if re.search(r"\b(mute)\b", lowered):
            return self._intent("SystemControl", "volume", {"command": "mute"}, "Muted.")

        # web shortcuts
        if "open youtube" in lowered:
            return self._intent("WebSearch", "web_search", {"engine": "youtube", "query": ""}, "Opening YouTube.")
        if "open github" in lowered:
            return self._intent("WebSearch", "web_search", {"engine": "github", "query": ""}, "Opening GitHub.")
        m = re.match(r"search (google )?(for )?(.+)", lowered)
        if m:
            query = m.group(3).strip()
            return self._intent("WebSearch", "web_search", {"engine": "google", "query": query}, f"Searching for {query}.")

        return None

    # -- helpers ------------------------------------------------------------
    def _find_app(self, text: str) -> str | None:
        for app in sorted(_KNOWN_APPS, key=len, reverse=True):
            if app in text:
                return app
        return None

    @staticmethod
    def _intent(intent: str, action: str | None, params: dict[str, Any], speech: str) -> dict[str, Any]:
        return {"intent": intent, "action": action, "parameters": params, "speech": speech}

    @staticmethod
    def _chat(speech: str) -> dict[str, Any]:
        return {"intent": "GeneralQuestion", "action": None, "parameters": {}, "speech": speech}

    @staticmethod
    def _normalise(result: dict[str, Any]) -> dict[str, Any]:
        result.setdefault("intent", "GeneralQuestion")
        result.setdefault("action", None)
        result.setdefault("parameters", {})
        result.setdefault("speech", "")
        if not isinstance(result.get("parameters"), dict):
            result["parameters"] = {}
        return result

    @staticmethod
    def needs_confirmation(intent: dict[str, Any]) -> bool:
        action = intent.get("action")
        if action in DANGEROUS_ACTIONS:
            return True
        if action == "system_power":
            return str(intent.get("parameters", {}).get("command", "")).lower() in DANGEROUS_POWER
        return False
