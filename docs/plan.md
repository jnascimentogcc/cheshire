# Plan

Work one milestone at a time. Each ends with passing tests and updated docs.

## M0 - Repository and stack (done)
Delivered as backend-only skeleton: no frontend (M4), no migrations/`migrate`
service (M2). The CI workflow is GitHub Actions (assumed; the repo has no Git
remote yet).
Apply `docs/tech-stack.md` (derived from the STC stack guide) and
`docs/ui-spec.md`: `src/cheshire` layout, uv/hatchling, ruff, mypy, pytest,
CI, an architecture test that keeps `cheshire.engine` free of LLM/DB/API
imports, Docker Compose skeleton with PostgreSQL 17. Authentication (D26) and
the LLM provider (D25, OpenAI) are already decided. Nothing else.

## M1 - Core (no UI, no LLM, no DB) (done)
- Catalog file format (`catalog/*.yaml`) loader and **validator**
  (see `docs/rule-language.md` section 10).
- Rule engine: three-valued conditions, fixed point, SBB eligibility,
  coverage, pending questions, trace.
- Scenario runner executing `scenarios/*.yaml` (interpreter output fixtures ->
  expected result). **All scenarios pass.**
- Property/unit tests for condition evaluation and for cycle detection.

Done when: `scenarios/` pass and the validator rejects each invalid-catalog
case listed in the tests.

## M2 - Storage, catalog and API (done)
HTTP contract: `docs/api.md`. Deviations from the data model: `docs/data-model.md` section 13.
`docs/data-model.md` migrations 001-003.
- Local authentication and roles (D26): users, invitations, `create-admin`,
  sessions, permission layer, audit log.
- Typed, versioned catalog (items, versions, per-kind tables, conditions,
  effective views, snapshots); repository per kind; **round-trip test**
  `catalog/*.yaml` -> database -> `Catalog` -> YAML.
- YAML/JSON import (dry-run diff, lands as `proposed`) and export.
- API for catalog CRUD and for running the engine.

## M3 - LLM adapter, Interpreter, Writer (done)
Contract: `docs/api.md` (Consultations); storage: `docs/data-model.md` section 14.
Not in M3: streaming (SSE) and the automatic first rationale (M4, with the UI).
Migration 004. Adapter interface and the OpenAI provider (D25). Interpreter
with validation against the catalog and one retry. Writer with sentence-level
refs and the checker. `llm_runs`, consultations, facts, evaluations,
rationales stored. Evaluation set: the scenario requirements.

## M4 - Consult UI (done)
Contract: `docs/api.md` (Consultations, M4 additions); storage: `docs/data-model.md`
section 15; UI notes: `frontend/README.md`.
Migration 005. `docs/features/consult.md`: living session page, questions,
result, comparison, automatic rationale, choice records, feedback, reference
cases (pinning), Markdown/JSON export. Frontend foundation per `docs/ui-spec.md`.

## M5 - Catalog maintenance and capture (done)
Contract: `docs/api.md` (Catalog maintenance, M5); storage: `docs/data-model.md` section 16;
UI notes and deviations: `frontend/README.md`.
Migration 006. `docs/features/catalog-maintenance.md`: catalog UI and item
pages, rule editor with *Try it*, impact preview over reference cases, work
queue with expiring claims, vocabulary management, starter pack, Interviewer
agent and suggestions.

## M6 - Discussions (done)
Contract: `docs/api.md` (Discussions, M6); storage: `docs/data-model.md` section 17;
UI notes and deviations: `frontend/README.md`.
Migration 007. `docs/features/discussions.md`: discussions, comments and
positions, Mediator agent, impact snapshots, decision records with responses to
opposing positions, transfer/reassign, in-app notifications.

## Design status
Done: vision, decisions, rule language, architecture, tech stack, UI standard,
the three feature specs and the data model.
Still open: hosting/reverse proxy, OpenAI models per agent role, licence,
starter-pack content and governance, prompts for the four agents, the HTTP API
contract (derive it during M2 from the feature specs).
