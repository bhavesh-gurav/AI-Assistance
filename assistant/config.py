from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = PROJECT_ROOT.parent


SYSTEM_PROMPT = """
You are a personal desktop assistant running on the user's local Windows machine.
Interpret the user's text as one of three response modes and return only valid JSON.

Supported JSON shapes:

1. Command mode:
{
  "mode": "command",
  "action": "open_application | close_application | open_file | search_file | create_file | delete_file | execute_shell_command | control_system | open_url",
  "parameters": {}
}

2. Coding mode:
{
  "mode": "code",
  "language": "python",
  "filename": "example.py",
  "content": "complete runnable code"
}

3. Chat mode:
{
  "mode": "chat",
  "response": "short helpful answer"
}

Safety:
- Never choose delete_file, shutdown, restart, or risky shell commands unless the user explicitly asked.
- For coding tasks, return complete runnable code.
- Keep responses concise.
""".strip()


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    request_timeout_seconds: int = 45
    speech_timeout_seconds: int = 5
    phrase_time_limit_seconds: int = 12
    listen_forever: bool = True
    output_dir: Path = WORKSPACE_ROOT / "generated_files"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
            gemini_base_url=os.getenv(
                "GEMINI_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta",
            ).rstrip("/"),
            request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "45")),
            speech_timeout_seconds=int(os.getenv("SPEECH_TIMEOUT_SECONDS", "5")),
            phrase_time_limit_seconds=int(os.getenv("PHRASE_TIME_LIMIT_SECONDS", "12")),
            listen_forever=os.getenv("LISTEN_FOREVER", "true").lower() == "true",
            output_dir=Path(os.getenv("OUTPUT_DIR", str(WORKSPACE_ROOT / "generated_files"))),
        )
