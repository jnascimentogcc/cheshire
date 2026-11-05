"""Interpreter: free text -> catalog vocabulary (ABBs and attribute values with spans).

It translates, it does not decide (invariant 4). Everything it returns is validated
against the catalog before use (invariant 5): unknown ABB, attribute or value ids are
rejected, never silently accepted; the model gets one retry with the problems listed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from cheshire.agents.base import AgentError, OutputRejected, ProviderFailure, RunRecord
from cheshire.catalog.models import Catalog
from cheshire.engine.model import AbbMention, AttributeValue, InterpreterOutput
from cheshire.providers.base import LLMClient, LLMError, LLMRequest, LLMResponse, LLMUnavailable

PROMPT_VERSION = "interpreter-1"

SYSTEM_PROMPT = """You map a software requirement written in free text onto a fixed vocabulary.
You translate; you never decide which solution to use and you never invent identifiers.

Rules:
- Report an ABB only if the requirement clearly needs that kind of building block, and only
  with an id from the ABB list. Use the recognition hints as cues, not as keyword matching.
- Report an attribute value only with an attribute id and value from the attribute list.
  source "stated": the text says it explicitly. source "inferred": the text implies it.
  If the text gives no evidence for an attribute, leave it out; never guess to fill gaps.
- Every ABB and every attribute value needs a span: a short quote copied exactly from the
  requirement. Use " ... " between two quotes when the evidence is in separate places.
- A single-valued attribute has exactly one value; a multi-valued one may have several.
- Write nothing else. If nothing in the catalog applies, return empty lists."""


class _RawAbb(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    span: str


class _RawAttribute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attribute: str
    values: list[str]
    source: str
    span: str


class _Raw(BaseModel):
    model_config = ConfigDict(extra="forbid")
    abbs: list[_RawAbb]
    attributes: list[_RawAttribute]


def output_schema(catalog: Catalog) -> dict[str, Any]:
    """JSON Schema of the answer (strict-mode friendly). Ids are enums when possible."""
    abb_id: dict[str, Any] = {"type": "string"}
    attr_id: dict[str, Any] = {"type": "string"}
    if catalog.abbs:
        abb_id["enum"] = [a.id for a in catalog.abbs]
    if catalog.attributes:
        attr_id["enum"] = [a.id for a in catalog.attributes]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["abbs", "attributes"],
        "properties": {
            "abbs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "span"],
                    "properties": {"id": abb_id, "span": {"type": "string"}},
                },
            },
            "attributes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["attribute", "values", "source", "span"],
                    "properties": {
                        "attribute": attr_id,
                        "values": {"type": "array", "items": {"type": "string"}},
                        "source": {"type": "string", "enum": ["stated", "inferred"]},
                        "span": {"type": "string"},
                    },
                },
            },
        },
    }


def catalog_prompt(catalog: Catalog) -> str:
    lines = ["ABB list (id: name - description; recognition hints):"]
    for abb in catalog.abbs:
        hints = f"; hints: {', '.join(abb.recognition)}" if abb.recognition else ""
        lines.append(f"- {abb.id}: {abb.name} - {abb.description}{hints}")
    lines.append("\nAttribute list (id [single|multi]: question; allowed values):")
    for attr in catalog.attributes:
        kind = "multi" if attr.multi else "single"
        lines.append(f"- {attr.id} [{kind}]: {attr.question} values: {', '.join(attr.values)}")
    return "\n".join(lines)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _span_problem(span: str, requirement: str, what: str) -> str | None:
    if not span.strip():
        return f"{what}: the span is empty"
    haystack = _norm(requirement)
    for part in re.split(r"\s*\.\.\.\s*|\s*…\s*", span):
        if part.strip() and _norm(part) not in haystack:
            return f"{what}: span {part.strip()!r} does not appear in the requirement"
    return None


def validate_interpretation(
    data: dict[str, Any], catalog: Catalog, requirement: str
) -> tuple[InterpreterOutput | None, list[str]]:
    """Check a raw model answer against the catalog. Returns (output, problems)."""
    try:
        raw = _Raw.model_validate(data)
    except ValidationError as exc:
        return None, [f"answer has the wrong shape: {exc.errors()[0]['msg']}"]

    problems: list[str] = []
    abbs: list[AbbMention] = []
    seen_abbs: set[str] = set()
    for item in raw.abbs:
        if catalog.abb(item.id) is None:
            problems.append(f"unknown ABB id {item.id!r}")
            continue
        if bad := _span_problem(item.span, requirement, f"ABB {item.id}"):
            problems.append(bad)
        if item.id not in seen_abbs:
            seen_abbs.add(item.id)
            abbs.append(AbbMention(id=item.id, span=item.span))

    attributes: dict[str, AttributeValue] = {}
    for entry in raw.attributes:
        attr = catalog.attribute(entry.attribute)
        if attr is None:
            problems.append(f"unknown attribute id {entry.attribute!r}")
            continue
        if entry.source not in ("stated", "inferred"):
            problems.append(f"attribute {attr.id}: source must be stated or inferred")
            continue
        values = [v for v in entry.values if v != "unknown"]
        if not values:
            continue  # "unknown" is the default; nothing to record
        unknown = [v for v in values if v not in attr.values]
        if unknown:
            problems.append(f"attribute {attr.id}: unknown value(s) {unknown}")
            continue
        if len(values) > 1 and not attr.multi:
            problems.append(f"attribute {attr.id} is single-valued but got {values}")
            continue
        if attr.id in attributes:
            problems.append(f"attribute {attr.id} appears more than once")
            continue
        if bad := _span_problem(entry.span, requirement, f"attribute {attr.id}"):
            problems.append(bad)
        attributes[attr.id] = AttributeValue(
            value=values[0] if len(values) == 1 else values,
            source="stated" if entry.source == "stated" else "inferred",
            span=entry.span,
        )
    if problems:
        return None, problems
    return InterpreterOutput(abbs=abbs, attributes=attributes), []


@dataclass
class Interpretation:
    output: InterpreterOutput
    run: RunRecord

    @property
    def recognised_nothing(self) -> bool:
        """No ABB found: the text is recorded as an unrecognised requirement."""
        return not self.output.abbs


def interpret(
    client: LLMClient, model: str, catalog: Catalog, requirement: str, language: str = "en"
) -> Interpretation:
    system = SYSTEM_PROMPT
    user = f'{catalog_prompt(catalog)}\n\nRequirement:\n"""\n{requirement}\n"""'
    schema = output_schema(catalog)
    run = RunRecord(
        purpose="interpreter",
        provider=client.provider,
        model=model,
        prompt_version=PROMPT_VERSION,
        input={"system": system, "user": user, "language": language},
    )
    previous: list[str] = []
    for _attempt in range(2):  # the first answer plus one retry
        prompt = user
        if previous:
            prompt += (
                "\n\nYour previous answer was rejected for these reasons:\n- "
                + "\n- ".join(previous)
                + "\nAnswer again, fixing every point."
            )
        run.attempts += 1
        try:
            response: LLMResponse = client.complete_json(
                LLMRequest(system, prompt, "interpretation", schema, model)
            )
        except LLMUnavailable as exc:
            run.status, run.error = "error", str(exc)
            raise ProviderFailure(str(exc), run) from exc
        except LLMError as exc:
            run.status, run.error = "error", str(exc)
            raise AgentError(str(exc), run) from exc
        run.tokens_in += response.tokens_in or 0
        run.tokens_out += response.tokens_out or 0
        run.latency_ms += response.latency_ms
        run.output = response.data
        output, problems = validate_interpretation(response.data, catalog, requirement)
        if output is not None:
            run.status, run.problems = "ok", []
            return Interpretation(output, run)
        previous, run.problems = problems, problems
    run.status = "rejected"
    raise OutputRejected(previous, run)
