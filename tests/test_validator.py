"""Each invalid-catalog case from docs/rule-language.md section 10 is rejected."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest

from cheshire.catalog.effective import effective_catalog
from cheshire.catalog.loader import CatalogLoadError, catalog_from_dict
from cheshire.catalog.models import Catalog
from cheshire.catalog.validator import Issue, has_errors, validate_catalog


def base() -> dict[str, Any]:
    return {
        "attributes": [
            {
                "id": "volume",
                "layer": "core",
                "values": ["low", "high"],
                "question": "How many?",
            },
            {
                "id": "file_format",
                "layer": "extension",
                "values": ["csv"],
                "question": "Format?",
                "applies_to_abbs": ["a"],
            },
        ],
        "characteristics": [{"id": "cost_model", "values": ["fixed", "per-use"]}],
        "lenses": [
            {
                "id": "perf",
                "name": "Performance",
                "question": "?",
                "feeds_attributes": ["volume"],
                "typical_dependencies": ["a"],
            }
        ],
        "abbs": [
            {"id": "a", "name": "A", "domain": "d"},
            {"id": "b", "name": "B", "domain": "d"},
            {"id": "c", "name": "C", "domain": "d"},
        ],
        "sbbs": [
            {
                "id": "s1",
                "name": "S1",
                "realises": "a",
                "state": "recommended",
                "applies_when": {"volume": ["low"]},
                "characteristics": {"cost_model": "fixed"},
            }
        ],
        "rules": [
            {
                "id": "R-1",
                "when": {"abb_present": ["a"], "volume": ["high"]},
                "activates": "b",
                "strength": "requires",
            }
        ],
    }


def issues_for(raw: dict[str, Any]) -> list[Issue]:
    return validate_catalog(catalog_from_dict(raw))


def codes(issues: list[Issue], severity: str = "error") -> set[str]:
    return {i.code for i in issues if i.severity == severity}


def test_base_catalog_is_valid() -> None:
    assert not has_errors(issues_for(base()))


def test_example_catalog_has_no_errors(example_catalog: Catalog) -> None:
    assert not has_errors(validate_catalog(example_catalog))


def mutate(fn: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    raw = deepcopy(base())
    fn(raw)
    return raw


INVALID: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
    "rule uses undeclared attribute": (
        lambda r: r["rules"][0]["when"].update(nope=["x"]),
        "unknown-attribute",
    ),
    "rule uses undeclared value": (
        lambda r: r["rules"][0]["when"].update(volume=["huge"]),
        "unknown-value",
    ),
    "sbb condition uses undeclared value": (
        lambda r: r["sbbs"][0]["applies_when"].update(volume=["huge"]),
        "unknown-value",
    ),
    "ask_if uses undeclared attribute": (
        lambda r: r["attributes"][0].update(ask_if={"nope": ["x"]}),
        "unknown-attribute",
    ),
    "rule activates undeclared ABB": (
        lambda r: r["rules"][0].update(activates="zzz"),
        "unknown-abb",
    ),
    "abb_present refers to undeclared ABB": (
        lambda r: r["rules"][0]["when"].update(abb_present=["zzz"]),
        "unknown-abb",
    ),
    "sbb realises undeclared ABB": (
        lambda r: r["sbbs"][0].update(realises="zzz"),
        "unknown-abb",
    ),
    "extension attribute scoped to undeclared ABB": (
        lambda r: r["attributes"][1].update(applies_to_abbs=["zzz"]),
        "unknown-abb",
    ),
    "lens feeds undeclared attribute": (
        lambda r: r["lenses"][0].update(feeds_attributes=["zzz"]),
        "unknown-attribute",
    ),
    "lens depends on undeclared ABB": (
        lambda r: r["lenses"][0].update(typical_dependencies=["zzz"]),
        "unknown-abb",
    ),
    "undeclared characteristic": (
        lambda r: r["sbbs"][0]["characteristics"].update(colour="red"),
        "unknown-characteristic",
    ),
    "undeclared characteristic value": (
        lambda r: r["sbbs"][0]["characteristics"].update(cost_model="free"),
        "unknown-characteristic-value",
    ),
    "duplicate ABB id": (
        lambda r: r["abbs"].append({"id": "a", "name": "again", "domain": "d"}),
        "duplicate-id",
    ),
    "duplicate rule id": (
        lambda r: r["rules"].append(deepcopy(r["rules"][0])),
        "duplicate-id",
    ),
    "extension attribute without scope": (
        lambda r: r["attributes"][1].update(applies_to_abbs=[]),
        "invalid-attribute",
    ),
    "core attribute with scope": (
        lambda r: r["attributes"][0].update(applies_to_abbs=["a"]),
        "invalid-attribute",
    ),
    "attribute declares unknown explicitly": (
        lambda r: r["attributes"][0]["values"].append("unknown"),
        "invalid-attribute",
    ),
    "attribute without values": (
        lambda r: r["attributes"][0].update(values=[]),
        "invalid-attribute",
    ),
    "attribute named like a reserved key": (
        lambda r: r["attributes"][0].update(id="except"),
        "reserved-id",
    ),
    "abb_present inside except": (
        lambda r: r["rules"][0]["when"].update({"except": {"abb_present": ["c"]}}),
        "abb-present-in-except",
    ),
    "rule depends on a draft ABB": (
        lambda r: r["abbs"][1].update(status="draft"),
        "dangling-reference",
    ),
    "sbb realises a draft ABB": (
        lambda r: r["abbs"][0].update(status="draft"),
        "dangling-reference",
    ),
}


@pytest.mark.parametrize("name", list(INVALID))
def test_invalid_catalog_is_rejected(name: str) -> None:
    fn, expected_code = INVALID[name]
    issues = issues_for(mutate(fn))
    assert expected_code in codes(issues), [str(i) for i in issues]
    assert has_errors(issues)


@pytest.mark.parametrize(
    "fn",
    [
        lambda r: r["rules"][0].update(strength="maybe"),
        lambda r: r["rules"][0].update(status="approved"),
        lambda r: r["sbbs"][0].update(state="great"),
        lambda r: r["attributes"][0].update(layer="middle"),
        lambda r: r["rules"][0].update(surprise=1),
        lambda r: r["rules"][0]["when"].update(volume="high"),  # must be a list
        lambda r: r["rules"][0]["when"].update(volume=[True]),  # YAML `yes` parsed as bool
    ],
    ids=["strength", "status", "state", "layer", "extra-key", "scalar-test", "bool-value"],
)
def test_schema_violations_fail_to_load(fn: Callable[[dict[str, Any]], None]) -> None:
    with pytest.raises(CatalogLoadError):
        catalog_from_dict(mutate(fn))


# --- cycles --------------------------------------------------------------------


def rule(rule_id: str, src: str, dst: str) -> dict[str, Any]:
    return {
        "id": rule_id,
        "when": {"abb_present": [src]},
        "activates": dst,
        "strength": "considers",
    }


def test_direct_cycle_is_rejected() -> None:
    raw = mutate(lambda r: r["rules"].extend([rule("R-2", "b", "a")]))
    issues = issues_for(raw)
    assert "cycle" in codes(issues)


def test_indirect_cycle_is_rejected_and_names_the_path() -> None:
    raw = mutate(lambda r: r["rules"].extend([rule("R-2", "b", "c"), rule("R-3", "c", "a")]))
    cycle = [i for i in issues_for(raw) if i.code == "cycle"]
    assert cycle
    assert "R-1" in cycle[0].message and "R-2" in cycle[0].message and "R-3" in cycle[0].message


def test_self_activation_is_a_cycle() -> None:
    raw = mutate(lambda r: r["rules"].append(rule("R-2", "a", "a")))
    assert "cycle" in codes(issues_for(raw))


def test_cycle_through_nested_alternatives_is_found() -> None:
    raw = mutate(
        lambda r: r["rules"].append(
            {
                "id": "R-2",
                "when": {"abb_present": ["b", "c"]},
                "activates": "a",
                "strength": "considers",
            }
        )
    )
    assert "cycle" in codes(issues_for(raw))


def test_diamond_is_not_a_cycle() -> None:
    raw = mutate(
        lambda r: r["rules"].extend(
            [rule("R-2", "a", "c"), rule("R-3", "b", "d"), rule("R-4", "c", "d")]
        )
    )
    raw["abbs"].append({"id": "d", "name": "D", "domain": "d"})
    assert "cycle" not in codes(issues_for(raw))


# --- warnings and status -------------------------------------------------------


def test_thin_cross_cutting_abb_is_a_warning_not_an_error() -> None:
    raw = mutate(lambda r: r["abbs"][2].update(cross_cutting=True))
    issues = issues_for(raw)
    assert "thin-cross-cutting" in codes(issues, "warning")
    assert not has_errors(issues)


def test_cross_cutting_abb_with_only_conditional_sbbs_warns() -> None:
    def fn(r: dict[str, Any]) -> None:
        r["abbs"][0]["cross_cutting"] = True
        r["sbbs"].append(
            {
                "id": "s2",
                "name": "S2",
                "realises": "a",
                "state": "accepted",
                "not_applies_when": {"volume": ["high"]},
                "reason_not_applies": "x",
            }
        )

    assert "conditional-cross-cutting" in codes(issues_for(mutate(fn)), "warning")


def test_proposed_items_are_valid_but_draft_dependencies_are_not() -> None:
    raw = mutate(lambda r: r["rules"][0].update(status="proposed"))
    assert not has_errors(issues_for(raw))


def test_draft_rule_may_reference_draft_abb() -> None:
    def fn(r: dict[str, Any]) -> None:
        r["abbs"][1]["status"] = "draft"
        r["rules"][0]["status"] = "draft"

    assert not has_errors(issues_for(mutate(fn)))


def test_effective_catalog_drops_drafts_and_their_dependents() -> None:
    def fn(r: dict[str, Any]) -> None:
        r["abbs"][1]["status"] = "draft"

    catalog = catalog_from_dict(mutate(fn))
    effective = effective_catalog(catalog)
    assert [a.id for a in effective.abbs] == ["a", "c"]
    assert effective.rules == []  # R-1 activates the dropped ABB
    assert len(effective_catalog(catalog, include_drafts=True).abbs) == 3
