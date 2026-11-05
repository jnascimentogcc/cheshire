import shutil
from pathlib import Path

from typer.testing import CliRunner

from cheshire.cli import app

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_validate_catalog_ok_with_warnings() -> None:
    result = runner.invoke(app, ["validate-catalog", "--catalog", str(ROOT / "catalog")])
    assert result.exit_code == 0
    assert "0 error(s)" in result.stdout


def test_validate_catalog_fails_on_broken_catalog(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "catalog", tmp_path / "c")
    rules = tmp_path / "c" / "rules.yaml"
    rules.write_text(
        rules.read_text(encoding="utf-8").replace(
            "activates: failure-handling", "activates: nope", 1
        ),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["validate-catalog", "--catalog", str(tmp_path / "c")])
    assert result.exit_code == 1
    assert "unknown-abb" in result.stdout


def test_validate_catalog_reports_missing_files(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate-catalog", "--catalog", str(tmp_path)])
    assert result.exit_code == 1


def test_test_scenarios_passes() -> None:
    result = runner.invoke(
        app,
        [
            "test-scenarios",
            "--catalog",
            str(ROOT / "catalog"),
            "--scenarios",
            str(ROOT / "scenarios"),
        ],
    )
    assert result.exit_code == 0
    assert "4/4 scenarios passed" in result.stdout


def test_test_scenarios_fails_on_empty_directory(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["test-scenarios", "--catalog", str(ROOT / "catalog"), "--scenarios", str(tmp_path)]
    )
    assert result.exit_code == 1
