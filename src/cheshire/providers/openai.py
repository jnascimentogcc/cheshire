"""OpenAI adapter (D25) over the Chat Completions API with structured outputs.

Works with any OpenAI-compatible endpoint (`CHESHIRE_LLM_BASE_URL`), which is how local
models are used. Provider-specific logic stays in this module.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from cheshire.providers.base import LLMError, LLMRequest, LLMResponse, LLMUnavailable


class OpenAIClient:
    provider = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "strict": True,
                    "schema": request.schema,
                },
            },
        }
        started = time.monotonic()
        try:
            response = self._http.post("/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"cannot reach the provider: {type(exc).__name__}") from exc
        latency = int((time.monotonic() - started) * 1000)

        if response.status_code == 429 or response.status_code >= 500:
            raise LLMUnavailable(f"provider answered {response.status_code}")
        if response.status_code >= 400:
            # never echo the response body: it can contain parts of the prompt
            raise LLMError(f"provider rejected the request ({response.status_code})")

        try:
            payload = response.json()
            message = payload["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("unexpected response shape from the provider") from exc
        if message.get("refusal"):
            raise LLMError("the model refused to answer")
        raw = message.get("content") or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError("the model did not return valid JSON") from exc
        if not isinstance(data, dict):
            raise LLMError("the model returned JSON that is not an object")
        usage = payload.get("usage") or {}
        return LLMResponse(
            data=data,
            model=str(payload.get("model", request.model)),
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            latency_ms=latency,
            raw=raw,
        )
