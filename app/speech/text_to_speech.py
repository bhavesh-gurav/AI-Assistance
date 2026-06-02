"""Text-to-speech using pyttsx3 (offline, cross-platform).

On Windows, pyttsx3 drives the SAPI5 engine through COM. COM objects are
*thread-affine*: the engine must be created and used on the **same** thread, and
that thread must have COM initialised. The assistant speaks from background
threads (voice loop / UI worker), so we run a single dedicated speech thread
that owns the engine and processes a queue. ``speak`` blocks until the phrase
finishes so the microphone doesn't record the assistant's own voice.
"""

from __future__ import annotations

import queue
import threading

from app.config.logger import get_logger
from app.config.settings import settings

logger = get_logger(__name__)

try:
    import pyttsx3
except Exception:  # pragma: no cover
    pyttsx3 = None  # type: ignore[assignment]


class TextToSpeech:
    """Speak text aloud on a dedicated, COM-initialised worker thread."""

    _STOP = object()

    def __init__(self) -> None:
        self._queue: "queue.Queue" = queue.Queue()
        self._ready = threading.Event()
        self._ok = False
        if pyttsx3 is None:
            logger.warning("pyttsx3 not installed; speech will be printed instead.")
            self._ready.set()
            return
        self._thread = threading.Thread(target=self._run, name="tts", daemon=True)
        self._thread.start()
        # Wait briefly for the engine to come up.
        self._ready.wait(timeout=10)

    @property
    def available(self) -> bool:
        return self._ok

    def _run(self) -> None:
        # Initialise COM for this thread (Windows/SAPI5).
        try:
            import pythoncom  # type: ignore

            pythoncom.CoInitialize()
        except Exception:
            pass

        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", settings.tts_rate)
            if settings.tts_voice:
                self._select_voice(engine, settings.tts_voice)
            self._ok = True
        except Exception:
            logger.exception("Failed to initialise TTS engine")
            self._ready.set()
            return
        finally:
            self._ready.set()

        while True:
            item = self._queue.get()
            if item is self._STOP:
                break
            text, done = item
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception:
                logger.exception("TTS playback failed")
                print(f"[{settings.assistant_name}] {text}")
            finally:
                if done is not None:
                    done.set()

        try:
            engine.stop()
        except Exception:
            pass

    @staticmethod
    def _select_voice(engine, needle: str) -> None:
        try:
            for voice in engine.getProperty("voices"):
                name = (voice.name or "").lower()
                vid = (voice.id or "").lower()
                if needle.lower() in name or needle.lower() in vid:
                    engine.setProperty("voice", voice.id)
                    return
        except Exception:
            logger.debug("Voice selection failed", exc_info=True)

    def speak(self, text: str, block: bool = True) -> None:
        if not text:
            return
        if not self._ok:
            print(f"[{settings.assistant_name}] {text}")
            return
        done = threading.Event() if block else None
        self._queue.put((text, done))
        if done is not None:
            done.wait(timeout=60)

    def shutdown(self) -> None:
        if self._ok:
            self._queue.put(self._STOP)
