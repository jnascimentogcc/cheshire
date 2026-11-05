"""Scenario runner: `scenarios/*.yaml` are the engine's acceptance contract.

Each fixture holds what the Interpreter produced (so no LLM is involved), optional
answers and the expected result. Expected results are never adjusted to make a run
pass (CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from cheshire.catalog.effective import effective_catalog
from cheshire.catalog.models import Catalog
from cheshire.engine.model import AbbResult, EngineResult, InterpreterOutput
from cheshire.engine.run import run


class ExpectedAbb(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activation: str
    strength: str | None = None
    validation: str | None = None
    coverage: str
    eligible: list[str] = Field(default_factory=list)
    conditional: list[str] = Field(default_factory=list)
    excluded: dict[str, str] = Field(default_factory=dict)


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abbs: dict[str, ExpectedAbb]
    pending_questions: list[str] = Field(default_factory=list)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    requirement: str = ""
    interpreter_output: InterpreterOutput
    answers: dict[str, str | list[str]] = Field(default_factory=dict)
    expect: Expected


@dataclass
class ScenarioReport:
    scenario_id: str
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def load_scenario(path: Path) -> Scenario:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Scenario.model_validate(data)


def compare(scenario: Scenario, result: EngineResult) -> list[str]:
    """Differences between expected and actual; empty when they match."""
    problems: list[str] = []
    actual = {a.id: a for a in result.abbs}
    expected = scenario.expect.abbs

    for missing in sorted(set(expected) - set(actual)):
        problems.append(f"abb {missing}: expected in result, absent")
    for extra in sorted(set(actual) - set(expected)):
        problems.append(f"abb {extra}: in result but not expected")

    for abb_id in sorted(set(expected) & set(actual)):
        problems += _compare_abb(abb_id, expected[abb_id], actual[abb_id])

    got_questions = [q.attribute for q in result.pending_questions]
    if got_questions != scenario.expect.pending_questions:
        problems.append(
            f"pending_questions: expected {scenario.expect.pending_questions}, got {got_questions}"
        )
    return problems


def _compare_abb(abb_id: str, exp: ExpectedAbb, act: AbbResult) -> list[str]:
    problems: list[str] = []

    def check(label: str, want: object, got: object) -> None:
        if want != got:
            problems.append(f"abb {abb_id}: {label}: expected {want!r}, got {got!r}")

    check("activation", exp.activation, act.activation)
    check("strength", exp.strength, act.strength)
    check("coverage", exp.coverage, act.coverage)
    # `validation` is asserted only when not `validated`; otherwise it must not be weaker.
    if exp.validation is not None:
        check("validation", exp.validation, act.validation)
    else:
        check("validation", True, act.validation in (None, "validated"))
    check("eligible", sorted(exp.eligible), act.ids("eligible"))
    check("conditional", sorted(exp.conditional), act.ids("conditional"))
    check(
        "excluded",
        dict(sorted(exp.excluded.items())),
        {s.id: s.exclusion for s in sorted(act.sbbs, key=lambda s: s.id) if s.result == "excluded"},
    )
    return problems


def run_scenario(catalog: Catalog, scenario: Scenario) -> ScenarioReport:
    result = run(catalog, scenario.interpreter_output, scenario.answers)
    return ScenarioReport(scenario.id, compare(scenario, result))


def run_all(catalog: Catalog, scenarios_dir: Path) -> list[ScenarioReport]:
    effective = effective_catalog(catalog)
    return [
        run_scenario(effective, load_scenario(path))
        for path in sorted(scenarios_dir.glob("*.yaml"))
    ]
