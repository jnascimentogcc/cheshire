from fastapi.testclient import TestClient
from typer.testing import CliRunner

from cheshire import __version__
from cheshire.api import create_app
from cheshire.cli import app as cli_app


def test_health() -> None:
    response = TestClient(create_app()).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_cli_version() -> None:
    result = CliRunner().invoke(cli_app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
