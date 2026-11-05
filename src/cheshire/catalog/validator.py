"""Automatic catalog validation (docs/rule-language.md section 10)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from cheshire.catalog.models import RESERVED_CONDITION_KEYS, Catalog, Condition


@dataclass(frozen=True)
class Issue:
    severity: Literal["error", "warning"]
    code: str
    subject: str  # e.g. "rule R-001"
    message: str

    def __str__(self) -> str:
        return f"{self.severity}: [{self.code}] {self.subject}: {self.message}"


def _walk(cond: Condition, in_except: bool = False) -> Iterator[tuple[Condition, bool]]:
    yield cond, in_except
    if cond.unless is not None:
        yield from _walk(cond.unless, True)


def validate_catalog(catalog: Catalog) -> list[Issue]:
    """Return every problem found; errors make the catalog unusable, warnings do not."""
    issues: list[Issue] = []

    def err(code: str, subject: str, message: str) -> None:
        issues.append(Issue("error", code, subject, message))

    def warn(code: str, subject: str, message: str) -> None:
        issues.append(Issue("warning", code, subject, message))

    # --- duplicate ids -------------------------------------------------------
    for kind, items in (
        ("attribute", catalog.attributes),
        ("characteristic", catalog.characteristics),
        ("lens", catalog.lenses),
        ("abb", catalog.abbs),
        ("sbb", catalog.sbbs),
        ("rule", catalog.rules),
    ):
        for item_id, n in Counter(i.id for i in items).items():
            if n > 1:
                err("duplicate-id", f"{kind} {item_id}", f"declared {n} times")

    attributes = {a.id: a for a in catalog.attributes}
    abbs = {a.id: a for a in catalog.abbs}
    characteristics = {c.id: c for c in catalog.characteristics}

    # --- conditions ----------------------------------------------------------
    def check_condition(subject: str, cond: Condition) -> None:
        if cond.unless is not None and cond.unless.unless is not None:
            err("nested-except", subject, "except cannot contain another except")
        for node, in_except in _walk(cond):
            for attr_id, values in node.attributes.items():
                attr = attributes.get(attr_id)
                if attr is None:
                    err("unknown-attribute", subject, f"uses undeclared attribute {attr_id!r}")
                    continue
                for value in values:
                    if value not in attr.values:
                        err(
                            "unknown-value",
                            subject,
                            f"{value!r} is not a declared value of attribute {attr_id!r}",
                        )
            for abb_id in node.abb_present:
                if abb_id not in abbs:
                    err("unknown-abb", subject, f"abb_present refers to undeclared ABB {abb_id!r}")
                elif in_except:
                    err(
                        "abb-present-in-except",
                        subject,
                        "abb_present inside except is not allowed: the rule would stop being "
                        "monotonic and the fixed point could flip-flop",
                    )

    # --- attributes ----------------------------------------------------------
    for attr in catalog.attributes:
        subject = f"attribute {attr.id}"
        if attr.id in RESERVED_CONDITION_KEYS:
            err("reserved-id", subject, f"{attr.id!r} is a reserved condition key")
        if not attr.values:
            err("invalid-attribute", subject, "declares no values")
        if len(set(attr.values)) != len(attr.values):
            err("invalid-attribute", subject, "declares duplicate values")
        if "unknown" in attr.values:
            err("invalid-attribute", subject, "'unknown' is implicit and must not be declared")
        if attr.layer == "extension" and not attr.applies_to_abbs:
            err("invalid-attribute", subject, "an extension attribute needs applies_to_abbs")
        if attr.layer == "core" and attr.applies_to_abbs:
            err("invalid-attribute", subject, "applies_to_abbs is only for extension attributes")
        for abb_id in attr.applies_to_abbs:
            if abb_id not in abbs:
                err("unknown-abb", subject, f"applies_to_abbs refers to undeclared ABB {abb_id!r}")
        check_condition(f"{subject} (ask_if)", attr.ask_if)

    # --- characteristics -----------------------------------------------------
    for decl in catalog.characteristics:
        if len(set(decl.values)) != len(decl.values):
            err("invalid-characteristic", f"characteristic {decl.id}", "duplicate values")

    # --- lenses --------------------------------------------------------------
    for lens in catalog.lenses:
        subject = f"lens {lens.id}"
        for attr_id in lens.feeds_attributes:
            if attr_id not in attributes:
                err("unknown-attribute", subject, f"feeds_attributes: undeclared {attr_id!r}")
        for abb_id in lens.typical_dependencies:
            if abb_id not in abbs:
                err("unknown-abb", subject, f"typical_dependencies: undeclared ABB {abb_id!r}")

    # --- SBBs ----------------------------------------------------------------
    for sbb in catalog.sbbs:
        subject = f"sbb {sbb.id}"
        if sbb.realises not in abbs:
            err("unknown-abb", subject, f"realises undeclared ABB {sbb.realises!r}")
        check_condition(f"{subject} (applies_when)", sbb.applies_when)
        check_condition(f"{subject} (not_applies_when)", sbb.not_applies_when)
        for key, value in sbb.characteristics.items():
            ch = characteristics.get(key)
            if ch is None:
                err("unknown-characteristic", subject, f"undeclared characteristic {key!r}")
            elif value not in ch.values:
                err(
                    "unknown-characteristic-value",
                    subject,
                    f"{value!r} is not a declared value of characteristic {key!r}",
                )
        if sbb.state == "prohibited" and not sbb.reason_prohibited:
            err("missing-reason", subject, "a prohibited SBB needs reason_prohibited")
        if not sbb.not_applies_when.is_empty() and not sbb.reason_not_applies:
            warn("missing-reason", subject, "not_applies_when without reason_not_applies")

    # --- rules ---------------------------------------------------------------
    for rule in catalog.rules:
        subject = f"rule {rule.id}"
        if rule.activates not in abbs:
            err("unknown-abb", subject, f"activates undeclared ABB {rule.activates!r}")
        check_condition(subject, rule.when)

    # --- dependency cycles among activation rules ----------------------------
    edges: dict[str, dict[str, str]] = {}  # abb present -> activated abb -> rule id
    for rule in catalog.rules:
        for node, _ in _walk(rule.when):
            for src in node.abb_present:
                edges.setdefault(src, {})[rule.activates] = rule.id
    for cycle in _find_cycles(edges):
        path = " -> ".join(cycle)
        rules = ", ".join(edges[a][b] for a, b in pairwise(cycle))
        err("cycle", f"abb {cycle[0]}", f"activation cycle {path} (rules {rules})")

    # --- dangling references to excluded (draft) items -----------------------
    def draft_abb(abb_id: str) -> bool:
        abb = abbs.get(abb_id)
        return abb is not None and abb.status == "draft"

    for rule in catalog.rules:
        if rule.status == "draft":
            continue
        refs = {rule.activates}
        for node, _ in _walk(rule.when):
            refs.update(node.abb_present)
        for abb_id in sorted(r for r in refs if draft_abb(r)):
            err("dangling-reference", f"rule {rule.id}", f"references draft ABB {abb_id!r}")
    for sbb in catalog.sbbs:
        if sbb.status != "draft" and draft_abb(sbb.realises):
            err("dangling-reference", f"sbb {sbb.id}", f"realises draft ABB {sbb.realises!r}")

    # --- warnings: thin coverage of cross-cutting ABBs -----------------------
    for abb in catalog.abbs:
        if not abb.cross_cutting:
            continue
        sbbs = [
            s for s in catalog.sbbs_for(abb.id) if s.state != "prohibited" and s.status != "draft"
        ]
        if len(sbbs) < 2:
            warn(
                "thin-cross-cutting",
                f"abb {abb.id}",
                f"cross-cutting ABB with {len(sbbs)} effective SBB(s); fewer than two",
            )
        if sbbs and all(
            not s.applies_when.is_empty() or not s.not_applies_when.is_empty() for s in sbbs
        ):
            warn("conditional-cross-cutting", f"abb {abb.id}", "all its SBBs are conditional")

    return issues


def _find_cycles(edges: dict[str, dict[str, str]]) -> list[list[str]]:
    """Return one representative cycle per strongly cyclic region (DFS, deterministic)."""
    cycles: list[list[str]] = []
    state: dict[str, int] = {}  # 1 = on stack, 2 = done
    stack: list[str] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in sorted(edges.get(node, {})):
            if state.get(nxt) == 1:
                cycles.append([*stack[stack.index(nxt) :], nxt])
            elif nxt not in state:
                visit(nxt)
        stack.pop()
        state[node] = 2

    for start in sorted(edges):
        if start not in state:
            visit(start)
    return cycles


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)
