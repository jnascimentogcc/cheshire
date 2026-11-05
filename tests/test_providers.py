import json

import httpx
import pytest

from cheshire.providers import build_client
from cheshire.providers.base import LLMError, LLMNotConfigured, LLMRequest, LLMUnavailable
from cheshire.providers.openai import OpenAIClient
from cheshire.settings import Settings

REQUEST = LLMRequest(
    system="sys",
    user="usr",
    schema_name="thing",
    schema={"type": "object", "properties": {}, "additionalProperties": False, "required": []},
    model="some-model",
)


def client(handler: httpx.MockTransport | None = None, **kw: object) -> OpenAIClient:
    return OpenAIClient("sk-secret-key", transport=handler, **kw)  # type: ignore[arg-type]


def reply(content: str, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "model": "some-model-2025",
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        }
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def test_request_shape_and_parsing() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return reply('{"a": 1}').handle_request(request)

    result = client(httpx.MockTransport(handler)).complete_json(REQUEST)
    assert result.data == {"a": 1}
    assert (result.model, result.tokens_in, result.tokens_out) == ("some-model-2025", 11, 7)

    sent = seen[0]
    assert sent.url.path.endswith("/chat/completions")
    assert sent.headers["authorization"] == "Bearer sk-secret-key"
    body = json.loads(sent.content)
    assert body["model"] == "some-model"
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "temperature" not in body  # not all models accept it


@pytest.mark.parametrize("status", [429, 500, 503])
def test_server_side_errors_are_unavailable(status: int) -> None:
    with pytest.raises(LLMUnavailable):
        client(reply("{}", status)).complete_json(REQUEST)


def test_network_failure_is_unavailable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(LLMUnavailable):
        client(httpx.MockTransport(boom)).complete_json(REQUEST)


def test_client_errors_do_not_leak_the_body_or_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key sk-secret-key; prompt was: usr"})

    with pytest.raises(LLMError) as info:
        client(httpx.MockTransport(handler)).complete_json(REQUEST)
    assert "sk-secret-key" not in str(info.value) and "prompt" not in str(info.value)
    assert not isinstance(info.value, LLMUnavailable)


@pytest.mark.parametrize("content", ["not json", "[1, 2]", ""])
def test_unusable_content_is_an_error(content: str) -> None:
    with pytest.raises(LLMError):
        client(reply(content)).complete_json(REQUEST)


def test_refusal_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"refusal": "no", "content": None}}]}
        )

    with pytest.raises(LLMError, match="refused"):
        client(httpx.MockTransport(handler)).complete_json(REQUEST)


def test_build_client_needs_a_key_and_a_known_provider() -> None:
    with pytest.raises(LLMNotConfigured):
        build_client(Settings(llm_api_key=None))
    with pytest.raises(LLMNotConfigured):
        build_client(Settings(llm_provider="nope", llm_api_key="k"))
    assert build_client(Settings(llm_api_key="k")).provider == "openai"


def test_base_url_is_configurable_for_local_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "localhost" and request.url.port == 11434
        return reply('{"ok": true}').handle_request(request)

    c = OpenAIClient("k", "http://localhost:11434/v1/", transport=httpx.MockTransport(handler))
    assert c.complete_json(REQUEST).data == {"ok": True}
