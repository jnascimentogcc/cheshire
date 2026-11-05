"""`cheshire` command line. Commands arrive with their milestones
(validate-catalog, test-scenarios in M1; migrate-db, create-admin in M2)."""

from pathlib import Path
from typing import Annotated

import psycopg
import typer
import uvicorn

from cheshire import __version__
from cheshire.auth import service as auth_service
from cheshire.catalog.loader import CATALOG_FILES, CatalogLoadError, load_catalog
from cheshire.catalog.transfer import dump_files
from cheshire.catalog.validator import has_errors, validate_catalog
from cheshire.db.catalog_repo import CatalogRepo
from cheshire.db.migrate import migrate
from cheshire.evaluation import evaluate_scenarios
from cheshire.providers import build_client
from cheshire.providers.base import LLMNotConfigured
from cheshire.scenarios import run_all
from cheshire.settings import Settings

app = typer.Typer(help="Cheshire command line.", no_args_is_help=True)


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


CatalogDir = Annotated[Path, typer.Option("--catalog", help="Directory with catalog/*.yaml")]
ScenariosDir = Annotated[Path, typer.Option("--scenarios", help="Directory with scenarios/*.yaml")]


@app.command("validate-catalog")
def validate_catalog_cmd(catalog: CatalogDir = Path("catalog")) -> None:
    """Validate the catalog files. Exits 1 on errors; warnings do not fail."""
    try:
        loaded = load_catalog(catalog)
    except CatalogLoadError as exc:
        for problem in exc.problems:
            typer.echo(f"error: [schema] {problem}")
        raise typer.Exit(1) from exc
    issues = validate_catalog(loaded)
    for issue in issues:
        typer.echo(str(issue))
    errors = sum(i.severity == "error" for i in issues)
    typer.echo(f"{errors} error(s), {len(issues) - errors} warning(s)")
    if errors:
        raise typer.Exit(1)


@app.command("test-scenarios")
def test_scenarios_cmd(
    catalog: CatalogDir = Path("catalog"),
    scenarios: ScenariosDir = Path("scenarios"),
) -> None:
    """Run scenarios/*.yaml against the engine. Exits 1 if any fails."""
    try:
        loaded = load_catalog(catalog)
    except CatalogLoadError as exc:
        typer.echo(f"catalog does not load: {exc}")
        raise typer.Exit(1) from exc
    if has_errors(validate_catalog(loaded)):
        typer.echo("catalog has validation errors; run validate-catalog")
        raise typer.Exit(1)
    reports = run_all(loaded, scenarios)
    for report in reports:
        typer.echo(f"{'PASS' if report.passed else 'FAIL'} {report.scenario_id}")
        for failure in report.failures:
            typer.echo(f"    {failure}")
    failed = sum(not r.passed for r in reports)
    typer.echo(f"{len(reports) - failed}/{len(reports)} scenarios passed")
    if failed or not reports:
        raise typer.Exit(1)


@app.command("evaluate-llm")
def evaluate_llm_cmd(
    catalog: CatalogDir = Path("catalog"),
    scenarios: ScenariosDir = Path("scenarios"),
    strict: Annotated[bool, typer.Option(help="Exit 1 unless every scenario is exact")] = False,
) -> None:
    """Run the Interpreter and Writer over the scenario requirements (needs LLM settings)."""
    settings = Settings()
    try:
        client = build_client(settings)
        if not (settings.llm_interpreter_model and settings.llm_writer_model):
            raise LLMNotConfigured(
                "set CHESHIRE_LLM_INTERPRETER_MODEL and CHESHIRE_LLM_WRITER_MODEL"
            )
        loaded = load_catalog(catalog)
    except (LLMNotConfigured, CatalogLoadError) as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc
    rows = evaluate_scenarios(
        client, settings.llm_interpreter_model, settings.llm_writer_model, loaded, scenarios,
        settings.language,
    )  # fmt: skip
    exact = 0
    for r in rows:
        exact += r.interpreter_exact
        typer.echo(f"{'EXACT' if r.interpreter_exact else 'DIFF '} {r.scenario_id}")
        for label, items in (
            ("interpreter error", [r.interpreter_error] if r.interpreter_error else []),
            ("missing ABBs", r.missing_abbs),
            ("extra ABBs", r.extra_abbs),
            ("missing attributes", r.missing_attributes),
            ("extra attributes", r.extra_attributes),
            ("wrong attributes", r.wrong_attributes),
            ("writer error", [r.writer_error] if r.writer_error else []),
        ):
            if items:
                typer.echo(f"    {label}: {'; '.join(items)}")
        typer.echo(f"    writer: {r.writer_status or 'n/a'} ({r.writer_unverified} unverified)")
    typer.echo(f"interpreter exact: {exact}/{len(rows)}")
    if strict and exact != len(rows):
        raise typer.Exit(1)


@app.command("migrate-db")
def migrate_db() -> None:
    """Apply pending SQL migrations as the owner role and set the app role's password."""
    settings = Settings()
    password = settings.app_db_password.get_secret_value() if settings.app_db_password else None
    applied = migrate(settings.owner_database_url, password)
    typer.echo("applied: " + (", ".join(applied) if applied else "nothing to do"))


@app.command("create-admin")
def create_admin_cmd(
    email: Annotated[str, typer.Option(prompt=True)],
    name: Annotated[str, typer.Option(prompt="Display name")],
    password: Annotated[str, typer.Option(prompt=True, hide_input=True, confirmation_prompt=True)],
) -> None:
    """Create the first admin. Nobody can register on their own (invitations only)."""
    settings = Settings()
    try:
        with psycopg.connect(settings.database_url) as conn:
            user = auth_service.create_admin(conn, settings, email, name, password)
    except auth_service.AuthError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc
    typer.echo(f"created admin {user.email}")


@app.command("export-catalog")
def export_catalog_cmd(
    directory: Path,
    include_drafts: bool = False,
) -> None:
    """Write the effective catalog to catalog/*.yaml-style files."""
    settings = Settings()
    with psycopg.connect(settings.database_url) as conn:
        catalog = CatalogRepo(conn).load_catalog(include_drafts)
    dump_files(catalog, directory)
    typer.echo(f"wrote {len(CATALOG_FILES)} files to {directory}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the API."""
    uvicorn.run("cheshire.api:create_app", factory=True, host=host, port=port)
