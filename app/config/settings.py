"""Centralised configuration for the JARVIS assistant.

All tunables are read from environment variables (optionally loaded from a
`.env` file at the project root) so the same code runs across machines without
edits. Import :data:`settings` anywhere you need configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    # Optional: load variables from a local .env file when present.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional at runtime.
    pass


# Project layout ------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parents[1]          # .../app
PROJECT_ROOT = APP_DIR.parent                          # project root
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
GENERATED_DIR = PROJECT_ROOT / "generated_files"

for _directory in (DATA_DIR, LOG_DIR, GENERATED_DIR):
    _directory.mkdir(parents=True, exist_ok=True)


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _get_optional_int(name: str) -> int | None:
    """Return an int from env, or None if unset/blank (used for device index)."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class Settings:
    """Immutable runtime configuration."""

    # --- Gemini / AI ---
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip())
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-1.5-pro").strip())
    gemini_base_url: str = field(
        default_factory=lambda: os.getenv(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/")
    )
    request_timeout_seconds: int = field(default_factory=lambda: _get_int("REQUEST_TIMEOUT_SECONDS", 60))
    temperature: float = field(default_factory=lambda: _get_float("GEMINI_TEMPERATURE", 0.3))

    # --- Speech ---
    wake_word: str = field(default_factory=lambda: os.getenv("WAKE_WORD", "hey jarvis").strip().lower())
    assistant_name: str = field(default_factory=lambda: os.getenv("ASSISTANT_NAME", "Jarvis").strip())
    whisper_model_size: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL_SIZE", "base.en").strip())
    whisper_device: str = field(default_factory=lambda: os.getenv("WHISPER_DEVICE", "cpu").strip())
    whisper_compute_type: str = field(
        default_factory=lambda: os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip()
    )
    tts_rate: int = field(default_factory=lambda: _get_int("TTS_RATE", 185))
    tts_voice: str = field(default_factory=lambda: os.getenv("TTS_VOICE", "").strip())
    mic_record_seconds: float = field(default_factory=lambda: _get_float("MIC_RECORD_SECONDS", 5.0))
    mic_sample_rate: int = field(default_factory=lambda: _get_int("MIC_SAMPLE_RATE", 16000))
    input_device: int | None = field(default_factory=lambda: _get_optional_int("INPUT_DEVICE"))

    # --- Behaviour ---
    require_confirmation: bool = field(default_factory=lambda: _get_bool("REQUIRE_CONFIRMATION", True))
    require_wake_word: bool = field(default_factory=lambda: _get_bool("REQUIRE_WAKE_WORD", False))
    command_end_silence: float = field(default_factory=lambda: _get_float("COMMAND_END_SILENCE", 2.0))
    conversation_window: int = field(default_factory=lambda: _get_int("CONVERSATION_WINDOW", 12))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").strip().upper())

    # --- Paths ---
    database_path: Path = field(
        default_factory=lambda: Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "jarvis.db")))
    )
    generated_dir: Path = field(
        default_factory=lambda: Path(os.getenv("OUTPUT_DIR", str(GENERATED_DIR)))
    )

    @property
    def is_configured(self) -> bool:
        """Whether a Gemini API key has been provided."""
        return bool(self.gemini_api_key)


# A single shared instance the rest of the app imports.
settings = Settings()
