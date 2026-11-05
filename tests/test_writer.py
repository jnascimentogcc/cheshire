from typing import Any

import pytest

from cheshire.agents.base import OutputRejected, ProviderFailure
from cheshire.agents.writer import _RawSentence, check_sentences, write_rationale
from cheshire.catalog.effective import effective_catalog
from cheshire.catalog.models import Catalog
from cheshire.engine.model import EngineResult
from cheshire.engine.run import run
from cheshire.engine.trace import TraceEntry, build_trace
from cheshire.providers.base import LLMUnavailable
from cheshire.providers.fake import ScriptedLLM
from tests.helpers import all_scenarios


@pytest.fixture
def catalog(example_catalog: Catalog) -> Catalog:
    return effective_catalog(example_catalog)


@pytest.fixture
def result(catalog: Catalog) -> EngineResult:
    scenario = next(s for s in all_scenarios() if s.id == "notify-shipped-order")
    return run(catalog, scenario.interpreter_output, scenario.answers)


@pytest.fixture
def entries(result: EngineResult, catalog: Catalog) -> list[TraceEntry]:
    return build_trace(result, catalog)


# --- trace ---------------------------------------------------------------------------


def test_trace_entries_are_addressable_and_grounded(entries: list[TraceEntry]) -> None:
    refs = {e.ref for e in entries}
    assert len(refs) == len(entries)  # unique
    assert {"abb:channel-sms", "rule:consent-management:R-002", "sbb:channel-sms:sms-provider-b",
            "question:message_type", "question:volume"} <= refs  # fmt: skip
    by_ref = {e.ref: e for e in entries}
    sms = by_ref["sbb:channel-sms:sms-provider-b"]
    assert "prohibited" in sms.text and "outside the EU" in sms.text
    rule = by_ref["rule:consent-management:R-002"]
    assert "message_type in [transactional]: unknown" in rule.text
    assert (
        "personal_data in [personal, sensitive]: true (value: personal; source: inferred)"
        in rule.text
    )
    assert "undecided" in rule.text


def test_trace_is_deterministic(result: EngineResult, catalog: Catalog) -> None:
    assert build_trace(result, catalog) == build_trace(result, catalog)


# --- checker -------------------------------------------------------------------------


def sentence(text: str, *refs: str) -> _RawSentence:
    return _RawSentence(text=text, refs=list(refs))


def check(entries: list[TraceEntry], catalog: Catalog, *sentences: _RawSentence) -> list[list[str]]:
    return check_sentences(list(sentences), entries, catalog)


def test_grounded_sentence_passes(entries: list[TraceEntry], catalog: Catalog) -> None:
    ok = sentence("Channel: SMS has no SMS provider that is eligible yet.", "abb:channel-sms")
    assert check(entries, catalog, ok) == [[]]


def test_missing_and_unknown_refs_are_flagged(entries: list[TraceEntry], catalog: Catalog) -> None:
    got = check(
        entries, catalog,
        sentence("Something happened."),
        sentence("Something happened.", "abb:made-up"),
    )  # fmt: skip
    assert "cites no trace entry" in got[0][0]
    assert "unknown trace reference" in got[1][0]


def test_naming_an_abb_that_is_not_in_the_trace_is_flagged(
    entries: list[TraceEntry], catalog: Catalog
) -> None:
    # report-generation exists in the catalog but not in this result
    got = check(entries, catalog, sentence("It also needs Report generation.", "abb:channel-sms"))
    assert any("Report generation" in p for p in got[0])
    got = check(entries, catalog, sentence("Consider sftp-gateway here.", "abb:channel-sms"))
    assert any("sftp-gateway" in p for p in got[0])


def test_naming_an_sbb_that_is_not_in_the_trace_is_flagged(
    entries: list[TraceEntry], catalog: Catalog
) -> None:
    got = check(entries, catalog, sentence("Use SFTP gateway for this.", "abb:channel-sms"))
    assert any("SFTP gateway" in p for p in got[0])


def test_names_inside_allowed_names_are_not_false_positives(
    entries: list[TraceEntry], catalog: Catalog
) -> None:
    """'Audit log' is an ABB but not in this trace; it must not be flagged inside a longer
    allowed name, and 'Channel: SMS' must still be fine."""
    text = "The notification hub covers Notification orchestration."
    assert check(entries, catalog, sentence(text, "abb:notification-orchestration")) == [[]]


@pytest.mark.parametrize(
    "text",
    [
        "SMS provider A is the best option.",
        "SMS provider A is better than SMS provider C.",
        "You should choose SMS provider A.",
        "This is the preferred choice.",
    ],
)
def test_ranking_language_is_flagged(
    text: str, entries: list[TraceEntry], catalog: Catalog
) -> None:
    got = check(entries, catalog, sentence(text, "abb:channel-sms"))
    assert any("ranking" in p for p in got[0])


# --- writing -------------------------------------------------------------------------

GOOD = {
    "sentences": [{"text": "Channel: SMS is covered conditionally.", "refs": ["abb:channel-sms"]}]
}
BAD = {"sentences": [{"text": "Use sftp-gateway.", "refs": ["abb:channel-sms"]}]}


def write(llm: ScriptedLLM, result: EngineResult, catalog: Catalog) -> Any:
    return write_rationale(llm, "m", result, catalog, "en", "summary")


def test_clean_draft_is_ok(result: EngineResult, catalog: Catalog) -> None:
    llm = ScriptedLLM(GOOD)
    out = write(llm, result, catalog)
    assert out.status == "ok" and out.run.attempts == 1
    assert out.rationale.sentences[0].verified
    prompt = llm.requests[0].user
    assert "[abb:channel-sms]" in prompt and "message_type" in prompt
    assert "never rank" in llm.requests[0].system.lower()


def test_checker_failure_triggers_one_retry_naming_the_problems(
    result: EngineResult, catalog: Catalog
) -> None:
    llm = ScriptedLLM(BAD, GOOD)
    out = write(llm, result, catalog)
    assert out.status == "ok" and out.run.attempts == 2
    assert "sftp-gateway" in llm.requests[1].user


def test_still_bad_after_retry_is_kept_but_flagged(result: EngineResult, catalog: Catalog) -> None:
    mixed = {"sentences": [*GOOD["sentences"], *BAD["sentences"]]}
    out = write(ScriptedLLM(mixed, mixed), result, catalog)
    assert out.status == "warnings"
    flags = [s.verified for s in out.rationale.sentences]
    assert flags == [True, False]
    assert out.checker["unverified"] == 1 and out.checker["problems"][0]["sentence"] == 2


def test_all_sentences_unverified_is_failed(result: EngineResult, catalog: Catalog) -> None:
    out = write(ScriptedLLM(BAD, BAD), result, catalog)
    assert out.status == "failed"


def test_empty_or_malformed_output_is_rejected(result: EngineResult, catalog: Catalog) -> None:
    with pytest.raises(OutputRejected):
        write(ScriptedLLM({"sentences": []}, {"sentences": []}), result, catalog)
    with pytest.raises(OutputRejected):
        write(ScriptedLLM({"text": "x"}, {"text": "x"}), result, catalog)


def test_provider_failure(result: EngineResult, catalog: Catalog) -> None:
    with pytest.raises(ProviderFailure) as info:
        write(ScriptedLLM(LLMUnavailable("down")), result, catalog)
    assert info.value.run.status == "error"
