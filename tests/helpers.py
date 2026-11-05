"""Scripted LLM replies built from the scenario fixtures."""

import re
from pathlib import Path
from typing import Any

from cheshire.engine.model import InterpreterOutput
from cheshire.providers.base import LLMRequest
from cheshire.scenarios import Scenario, load_scenario

ROOT = Path(__file__).resolve().parents[1]


def all_scenarios() -> list[Scenario]:
    return [load_scenario(p) for p in sorted((ROOT / "scenarios").glob("*.yaml"))]


def raw_interpretation(out: InterpreterOutput) -> dict[str, Any]:
    """The Interpreter's wire format for a given interpretation."""
    return {
        "abbs": [{"id": m.id, "span": m.span} for m in out.abbs],
        "attributes": [
            {
                "attribute": attr,
                "values": [v.value] if isinstance(v.value, str) else v.value,
                "source": v.source,
                "span": v.span,
            }
            for attr, v in out.attributes.items()
        ],
    }


def perfect_llm(request: LLMRequest) -> dict[str, Any]:
    """Behaves like an ideal model for both agents, based on the scenario fixtures."""
    if request.schema_name == "interpretation":
        for scenario in all_scenarios():
            if scenario.requirement in request.user:
                return raw_interpretation(scenario.interpreter_output)
        return {"abbs": [], "attributes": []}
    # writer: one verified sentence per ABB entry, naming only what the entry names
    sentences = []
    for ref, name in re.findall(r"\[(abb:[^\]]+)\] Building block (.+?) \(", request.user):
        sentences.append({"text": f"{name} is part of this result.", "refs": [ref]})
    return {"sentences": sentences}
