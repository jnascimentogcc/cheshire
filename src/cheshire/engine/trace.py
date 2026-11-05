"""Turn an engine result into addressable trace entries.

The trace is the source of truth for the rationale (invariant 6): the Writer may only
cite these entries, and the checker rejects names that are not in them. Text is built
here, deterministically, from the engine output and the catalog; no LLM is involved.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from cheshire.catalog.models import Catalog
from cheshire.engine.conditions import TraceTest
from cheshire.engine.model import AbbResult, EngineResult, SbbOutcome


class TraceEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: str  # abb:<abb> | rule:<abb>:<rule> | sbb:<abb>:<sbb> | question:<attribute>
    kind: str  # abb | rule | sbb | question
    abb: str | None
    text: str
    names: tuple[str, ...]  # catalog names and ids this entry mentions


def describe_tests(tests: list[TraceTest], indent: str = "") -> list[str]:
    lines: list[str] = []
    for t in tests:
        outcome = {True: "true", False: "false", None: "unknown"}[t.result]
        detail = ""
        if t.value is not None:
            shown = ", ".join(t.value) if isinstance(t.value, list) else t.value
            detail = f" (value: {shown}; source: {t.source})"
        lines.append(f"{indent}- {t.test}: {outcome}{detail}")
        lines += describe_tests(t.children, indent + "  ")
    return lines


def _abb_entry(abb: AbbResult, name: str) -> TraceEntry:
    parts = [f"Building block {name} ({abb.id}): activation {abb.activation}"]
    if abb.strength:
        parts.append(f"strength {abb.strength}")
    if abb.validation:
        parts.append(f"rules behind it are {abb.validation}")
    parts.append(f"coverage {abb.coverage}")
    if abb.coverage == "gap":
        parts.append("no solution is registered in the catalog for it")
    return TraceEntry(
        ref=f"abb:{abb.id}",
        kind="abb",
        abb=abb.id,
        text="; ".join(parts) + ".",
        names=(abb.id, name),
    )


def _sbb_entry(abb: AbbResult, sbb: SbbOutcome) -> TraceEntry:
    text = f"Solution {sbb.name} ({sbb.id}) for {abb.id}: {sbb.result}; catalog state {sbb.state}"
    if sbb.exclusion:
        text += f"; excluded because {sbb.exclusion}"
        if sbb.reason:
            text += f" ({sbb.reason})"
    text += "." + "".join(f" {n}." for n in sbb.notes)
    return TraceEntry(
        ref=f"sbb:{abb.id}:{sbb.id}",
        kind="sbb",
        abb=abb.id,
        text=text,
        names=(sbb.id, sbb.name),
    )


def build_trace(result: EngineResult, catalog: Catalog) -> list[TraceEntry]:
    entries: list[TraceEntry] = []
    for abb in result.abbs:
        item = catalog.abb(abb.id)
        name = item.name if item else abb.id
        entries.append(_abb_entry(abb, name))
        for ev in abb.origin:
            kind = {True: "applied", None: "undecided (a needed answer is missing)"}[ev.result]
            body = "\n".join(describe_tests(ev.tests))
            entries.append(
                TraceEntry(
                    ref=f"rule:{abb.id}:{ev.rule}",
                    kind="rule",
                    abb=abb.id,
                    text=(
                        f"Rule {ev.rule} for {abb.id} {kind}; strength {ev.strength}; "
                        f"status {ev.status}. Reason: {ev.reason}\n{body}"
                    ),
                    names=(abb.id, name),
                )
            )
        entries += [_sbb_entry(abb, s) for s in abb.sbbs]
    for q in result.pending_questions:
        names = tuple(a for abb_id in q.impact for a in (abb_id, _name(catalog, abb_id)))
        entries.append(
            TraceEntry(
                ref=f"question:{q.attribute}",
                kind="question",
                abb=None,
                text=(
                    f"Open question about {q.attribute}: {q.question} "
                    f"Answering it could change: {', '.join(q.impact)}."
                ),
                names=names,
            )
        )
    return entries


def _name(catalog: Catalog, abb_id: str) -> str:
    abb = catalog.abb(abb_id)
    return abb.name if abb else abb_id
