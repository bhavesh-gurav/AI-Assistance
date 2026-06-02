"""Text-to-speech using pyttsx3 (offline, cross-platform).

On Windows, pyttsx3 drives the SAPI5 engine through COM. COM objects are
*thread-affine*: the engine must be created and used on the **same** thread, and
that thread must have COM initialised. The assistant speaks from background
threads (voice loop / UI worker), so we run a single dedicated speech thread
that owns the engine and processes a queue. ``speak`` blocks until the phrase
finishes so the microphone doesn't record the assistant's own voice.

Why a fresh engine per phrase: SAPI5 has a long-standing bug where reusing one
pyttsx3 engine across repeated ``runAndWait()`` calls speaks the first phrase
and then silently hangs (the internal run-loop never restarts). Building a new
engine for each utterance — and forcing pyttsx3 to forget the cached one with a
GC pass — keeps the assistant talking on every turn.
"""

from __future__ import annotations

import gc
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

        # Verify we can build an engine at least once before reporting ready.
        try:
            probe = self._make_engine()
            self._dispose(probe)
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
                self._speak_once(text)
            except Exception:
                logger.exception("TTS playback failed")
                print(f"[{settings.assistant_name}] {text}")
            finally:
                if done is not None:
                    done.set()

    def _speak_once(self, text: str) -> None:
        """Speak a single phrase with its own short-lived engine."""
        engine = self._make_engine()
        try:
            engine.say(text)
            engine.runAndWait()
        finally:
            self._dispose(engine)

    @staticmethod
    def _make_engine():
        engine = pyttsx3.init()
        engine.setProperty("rate", settings.tts_rate)
        if settings.tts_voice:
            TextToSpeech._select_voice(engine, settings.tts_voice)
        return engine

    @staticmethod
    def _dispose(engine) -> None:
        """Tear an engine down so the next ``pyttsx3.init()`` returns a fresh one.

        pyttsx3 caches engines in a weak-value registry keyed by driver name, so
        a lingering reference would hand us the same (stuck) engine again. We
        stop it, drop the reference and force a GC pass to clear the registry.
        """
        try:
            engine.stop()
        except Exception:
            pass
        del engine
        gc.collect()

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
