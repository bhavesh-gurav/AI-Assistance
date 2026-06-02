"""Wake-word detection ("Hey Jarvis").

A lightweight, dependency-free detector built on top of the local Whisper STT:
it transcribes short rolling audio windows and checks whether the configured
wake phrase appears. Any words spoken *after* the wake phrase in the same
breath are returned as the command, so "Hey Jarvis, open Chrome" works in one
utterance.

For production deployments needing always-on, low-power detection you can later
swap this for openWakeWord or Porcupine behind the same interface.
"""

from __future__ import annotations

import re

from app.config.logger import get_logger
from app.config.settings import settings
from app.speech.speech_to_text import SpeechToText

logger = get_logger(__name__)


class WakeWordDetector:
    """Detects the wake phrase and extracts any trailing command."""

    def __init__(self, stt: SpeechToText, wake_word: str | None = None) -> None:
        self.stt = stt
        self.wake_word = (wake_word or settings.wake_word).lower().strip()
        # Tolerate common mishearings of "jarvis".
        self._variants = [
            self.wake_word,
            self.wake_word.replace("hey ", "hi "),
            "jarvis",
            "jervis",
            "travis",
        ]

    def contains_wake_word(self, text: str) -> bool:
        lowered = text.lower()
        return any(variant and variant in lowered for variant in self._variants)

    def strip_wake_word(self, text: str) -> str:
        """Remove the wake phrase and return whatever command followed it."""
        lowered = text.lower()
        for variant in sorted(self._variants, key=len, reverse=True):
            idx = lowered.find(variant)
            if idx != -1:
                tail = text[idx + len(variant):]
                return re.sub(r"^[\s,.:;-]+", "", tail).strip()
        return text.strip()

    def wait_for_wake(self, window_seconds: float = 3.0) -> str | None:
        """Block until the wake word is heard.

        Returns the trailing command (possibly empty string) when detected, or
        ``None`` if a single listen attempt heard nothing of interest. The
        caller loops on this.
        """
        try:
            heard = self.stt.capture_utterance(max_wait=window_seconds)
        except Exception as exc:
            logger.debug("Wake listen error: %s", exc)
            return None

        if not heard:
            return None

        logger.debug("Heard: %s", heard)
        if self.contains_wake_word(heard):
            return self.strip_wake_word(heard)
        return None
