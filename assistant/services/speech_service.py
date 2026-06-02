from __future__ import annotations

import asyncio

import pyttsx3
import speech_recognition as sr

from config import Settings
from utils.logger import get_logger


logger = get_logger(__name__)


class SpeechService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        self.tts_engine = pyttsx3.init()

    async def listen(self) -> str:
        return await asyncio.to_thread(self._listen_sync)

    async def speak(self, text: str) -> None:
        if not text:
            return
        await asyncio.to_thread(self._speak_sync, text)

    def _listen_sync(self) -> str:
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            print("Listening...")
            try:
                audio = self.recognizer.listen(
                    source,
                    timeout=self.settings.speech_timeout_seconds,
                    phrase_time_limit=self.settings.phrase_time_limit_seconds,
                )
            except sr.WaitTimeoutError:
                return ""

        try:
            return self.recognizer.recognize_google(audio).strip()
        except sr.UnknownValueError:
            logger.info("Speech was not understood")
            return ""
        except sr.RequestError as exc:
            logger.exception("Speech recognition service failed")
            raise RuntimeError(f"Speech recognition failed: {exc}") from exc

    def _speak_sync(self, text: str) -> None:
        self.tts_engine.say(text)
        self.tts_engine.runAndWait()
