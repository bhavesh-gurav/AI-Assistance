"""Speech-to-text using faster-whisper with energy-based (VAD) capture.

Instead of recording fixed-length windows (which leave the mic *off* during the
slow CPU transcription step and chop phrases in half), we open a continuous
audio stream and:

    1. Calibrate the ambient noise floor.
    2. Wait until the user actually starts speaking (energy > threshold).
    3. Buffer until they stop (a short trailing silence) or a max length.
    4. Transcribe only that captured utterance.

This removes the dead gaps, captures whole commands, and avoids the phantom
"thanks / please subscribe" hallucinations Whisper produces from pure silence.
"""

from __future__ import annotations

import math
import queue as _queue
from typing import Optional

from app.config.logger import get_logger
from app.config.settings import settings

logger = get_logger(__name__)

try:
    import numpy as np
    import sounddevice as sd
except Exception:  # pragma: no cover
    np = None  # type: ignore[assignment]
    sd = None  # type: ignore[assignment]

try:
    from faster_whisper import WhisperModel
except Exception:  # pragma: no cover
    WhisperModel = None  # type: ignore[assignment]


# Phrases Whisper commonly hallucinates from silence/noise — ignore them.
_HALLUCINATIONS = {
    "thank you.", "thanks.", "thank you for watching.", "thank you very much.",
    "please subscribe.", "bye.", "you", ".", "thanks for watching.",
    "please pause it again.", "okay.", "so.",
}

_BLOCK_SECONDS = 0.05  # 50 ms analysis blocks


def _rms(block: "np.ndarray") -> float:
    if block.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))


class SpeechToText:
    """Microphone capture + local Whisper transcription."""

    def __init__(self) -> None:
        self.sample_rate = settings.mic_sample_rate
        self._model: Optional["WhisperModel"] = None

        self._device: int | None = settings.input_device  # resolved lazily

    @property
    def available(self) -> bool:
        return WhisperModel is not None and sd is not None and np is not None

    def _candidate_devices(self) -> list[int | None]:
        """Devices to try, in order: configured, system default, then any input."""
        candidates: list[int | None] = []
        if settings.input_device is not None:
            candidates.append(settings.input_device)
        candidates.append(None)  # PortAudio default
        try:
            default_in = sd.default.device[0]
            if isinstance(default_in, int):
                candidates.append(default_in)
            for i, d in enumerate(sd.query_devices()):
                if d.get("max_input_channels", 0) > 0:
                    candidates.append(i)
        except Exception:
            pass
        # De-duplicate preserving order.
        seen, ordered = set(), []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                ordered.append(c)
        return ordered

    def _open_stream(self, callback, block_frames: int):
        """Open an InputStream, falling back across devices on failure."""
        last_exc: Exception | None = None
        for device in self._candidate_devices():
            try:
                stream = sd.InputStream(
                    samplerate=self.sample_rate, channels=1, dtype="float32",
                    blocksize=block_frames, callback=callback, device=device,
                )
                stream.start()
                if self._device != device:
                    logger.info("Using input device: %s", device)
                    self._device = device
                return stream
            except Exception as exc:
                last_exc = exc
                logger.debug("Input device %s unavailable: %s", device, exc)
        raise RuntimeError(f"No working microphone could be opened. Last error: {last_exc}")

    def preload(self) -> None:
        self._ensure_model()

    def _ensure_model(self) -> None:
        if self._model is None:
            if WhisperModel is None:
                raise RuntimeError("faster-whisper is not installed.")
            logger.info("Loading Whisper model '%s' (%s)...", settings.whisper_model_size, settings.whisper_device)
            self._model = WhisperModel(
                settings.whisper_model_size,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
            )

    # -- transcription ------------------------------------------------------
    def transcribe(self, audio: "np.ndarray") -> str:
        self._ensure_model()
        assert self._model is not None
        segments, _info = self._model.transcribe(
            audio, language="en", vad_filter=True, beam_size=1,
        )
        text = " ".join(seg.text for seg in segments).strip()
        if text.lower().strip() in _HALLUCINATIONS:
            logger.debug("Filtered hallucination: %s", text)
            return ""
        return text

    # -- energy-based capture ----------------------------------------------
    def capture_utterance(
        self,
        max_wait: float = 8.0,
        max_len: float = 12.0,
        silence: float = 0.8,
    ) -> str:
        """Wait for speech, capture the full phrase, and return its transcription.

        Returns "" if nothing was spoken within ``max_wait`` seconds.
        """
        if not self.available:
            raise RuntimeError("Speech-to-text dependencies are not installed.")

        sr = self.sample_rate
        block_frames = int(sr * _BLOCK_SECONDS)
        q: "_queue.Queue" = _queue.Queue()

        def callback(indata, _frames, _time, status):  # noqa: ANN001
            if status:
                logger.debug("audio status: %s", status)
            q.put(indata[:, 0].copy())

        collected: list["np.ndarray"] = []
        started = False
        silence_blocks = 0
        silence_needed = max(1, int(silence / _BLOCK_SECONDS))
        max_wait_blocks = int(max_wait / _BLOCK_SECONDS)
        max_len_blocks = int(max_len / _BLOCK_SECONDS)
        waited = 0
        spoken = 0

        # If a callback never fires (driver stall), q.get must not block forever.
        block_timeout = max(1.0, _BLOCK_SECONDS * 40)

        stream = self._open_stream(callback, block_frames)
        try:
            # Calibrate ambient noise from the first few blocks.
            floor_samples = []
            for _ in range(8):
                floor_samples.append(_rms(q.get(timeout=block_timeout)))
            base = sorted(floor_samples)[len(floor_samples) // 2]
            threshold = max(0.010, base * 3.0)
            logger.debug("VAD floor=%.4f threshold=%.4f", base, threshold)

            while True:
                block = q.get(timeout=block_timeout)
                level = _rms(block)

                if not started:
                    waited += 1
                    if level >= threshold:
                        started = True
                        collected.append(block)
                    elif waited >= max_wait_blocks:
                        return ""  # nobody spoke
                else:
                    collected.append(block)
                    spoken += 1
                    if level < threshold:
                        silence_blocks += 1
                        if silence_blocks >= silence_needed:
                            break
                    else:
                        silence_blocks = 0
                    if spoken >= max_len_blocks:
                        break
        except _queue.Empty:
            logger.warning("Microphone produced no audio (driver stall).")
            return ""
        except Exception as exc:
            logger.exception("Audio capture failed")
            raise RuntimeError(f"Microphone capture failed: {exc}") from exc
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        if not collected:
            return ""
        audio = np.concatenate(collected).astype("float32")
        # Guard against ultra-short blips.
        if audio.size < int(sr * 0.25):
            return ""
        return self.transcribe(audio)

    # -- diagnostics --------------------------------------------------------
    def record_blocks(self, seconds: float) -> "np.ndarray":
        """Stream-record for ``seconds`` using a timeout-guarded callback."""
        sr = self.sample_rate
        block_frames = int(sr * _BLOCK_SECONDS)
        q: "_queue.Queue" = _queue.Queue()

        def callback(indata, _frames, _time, status):  # noqa: ANN001
            q.put(indata[:, 0].copy())

        collected: list["np.ndarray"] = []
        n_blocks = max(1, int(seconds / _BLOCK_SECONDS))
        stream = self._open_stream(callback, block_frames)
        try:
            for _ in range(n_blocks):
                collected.append(q.get(timeout=2.0))
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        return np.concatenate(collected).astype("float32") if collected else np.zeros(1, dtype="float32")

    def mic_level(self, seconds: float = 1.0) -> float:
        """Return the RMS level of a short recording (for mic testing)."""
        return _rms(self.record_blocks(seconds))
