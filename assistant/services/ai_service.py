from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import requests

from config import SYSTEM_PROMPT, Settings
from utils.logger import get_logger


logger = get_logger(__name__)


class GeminiService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_response(self, user_text: str) -> dict[str, Any]:
        if not self.settings.gemini_api_key:
            raise RuntimeError("Missing GEMINI_API_KEY environment variable.")

        return await asyncio.to_thread(self._request_response, user_text)

    def _request_response(self, user_text: str) -> dict[str, Any]:
        url = (
            f"{self.settings.gemini_base_url}/models/"
            f"{self.settings.gemini_model}:generateContent"
        )
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.settings.gemini_api_key,
        }
        payload = {
            "systemInstruction": {
                "parts": [{"text": SYSTEM_PROMPT}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_text}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()

        raw_text = self._extract_text(response.json())
        return self._parse_json(raw_text)

    def _extract_text(self, payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates") or []
        if not candidates:
            raise ValueError("Gemini returned no candidates.")

        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []
        text_parts = [str(part.get("text", "")) for part in parts if part.get("text")]
        text = "\n".join(text_parts).strip()
        if not text:
            raise ValueError("Gemini response did not include text.")
        return text

    def _parse_json(self, text: str) -> dict[str, Any]:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                logger.error("Could not parse Gemini response: %s", text)
                raise
            parsed = json.loads(match.group(0))

        if not isinstance(parsed, dict):
            raise ValueError("Gemini JSON response must be an object.")
        return parsed
