"""Google Gemini provider (REST ``generateContent`` endpoint)."""

from __future__ import annotations

from typing import Any

import requests

from app.ai.providers.base import LLMError, LLMProvider, ProviderStatus
from app.config.logger import get_logger
from app.config.settings import settings

logger = get_logger(__name__)


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self) -> None:
        self._session = requests.Session()

    @property
    def model(self) -> str:
        return settings.gemini_model

    @property
    def configured(self) -> bool:
        return bool(settings.gemini_api_key)

    # -- main call ----------------------------------------------------------
    def generate(
        self,
        system_prompt: str | None,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
    ) -> str:
        if not self.configured:
            raise LLMError("GEMINI_API_KEY is not set.")

        url = f"{settings.gemini_base_url}/models/{settings.gemini_model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": settings.gemini_api_key,
        }
        payload: dict[str, Any] = {
            "contents": self._to_contents(messages),
            "generationConfig": {"temperature": settings.temperature},
        }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        try:
            response = self._session.post(
                url, headers=headers, json=payload, timeout=settings.request_timeout_seconds
            )
        except requests.RequestException as exc:
            logger.warning("Gemini network error: %s", exc)
            raise LLMError(f"Gemini network error: {exc}") from exc

        if response.status_code != 200:
            detail = self._error_detail(response)
            logger.warning("Gemini %s: %s", response.status_code, detail)
            if response.status_code == 403:
                raise LLMError(
                    "Gemini denied access (403). The API key's Google project isn't allowed "
                    f"to use generateContent. Details: {detail}"
                )
            raise LLMError(f"Gemini error {response.status_code}: {detail}")

        return self._extract_text(response.json())

    # -- health -------------------------------------------------------------
    def health_check(self) -> ProviderStatus:
        if not self.configured:
            return ProviderStatus(self.name, self.model, configured=False, reachable=None)
        url = f"{settings.gemini_base_url}/models/{settings.gemini_model}"
        try:
            resp = self._session.get(
                url, headers={"x-goog-api-key": settings.gemini_api_key}, timeout=8
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
    def _to_contents(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for turn in messages:
            role = "model" if turn.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": turn.get("content", "")}]})
        return contents

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        try:
            return str(response.json().get("error", {}).get("message", response.text[:200]))
        except Exception:
            return response.text[:200]

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates") or []
        if not candidates:
            feedback = payload.get("promptFeedback")
            raise LLMError(f"Gemini returned no candidates. Feedback: {feedback}")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "\n".join(str(p.get("text", "")) for p in parts if p.get("text")).strip()
        if not text:
            raise LLMError("Gemini response contained no text.")
        return text
