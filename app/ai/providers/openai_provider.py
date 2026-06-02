"""OpenAI-compatible provider.

Works with the OpenAI Chat Completions API and any backend that mirrors it
(DeepSeek, Groq, OpenRouter, Together, local Ollama/LM Studio, ...). Each
concrete model is just a different ``(name, api_key, model, base_url)`` tuple,
so one class serves them all.
"""

from __future__ import annotations

from typing import Any

import requests

from app.ai.providers.base import LLMError, LLMProvider, ProviderStatus
from app.config.logger import get_logger
from app.config.settings import settings

logger = get_logger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """A provider speaking the OpenAI ``/chat/completions`` dialect."""

    def __init__(self, name: str, api_key: str, model: str, base_url: str) -> None:
        self.name = name
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()

    @property
    def model(self) -> str:
        return self._model

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    # -- main call ----------------------------------------------------------
    def generate(
        self,
        system_prompt: str | None,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
    ) -> str:
        if not self.configured:
            raise LLMError(f"{self.name} API key is not set.")

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._to_messages(system_prompt, messages),
            "temperature": settings.temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            response = self._session.post(
                url, headers=headers, json=payload, timeout=settings.request_timeout_seconds
            )
        except requests.RequestException as exc:
            logger.warning("%s network error: %s", self.name, exc)
            raise LLMError(f"{self.name} network error: {exc}") from exc

        if response.status_code != 200:
            detail = self._error_detail(response)
            logger.warning("%s %s: %s", self.name, response.status_code, detail)
            raise LLMError(f"{self.name} error {response.status_code}: {detail}")

        return self._extract_text(response.json())

    # -- health -------------------------------------------------------------
    def health_check(self) -> ProviderStatus:
        if not self.configured:
            return ProviderStatus(self.name, self.model, configured=False, reachable=None)
        try:
            resp = self._session.get(
                f"{self._base_url}/models",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=8,
            )
            ok = resp.status_code == 200
            return ProviderStatus(
                self.name, self.model, configured=True, reachable=ok,
                detail="" if ok else self._error_detail(resp),
            )
        except requests.RequestException as exc:
            return ProviderStatus(self.name, self.model, True, reachable=False, detail=str(exc))

    # -- conversion ---------------------------------------------------------
    @staticmethod
    def _to_messages(
        system_prompt: str | None, messages: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        if system_prompt:
            out.append({"role": "system", "content": system_prompt})
        for turn in messages:
            role = turn.get("role", "user")
            role = "assistant" if role == "assistant" else "user"
            out.append({"role": role, "content": turn.get("content", "")})
        return out

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        try:
            body = response.json()
            err = body.get("error")
            if isinstance(err, dict):
                return str(err.get("message", response.text[:200]))
            return str(err or response.text[:200])
        except Exception:
            return response.text[:200]

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            raise LLMError("Response contained no choices.")
        message = (choices[0] or {}).get("message") or {}
        text = str(message.get("content", "")).strip()
        if not text:
            raise LLMError("Response contained no text.")
        return text
