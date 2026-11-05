from typing import Any

import pytest

from cheshire.agents.base import AgentError, OutputRejected, ProviderFailure
from cheshire.agents.interpreter import interpret, validate_interpretation
from cheshire.catalog.effective import effective_catalog
from cheshire.catalog.models import Catalog
from cheshire.providers.base import LLMError, LLMUnavailable
from cheshire.providers.fake import ScriptedLLM
from tests.helpers import all_scenarios, raw_interpretation

REQ = "When an order is shipped, the customer must receive a notification by e-mail and SMS."


@pytest.fixture
def catalog(example_catalog: Catalog) -> Catalog:
    return effective_catalog(example_catalog)


def good() -> dict[str, Any]:
    return {
        "abbs": [{"id": "channel-sms", "span": "SMS"}],
        "attributes": [
            {
                "attribute": "interaction_mode",
                "values": ["event"],
                "source": "inferred",
                "span": "When an order is shipped",
            }
        ],
    }


@pytest.mark.parametrize("scenario", all_scenarios(), ids=lambda s: s.id)
def test_scenario_interpretations_round_trip(scenario: Any, catalog: Catalog) -> None:
    """A model that returns exactly the fixture passes validation unchanged."""
    out, problems = validate_interpretation(
        raw_interpretation(scenario.interpreter_output), catalog, scenario.requirement
    )
    assert problems == []
    assert out == scenario.interpreter_output


def run_with(*replies: Any, catalog: Catalog) -> tuple[Any, ScriptedLLM]:
    llm = ScriptedLLM(*replies)
    return interpret(llm, "m", catalog, REQ), llm


def test_valid_answer_is_accepted_on_the_first_try(catalog: Catalog) -> None:
    result, llm = run_with(good(), catalog=catalog)
    assert [m.id for m in result.output.abbs] == ["channel-sms"]
    assert result.run.attempts == 1 and result.run.status == "ok"
    assert len(llm.requests) == 1
    assert "channel-sms" in llm.requests[0].user  # the catalog is in the prompt
    assert REQ in llm.requests[0].user


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda d: d["abbs"].append({"id": "invented-abb", "span": "SMS"}), "unknown ABB id"),
        (lambda d: d["attributes"][0].update(attribute="invented"), "unknown attribute id"),
        (lambda d: d["attributes"][0].update(values=["sometimes"]), "unknown value"),
        (lambda d: d["attributes"][0].update(values=["event", "scheduled-batch"]), "single-valued"),
        (lambda d: d["attributes"][0].update(source="answered"), "source must be"),
        (lambda d: d["abbs"][0].update(span="not in the text"), "does not appear"),
        (lambda d: d["abbs"][0].update(span=""), "span is empty"),
        (lambda d: d["attributes"].append(dict(d["attributes"][0])), "more than once"),
        (lambda d: d.update(extra=1), "wrong shape"),
        (lambda d: d.pop("abbs"), "wrong shape"),
    ],
)
def test_invalid_answers_are_rejected(mutate: Any, fragment: str, catalog: Catalog) -> None:
    data = good()
    mutate(data)
    out, problems = validate_interpretation(data, catalog, REQ)
    assert out is None
    assert any(fragment in p for p in problems), problems


def test_one_retry_that_names_the_problems(catalog: Catalog) -> None:
    bad = good()
    bad["abbs"].append({"id": "invented-abb", "span": "SMS"})
    result, llm = run_with(bad, good(), catalog=catalog)
    assert result.run.attempts == 2 and result.run.status == "ok"
    assert "invented-abb" in llm.requests[1].user
    assert "rejected" in llm.requests[1].user
    assert "invented-abb" not in str(result.output)  # never silently accepted


def test_two_bad_answers_are_rejected_with_the_problems(catalog: Catalog) -> None:
    bad = good()
    bad["abbs"][0]["id"] = "invented-abb"
    with pytest.raises(OutputRejected) as info:
        run_with(bad, bad, catalog=catalog)
    assert info.value.run.status == "rejected" and info.value.run.attempts == 2
    assert any("invented-abb" in p for p in info.value.problems)


def test_provider_unavailable_is_reported_with_its_run(catalog: Catalog) -> None:
    with pytest.raises(ProviderFailure) as info:
        run_with(LLMUnavailable("timeout"), catalog=catalog)
    assert info.value.run.status == "error" and info.value.run.error == "timeout"


def test_other_provider_errors_are_agent_errors(catalog: Catalog) -> None:
    with pytest.raises(AgentError) as info:
        run_with(LLMError("bad request"), catalog=catalog)
    assert not isinstance(info.value, ProviderFailure)


def test_nothing_recognised_is_reported(catalog: Catalog) -> None:
    result, _ = run_with({"abbs": [], "attributes": []}, catalog=catalog)
    assert result.recognised_nothing


def test_unknown_values_are_dropped_not_recorded(catalog: Catalog) -> None:
    data = good()
    data["attributes"][0]["values"] = ["unknown"]
    out, problems = validate_interpretation(data, catalog, REQ)
    assert problems == [] and out is not None and out.attributes == {}


def test_spans_with_ellipsis_check_each_part(catalog: Catalog) -> None:
    data = good()
    data["abbs"][0]["span"] = "the customer ... e-mail and SMS"
    assert validate_interpretation(data, catalog, REQ)[1] == []
    data["abbs"][0]["span"] = "the customer ... fax"
    assert validate_interpretation(data, catalog, REQ)[1] != []


def test_schema_constrains_ids_to_the_catalog(catalog: Catalog) -> None:
    llm = ScriptedLLM(good())
    interpret(llm, "m", catalog, REQ)
    schema = llm.requests[0].schema
    assert "channel-sms" in schema["properties"]["abbs"]["items"]["properties"]["id"]["enum"]
    assert schema["additionalProperties"] is False
