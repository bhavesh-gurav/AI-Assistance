"""Pluggable LLM providers.

Each provider wraps a single model backend (Gemini, OpenAI, DeepSeek, ...)
behind the common :class:`LLMProvider` interface so the :class:`ModelRouter`
can try them in order and fall back automatically.
"""

from app.ai.providers.base import LLMError, LLMProvider, ProviderStatus
from app.ai.providers.gemini_provider import GeminiProvider
from app.ai.providers.openai_provider import OpenAICompatibleProvider

__all__ = [
    "LLMError",
    "LLMProvider",
    "ProviderStatus",
    "GeminiProvider",
    "OpenAICompatibleProvider",
]
