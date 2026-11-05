"""Three-valued condition evaluation: examples and properties."""

from itertools import product

from hypothesis import given
from hypothesis import strategies as st

from cheshire.catalog.models import Condition, parse_condition
from cheshire.engine.conditions import Context, Fact, Tri, evaluate, kleene_and, unknown_attributes


def cond(raw: dict[str, object]) -> Condition:
    parsed = parse_condition(raw)
    assert isinstance(parsed, Condition)
    return parsed


def ctx(facts: dict[str, list[str]] | None = None, present: set[str] | None = None) -> Context:
    return Context(
        {k: Fact(frozenset(v), "stated") for k, v in (facts or {}).items()},
        frozenset(present or ()),
    )


def result(raw: dict[str, object], c: Context) -> Tri:
    return evaluate(cond(raw), c)[0]


# --- attribute tests -----------------------------------------------------------


def test_attribute_in_list_is_true() -> None:
    assert result({"a": ["x", "y"]}, ctx({"a": ["x"]})) is True


def test_known_value_not_in_list_is_false() -> None:
    assert result({"a": ["x"]}, ctx({"a": ["y"]})) is False


def test_unknown_attribute_is_indeterminate() -> None:
    assert result({"a": ["x"]}, ctx()) is None


def test_multi_valued_intersection() -> None:
    assert result({"r": ["gdpr", "health"]}, ctx({"r": ["gdpr", "public-sector"]})) is True
    assert result({"r": ["health"]}, ctx({"r": ["gdpr", "public-sector"]})) is False


def test_empty_condition_is_true() -> None:
    assert result({}, ctx()) is True


# --- abb_present ---------------------------------------------------------------


def test_abb_present_is_any_of() -> None:
    assert result({"abb_present": ["a", "b"]}, ctx(present={"b"})) is True
    assert result({"abb_present": ["a", "b"]}, ctx(present={"c"})) is False


def test_abb_present_is_never_indeterminate() -> None:
    assert result({"abb_present": ["a"]}, ctx()) is False


# --- except --------------------------------------------------------------------


def test_except_passes_when_nested_is_false() -> None:
    assert result({"except": {"a": ["x"]}}, ctx({"a": ["y"]})) is True


def test_except_fails_when_nested_is_true() -> None:
    assert result({"except": {"a": ["x"]}}, ctx({"a": ["x"]})) is False


def test_except_stays_indeterminate() -> None:
    assert result({"except": {"a": ["x"]}}, ctx()) is None


# --- Kleene AND ----------------------------------------------------------------


def test_false_beats_indeterminate() -> None:
    assert result({"a": ["x"], "b": ["x"]}, ctx({"b": ["y"]})) is False


def test_indeterminate_beats_true() -> None:
    assert result({"a": ["x"], "b": ["x"]}, ctx({"b": ["x"]})) is None


def test_kleene_truth_table() -> None:
    values: list[Tri] = [True, False, None]
    for a, b in product(values, repeat=2):
        got = kleene_and([a, b])
        if a is False or b is False:
            assert got is False
        elif a is None or b is None:
            assert got is None
        else:
            assert got is True


# --- trace ---------------------------------------------------------------------


def test_trace_records_value_and_source() -> None:
    _, tests = evaluate(cond({"a": ["x"]}), ctx({"a": ["x"]}))
    assert tests[0].test == "a in [x]"
    assert tests[0].value == "x"
    assert tests[0].source == "stated"


def test_unknown_attributes_found_inside_except() -> None:
    _, tests = evaluate(cond({"except": {"a": ["x"]}, "b": ["y"]}), ctx({"b": ["y"]}))
    assert unknown_attributes(tests) == {"a"}


# --- properties ----------------------------------------------------------------

tri = st.sampled_from([True, False, None])


@given(st.lists(tri))
def test_and_is_order_independent(results: list[Tri]) -> None:
    assert kleene_and(results) == kleene_and(list(reversed(results)))


@given(st.lists(tri), st.lists(tri))
def test_and_is_associative_over_concatenation(xs: list[Tri], ys: list[Tri]) -> None:
    assert kleene_and([kleene_and(xs), kleene_and(ys)]) == kleene_and(xs + ys)


ATTRS = ["a", "b", "c"]
VALUES = ["x", "y", "z"]


@st.composite
def conditions(draw: st.DrawFn, depth: int = 2) -> dict[str, object]:
    raw: dict[str, object] = {}
    for attr in draw(st.lists(st.sampled_from(ATTRS), unique=True, max_size=3)):
        raw[attr] = draw(st.lists(st.sampled_from(VALUES), min_size=1, unique=True))
    if depth > 0 and draw(st.booleans()):
        raw["except"] = draw(conditions(depth=depth - 1))
    return raw


@st.composite
def partial_facts(draw: st.DrawFn) -> dict[str, list[str]]:
    return {attr: [draw(st.sampled_from(VALUES))] for attr in ATTRS if draw(st.booleans())}


@given(conditions(), partial_facts(), st.sampled_from(ATTRS), st.sampled_from(VALUES))
def test_answering_never_contradicts_a_determinate_result(
    raw: dict[str, object], facts: dict[str, list[str]], attr: str, value: str
) -> None:
    """Knowing more can only resolve `None`; it never flips a known true/false.

    This is why asking a question is always safe.
    """
    if attr in facts:
        return
    before = result(raw, ctx(facts))
    after = result(raw, ctx({**facts, attr: [value]}))
    if before is not None:
        assert after == before


@given(conditions(), partial_facts())
def test_indeterminate_result_always_has_an_unknown_cause(
    raw: dict[str, object], facts: dict[str, list[str]]
) -> None:
    res, tests = evaluate(cond(raw), ctx(facts))
    if res is None:
        causes = unknown_attributes(tests)
        assert causes and causes.isdisjoint(facts)


@given(conditions())
def test_fully_known_facts_are_never_indeterminate(raw: dict[str, object]) -> None:
    facts = {attr: ["x"] for attr in ATTRS}
    assert result(raw, ctx(facts)) is not None
