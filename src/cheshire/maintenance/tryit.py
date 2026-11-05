"""The rule editor's *Try it* panel: one condition against hand-set facts (no I/O).

Uses the engine's own evaluator, so the answer and the trace are exactly what a
consultation would show. Nothing is stored.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from cheshire.catalog.models import Catalog, Condition
from cheshire.engine.conditions import Context, Fact, TraceTest, evaluate
from cheshire.engine.trace import describe_tests

UNKNOWN = "unknown"


class TryInputError(ValueError):
    """The facts or the condition do not fit the catalog vocabulary."""


class TryResult(BaseModel):
    result: bool | None  # None = indeterminate
    outcome: str  # true | false | indeterminate
    tests: list[TraceTest]
    text: list[str]
    unknown_attributes: list[str]


def check_condition(catalog: Catalog, cond: Condition) -> list[str]:
    """Unknown attributes, values or ABBs referenced by the condition."""
    problems: list[str] = []
    abb_ids = {a.id for a in catalog.abbs}
    stack: list[Condition] = [cond]
    while stack:
        c = stack.pop()
        for attr_id, values in c.attributes.items():
            attr = catalog.attribute(attr_id)
            if attr is None:
                problems.append(f"unknown attribute {attr_id!r}")
                continue
            problems += [
                f"attribute {attr_id!r} has no value {v!r}" for v in values if v not in attr.values
            ]
        problems += [f"unknown ABB {a!r}" for a in c.abb_present if a not in abb_ids]
        if c.unless is not None:
            stack.append(c.unless)
    return problems


def _unknown(tests: list[TraceTest]) -> set[str]:
    found: set[str] = set()
    for t in tests:
        if t.result is None and t.attribute is not None:
            found.add(t.attribute)
        found |= _unknown(t.children)
    return found


def try_condition(
    catalog: Catalog,
    cond: Condition,
    attributes: Mapping[str, str | list[str]],
    abbs: list[str],
) -> TryResult:
    problems = check_condition(catalog, cond)
    if problems:
        raise TryInputError("; ".join(problems))
    facts: dict[str, Fact] = {}
    for attr_id, raw in attributes.items():
        attr = catalog.attribute(attr_id)
        if attr is None:
            raise TryInputError(f"unknown attribute {attr_id!r}")
        values = [raw] if isinstance(raw, str) else list(raw)
        if values == [UNKNOWN]:
            continue  # absent = unknown (invariant 3)
        if not values:
            raise TryInputError(f"attribute {attr_id!r}: empty value")
        if len(values) > 1 and not attr.multi:
            raise TryInputError(f"attribute {attr_id!r} is single-valued")
        for v in values:
            if v not in attr.values:
                raise TryInputError(f"attribute {attr_id!r} has no value {v!r}")
        facts[attr_id] = Fact(values=frozenset(values), source="answered")
    known_abbs = {a.id for a in catalog.abbs}
    for abb in abbs:
        if abb not in known_abbs:
            raise TryInputError(f"unknown ABB {abb!r}")
    result, tests = evaluate(cond, Context(facts, frozenset(abbs)))
    return TryResult(
        result=result,
        outcome={True: "true", False: "false", None: "indeterminate"}[result],
        tests=tests,
        text=describe_tests(tests),
        unknown_attributes=sorted(_unknown(tests)),
    )
