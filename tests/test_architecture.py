"""Invariant 1: `cheshire.engine` must not depend on LLM, DB, API or agents.

The same rule is declared for import-linter in pyproject.toml (run in CI);
this test enforces it inside pytest too, including transitive imports.
"""

import ast
import subprocess
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1] / "src" / "cheshire" / "engine"

FORBIDDEN = (
    "cheshire.agents",
    "cheshire.providers",
    "cheshire.db",
    "cheshire.api",
    "cheshire.cli",
    "psycopg",
    "fastapi",
    "uvicorn",
    "openai",
    "anthropic",
    "httpx",
    "requests",
    "socket",
    "subprocess",
)


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _is_forbidden(module: str) -> bool:
    return any(module == f or module.startswith(f + ".") for f in FORBIDDEN)


def test_engine_has_no_forbidden_imports() -> None:
    offenders = {
        str(path.relative_to(ENGINE_DIR)): sorted(
            m for m in _imported_modules(path) if _is_forbidden(m)
        )
        for path in ENGINE_DIR.rglob("*.py")
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, f"engine must stay pure, found: {offenders}"


def test_import_linter_contract_holds() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from importlinter.cli import lint_imports; sys.exit(lint_imports())",
        ],
        capture_output=True,
        text=True,
        cwd=ENGINE_DIR.parents[2],
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
