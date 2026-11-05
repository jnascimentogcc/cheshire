"""LLM-stage evaluation set: the scenario requirements.

For each `scenarios/*.yaml` the Interpreter reads the requirement and its output is
compared with the fixture's `interpreter_output` (the deterministic engine is covered
by `cheshire test-scenarios`); the Writer then explains the engine result computed from
the fixture and the checker's verdict is reported. Metrics only: nothing here gates a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cheshire.agents.base import AgentError
from cheshire.agents.interpreter import interpret
from cheshire.agents.writer import write_rationale
from cheshire.catalog.effective import effective_catalog
from cheshire.catalog.models import Catalog
from cheshire.engine.run import run
from cheshire.providers.base import LLMClient
from cheshire.scenarios import Scenario, load_scenario


@dataclass
class ScenarioEvaluation:
    scenario_id: str
    interpreter_error: str = ""
    missing_abbs: list[str] = field(default_factory=list)
    extra_abbs: list[str] = field(default_factory=list)
    wrong_attributes: list[str] = field(default_factory=list)  # "attr: expected X, got Y"
    missing_attributes: list[str] = field(default_factory=list)
    extra_attributes: list[str] = field(default_factory=list)
    writer_status: str = ""
    writer_unverified: int = 0
    writer_error: str = ""

    @property
    def interpreter_exact(self) -> bool:
        return not (
            self.interpreter_error
            or self.missing_abbs
            or self.extra_abbs
            or self.wrong_attributes
            or self.missing_attributes
            or self.extra_attributes
        )


def _values(value: str | list[str]) -> set[str]:
    return {value} if isinstance(value, str) else set(value)


def evaluate_scenario(
    client: LLMClient,
    interpreter_model: str,
    writer_model: str,
    catalog: Catalog,
    scenario: Scenario,
    language: str = "en",
) -> ScenarioEvaluation:
    ev = ScenarioEvaluation(scenario.id)
    expected = scenario.interpreter_output
    try:
        got = interpret(client, interpreter_model, catalog, scenario.requirement, language).output
    except AgentError as exc:
        ev.interpreter_error = str(exc)
    else:
        want_abbs = {m.id for m in expected.abbs}
        got_abbs = {m.id for m in got.abbs}
        ev.missing_abbs = sorted(want_abbs - got_abbs)
        ev.extra_abbs = sorted(got_abbs - want_abbs)
        for attr, want in sorted(expected.attributes.items()):
            if attr not in got.attributes:
                ev.missing_attributes.append(attr)
            elif _values(got.attributes[attr].value) != _values(want.value):
                ev.wrong_attributes.append(
                    f"{attr}: expected {want.value}, got {got.attributes[attr].value}"
                )
        ev.extra_attributes = sorted(set(got.attributes) - set(expected.attributes))

    # The Writer explains the engine result for the *fixture* input, so Interpreter errors
    # do not hide Writer problems.
    result = run(catalog, expected, scenario.answers)
    try:
        outcome = write_rationale(client, writer_model, result, catalog, language, "summary")
    except AgentError as exc:
        ev.writer_error = str(exc)
    else:
        ev.writer_status = outcome.status
        ev.writer_unverified = outcome.checker["unverified"]
    return ev


def evaluate_scenarios(
    client: LLMClient,
    interpreter_model: str,
    writer_model: str,
    catalog: Catalog,
    scenarios_dir: Path,
    language: str = "en",
) -> list[ScenarioEvaluation]:
    effective = effective_catalog(catalog)
    return [
        evaluate_scenario(
            client, interpreter_model, writer_model, effective, load_scenario(path), language
        )
        for path in sorted(scenarios_dir.glob("*.yaml"))
    ]
