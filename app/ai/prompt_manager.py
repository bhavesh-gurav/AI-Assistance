"""Builds prompts and message payloads for Gemini.

The model is instructed to always reply with a single JSON object that the
:class:`~app.core.intent_engine.IntentEngine` can route. Keeping the contract
in one place makes it easy to extend with new intents/actions later.
"""

from __future__ import annotations

import json
from typing import Any

from app.config.settings import settings

# Canonical intent categories understood by the router.
INTENTS = [
    "ApplicationControl",
    "SystemControl",
    "CodingTask",
    "GeneralQuestion",
    "FileOperation",
    "WebSearch",
    "MemoryTask",
]

# Actions the assistant can execute, grouped by intent. Kept in the prompt so
# the model knows exactly what verbs/parameters are valid.
ACTION_REFERENCE = """
ApplicationControl:
  - open_application      { "name": "<chrome|edge|vscode|cursor|notepad|calculator|file explorer|spotify|discord|whatsapp|...>" }
  - close_application     { "name": "<app>" }
  - minimize_all          { }

SystemControl:
  - system_power          { "command": "<shutdown|restart|lock|sleep>" }      # dangerous -> confirmation
  - volume                { "command": "<up|down|mute|unmute>", "amount": <int optional> }
  - brightness            { "level": <0-100> }

CodingTask:
  - generate_code         { "language": "<csharp|dotnet|angular|typescript|sql|python|javascript|html|css>",
                            "filename": "<suggested file name>",
                            "to_cursor": <true|false>,     # type code straight into Cursor
                            "save_file": <true|false> }    # also save to generated_files

FileOperation:
  - create_folder         { "path": "<path or name>" }
  - create_file           { "path": "<path or name>", "content": "<optional>" }
  - rename_path           { "path": "<src>", "new_name": "<name>" }
  - delete_path           { "path": "<path>" }            # dangerous -> confirmation
  - move_path             { "path": "<src>", "destination": "<dst>" }
  - search_files          { "query": "<text>", "root": "<optional folder>" }
  - open_path             { "path": "<file or folder, e.g. Downloads>" }

WebSearch:
  - web_search            { "engine": "<google|youtube|github|stackoverflow>", "query": "<text>" }
  - open_url              { "url": "<https url>" }

MemoryTask:
  - remember              { "key": "<short key>", "value": "<value>" }
  - recall                { "key": "<short key>" }
  - forget                { "key": "<short key>" }

GeneralQuestion:
  - (no action) just answer in the "speech" field.
""".strip()


class PromptManager:
    """Produces the system prompt and per-turn message payloads."""

    def build_system_prompt(self, memory_context: str = "") -> str:
        return f"""
You are {settings.assistant_name}, a voice-controlled AI desktop assistant running locally on the user's Windows PC.
You understand the user's intent and respond with EXACTLY ONE valid JSON object and nothing else.

JSON shape:
{{
  "intent": one of {INTENTS},
  "action": "<an action name from the reference below, or null for GeneralQuestion>",
  "parameters": {{ ... }},
  "speech": "<a short, natural sentence to speak back to the user>",
  "code": {{ "language": "...", "filename": "...", "content": "..." }}   // ONLY for CodingTask, else omit
}}

Action reference (choose the best match):
{ACTION_REFERENCE}

Rules:
- Always include "intent" and "speech". Keep "speech" concise and friendly, like a helpful assistant.
- For CodingTask, put complete, runnable, production-quality code in code.content (no markdown fences) and a brief "speech" like "Here's your C# repository pattern.".
- For dangerous actions (system_power shutdown/restart, delete_path) still return the action; the app handles confirmation.
- Prefer ApplicationControl/SystemControl/FileOperation/WebSearch over GeneralQuestion when the user clearly wants an action.
- For pure questions or chit-chat, use intent "GeneralQuestion", action null, and answer in "speech".
- Never include explanations outside the JSON object.

What you know about this user:
{memory_context or "Nothing yet."}
""".strip()

    def build_contents(self, history: list[dict[str, str]], user_text: str) -> list[dict[str, Any]]:
        """Convert rolling history + the new message into Gemini `contents`."""
        contents: list[dict[str, Any]] = []
        for turn in history:
            role = "model" if turn.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": turn.get("content", "")}]})
        contents.append({"role": "user", "parts": [{"text": user_text}]})
        return contents

    def coding_prompt(self, request: str, language: str) -> str:
        """A focused prompt for code-only generation (used by CursorController flows)."""
        return (
            f"Write complete, production-ready {language} code for the following request. "
            f"Return only the code with no markdown fences and no commentary.\n\nRequest: {request}"
        )

    @staticmethod
    def to_json(data: dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False)
