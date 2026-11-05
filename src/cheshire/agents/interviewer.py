"""Interviewer: an architect's answer -> suggestions for catalog items, never silent edits.

The questions come from the lenses (deterministic, `maintenance.interviews`); the model
only turns an answer into *suggestions*. It translates, it does not decide (invariant 4):
a human accepts, rejects or qualifies every suggestion. Everything it returns is validated
against the catalog before it is stored (invariant 5): unknown ABBs, attributes, values
or states are rejected, an id that already exists is rejected, and each suggestion must
quote the answer it came from so the source stays visible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from cheshire.agents.base import AgentError, OutputRejected, ProviderFailure, RunRecord
from cheshire.catalog.models import Abb, Attribute, Catalog, Rule, Sbb
from cheshire.catalog.transfer import item_to_raw
from cheshire.maintenance.tryit import check_condition
from cheshire.providers.base import LLMClient, LLMError, LLMRequest, LLMResponse, LLMUnavailable

PROMPT_VERSION = "interviewer-1"
SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
Kind = Literal["sbb", "rule", "abb", "attribute_value"]

SYSTEM_PROMPT = """You help an enterprise architect capture knowledge for a catalog of
Architectural Building Blocks (ABBs), Solution Building Blocks (SBBs) and rules.
You read the architect's answer to one question and propose catalog items it implies.

Rules:
- Propose only what the answer supports. Every suggestion needs a "quote": a short phrase
  copied exactly from the architect's answer. If the answer implies nothing, return an
  empty list; never invent items to be helpful.
- You suggest; you never decide, rank, score or recommend one solution over another.
- Use only ids from the vocabulary below for ABBs, attributes, attribute values, states and
  characteristics. A new item needs a new id (lowercase letters, digits and hyphens) that is
  not in the lists.
- kinds: "sbb" (a solution for an existing ABB: id, name, realises, state, optional
  when/not_when conditions, reason, when_to_choose, limitations), "rule" (id, when,
  activates an existing ABB, strength requires|considers, reason), "abb" (id, name, domain,
  description), "attribute_value" (an existing attribute and one new value key).
- A condition lists attribute tests ("attribute" is one of "values") and ABBs that must be
  present. Leave a condition empty when the answer states none.
- "why" is one sentence saying how the quote leads to the suggestion.
- If one short question would resolve an ambiguity, put it in "follow_up"; otherwise null.
- Write nothing else."""

_COND = {
    "type": ["object", "null"],
    "additionalProperties": False,
    "required": ["attributes", "abb_present"],
    "properties": {
        "attributes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["attribute", "values"],
                "properties": {
                    "attribute": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "abb_present": {"type": "array", "items": {"type": "string"}},
    },
}
_NULLABLE_STRING: dict[str, Any] = {"type": ["string", "null"]}
_FIELDS = (
    "id",
    "name",
    "realises",
    "state",
    "domain",
    "description",
    "strength",
    "activates",
    "attribute",
    "value",
    "reason",
    "when_to_choose",
    "limitations",
)


def output_schema() -> dict[str, Any]:
    """Strict-mode friendly: every property required, unused ones null."""
    props: dict[str, Any] = {
        "kind": {"type": "string", "enum": ["sbb", "rule", "abb", "attribute_value"]},
        "quote": {"type": "string"},
        "why": {"type": "string"},
        "when": _COND,
        "not_when": _COND,
        **{name: _NULLABLE_STRING for name in _FIELDS},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["suggestions", "follow_up"],
        "properties": {
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(props),
                    "properties": props,
                },
            },
            "follow_up": _NULLABLE_STRING,
        },
    }


class _Cond(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attributes: list[dict[str, Any]]
    abb_present: list[str]


class _RawSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    quote: str
    why: str
    when: _Cond | None = None
    not_when: _Cond | None = None
    id: str | None = None
    name: str | None = None
    realises: str | None = None
    state: str | None = None
    domain: str | None = None
    description: str | None = None
    strength: str | None = None
    activates: str | None = None
    attribute: str | None = None
    value: str | None = None
    reason: str | None = None
    when_to_choose: str | None = None
    limitations: str | None = None


class _Raw(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggestions: list[_RawSuggestion]
    follow_up: str | None = None


@dataclass(frozen=True)
class Draft:
    """One validated suggestion, ready to be stored as `pending`."""

    kind: Kind
    payload: dict[str, Any]  # {"item": <raw item>, ...}; attribute_value: {"attribute", "value"}
    quote: str
    why: str


def vocabulary(catalog: Catalog) -> str:
    lines = ["ABBs (id: name):"]
    lines += [f"- {a.id}: {a.name} ({a.domain})" for a in catalog.abbs]
    lines.append("\nAttributes (id [single|multi]: allowed values):")
    lines += [
        f"- {a.id} [{'multi' if a.multi else 'single'}]: {', '.join(a.values)}"
        for a in catalog.attributes
    ]
    lines.append("\nCharacteristics (id: values):")
    lines += [f"- {c.id}: {', '.join(c.values)}" for c in catalog.characteristics]
    lines.append("\nSolution states: recommended, accepted, deprecating, prohibited")
    lines.append("\nExisting SBB ids: " + (", ".join(s.id for s in catalog.sbbs) or "(none)"))
    lines.append("Existing rule ids: " + (", ".join(r.id for r in catalog.rules) or "(none)"))
    return "\n".join(lines)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _quote_problem(quote: str, answer: str, what: str) -> str | None:
    if not quote.strip():
        return f"{what}: the quote is empty"
    for part in re.split(r"\s*\.\.\.\s*|\s*…\s*", quote):
        if part.strip() and _norm(part) not in _norm(answer):
            return f"{what}: quote {part.strip()!r} does not appear in the answer"
    return None


def _condition(raw: _Cond | None) -> dict[str, Any]:
    if raw is None:
        return {}
    out: dict[str, Any] = {}
    for test in raw.attributes:
        attr, values = test.get("attribute"), test.get("values")
        if isinstance(attr, str) and isinstance(values, list):
            out[attr] = [v for v in values if isinstance(v, str)]
    if raw.abb_present:
        out["abb_present"] = list(raw.abb_present)
    return out


def _clean(**fields: Any) -> dict[str, Any]:
    return {k: v for k, v in fields.items() if v not in (None, "", {}, [])}


def _one(s: _RawSuggestion, catalog: Catalog, answer: str, taken: set[str]) -> Draft | list[str]:
    what = f"{s.kind} suggestion {s.id or s.attribute or '?'}"
    problems: list[str] = []
    if bad := _quote_problem(s.quote, answer, what):
        problems.append(bad)
    if s.kind not in ("sbb", "rule", "abb", "attribute_value"):
        return [f"{what}: unknown kind {s.kind!r}"]
    kind: Kind = s.kind  # type: ignore[assignment]

    if kind == "attribute_value":
        attr = catalog.attribute(s.attribute or "")
        if attr is None:
            return [*problems, f"{what}: unknown attribute {s.attribute!r}"]
        if not s.value or not SLUG.match(s.value):
            problems.append(f"{what}: {s.value!r} is not a valid value key")
        elif s.value in attr.values:
            problems.append(f"{what}: attribute {attr.id!r} already has the value {s.value!r}")
        if problems:
            return problems
        assert s.value is not None
        return Draft(kind, {"attribute": attr.id, "value": s.value}, s.quote, s.why)

    if not s.id or not SLUG.match(s.id):
        return [*problems, f"{what}: {s.id!r} is not a valid new id"]
    existing = {
        "sbb": {i.id for i in catalog.sbbs},
        "rule": {i.id for i in catalog.rules},
        "abb": {i.id for i in catalog.abbs},
    }[kind]
    if s.id in existing or f"{kind}:{s.id}" in taken:
        return [*problems, f"{what}: id {s.id!r} already exists"]

    item: Abb | Sbb | Rule
    try:
        if kind == "sbb":
            item = Sbb.model_validate(
                _clean(
                    id=s.id,
                    name=s.name,
                    realises=s.realises,
                    state=s.state,
                    applies_when=_condition(s.when),
                    not_applies_when=_condition(s.not_when),
                    reason_prohibited=s.reason if s.state == "prohibited" else None,
                    reason_not_applies=s.reason if s.state != "prohibited" else None,
                    when_to_choose=s.when_to_choose,
                    limitations=s.limitations,
                    status="draft",
                )
            )
            if catalog.abb(item.realises) is None:
                problems.append(f"{what}: unknown ABB {item.realises!r}")
            for cond in (item.applies_when, item.not_applies_when):
                problems += [f"{what}: {p}" for p in check_condition(catalog, cond)]
        elif kind == "rule":
            item = Rule.model_validate(
                _clean(
                    id=s.id,
                    when=_condition(s.when),
                    activates=s.activates,
                    strength=s.strength,
                    reason=s.reason,
                    status="draft",
                )
            )
            if catalog.abb(item.activates) is None:
                problems.append(f"{what}: unknown ABB {item.activates!r}")
            problems += [f"{what}: {p}" for p in check_condition(catalog, item.when)]
        else:
            item = Abb.model_validate(
                _clean(
                    id=s.id,
                    name=s.name,
                    domain=s.domain,
                    description=s.description,
                    status="draft",
                )
            )
    except ValidationError as exc:
        err = exc.errors()[0]
        return [*problems, f"{what}: {'.'.join(map(str, err['loc']))}: {err['msg']}"]
    if problems:
        return problems
    raw = item_to_raw(item)
    raw.pop("status", None)
    taken.add(f"{kind}:{s.id}")
    return Draft(kind, {"item": raw}, s.quote, s.why)


def validate_suggestions(
    data: dict[str, Any], catalog: Catalog, answer: str
) -> tuple[list[Draft], str, list[str]]:
    """Check a raw model answer against the catalog. Returns (drafts, follow_up, problems)."""
    try:
        raw = _Raw.model_validate(data)
    except ValidationError as exc:
        return [], "", [f"answer has the wrong shape: {exc.errors()[0]['msg']}"]
    drafts: list[Draft] = []
    problems: list[str] = []
    taken: set[str] = set()
    for s in raw.suggestions:
        found = _one(s, catalog, answer, taken)
        if isinstance(found, Draft):
            drafts.append(found)
        else:
            problems += found
    if problems:
        return [], "", problems
    return drafts, (raw.follow_up or "").strip(), []


@dataclass
class Turn:
    suggestions: list[Draft]
    follow_up: str
    run: RunRecord
    problems: list[str] = field(default_factory=list)


def interview_turn(
    client: LLMClient,
    model: str,
    catalog: Catalog,
    *,
    subject: str | None,
    question: str,
    answer: str,
    context: str = "",
    language: str = "en",
) -> Turn:
    """One answer in, validated suggestions out (one retry with the problems listed)."""
    focus = f"Focus ABB: {subject}\n" if subject else ""
    extra = f"\nContext:\n{context}\n" if context else ""
    user = (
        f"{vocabulary(catalog)}\n\n{focus}Question asked: {question}{extra}\n"
        f'Architect\'s answer:\n"""\n{answer}\n"""'
    )
    run = RunRecord(
        purpose="interviewer",
        provider=client.provider,
        model=model,
        prompt_version=PROMPT_VERSION,
        input={"system": SYSTEM_PROMPT, "user": user, "language": language},
    )
    schema = output_schema()
    previous: list[str] = []
    for _attempt in range(2):
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
                LLMRequest(SYSTEM_PROMPT, prompt, "interview_suggestions", schema, model)
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
        drafts, follow_up, problems = validate_suggestions(response.data, catalog, answer)
        if not problems:
            run.status, run.problems = "ok", []
            return Turn(drafts, follow_up, run)
        previous, run.problems = problems, problems
    run.status = "rejected"
    raise OutputRejected(previous, run)


def attribute_with_value(attribute: Attribute, value: str) -> Attribute:
    """The attribute as it would be after accepting an `attribute_value` suggestion."""
    return attribute.model_copy(update={"values": [*attribute.values, value]})
