"""JARVIS entry point.

Run modes:
    python -m app.main            # GUI (CustomTkinter) — default
    python -m app.main --voice    # headless continuous voice loop
    python -m app.main --text     # type commands in the terminal

From the project root you can also use the helper: ``python run.py``.
"""

from __future__ import annotations

import argparse
import sys

from app.config.logger import get_logger
from app.config.settings import settings

logger = get_logger(__name__)


def run_ui() -> None:
    try:
        from app.ui.tray_app import JarvisApp
    except RuntimeError as exc:
        print(f"UI unavailable: {exc}")
        print("Falling back to text mode. Use --voice for the voice loop.")
        return run_text()
    JarvisApp().run()


def run_voice() -> None:
    from app.core.assistant import Assistant
    from app.core.voice_engine import VoiceEngine

    assistant = Assistant()
    engine = VoiceEngine(
        assistant,
        on_status=lambda s: print(f"[status] {s}"),
        on_transcript=lambda role, text: print(f"{role}: {text}"),
    )
    if not engine.stt.available:
        print("Speech dependencies missing. Install faster-whisper + sounddevice, or use --text.")
        return
    print(f"{settings.assistant_name} is listening. Say '{settings.wake_word}'. Ctrl+C to quit.")
    engine.start()
    try:
        while engine.running:
            engine._thread.join(0.5)  # type: ignore[union-attr]
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        engine.stop()
        assistant.shutdown()


def run_text() -> None:
    from app.core.assistant import Assistant
    from app.speech.text_to_speech import TextToSpeech

    assistant = Assistant()
    tts = TextToSpeech()
    assistant.on_speak = tts.speak
    print(f"{settings.assistant_name} (text mode). Type 'exit' to quit.")
    try:
        while True:
            text = input("You: ").strip()
            if text.lower() in {"exit", "quit"}:
                break
            if not text:
                continue
            result = assistant.process_text(text)
            print(f"{settings.assistant_name}: {result.get('speech', '')}")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        assistant.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JARVIS AI Desktop Assistant")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--ui", action="store_true", help="Launch the graphical UI (default).")
    group.add_argument("--voice", action="store_true", help="Headless continuous voice loop.")
    group.add_argument("--text", action="store_true", help="Type commands in the terminal.")
    args = parser.parse_args(argv)

    if not settings.is_configured:
        print("⚠ GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")

    if args.voice:
        run_voice()
    elif args.text:
        run_text()
    else:
        run_ui()
    return 0


if __name__ == "__main__":
    sys.exit(main())
