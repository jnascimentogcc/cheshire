# Cheshire - Technology stack (derived)

This stack is derived from the stack guide of a sibling project (STC, a
code-catalog chat; the original file is no longer kept in this repo). It was
a **guide**, not the Cheshire spec. This document records what
Cheshire takes from it, what it changes and what is still open.
`docs/ui-spec.md` is Cheshire's own global UI standard (feature specs for
Cheshire are still to be written).

Naming: Python package `cheshire`, CLI `cheshire`, env prefix `CHESHIRE_`.

## 1. Adopted as is

| Area | Choice |
|---|---|
| Backend | Python >= 3.12, strict typing, FastAPI + Uvicorn, Pydantic >= 2, jsonschema |
| Database | PostgreSQL 17, `psycopg` 3 (binary, pool), numbered forward-only SQL migrations applied by `cheshire migrate-db`, two roles (owner for migrations, `cheshire_app` for API/workers) |
| Tooling | hatchling + uv, `src/` layout, pytest, ruff, mypy, httpx (test client), structlog (JSON logs), Typer CLI |
| LLM | Own interfaces (`LLMClient`, and `EmbeddingsClient` only if embeddings are ever needed) with provider adapters; structured output validated against a schema before acceptance; SSE streaming; provider and models by configuration (`CHESHIRE_LLM_PROVIDER`, `CHESHIRE_LLM_*_MODEL`), never hardcoded |
| Frontend | Angular (standalone components, signals, `OnPush`), TypeScript, Tailwind with the ui-spec tokens, SpartanNG (`brain`/`helm`) on `@angular/cdk`, ng-icons + Lucide, Transloco (`en` default), DM Sans + IBM Plex Mono, marked + DOMPurify, Vitest + jsdom, Prettier, npm |
| Infra | Docker + Compose (`db`, `migrate`, `api`, `web`, `cli` under a `tools` profile), unprivileged containers, nginx for the built app with CSP and `/api` proxy with buffering off, `.env` via `env_file`, published on 127.0.0.1 only |
| UI | `docs/ui-spec.md` as is (tokens, components, states, WCAG 2.2 AA, i18n, light/dark) |
| Quality | CI with ruff, mypy, pytest, Vitest; an `evaluate`-style command on fixtures |

## 2. Adapted for Cheshire

| STC | Cheshire | Why |
|---|---|---|
| Markdown catalogs in Git are the source of truth; DB is only an index | **The database is the source of truth.** YAML/JSON import/export is a feature, not the storage | D10 (own UI and data, no Git in the product) |
| Query engine over indexed code | **Rule engine** (`cheshire.engine`): pure Python, no I/O, no DB, no LLM, loads a `Catalog` model | Invariant 1. Same idea as STC's "single engine", different content |
| Citations verified against tool results | **Rationale checker**: every sentence cites trace entries; names absent from the trace are rejected | Invariant 6 |
| Chat is the main UI | Chat-style streaming is reused only for the Interviewer and Mediator. The main UI is **forms and views**: Consult (requirement -> questions -> result -> record choice), Catalog (maintain items, versions), Discussions | Cheshire is not a Q&A tool |
| Feedback "incorrect/incomplete" proposes a catalog correction approved by a maintainer from CLI | "Something is missing/wrong" creates a proposal that an architect **adopts as a discussion** (the adopter becomes the decider) | D6, D7 |
| `stc evaluate` over questions | `cheshire test-scenarios` runs `scenarios/*.yaml` against the engine (M1); later also an LLM-stage evaluation set | `scenarios/` is the acceptance contract |
| Workers on PostgreSQL for indexing | Only if needed (long interviews, bulk draft generation). Start with in-request SSE | No indexing pipeline in Cheshire |
| Env `STC_*` | `CHESHIRE_*` | Naming |

## 3. Not carried over (yet)

- Indexer, tree-sitter, detect-secrets, ripgrep-like search, `stc.toml`, GitHub sync, Root mounted read-only.
- pgvector and embeddings: not needed in v1 (the catalog is small enough to give the Interpreter in the prompt; ABB `recognition` hints help). Use the plain `postgres:17` image; switch to `pgvector/pgvector:pg17` only if semantic search over a large catalog is needed. Use `pg_trgm`/`tsvector` for catalog search first.
- MCP server: possible later as a thin layer over the engine and consult flow (letting an assistant consult the catalog), not in v1.
- Reranking.

## 4. New decisions needed because Cheshire differs

1. **Authentication and identity (decided, see D26).** STC has none; Cheshire has
   roles (architect, user, admin) and "whoever opens a discussion decides".
   - Target: **internal installations** behind a reverse proxy with TLS.
   - **Login is required for everyone**, including consult-only users (sessions
     store the requirement and choice records, which need attribution).
   - v1: **local accounts**, cookie sessions (`HttpOnly`, `SameSite`, CSRF
     protection), argon2 hashes, login rate limiting. No open registration:
     an admin invites users; the first admin is created with
     `cheshire create-admin`.
   - The domain only knows `User` (id, name, role) and the current session,
     never how the user authenticated. Authentication is a swappable module so
     **OIDC/SSO** can be added later as a second provider.
   - Only an admin assigns the architect role. Users are deactivated, never
     deleted, so decision history stays readable. Discussion transfer by the
     initiator and reassignment by an admin are recorded (who, when).
2. **Engine isolation enforced by a test.** An architecture test (e.g.
   import-linter) fails if `cheshire.engine` imports anything from `agents`,
   `providers`, `db` or `api`. Direction is agents -> engine only.
3. **One `Catalog` model, two loaders.** The same Pydantic model is built from
   `catalog/*.yaml` (M1, tests, import) and from the DB (M2+). The engine never
   knows which.
4. **Item versioning in the DB** (`ItemVersion`) replaces what Git would give.
5. **LLM provider at launch: OpenAI** (maintainer's decision; the API key is
   already available). The `LLMClient` adapter stays provider-neutral, so
   Anthropic or local models can be added through configuration. Requirement
   text and catalog excerpts go to the provider; the API key lives only in
   `.env`, never in the repo or images.
6. **Language.** Code, docs, identifiers and the default UI locale in English;
   a `pt` locale is optional later. Generated text follows `CHESHIRE_LANGUAGE`.

## 5. Proposed layout

```
src/cheshire/
  engine/        pure rule engine, condition evaluation, trace      (no I/O, no LLM)
  catalog/       Pydantic models, YAML loader, validator, import/export
  db/            migrations (numbered SQL), repositories
  providers/     LLMClient + adapters
  agents/        interpreter, writer (+checker), interviewer, mediator
  api/           FastAPI routers, SSE
  cli.py         cheshire migrate-db | validate-catalog | test-scenarios | serve ...
frontend/        Angular app: consult / catalog / discussions
catalog/  scenarios/  docs/  tests/
```

## 6. UI notes (to settle in Cheshire feature specs, within ui-spec)

- Coverage badges use text plus semantic color (ui-spec 6.5): covered ->
  success, conditional -> warning, blocked -> danger, gap -> info.
- Validation status (`draft` / `proposed` / `validated`) is always visible as a
  badge, never color alone.
- SBB `state` labels (recommended / accepted / deprecating) use **neutral**
  badges so the colours do not rank options (D13, D14); only exclusions
  (e.g. prohibited) use the danger style, in the "excluded" region.
- SBBs in a list keep the alphabetical order; no sort-by-quality control.
- Pending questions, gaps and "unknown" values are first-class regions with
  their own empty/loading/error states (ui-spec 7), not tooltips.
- Traceability principle (ui-spec 2): every statement of the rationale links to
  its trace entry, the rule, and the discussion that originated the rule.
- The ui-spec mentions "UI engineering" and "UI review" skills; they do not
  exist in this repository yet.

## 7. Open items

- Hosting and reverse proxy (internal; TLS in front).
- Choose the OpenAI models for the Interpreter/Writer and the Interviewer/Mediator (configuration, not code).
- Feature specs (consult, catalog maintenance, discussions) and the data model
  are written (`docs/features/`, `docs/data-model.md`); no separate functional
  spec is planned (the STC guide had one; `docs/vision.md` plus the feature
  specs play that role).
- Licence.
