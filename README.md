# Cheshire

> Named after the Cheshire Cat in *Alice's Adventures in Wonderland*: when Alice
> meets the Cat and asks which way to go, the Cat orients her path. Cheshire does
> the same for a requirement, showing the way (ABBs, eligible SBBs, rationale)
> while the decision stays with you.

An open-source tool that turns a requirement into the **Architectural Building
Blocks (ABBs)** it needs, the **Solution Building Blocks (SBBs)** that are
eligible to realise them, and a **decision rationale** grounded in your own
architecture catalog.

- Architects capture and maintain the catalog (ABBs, SBBs, rules) through
  guided interviews and discussions mediated by an agent.
- Functional and technical teams submit requirements and get orientation
  without waiting for an architect.
- Decisions come from explicit rules, not from an LLM. The LLM only
  translates between free text and the catalog vocabulary, and writes the
  explanation from the rule trace.

Status: M0 (repository and stack), M1 (catalog loader/validator, rule engine,
scenario runner) and M2 (PostgreSQL storage, authentication, versioned catalog, import/export,
HTTP API; see `docs/api.md`), M3 (LLM adapter, Interpreter, Writer, stored
consultations) M4 (Consult UI in Angular) and M5 (catalog maintenance and capture) and M6 (discussions) are done (release v0.2.0); the next milestone is not defined yet. Start with `docs/vision.md`; implementation order is in `docs/plan.md`. An example catalog
and executable scenarios live in `catalog/` and `scenarios/`.

## Screenshots

Taken from a demo instance with the fictional example catalog (`catalog/`). The Interpreter,
Writer and Mediator were scripted for the demo, so no language model was called.

**Consult.** A requirement is read into facts and building blocks; open questions say what they
change, and nothing is ranked.

![A consultation: the requirement with the understood parts marked, the facts, the building blocks identified and the open questions](docs/images/consult-result.png)

**Catalog health and work queue.** Gaps and drafts found while people consult the catalog wait
here for an architect to claim them.

![The catalog home: health counters and the work queue](docs/images/catalog-home.png)

**Item page.** Status, connections, usage and the history of every version, with `proposed` and
`validated` always visible.

![The page of an ABB with its content, connections, usage and history](docs/images/catalog-item.png)

**Rule editor.** A rule is a list of tests, with *Try it* to see its result (true, false or
indeterminate) before saving.

![The rule editor with the condition builder and the Try it panel](docs/images/rule-editor.png)

**Discussion.** Whoever opens a discussion decides it. The impact radius is computed by the
catalog; the Mediator only cites facts.

![A discussion with the proposal, the impact radius, the Mediator's opening brief and the thread](docs/images/discussion.png)

## Development

Requires Python >= 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run lint-imports   # engine isolation (also enforced by tests/test_architecture.py)
uv run pytest
uv run cheshire validate-catalog   # catalog/*.yaml
uv run cheshire test-scenarios     # scenarios/*.yaml against the engine
```

Tests that need PostgreSQL read `CHESHIRE_TEST_DATABASE_URL` (a superuser URL of a
throwaway server, e.g. `docker run -p 55432:5432 -e POSTGRES_PASSWORD=test postgres:17`
and `postgresql://postgres:test@127.0.0.1:55432/postgres`); without it they are skipped.

Docker (PostgreSQL 17, migrations, API; bound to 127.0.0.1):

```bash
cp .env.example .env   # set the passwords and matching URLs
docker compose up --build
docker compose run --rm cli create-admin   # first admin; everyone else is invited
```

The app is then at `http://127.0.0.1:8080` (`CHESHIRE_WEB_PORT`): nginx serves the Angular
app and proxies `/api` to the API. Put a TLS reverse proxy in front for real use.

Frontend (Node 24, in `frontend/`; see `frontend/README.md`):

```bash
cd frontend && npm ci
npm run format:check && npm test && npx ng build --configuration production
npx ng serve   # http://localhost:4200, /api proxied to 127.0.0.1:8000 (cheshire serve)
```
