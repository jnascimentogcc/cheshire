"""The deterministic rule engine. Pure: no I/O, no LLM, no clock, no randomness."""

from __future__ import annotations

from collections.abc import Mapping

from cheshire.catalog.models import STATUS_ORDER, Catalog, Sbb, Status, Strength
from cheshire.engine.conditions import (
    Context,
    Fact,
    TraceTest,
    Tri,
    evaluate,
    unknown_attributes,
)
from cheshire.engine.model import (
    AbbResult,
    Activation,
    Coverage,
    EngineInputError,
    EngineResult,
    InterpreterOutput,
    PendingQuestion,
    RuleEvidence,
    SbbOutcome,
)

UNKNOWN = "unknown"


def build_facts(
    catalog: Catalog,
    interpreter: InterpreterOutput,
    answers: Mapping[str, str | list[str]],
) -> dict[str, Fact]:
    """Validate and merge facts. Answers override the interpreter. Unknown ids are rejected."""
    facts: dict[str, Fact] = {}
    entries: list[tuple[str, str | list[str], str]] = [
        (attr_id, av.value, av.source) for attr_id, av in interpreter.attributes.items()
    ]
    entries += [(attr_id, value, "answered") for attr_id, value in answers.items()]
    for attr_id, raw, source in entries:
        attr = catalog.attribute(attr_id)
        if attr is None:
            raise EngineInputError(f"unknown attribute {attr_id!r}")
        values = [raw] if isinstance(raw, str) else list(raw)
        if not values:
            raise EngineInputError(f"attribute {attr_id!r}: empty value")
        if len(values) > 1 and not attr.multi:
            raise EngineInputError(f"attribute {attr_id!r} is single-valued, got {values}")
        if values == [UNKNOWN]:
            facts.pop(attr_id, None)
            continue
        for value in values:
            if value not in attr.values:
                raise EngineInputError(f"attribute {attr_id!r}: unknown value {value!r}")
        facts[attr_id] = Fact(values=frozenset(values), source=source)
    return facts


def run(
    catalog: Catalog,
    interpreter: InterpreterOutput,
    answers: Mapping[str, str | list[str]] | None = None,
) -> EngineResult:
    """Evaluate the (effective) catalog against the facts. Same input -> same output."""
    facts = build_facts(catalog, interpreter, answers or {})

    identified = frozenset(m.id for m in interpreter.abbs)
    for abb_id in sorted(identified):
        if catalog.abb(abb_id) is None:
            raise EngineInputError(f"unknown ABB {abb_id!r}")

    # --- fixed point: ABBs are only ever added --------------------------------
    present = set(identified)
    changed = True
    while changed:
        changed = False
        ctx = Context(facts, frozenset(present))
        for rule in catalog.rules:
            if rule.activates not in present and evaluate(rule.when, ctx)[0] is True:
                present.add(rule.activates)
                changed = True
    ctx = Context(facts, frozenset(present))

    # --- final evaluation of every rule, for evidence -------------------------
    evidence: dict[str, list[RuleEvidence]] = {}
    causes: dict[str, set[str]] = {}  # unknown attribute -> ABBs it leaves indeterminate
    for rule in catalog.rules:
        result, tests = evaluate(rule.when, ctx)
        if result is False:
            continue
        evidence.setdefault(rule.activates, []).append(
            RuleEvidence(
                rule=rule.id,
                result=result,
                strength=rule.strength,
                status=rule.status,
                reason=rule.reason,
                tests=tests,
            )
        )
        if result is None:
            for attr_id in unknown_attributes(tests):
                causes.setdefault(attr_id, set()).add(rule.activates)

    in_result = set(present) | {
        a for a, ev in evidence.items() if any(e.result is None for e in ev)
    }

    abbs: list[AbbResult] = []
    for abb_id in sorted(in_result):
        origin = evidence.get(abb_id, [])
        true_rules = [e for e in origin if e.result is True]
        activation: Activation = (
            "identified"
            if abb_id in identified
            else "confirmed"
            if abb_id in present
            else "potential"
        )
        strength: Strength | None = (
            "requires"
            if any(e.strength == "requires" for e in true_rules)
            else "considers"
            if true_rules
            else None
        )
        statuses: list[Status] = [e.status for e in true_rules]
        validation: Status | None = None
        if statuses:
            weakest = min(statuses, key=_status_rank)
            validation = weakest
        sbbs = [_evaluate_sbb(sbb, ctx) for sbb in catalog.sbbs_for(abb_id)]
        for outcome, tests in sbbs:
            if outcome.result == "conditional":
                for attr_id in unknown_attributes(tests):
                    causes.setdefault(attr_id, set()).add(abb_id)
        outcomes = [o for o, _ in sbbs]
        coverage: Coverage = (
            "gap"
            if not outcomes
            else "covered"
            if any(o.result == "eligible" for o in outcomes)
            else "conditional"
            if any(o.result == "conditional" for o in outcomes)
            else "blocked"
        )
        abbs.append(
            AbbResult(
                id=abb_id,
                activation=activation,
                strength=strength,
                validation=validation,
                origin=origin,
                coverage=coverage,
                sbbs=outcomes,
            )
        )

    return EngineResult(abbs=abbs, pending_questions=_pending(catalog, ctx, causes))


def _status_rank(status: Status) -> int:
    return STATUS_ORDER[status]


def _evaluate_sbb(sbb: Sbb, ctx: Context) -> tuple[SbbOutcome, list[TraceTest]]:
    """Fixed decision order (docs/rule-language.md section 5). No ranking."""
    base = {"id": sbb.id, "name": sbb.name, "state": sbb.state, "status": sbb.status}
    if sbb.state == "prohibited":
        return SbbOutcome(
            **base, result="excluded", exclusion="prohibited", reason=sbb.reason_prohibited
        ), []

    tests: list[TraceTest] = []
    conditional = False

    # An absent not_applies_when never excludes (an empty condition would be vacuously true).
    not_applies: Tri = False
    not_tests: list[TraceTest] = []
    if not sbb.not_applies_when.is_empty():
        not_applies, not_tests = evaluate(sbb.not_applies_when, ctx)
    tests += not_tests
    if not_applies is True:
        return SbbOutcome(
            **base,
            result="excluded",
            exclusion="not_applies_when",
            reason=sbb.reason_not_applies,
            tests=tests,
        ), tests
    conditional = not_applies is None

    applies, applies_tests = evaluate(sbb.applies_when, ctx)
    tests += applies_tests
    if applies is False:
        return SbbOutcome(
            **base,
            result="excluded",
            exclusion="applies_when_not_met",
            reason="Its applicability conditions are not met.",
            tests=tests,
        ), tests
    conditional = conditional or applies is None

    notes: list[str] = []
    if conditional:
        notes = [f"depends on unknown: {a}" for a in sorted(unknown_attributes(tests))]
    return SbbOutcome(
        **base,
        result="conditional" if conditional else "eligible",
        notes=notes,
        tests=tests,
    ), tests


def _pending(catalog: Catalog, ctx: Context, causes: dict[str, set[str]]) -> list[PendingQuestion]:
    questions: list[PendingQuestion] = []
    for attr_id, abb_ids in causes.items():
        attr = catalog.attribute(attr_id)
        if attr is None or attr_id in ctx.facts:
            continue
        ask: Tri = evaluate(attr.ask_if, ctx)[0]
        if ask is False:
            continue
        if attr.layer == "extension" and not any(
            a in ctx.present_abbs for a in attr.applies_to_abbs
        ):
            continue
        questions.append(
            PendingQuestion(
                attribute=attr_id,
                question=attr.question,
                values=list(attr.values),
                multi=attr.multi,
                impact=sorted(abb_ids),
            )
        )
    return sorted(questions, key=lambda q: (-len(q.impact), q.attribute))
