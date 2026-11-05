"""Writer: engine trace -> rationale prose, with sentence-level references, plus its checker.

The Writer explains; it never adds a conclusion (invariants 4 and 6). Every sentence must
cite trace entries, and a sentence may not mention an ABB or SBB that is not in the trace.
The checker is plain code, not an LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cheshire.agents.base import AgentError, OutputRejected, ProviderFailure, RunRecord
from cheshire.catalog.models import Catalog
from cheshire.engine.model import EngineResult
from cheshire.engine.trace import TraceEntry, build_trace
from cheshire.providers.base import LLMClient, LLMError, LLMRequest, LLMUnavailable

PROMPT_VERSION = "writer-1"
DetailLevel = Literal["summary", "detailed"]
SCHEMA_VERSION = 1

SYSTEM_PROMPT = """You explain the result of a deterministic rule engine to a person.
You are given trace entries, each with a reference like [abb:channel-sms]. Write the rationale
as a list of sentences, and give every sentence the references of the trace entries it rests on.

Hard rules:
- Use only facts present in the trace entries and the catalog text given for them.
- Mention only building blocks (ABBs) and solutions (SBBs) that appear in the trace entries.
- Never rank, score or recommend one solution over another, and never say one is "best" or
  "better". The state label (recommended, accepted, deprecating) is a label, not advice.
  The choice belongs to the person.
- Say plainly when something is a gap (no solution registered), conditional, blocked or still
  depends on an open question, and name the question.
- Say when a rule or item is only proposed (not yet validated).
- Do not invent rules, reasons, numbers or names."""

_STYLE = {
    "summary": "Plain language for a non-specialist; at most about 8 short sentences.",
    "detailed": "Technical wording; cover each ABB, the rules behind it and every open question.",
}

RANKING_WORDS = re.compile(
    r"\b(best|better|worse|worst|superior|inferior|top choice|preferred|first choice|"
    r"should (?:choose|pick|select|use))\b",
    re.IGNORECASE,
)


class Sentence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    refs: list[str]
    verified: bool = True
    problems: list[str] = Field(default_factory=list)


class Rationale(BaseModel):
    schema_version: int = SCHEMA_VERSION
    language: str
    detail: DetailLevel
    sentences: list[Sentence]


class _RawSentence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    refs: list[str]


class _Raw(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sentences: list[_RawSentence]


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sentences"],
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "refs"],
                "properties": {
                    "text": {"type": "string"},
                    "refs": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}


# ------------------------------------------------------------------- checker


def name_pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])", re.IGNORECASE)


def check_sentences(
    sentences: list[_RawSentence], entries: list[TraceEntry], catalog: Catalog
) -> list[list[str]]:
    """Problems per sentence (an empty list = verified)."""
    refs = {e.ref for e in entries}
    allowed = {n.casefold() for e in entries for n in e.names}
    catalog_names = {n for a in catalog.abbs for n in (a.id, a.name) if n.strip()} | {
        n for b in catalog.sbbs for n in (b.id, b.name) if n.strip()
    }
    forbidden = sorted(n for n in catalog_names if n.casefold() not in allowed)
    allowed_longest_first = sorted(allowed, key=len, reverse=True)

    result: list[list[str]] = []
    for sentence in sentences:
        problems: list[str] = []
        if not sentence.refs:
            problems.append("the sentence cites no trace entry")
        for ref in sentence.refs:
            if ref not in refs:
                problems.append(f"unknown trace reference {ref!r}")
        masked = sentence.text
        for name in allowed_longest_first:  # so "Audit log" inside an allowed longer name is fine
            masked = name_pattern(name).sub(" ", masked)
        for name in forbidden:
            if name_pattern(name).search(masked):
                problems.append(f"mentions {name!r}, which is not in the trace")
        if RANKING_WORDS.search(sentence.text):
            problems.append("uses ranking language; the tool never ranks solutions")
        result.append(problems)
    return result


# -------------------------------------------------------------------- writing


def writer_prompt(entries: list[TraceEntry], catalog: Catalog, language: str, detail: str) -> str:
    lines = ["Trace entries:"]
    lines += [f"[{e.ref}] {e.text}" for e in entries]
    lines.append("\nCatalog text for the items above (cite the same references):")
    seen: set[str] = set()
    for e in entries:
        if e.kind == "abb" and e.ref not in seen:
            seen.add(e.ref)
            abb = catalog.abb(e.abb or "")
            if abb and abb.description:
                lines.append(f"[{e.ref}] {abb.description}")
        elif e.kind == "sbb":
            sbb = next((s for s in catalog.sbbs if e.ref.endswith(f":{s.id}")), None)
            if sbb:
                facts = [t for t in (sbb.when_to_choose, sbb.limitations) if t]
                chars = ", ".join(f"{k}={v}" for k, v in sbb.characteristics.items())
                if chars:
                    facts.append(f"characteristics: {chars}")
                if facts:
                    lines.append(f"[{e.ref}] " + " ".join(facts))
    lines.append(f"\nLanguage: {language}. Style: {_STYLE[detail]}")
    return "\n".join(lines)


@dataclass
class Rationalisation:
    rationale: Rationale
    run: RunRecord
    checker: dict[str, Any]
    status: Literal["ok", "warnings", "failed"]


def write_rationale(
    client: LLMClient,
    model: str,
    result: EngineResult,
    catalog: Catalog,
    language: str = "en",
    detail: DetailLevel = "summary",
) -> Rationalisation:
    entries = build_trace(result, catalog)
    user = writer_prompt(entries, catalog, language, detail)
    run = RunRecord(
        purpose="writer",
        provider=client.provider,
        model=model,
        prompt_version=PROMPT_VERSION,
        input={
            "system": SYSTEM_PROMPT,
            "user": user,
            "refs": [e.ref for e in entries],
            "detail": detail,
            "language": language,
        },
    )
    previous: list[str] = []
    last: tuple[list[_RawSentence], list[list[str]]] | None = None
    for _attempt in range(2):  # the first draft plus one retry
        prompt = user
        if previous:
            prompt += (
                "\n\nYour previous draft was rejected by the checker:\n- "
                + "\n- ".join(previous)
                + "\nWrite it again, fixing every point."
            )
        run.attempts += 1
        try:
            response = client.complete_json(
                LLMRequest(SYSTEM_PROMPT, prompt, "rationale", OUTPUT_SCHEMA, model)
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
        try:
            raw = _Raw.model_validate(response.data)
        except ValidationError as exc:
            previous = [f"answer has the wrong shape: {exc.errors()[0]['msg']}"]
            run.problems = previous
            continue
        if not raw.sentences:
            previous = ["the rationale is empty"]
            run.problems = previous
            continue
        per_sentence = check_sentences(raw.sentences, entries, catalog)
        last = (raw.sentences, per_sentence)
        previous = [f"sentence {i + 1}: {p}" for i, ps in enumerate(per_sentence) for p in ps]
        run.problems = previous
        if not previous:
            break

    if last is None:
        run.status = "rejected"
        raise OutputRejected(previous, run)

    sentences = [
        Sentence(text=s.text, refs=s.refs, verified=not ps, problems=ps)
        for s, ps in zip(*last, strict=True)
    ]
    unverified = [s for s in sentences if not s.verified]
    status: Literal["ok", "warnings", "failed"] = (
        "ok" if not unverified else "failed" if len(unverified) == len(sentences) else "warnings"
    )
    run.status = "ok" if status == "ok" else "rejected" if status == "failed" else "ok"
    checker = {
        "schema_version": SCHEMA_VERSION,
        "unverified": len(unverified),
        "problems": [
            {"sentence": i + 1, "problems": s.problems}
            for i, s in enumerate(sentences)
            if not s.verified
        ],
    }
    return Rationalisation(
        Rationale(language=language, detail=detail, sentences=sentences), run, checker, status
    )
