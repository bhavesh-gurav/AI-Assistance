"""Gemini Pro API client.

Thin, dependency-light wrapper over the official ``generateContent`` REST
endpoint. Uses ``requests`` so we avoid the heavier SDK and keep full control
over the payload (system instruction, JSON response mode, history).
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from app.ai.prompt_manager import PromptManager
from app.config.logger import get_logger
from app.config.settings import settings

logger = get_logger(__name__)


class GeminiError(RuntimeError):
    """Raised when the Gemini API cannot be reached or returns no usable text."""


class GeminiService:
    """Calls Gemini and returns parsed structured responses."""

    def __init__(self, prompt_manager: PromptManager | None = None) -> None:
        self.prompts = prompt_manager or PromptManager()
        self._session = requests.Session()

    # -- public API ---------------------------------------------------------
    def route(
        self,
        user_text: str,
        history: list[dict[str, str]],
        memory_context: str = "",
    ) -> dict[str, Any]:
        """Send the user message and return the structured intent JSON."""
        system_prompt = self.prompts.build_system_prompt(memory_context)
        contents = self.prompts.build_contents(history, user_text)
        raw = self._generate(system_prompt, contents, json_mode=True)
        return self._parse_json(raw)

    def generate_text(self, prompt: str, *, json_mode: bool = False) -> str:
        """One-shot text/code generation with no history (used by CodingTask helpers)."""
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        return self._generate(system_prompt=None, contents=contents, json_mode=json_mode)

    # -- internals ----------------------------------------------------------
    def _generate(
        self,
        system_prompt: str | None,
        contents: list[dict[str, Any]],
        *,
        json_mode: bool,
    ) -> str:
        if not settings.is_configured:
            raise GeminiError("GEMINI_API_KEY is not set. Add it to your .env file.")

        url = f"{settings.gemini_base_url}/models/{settings.gemini_model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": settings.gemini_api_key,
        }
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": settings.temperature,
            },
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
            raise GeminiError(f"Gemini network error: {exc}") from exc

        if response.status_code != 200:
            detail = self._error_detail(response)
            logger.warning("Gemini %s: %s", response.status_code, detail)
            if response.status_code == 403:
                raise GeminiError(
                    "Gemini denied access (403). Your API key's Google project isn't allowed to "
                    "use generateContent. Create a fresh key at https://aistudio.google.com/app/apikey "
                    f"on a supported account/region. Details: {detail}"
                )
            raise GeminiError(f"Gemini error {response.status_code}: {detail}")

        return self._extract_text(response.json())

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
            raise GeminiError(f"Gemini returned no candidates. Feedback: {feedback}")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "\n".join(str(p.get("text", "")) for p in parts if p.get("text")).strip()
        if not text:
            raise GeminiError("Gemini response contained no text.")
        return text

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                logger.error("Unparseable Gemini response: %s", text)
                # Degrade gracefully into a plain spoken answer.
                return {"intent": "GeneralQuestion", "action": None, "speech": text}
            parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            return {"intent": "GeneralQuestion", "action": None, "speech": str(parsed)}
        return parsed
