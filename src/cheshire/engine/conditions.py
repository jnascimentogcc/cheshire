"""Three-valued condition evaluation (docs/rule-language.md section 2).

`True` / `False` / `None` (indeterminate). `None` is a first-class value: a missing
answer is never assumed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from cheshire.catalog.models import Condition

Tri = bool | None


def kleene_and(results: list[Tri]) -> Tri:
    """Any false -> false; else any indeterminate -> indeterminate; else true."""
    if any(r is False for r in results):
        return False
    if any(r is None for r in results):
        return None
    return True


@dataclass(frozen=True)
class Fact:
    values: frozenset[str]
    source: str


@dataclass(frozen=True)
class Context:
    """What a condition is evaluated against. Absent attribute = unknown."""

    facts: Mapping[str, Fact]
    present_abbs: frozenset[str]


class TraceTest(BaseModel):
    """One evaluated test, as it appears in the trace."""

    model_config = ConfigDict(frozen=True)

    test: str
    result: Tri
    attribute: str | None = None
    value: str | list[str] | None = None
    source: str | None = None
    children: list[TraceTest] = Field(default_factory=list)


def evaluate(cond: Condition, ctx: Context) -> tuple[Tri, list[TraceTest]]:
    records: list[TraceTest] = []

    for attr_id in sorted(cond.attributes):
        allowed = cond.attributes[attr_id]
        label = f"{attr_id} in [{', '.join(allowed)}]"
        fact = ctx.facts.get(attr_id)
        if fact is None:
            records.append(TraceTest(test=label, result=None, attribute=attr_id))
            continue
        shown: str | list[str] = (
            sorted(fact.values)[0] if len(fact.values) == 1 else sorted(fact.values)
        )
        records.append(
            TraceTest(
                test=label,
                result=bool(fact.values & set(allowed)),
                attribute=attr_id,
                value=shown,
                source=fact.source,
            )
        )

    if cond.abb_present:
        label = f"abb_present[{', '.join(cond.abb_present)}]"
        records.append(
            TraceTest(test=label, result=any(a in ctx.present_abbs for a in cond.abb_present))
        )

    if cond.unless is not None:
        inner, children = evaluate(cond.unless, ctx)
        negated: Tri = None if inner is None else not inner
        records.append(TraceTest(test="except", result=negated, children=children))

    return kleene_and([r.result for r in records]), records


def unknown_attributes(records: list[TraceTest]) -> set[str]:
    """Attributes whose unknown value made a test indeterminate."""
    found: set[str] = set()
    for rec in records:
        if rec.result is None and rec.attribute is not None:
            found.add(rec.attribute)
        found |= unknown_attributes(rec.children)
    return found
