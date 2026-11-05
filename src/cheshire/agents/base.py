"""Shared pieces of the agents: run records and errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RunStatus = Literal["ok", "rejected", "error"]


@dataclass
class RunRecord:
    """Everything `llm_runs` stores about one agent invocation (all attempts)."""

    purpose: Literal["interpreter", "writer", "interviewer", "mediator"]
    provider: str
    model: str
    prompt_version: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    status: RunStatus = "ok"
    attempts: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    error: str = ""
    problems: list[str] = field(default_factory=list)


class AgentError(Exception):
    """An agent could not deliver. `run` is still stored so the failure can be debugged."""

    def __init__(self, message: str, run: RunRecord) -> None:
        super().__init__(message)
        self.run = run


class ProviderFailure(AgentError):
    """The LLM provider was unavailable or failed (retry later)."""


class OutputRejected(AgentError):
    """The model's output failed validation, also after the single retry."""

    def __init__(self, problems: list[str], run: RunRecord) -> None:
        super().__init__("; ".join(problems), run)
        self.problems = problems
