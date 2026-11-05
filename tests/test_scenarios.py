"""The scenarios are the acceptance contract for the engine."""

from pathlib import Path

import pytest

from cheshire.catalog.effective import effective_catalog
from cheshire.catalog.models import Catalog
from cheshire.engine.model import InterpreterOutput
from cheshire.engine.run import run
from cheshire.scenarios import load_scenario, run_scenario

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_FILES = sorted((ROOT / "scenarios").glob("*.yaml"))


def test_scenarios_exist() -> None:
    assert len(SCENARIO_FILES) >= 4


@pytest.mark.parametrize("path", SCENARIO_FILES, ids=lambda p: p.stem)
def test_scenario_passes(path: Path, example_catalog: Catalog) -> None:
    report = run_scenario(effective_catalog(example_catalog), load_scenario(path))
    assert report.failures == []


@pytest.mark.parametrize("path", SCENARIO_FILES, ids=lambda p: p.stem)
def test_engine_is_deterministic(path: Path, example_catalog: Catalog) -> None:
    scenario = load_scenario(path)
    catalog = effective_catalog(example_catalog)
    first = run(catalog, scenario.interpreter_output, scenario.answers)
    second = run(catalog, scenario.interpreter_output, scenario.answers)
    assert first.model_dump_json() == second.model_dump_json()


@pytest.mark.parametrize("path", SCENARIO_FILES, ids=lambda p: p.stem)
def test_sbbs_are_listed_alphabetically(path: Path, example_catalog: Catalog) -> None:
    """Invariant 2: stable neutral order, never a ranking."""
    scenario = load_scenario(path)
    result = run(effective_catalog(example_catalog), scenario.interpreter_output, scenario.answers)
    for abb in result.abbs:
        ids = [s.id for s in abb.sbbs]
        assert ids == sorted(ids)
    assert [a.id for a in result.abbs] == sorted(a.id for a in result.abbs)


def test_nothing_known_confirms_nothing_and_asks(example_catalog: Catalog) -> None:
    """Unknown is first-class: with no facts, rules are indeterminate, never assumed."""
    result = run(effective_catalog(example_catalog), InterpreterOutput())
    assert result.abbs
    assert {a.activation for a in result.abbs} == {"potential"}
    assert all(a.strength is None for a in result.abbs)
    assert result.pending_questions
