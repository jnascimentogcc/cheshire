"""Run the rule engine against the effective catalog."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cheshire.api.deps import Conn, require
from cheshire.auth.permissions import allowed
from cheshire.auth.service import User
from cheshire.catalog.validator import has_errors, validate_catalog
from cheshire.db.catalog_repo import CatalogRepo
from cheshire.engine.model import EngineInputError, EngineResult, InterpreterOutput
from cheshire.engine.run import run

router = APIRouter(prefix="/api/engine")


class RunIn(BaseModel):
    interpreter_output: InterpreterOutput = Field(default_factory=InterpreterOutput)
    answers: dict[str, str | list[str]] = Field(default_factory=dict)
    include_drafts: bool = False  # architects only: a test run that includes drafts


class RunOut(BaseModel):
    snapshot_id: int  # the exact catalog state used, rebuildable later
    include_drafts: bool
    result: EngineResult


@router.post("/run", response_model=RunOut)
def run_engine(
    body: RunIn, user: Annotated[User, Depends(require("consult"))], conn: Conn
) -> RunOut:
    if body.include_drafts and not allowed(user.role, "catalog.write"):
        raise HTTPException(403, "only architects can include drafts in a run")
    repo = CatalogRepo(conn)
    catalog = repo.load_catalog(body.include_drafts)
    errors = [i for i in validate_catalog(catalog) if i.severity == "error"]
    if has_errors(errors):
        raise HTTPException(
            409,
            {"code": "catalog_invalid", "errors": [str(i) for i in errors]},
        )
    try:
        result = run(catalog, body.interpreter_output, body.answers)
    except EngineInputError as exc:
        raise HTTPException(422, {"code": "invalid_input", "message": str(exc)}) from exc
    return RunOut(
        snapshot_id=repo.snapshot(body.include_drafts),
        include_drafts=body.include_drafts,
        result=result,
    )
