"""A scripted client for tests and offline evaluation. Never talks to a network."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cheshire.providers.base import LLMError, LLMRequest, LLMResponse

Reply = dict[str, Any] | Exception | Callable[[LLMRequest], dict[str, Any]]


class ScriptedLLM:
    """Answers with the next scripted reply (a dict, an exception to raise, or a callable)."""

    provider = "scripted"

    def __init__(self, *replies: Reply) -> None:
        self._replies = list(replies)
        self.requests: list[LLMRequest] = []

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self._replies:
            raise LLMError("ScriptedLLM has no reply left")
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        data = reply(request) if callable(reply) else reply
        return LLMResponse(data=data, model="scripted-1", tokens_in=1, tokens_out=1, latency_ms=1)
