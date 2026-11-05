"""Engine behaviours that the four scenarios do not pin down."""

from typing import Any

import pytest

from cheshire.catalog.loader import catalog_from_dict
from cheshire.catalog.models import Catalog
from cheshire.engine.model import EngineInputError, InterpreterOutput
from cheshire.engine.run import run


def make(**overrides: Any) -> Catalog:
    raw: dict[str, Any] = {
        "attributes": [
            {"id": "p", "layer": "core", "values": ["no", "yes"], "question": "P?"},
            {
                "id": "q",
                "layer": "core",
                "values": ["no", "yes"],
                "question": "Q?",
                "ask_if": {"p": ["yes"]},
            },
            {"id": "r", "layer": "core", "values": ["m", "n"], "multi": True, "question": "R?"},
        ],
        "characteristics": [],
        "lenses": [],
        "abbs": [{"id": x, "name": x, "domain": "d"} for x in ("a", "b", "c")],
        "sbbs": [],
        "rules": [],
    }
    raw.update(overrides)
    return catalog_from_dict(raw)


def interp(abbs: list[str] = (), attrs: dict[str, Any] | None = None) -> InterpreterOutput:  # type: ignore[assignment]
    return InterpreterOutput.model_validate(
        {
            "abbs": [{"id": a} for a in abbs],
            "attributes": {k: {"value": v, "source": "stated"} for k, v in (attrs or {}).items()},
        }
    )


def rule(
    rule_id: str,
    when: dict[str, Any],
    activates: str,
    strength: str = "requires",
    status: str = "validated",
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "when": when,
        "activates": activates,
        "strength": strength,
        "status": status,
    }


def test_chained_rules_reach_a_fixed_point() -> None:
    catalog = make(
        rules=[
            rule("R-2", {"abb_present": ["b"]}, "c"),
            rule("R-1", {"abb_present": ["a"]}, "b"),
        ]
    )
    result = run(catalog, interp(["a"]))
    assert {a.id: a.activation for a in result.abbs} == {
        "a": "identified",
        "b": "confirmed",
        "c": "confirmed",
    }


def test_rule_order_does_not_change_the_result() -> None:
    rules = [rule("R-1", {"abb_present": ["a"]}, "b"), rule("R-2", {"abb_present": ["b"]}, "c")]
    forward = run(make(rules=rules), interp(["a"]))
    backward = run(make(rules=list(reversed(rules))), interp(["a"]))
    assert [a.id for a in forward.abbs] == [a.id for a in backward.abbs]
    assert [a.activation for a in forward.abbs] == [a.activation for a in backward.abbs]


def test_strength_is_the_strongest_true_rule_and_validation_the_weakest() -> None:
    catalog = make(
        rules=[
            rule("R-1", {"p": ["yes"]}, "b", "considers", "validated"),
            rule("R-2", {"p": ["yes"]}, "b", "requires", "proposed"),
        ]
    )
    b = run(catalog, interp(attrs={"p": "yes"})).abb("b")
    assert b is not None
    assert (b.strength, b.validation) == ("requires", "proposed")


def test_indeterminate_rule_alone_makes_a_potential_abb_without_strength() -> None:
    b = run(make(rules=[rule("R-1", {"p": ["yes"]}, "b")]), interp()).abb("b")
    assert b is not None
    assert (b.activation, b.strength, b.validation) == ("potential", None, None)
    assert b.origin[0].result is None


def test_false_rule_leaves_no_trace() -> None:
    result = run(make(rules=[rule("R-1", {"p": ["yes"]}, "b")]), interp(attrs={"p": "no"}))
    assert result.abbs == []


def test_unknown_stays_unknown_and_is_asked_for() -> None:
    result = run(make(rules=[rule("R-1", {"p": ["yes"]}, "b")]), interp())
    assert [q.attribute for q in result.pending_questions] == ["p"]
    assert result.pending_questions[0].impact == ["b"]


def test_answered_question_disappears() -> None:
    catalog = make(rules=[rule("R-1", {"p": ["yes"]}, "b")])
    result = run(catalog, interp(), {"p": "yes"})
    assert result.pending_questions == []
    b = result.abb("b")
    assert b is not None and b.activation == "confirmed"


def test_answers_override_the_interpreter_and_record_their_source() -> None:
    catalog = make(rules=[rule("R-1", {"p": ["yes"]}, "b")])
    result = run(catalog, interp(attrs={"p": "no"}), {"p": "yes"})
    b = result.abb("b")
    assert b is not None
    assert b.origin[0].tests[0].source == "answered"


def test_answering_unknown_explicitly_keeps_it_unknown() -> None:
    catalog = make(rules=[rule("R-1", {"p": ["yes"]}, "b")])
    result = run(catalog, interp(attrs={"p": "yes"}), {"p": "unknown"})
    assert [q.attribute for q in result.pending_questions] == ["p"]


def test_ask_if_false_suppresses_the_question() -> None:
    catalog = make(
        rules=[rule("R-1", {"q": ["yes"]}, "b")],
    )
    # p = no -> ask_if of q is false -> do not ask q
    assert run(catalog, interp(attrs={"p": "no"})).pending_questions == []
    # p unknown -> ask_if indeterminate -> ask both, q is asked, p is not (no rule needs it)
    assert [q.attribute for q in run(catalog, interp()).pending_questions] == ["q"]


def test_questions_ordered_by_impact_then_id() -> None:
    catalog = make(
        rules=[
            rule("R-1", {"q": ["yes"]}, "b"),
            rule("R-2", {"p": ["yes"]}, "b"),
            rule("R-3", {"p": ["yes"]}, "c"),
            rule("R-4", {"r": ["m"]}, "c"),
        ]
    )
    order = [q.attribute for q in run(catalog, interp()).pending_questions]
    assert order == ["p", "q", "r"]  # p: 2 ABBs; q and r: 1 each, then alphabetical


def test_multi_valued_answer() -> None:
    catalog = make(rules=[rule("R-1", {"r": ["n"]}, "b")])
    assert run(catalog, interp(attrs={"r": ["m", "n"]})).abb("b") is not None
    assert run(catalog, interp(attrs={"r": ["m"]})).abb("b") is None


def sbb(sbb_id: str, **kw: Any) -> dict[str, Any]:
    return {"id": sbb_id, "name": sbb_id, "realises": "a", "state": "recommended", **kw}


def test_sbb_without_conditions_is_always_eligible() -> None:
    a = run(make(sbbs=[sbb("s")]), interp(["a"])).abb("a")
    assert a is not None and a.coverage == "covered" and a.ids("eligible") == ["s"]


def test_abb_without_sbbs_is_a_gap() -> None:
    a = run(make(), interp(["a"])).abb("a")
    assert a is not None and a.coverage == "gap"


def test_prohibited_is_excluded_even_when_conditions_hold() -> None:
    a = run(make(sbbs=[sbb("s", state="prohibited", reason_prohibited="no")]), interp(["a"])).abb(
        "a"
    )
    assert a is not None and a.coverage == "blocked"
    assert a.sbbs[0].exclusion == "prohibited" and a.sbbs[0].reason == "no"


def test_not_applies_when_true_wins_over_applies_when_unknown() -> None:
    catalog = make(sbbs=[sbb("s", not_applies_when={"p": ["yes"]}, applies_when={"q": ["yes"]})])
    a = run(catalog, interp(["a"], {"p": "yes"})).abb("a")
    assert a is not None and a.sbbs[0].exclusion == "not_applies_when"


def test_applies_when_false_wins_over_not_applies_when_unknown() -> None:
    catalog = make(sbbs=[sbb("s", not_applies_when={"p": ["yes"]}, applies_when={"q": ["yes"]})])
    a = run(catalog, interp(["a"], {"q": "no"})).abb("a")
    assert a is not None and a.sbbs[0].exclusion == "applies_when_not_met"


def test_conditional_sbb_asks_for_the_attribute() -> None:
    catalog = make(sbbs=[sbb("s", applies_when={"p": ["yes"]})])
    result = run(catalog, interp(["a"]))
    a = result.abb("a")
    assert a is not None and a.coverage == "conditional"
    assert a.sbbs[0].notes == ["depends on unknown: p"]
    assert [q.attribute for q in result.pending_questions] == ["p"]


def test_extension_attribute_asked_only_when_its_abb_is_present() -> None:
    catalog = make(
        attributes=[
            {
                "id": "x",
                "layer": "extension",
                "values": ["u", "v"],
                "question": "X?",
                "applies_to_abbs": ["b"],
            },
        ],
        sbbs=[sbb("s", applies_when={"x": ["u"]})],
    )
    assert run(catalog, interp(["a"])).pending_questions == []
    catalog2 = make(
        attributes=[
            {
                "id": "x",
                "layer": "extension",
                "values": ["u", "v"],
                "question": "X?",
                "applies_to_abbs": ["a"],
            },
        ],
        sbbs=[sbb("s", applies_when={"x": ["u"]})],
    )
    assert [q.attribute for q in run(catalog2, interp(["a"])).pending_questions] == ["x"]


@pytest.mark.parametrize(
    ("abbs", "attrs", "answers"),
    [
        (["zzz"], {}, {}),
        ([], {"zzz": "yes"}, {}),
        ([], {"p": "maybe"}, {}),
        ([], {}, {"zzz": "yes"}),
        ([], {}, {"p": "maybe"}),
        ([], {"p": ["yes", "no"]}, {}),  # single-valued attribute given two values
    ],
)
def test_unknown_ids_in_input_are_rejected(
    abbs: list[str], attrs: dict[str, Any], answers: dict[str, Any]
) -> None:
    with pytest.raises(EngineInputError):
        run(make(), interp(abbs, attrs), answers)
