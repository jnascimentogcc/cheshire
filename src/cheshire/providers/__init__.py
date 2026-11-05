"""LLMClient interface and provider adapters. No provider logic anywhere else."""

from cheshire.providers.base import (
    LLMClient,
    LLMError,
    LLMNotConfigured,
    LLMRequest,
    LLMResponse,
    LLMUnavailable,
)
from cheshire.settings import Settings

__all__ = [
    "LLMClient",
    "LLMError",
    "LLMNotConfigured",
    "LLMRequest",
    "LLMResponse",
    "LLMUnavailable",
    "build_client",
]


def build_client(settings: Settings) -> LLMClient:
    """The client for `CHESHIRE_LLM_PROVIDER`. New providers are added here."""
    if settings.llm_provider == "openai":
        from cheshire.providers.openai import OpenAIClient

        if settings.llm_api_key is None:
            raise LLMNotConfigured("CHESHIRE_LLM_API_KEY is not set")
        return OpenAIClient(
            settings.llm_api_key.get_secret_value(),
            settings.llm_base_url,
            settings.llm_timeout_seconds,
        )
    raise LLMNotConfigured(f"unknown LLM provider {settings.llm_provider!r}")
