"""Routes AI requests across multiple models with automatic fallback.

Builds the set of providers named in ``LLM_PROVIDER_ORDER`` (Gemini, OpenAI,
DeepSeek, ...), keeps only those that have an API key, and tries them in order.
If a model is offline or denies the request, the next one is attempted. When no
model is configured/reachable the router raises :class:`LLMError` so callers can
fall back to local, offline command handling.

It is a drop-in replacement for the old ``GeminiService``: it exposes the same
``route`` and ``generate_text`` methods.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.ai.prompt_manager import PromptManager
from app.ai.providers import (
    GeminiProvider,
    LLMError,
    LLMProvider,
    OpenAICompatibleProvider,
    ProviderStatus,
)
from app.config.logger import get_logger
from app.config.settings import settings

logger = get_logger(__name__)


class ModelRouter:
    """Tries configured models in priority order and falls back on failure."""

    def __init__(self, prompt_manager: PromptManager | None = None) -> None:
        self.prompts = prompt_manager or PromptManager()
        self._all_providers = self._build_providers()
        self._log_startup_summary()

    # -- construction -------------------------------------------------------
    @staticmethod
    def _build_providers() -> list[LLMProvider]:
        """Instantiate every known provider in the configured priority order."""
        factories = {
            "gemini": lambda: GeminiProvider(),
            "openai": lambda: OpenAICompatibleProvider(
                "openai", settings.openai_api_key, settings.openai_model, settings.openai_base_url
            ),
            "deepseek": lambda: OpenAICompatibleProvider(
                "deepseek", settings.deepseek_api_key, settings.deepseek_model,
                settings.deepseek_base_url,
            ),
        }
        providers: list[LLMProvider] = []
        seen: set[str] = set()
        for name in settings.llm_provider_order:
            factory = factories.get(name)
            if factory is None:
                logger.warning("Unknown LLM provider in LLM_PROVIDER_ORDER: %r", name)
                continue
            if name in seen:
                continue
            seen.add(name)
            providers.append(factory())
        return providers

    # -- availability -------------------------------------------------------
    @property
    def configured_providers(self) -> list[LLMProvider]:
        """Providers that have an API key, in priority order."""
        return [p for p in self._all_providers if p.configured]

    @property
    def any_available(self) -> bool:
        """True when at least one model has an API key to try."""
        return bool(self.configured_providers)

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self.configured_providers]

    def status(self) -> list[ProviderStatus]:
        """Health snapshot of every known provider (configured or not)."""
        return [p.health_check() for p in self._all_providers]

    def _log_startup_summary(self) -> None:
        configured = self.provider_names
        if configured:
            logger.info("AI models available (priority order): %s", ", ".join(configured))
        else:
            logger.warning(
                "No AI model configured (no API keys). Running in local-only mode: "
                "apps, system, files and web commands still work."
            )

    # -- public API (mirrors the old GeminiService) -------------------------
    def route(
        self,
        user_text: str,
        history: list[dict[str, str]],
        memory_context: str = "",
    ) -> dict[str, Any]:
        """Send the user message and return the structured intent JSON."""
        system_prompt = self.prompts.build_system_prompt(memory_context)
        messages = list(history) + [{"role": "user", "content": user_text}]
        raw = self._generate(system_prompt, messages, json_mode=True)
        return self._parse_json(raw)

    def generate_text(self, prompt: str, *, json_mode: bool = False) -> str:
        """One-shot generation with no history."""
        messages = [{"role": "user", "content": prompt}]
        return self._generate(None, messages, json_mode=json_mode)

    # -- internals ----------------------------------------------------------
    def _generate(
        self,
        system_prompt: str | None,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
    ) -> str:
        providers = self.configured_providers
        if not providers:
            raise LLMError("No AI model is configured. Add an API key to your .env file.")

        last_error: LLMError | None = None
        for provider in providers:
            try:
                text = provider.generate(system_prompt, messages, json_mode=json_mode)
                logger.debug("Answered by %s (%s)", provider.name, provider.model)
                return text
            except LLMError as exc:
                logger.warning("%s unavailable, trying next model: %s", provider.name, exc)
                last_error = exc

        raise LLMError(
            f"All configured AI models are unavailable. Last error: {last_error}"
        )

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                logger.error("Unparseable model response: %s", text)
                return {"intent": "GeneralQuestion", "action": None, "speech": text}
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                return {"intent": "GeneralQuestion", "action": None, "speech": text}
        if not isinstance(parsed, dict):
            return {"intent": "GeneralQuestion", "action": None, "speech": str(parsed)}
        return parsed
