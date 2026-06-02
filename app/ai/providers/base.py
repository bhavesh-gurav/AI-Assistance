"""Common interface every LLM provider implements.

A provider knows how to turn a *neutral* request — a system prompt plus a list
of ``{"role": "user"|"assistant", "content": str}`` messages — into a single
text reply from its backend. Keeping the request format neutral lets the
:class:`~app.ai.model_router.ModelRouter` swap providers freely and fall back
when one is offline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class LLMError(RuntimeError):
    """Raised when a provider cannot be reached or returns no usable text."""


@dataclass(frozen=True)
class ProviderStatus:
    """A snapshot of one provider's availability (for logs / UI)."""

    name: str
    model: str
    configured: bool          # an API key is present
    reachable: bool | None    # True/False after a health check, None if unknown
    detail: str = ""

    def describe(self) -> str:
        if not self.configured:
            return f"{self.name}: no API key (skipped)"
        if self.reachable is False:
            return f"{self.name} ({self.model}): unreachable — {self.detail}".rstrip(" —")
        if self.reachable is True:
            return f"{self.name} ({self.model}): ready"
        return f"{self.name} ({self.model}): configured"


class LLMProvider(ABC):
    """Base class for a single model backend."""

    #: Human-readable, lower-case identifier used in LLM_PROVIDER_ORDER.
    name: str = "provider"

    @property
    @abstractmethod
    def model(self) -> str:
        """The model name this provider will call."""

    @property
    @abstractmethod
    def configured(self) -> bool:
        """Whether an API key (and any required config) is present."""

    @abstractmethod
    def generate(
        self,
        system_prompt: str | None,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
    ) -> str:
        """Return the model's text reply, or raise :class:`LLMError`.

        ``messages`` is an ordered list of ``{"role", "content"}`` turns where
        role is ``"user"`` or ``"assistant"``; the final turn is the new user
        message.
        """

    def health_check(self) -> ProviderStatus:
        """Cheap reachability probe used for status reporting.

        The default reports ``reachable=None`` (unknown) when configured so we
        avoid spending a request; routing still falls back on real failures.
        Providers may override to actually ping their endpoint.
        """
        return ProviderStatus(
            name=self.name,
            model=self.model,
            configured=self.configured,
            reachable=None,
        )
