"""Speech package: STT, TTS and wake-word detection."""

from app.speech.speech_to_text import SpeechToText
from app.speech.text_to_speech import TextToSpeech
from app.speech.wake_word import WakeWordDetector

__all__ = ["SpeechToText", "TextToSpeech", "WakeWordDetector"]
