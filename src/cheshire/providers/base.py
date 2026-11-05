"""The provider-neutral LLM interface (invariant 11). Nothing outside `providers/` knows
which vendor is behind it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(Exception):
    """The provider could not produce a usable answer."""


class LLMUnavailable(LLMError):
    """Network failure, timeout, rate limit or server error: worth trying again later."""


class LLMNotConfigured(LLMError):
    """No provider, key or model has been configured."""


@dataclass(frozen=True)
class LLMRequest:
    """One structured-output call: the answer must be JSON matching `schema`."""

    system: str
    user: str
    schema_name: str
    schema: dict[str, Any]
    model: str


@dataclass(frozen=True)
class LLMResponse:
    data: dict[str, Any]
    model: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int = 0
    raw: str = field(default="", repr=False)


class LLMClient(Protocol):
    provider: str

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        """Return the model's JSON answer. Raises `LLMUnavailable` or `LLMError`."""
        ...
