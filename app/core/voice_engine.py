"""Continuous voice loop: wake word -> command -> spoken response.

Runs on a background thread so the UI stays responsive. Flow:

    1. Idle/listening: transcribe short rolling windows, watch for the wake word.
    2. Activated: use any words trailing the wake phrase, or record a dedicated
       command window.
    3. Hand the command to the Assistant, speak the reply, then resume.

State changes are pushed through ``on_state`` so a UI can animate
(idle / listening / wake / thinking / speaking).
"""

from __future__ import annotations

import threading
from typing import Callable

from app.config.logger import get_logger
from app.config.settings import settings
from app.core.assistant import Assistant
from app.speech.speech_to_text import SpeechToText
from app.speech.text_to_speech import TextToSpeech
from app.speech.wake_word import WakeWordDetector

logger = get_logger(__name__)


class VoiceEngine:
    """Background wake-word + command loop wrapping an :class:`Assistant`."""

    def __init__(
        self,
        assistant: Assistant,
        on_status: Callable[[str], None] | None = None,
        on_transcript: Callable[[str, str], None] | None = None,
        on_state: Callable[[str], None] | None = None,
    ) -> None:
        self.assistant = assistant
        self.stt = SpeechToText()
        self.tts = TextToSpeech()
        self.wake = WakeWordDetector(self.stt)
        self.on_status = on_status
        self.on_transcript = on_transcript
        self.on_state = on_state

        # Speak everything the assistant produces.
        self.assistant.on_speak = self.speak

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if not self.stt.available:
            self._status("Speech-to-text unavailable. Install faster-whisper + sounddevice.")
            self._state("error")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="voice-loop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._state("idle")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def speak(self, text: str) -> None:
        if not text:
            return
        self._state("speaking")
        self.tts.speak(text)

    def listen_once(self) -> None:
        """Push-to-talk: capture one command (no wake word) and handle it.

        Safe to call from a UI button on a background thread.
        """
        if not self.stt.available:
            self._status("Speech-to-text unavailable.")
            return
        try:
            self.stt.preload()
            self._status("Listening — speak now...")
            self._state("listening")
            command = self.stt.capture_utterance(max_wait=6.0, silence=settings.command_end_silence)
            if not command:
                self._status("I didn't hear anything.")
                self._state("idle")
                return
            self._handle_command(command)
        except Exception:
            logger.exception("listen_once failed")
            self._status("Microphone error.")
            self._state("error")
        finally:
            if not self.running:
                self._state("idle")

    # -- main loop ----------------------------------------------------------
    def _loop(self) -> None:
        # Preload the model up front so the first command isn't delayed.
        self._status("Warming up speech model...")
        self._state("thinking")
        try:
            self.stt.preload()
        except Exception:
            logger.exception("Model preload failed")

        if settings.require_wake_word:
            self._idle_status()
        else:
            self._status("Listening — just speak. I'll reply when you pause.")
        self._state("listening")

        while not self._stop.is_set():
            try:
                if settings.require_wake_word:
                    self._wake_word_turn()
                else:
                    self._conversation_turn()
            except Exception:
                logger.exception("Voice loop error")
                self._status("Recovered from an error. Still listening.")
                self._state("listening")

    def _conversation_turn(self) -> None:
        """Continuous mode: listen, and respond once the user pauses (~2s)."""
        self._state("listening")
        # Short max_wait so the loop stays responsive to Stop; long end-silence
        # so a natural pause (default 2s) marks the end of the command.
        command = self.stt.capture_utterance(
            max_wait=3.0, silence=settings.command_end_silence
        )
        if not command:
            return
        logger.info("Heard: %s", command)
        self._handle_command(command)
        self._status("Listening — go ahead.")
        self._state("listening")

    def _wake_word_turn(self) -> None:
        """Wake-word mode: wait for 'hey jarvis', then take the command."""
        heard = self.stt.capture_utterance(max_wait=2.0, silence=0.8)
        if not heard:
            return
        logger.info("Heard: %s", heard)
        if not self.wake.contains_wake_word(heard):
            return

        self._state("wake")
        command = self.wake.strip_wake_word(heard)
        if not command:
            self.speak("Yes?")
            self._status("Listening for your command...")
            self._state("listening")
            command = self.stt.capture_utterance(max_wait=6.0, silence=settings.command_end_silence)
        if not command:
            self._idle_status()
            self._state("listening")
            return
        self._handle_command(command)
        self._idle_status()
        self._state("listening")

    def _idle_status(self) -> None:
        self._status(f"Listening for '{settings.wake_word}'...")

    def _handle_command(self, command: str) -> None:
        self._transcript("user", command)
        logger.info("Command: %s", command)
        self._status("Thinking...")
        self._state("thinking")
        result = self.assistant.process_text(command)
        speech = result.get("speech", "")
        if speech:
            self._transcript("assistant", speech)

    # -- callbacks ----------------------------------------------------------
    def _status(self, text: str) -> None:
        logger.info(text)
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:
                logger.debug("on_status failed", exc_info=True)

    def _state(self, state: str) -> None:
        if self.on_state:
            try:
                self.on_state(state)
            except Exception:
                logger.debug("on_state failed", exc_info=True)

    def _transcript(self, role: str, text: str) -> None:
        if self.on_transcript:
            try:
                self.on_transcript(role, text)
            except Exception:
                logger.debug("on_transcript failed", exc_info=True)
