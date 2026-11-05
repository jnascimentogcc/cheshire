"""Effective catalog for the file loader (docs/rule-language.md section 10).

With files there is one version per item, so "effective" reduces to: drop `draft`
items (unless a test run asks for them) and anything that references a dropped
item. The database layer applies the version rule (latest validated, else latest
proposed) before this point.
"""

from __future__ import annotations

from cheshire.catalog.models import Catalog, Condition


def _abb_refs(cond: Condition) -> set[str]:
    refs = set(cond.abb_present)
    if cond.unless is not None:
        refs |= _abb_refs(cond.unless)
    return refs


def _attr_refs(cond: Condition) -> set[str]:
    refs = set(cond.attributes)
    if cond.unless is not None:
        refs |= _attr_refs(cond.unless)
    return refs


def effective_catalog(catalog: Catalog, include_drafts: bool = False) -> Catalog:
    if include_drafts:
        return catalog
    abbs = [a for a in catalog.abbs if a.status != "draft"]
    abb_ids = {a.id for a in abbs}
    chars = [c for c in catalog.characteristics if c.status != "draft"]
    attrs = [
        a for a in catalog.attributes if a.status != "draft" and set(a.applies_to_abbs) <= abb_ids
    ]
    attr_ids = {a.id for a in attrs}
    # an attribute whose ask_if reads a dropped attribute is dropped too
    attrs = [
        a for a in attrs if _attr_refs(a.ask_if) <= attr_ids and _abb_refs(a.ask_if) <= abb_ids
    ]
    attr_ids = {a.id for a in attrs}
    char_ids = {c.id for c in chars}

    def usable(cond: Condition) -> bool:
        return _abb_refs(cond) <= abb_ids and _attr_refs(cond) <= attr_ids

    sbbs = [
        s
        for s in catalog.sbbs
        if s.status != "draft"
        and s.realises in abb_ids
        and usable(s.applies_when)
        and usable(s.not_applies_when)
        and set(s.characteristics) <= char_ids
    ]
    rules = [
        r
        for r in catalog.rules
        if r.status != "draft" and r.activates in abb_ids and usable(r.when)
    ]
    lenses = [lens for lens in catalog.lenses if lens.status != "draft"]
    return catalog.model_copy(
        update={
            "abbs": abbs,
            "attributes": attrs,
            "characteristics": chars,
            "sbbs": sbbs,
            "rules": rules,
            "lenses": lenses,
        }
    )
