# HTTP API (M2)

Derived from the feature specs during M2. JSON over HTTP under `/api`; the
interactive reference is FastAPI's `/docs`. Consultations (M3) and their M4 additions
(SSE streaming, choice records, feedback, reference cases, export, preferences) are below.

## Authentication (D26)

- Local accounts. No open registration: an admin invites (`POST /api/users/invitations`
  returns a one-time token the admin hands over; no e-mail in v1) and the invitee
  accepts with `POST /api/auth/accept-invitation`. The first admin is created with
  `cheshire create-admin`.
- `POST /api/auth/login` sets an `HttpOnly`, `SameSite=Lax` session cookie
  (`Secure` unless `CHESHIRE_COOKIE_SECURE=false`). Sessions are server-side; the
  cookie token and invitation tokens are stored only as SHA-256 hashes; passwords
  are argon2.
- **CSRF**: every non-GET request must send the `X-CSRF-Token` returned by login or
  `GET /api/auth/me`.
- **Rate limit**: after `CHESHIRE_LOGIN_MAX_FAILURES` (5) failed attempts for an
  e-mail within 15 minutes the account answers `429`, even for the right password.
- Passwords need at least 12 characters. Changing a password closes all sessions.

## Roles and permissions (`cheshire.auth.permissions`)

| Permission | Minimum role |
|---|---|
| `consult`, `catalog.read` | user |
| `catalog.write`, `catalog.validate`, `catalog.import`, `catalog.export` | architect |
| `users.manage` | admin |

`admin` includes architect rights. Users are deactivated, never deleted; the last
active admin cannot be demoted or deactivated. Role changes, invitations,
deactivations, password changes and imports are written to the append-only
`audit_log`.

## Endpoints

| Method and path | Who | Purpose |
|---|---|---|
| `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` | any | Session |
| `POST /api/auth/password` | logged in | Change password |
| `POST /api/auth/accept-invitation` | anonymous | Create the account from an invitation |
| `GET /api/users`, `POST /api/users/invitations`, `PATCH /api/users/{id}` | admin | Users, roles, (de)activation |
| `GET /api/catalog/{kind}` | user | Items of a kind with effective and latest version |
| `GET /api/catalog/{kind}/{slug}[?version=n]` | user | Item (effective, or a given version) plus version history |
| `PUT /api/catalog/{kind}/{slug}?status=&change_note=` | architect | Create the item or add a new immutable version |
| `POST /api/catalog/{kind}/{slug}/versions/{n}/status` | architect | Move a version between `draft`, `proposed`, `validated` |
| `POST /api/catalog/{kind}/{slug}/archive` | architect | Archive (refused while other items reference it) |
| `GET /api/catalog/{kind}/{slug}/dependents` | user | Items that reference this one |
| `GET /api/catalog/validation` | user | Validator findings on the effective catalog |
| `GET /api/catalog/export?format=yaml\|json` | architect | The effective catalog as one document |
| `POST /api/catalog/import` | architect | Dry-run diff (default) or apply (`dry_run: false`) |
| `POST /api/engine/run` | user | Run the engine against the effective catalog |

`kind` is one of `attribute`, `characteristic`, `abb`, `lens`, `sbb`, `rule`. Item
bodies use the same shape as `catalog/*.yaml` (conditions as `{attribute: [values],
abb_present: [...], except: {...}}`); the body `id` must equal the path slug.

Errors: `401` not logged in, `403` missing permission or CSRF, `404` unknown item,
`409` conflict (state, validation errors blocking an import, invalid catalog for a
run), `422` invalid input (schema, unknown reference or value, database constraint),
`429` rate limited. Saving an item is never blocked by catalog-wide findings; they
come back in `issues` of the response.

## Import and export

A document is the six `catalog/*.yaml` files merged under their top-level keys
(`attributes`, `characteristics`, `lenses`, `abbs`, `sbbs`, `rules`), in YAML or
JSON. A dry run reports `created`, `changed`, `unchanged` and `absent` (in the
database but not in the file; **never deleted**) per kind, plus validation findings
of the resulting catalog; findings of severity error block the apply. Applied
imports create new versions with status `proposed`, `origin = import` and the batch
id, in dependency order and two passes. `cheshire export-catalog DIR` writes the
effective catalog as the six files.

## Running the engine

`POST /api/engine/run` takes `interpreter_output`, `answers` and `include_drafts`
(architects only: a test run). It refuses to run (`409`) when the effective catalog
has validation errors, rejects unknown ids (`422`), and returns the engine result
plus the `snapshot_id` of the exact catalog state used, which can be rebuilt later
(`docs/data-model.md` 3.6).

## Consultations (M3)

Every authenticated user can consult. A user sees their own consultations; architects
and admins see all (anything else answers `404`, not `403`).

| Method and path | Purpose |
|---|---|
| `POST /api/consultations` | Create from `{requirement, title?}` and analyze (`201`) |
| `GET /api/consultations`, `GET /api/consultations/{id}` | List; the whole session page from stored data (no recomputation) |
| `POST /api/consultations/{id}/revisions` | Rewrite the text: a new revision, analyzed; earlier ones stay |
| `POST /api/consultations/{id}/analyze` | "Try again" after a provider error |
| `POST /api/consultations/{id}/answers` | `{attribute, value}`; `"unknown"` is a valid answer |
| `PUT /api/consultations/{id}/facts/{attribute}` | Edit a value the Interpreter filled in (source becomes `edited`) |
| `POST /api/consultations/{id}/abbs`, `DELETE .../abbs/{abb}` | Add or remove an identified ABB (rule-activated ABBs cannot be removed) |
| `POST /api/consultations/{id}/rationale` | `{detail: summary\|detailed}`: write the explanation of the latest evaluation |

Flow of `POST /api/consultations`: Interpreter (validated against the catalog, one
retry) -> facts and ABB events stored -> engine on the effective catalog ->
evaluation stored with its catalog snapshot, trace entries and per-item outcomes.
Answers, edits and ABB changes append facts/events and re-evaluate immediately; an
unchanged state reuses the stored evaluation. The response carries the facts with
their source (`stated`, `inferred`, `answered`, `edited`), the engine result, the
trace entries and the latest rationale with an `outdated` flag (its evaluation is no
longer the latest). The rationale is generated on request with the endpoint above, and
automatically once per revision by the streaming endpoints (M4).

Errors: `409 empty_catalog` / `catalog_invalid`, `422 invalid_input`,
`502 llm_unavailable` (retry later), `502 llm_output_rejected` (with `problems`),
`503 llm_not_configured`. Failed LLM runs are stored; the requirement text is kept.
When the Interpreter finds no ABB the revision is flagged `unrecognised` for the
architects' queue (M5) and no evaluation is made.

### LLM configuration

`CHESHIRE_LLM_PROVIDER` (`openai`), `CHESHIRE_LLM_API_KEY`, `CHESHIRE_LLM_BASE_URL`
(any OpenAI-compatible server, including local models),
`CHESHIRE_LLM_INTERPRETER_MODEL`, `CHESHIRE_LLM_WRITER_MODEL`. Models are
configuration only; nothing is defaulted. `cheshire evaluate-llm` runs the
scenario requirements through both agents and reports the differences.

## Consultations, M4 additions

| Method and path | Purpose |
|---|---|
| `GET /api/consultations/{id}?revision=n` | An earlier revision stays readable; `latest_revision` says which is current. Changes always apply to the latest |
| `POST /api/consultations/{id}/choices` | `{abb, kind: chosen\|decide_later\|outside_catalog, sbb?, reason?}`: append a choice record |
| `POST /api/consultations/{id}/feedback` | `{kind: missing\|wrong, text, abb?}`: feedback on one ABB or the whole result |
| `PUT /api/consultations/{id}/pin`, `DELETE .../pin` | Architects: pin the latest result as a reference case, or unpin it |
| `GET /api/consultations/{id}/export?format=markdown\|json` | Download of requirement, facts, result, rationale, choices and feedback |
| `GET /api/reference-cases` | Architects: the pinned cases |
| `GET /api/preferences`, `PUT /api/preferences` | `detail_level` (`summary`/`detailed`), `locale`, `theme` (`system`/`light`/`dark`) of the user |

The session view (`GET /api/consultations/{id}` and every response that returns it) also
carries `catalog` (names, descriptions, SBB texts and characteristics, and the questions
of the attributes involved, from the catalog snapshot the evaluation used), `choices`
(the latest per ABB), `feedback` and `pinned`.

**Choices.** The server reads the SBB's result and state from the stored evaluation; the
client cannot assert them. A reason is required (`422`) when the chosen SBB is conditional
or deprecating; the database enforces the same with a CHECK. Excluded SBBs cannot be
chosen, `outside_catalog` is only for an ABB with a gap, and a conditional choice stores the
questions still unresolved. Records are append-only; the latest per ABB is current.

**Feedback** is stored per revision and evaluation; the architects' queue (M5) is built
from these rows. **Reference cases** store the expected coverage and SBB results at pin time;
the impact preview of M5 replays them.

### Streaming (SSE)

`POST /api/consultations/stream` (`{requirement, title?}`), `POST
/api/consultations/{id}/revisions/stream` (`{requirement}`) and `POST
/api/consultations/{id}/analyze/stream` return `text/event-stream`:

| Event | Data | Meaning |
|---|---|---|
| `created` | `{id}` | The consultation exists and its text is kept (new consultations only) |
| `stage` | `{stage}` | `interpreting`, `checking`, `evaluating`, then `writing` |
| `result` | the session view | Sent as soon as the engine finished |
| `rationale` | the session view | The automatic first explanation, only when the revision has none yet |
| `rationale_error` | `{code, message}` | The explanation failed; the result stays valid |
| `error` | `{code, message, problems?}` | The analysis failed (same codes as the plain endpoints) |
| `done` | `{}` | End of the stream |

The explanation is sent whole after the checker has verified its sentences against the
trace; tokens are not streamed, because an unchecked sentence must never be shown as if it
were grounded (invariant 6). The pipeline runs in its own thread and connection, so the page
shows the result before the explanation is ready. The CSRF header is required like on any
other POST; the browser uses `fetch`, not `EventSource`.


## Catalog maintenance (M5)

Architects (and admins) unless noted. Fixed paths come before `{kind}` in the router.

| Method and path | Who | Purpose |
|---|---|---|
| `GET /api/catalog/health` | user | Items by status (latest version), ABBs without a solution, validator errors/warnings, queue counts, `empty` |
| `GET /api/catalog/{kind}?detail=true` | user | Table rows: key facts, latest and effective status, `sbbs` per ABB, consultations and corrections. Sorted by id; the plain list keeps its shape |
| `GET /api/catalog/{kind}/{slug}/usage` | user | Consultations that used it, last use, times flagged, removed by a user, chosen |
| `GET /api/catalog/{kind}/{slug}/connections` | user | `uses` (what it reads) and `used_by`, on effective versions |
| `GET /api/catalog/{kind}/{slug}/diff?from_version=&to_version=` | user | Readable changes between two versions (sentences with a kind: added, removed, changed) |
| `POST /api/catalog/{kind}/{slug}/versions/{n}/restore` | architect | Saves version `n` again as a new `proposed` version (`origin = restore`); history is never rewritten |
| `PUT /api/catalog/{kind}/{slug}?base_version=n` | architect | Optimistic locking: `409 stale` with `latest_version`, `latest_item` and `changes` when someone saved in between; omit `base_version` to keep the old behaviour |
| `POST /api/catalog/try` | architect | A condition against hand-set facts (`attributes`, with `"unknown"`, and `abbs`): `outcome` true/false/indeterminate plus the trace text. Nothing is stored |
| `POST /api/catalog/impact` | architect | `{kind, item, status}`: dependents, new validator findings, and every pinned reference case and the last N consultations replayed with the change; differences in words with a label (`added`, `removed`, `changed`, `question`). `effective_now` says whether the version would be used at once (a pending change never replaces a validated version) |
| `GET /api/catalog/starter-packs`, `POST /api/catalog/starter-packs/{name}/import` | architect | List packs; dry-run diff (default) or apply through the normal import (lands as `proposed`) |
| `GET /api/catalog/work?status=&kind=` | architect | The work queue (see below) |
| `POST /api/catalog/work/{id}/claim`, `/renew`, `/release`, `/dismiss`, `/resolve` | architect | Claim ("I'll handle this"), renew, release, dismiss (reason required), mark handled |
| `POST /api/catalog/work/{id}/assign` | admin | Hand an entry to an active architect |
| `POST /api/interviews`, `GET /api/interviews`, `GET /api/interviews/{id}` | architect | Start (`{subject?}`: an ABB or from scratch), list, read the conversation and suggestions |
| `POST /api/interviews/{id}/answers` | architect | `{text}` or `{not_applicable: true}`. The answer is kept even if the provider fails |
| `POST /api/interviews/{id}/retry`, `/close` | architect | Process the last answer again; close |
| `POST /api/suggestions/{id}/decision` | architect | `{decision: accept\|reject\|depends, note?}` |

**Work queue.** Entries are derived from stored facts each time the queue is read, so an entry
whose cause is gone closes itself: `gap` (an ABB used in a consultation with no solution in the
catalog, with the number of sessions), `unrecognised` (the Interpreter found no ABB),
`feedback` (from consultations), `draft_review`, `validation_backlog` (latest version `draft` /
`proposed`) and `validator_finding`. Claims expire after `CHESHIRE_CLAIM_TTL_DAYS` (7) and the
entry returns to the queue; `expiring_soon` is true within `CHESHIRE_CLAIM_WARNING_HOURS` (24) so
the claimer can renew. A dismissed or handled entry only comes back if something new happened
after it. Errors: `404 not_found`, `409 conflict` (already claimed, not yours, already closed),
`422 invalid` (dismissal without a reason).

**Interviewer.** The questions are deterministic: one per lens, in catalog order, then a
pre-mortem. The model only turns an answer into *suggestions* (SBB, rule, ABB, or a new
attribute value), validated against the catalog before they are stored (unknown ABBs, attributes,
values, states, or an id that already exists are rejected, with one retry); each carries a quote
of the answer it came from. Nothing is written until a person accepts: accepting saves a
`proposed` version with `origin = interview` and the suggestion as `origin_ref`. *It depends*
stores the qualification and asks the model for a refined suggestion. Needs
`CHESHIRE_LLM_INTERVIEWER_MODEL`; without a provider only this feature is affected (`503
llm_not_configured` / `502 llm_unavailable`), manual editing works.

## Discussions (M6)

All routes need an architect (`403` otherwise), except the item decision summaries, which any
signed-in user can read. Mutations need `X-CSRF-Token`.

| Route | Purpose |
|---|---|
| `GET /api/discussions?tab=attention\|mine\|open\|closed\|orphaned` | Inbox; filters `kind`, `domain`, `older_than_days`, `inactive_days`. `orphaned` is admin only |
| `POST /api/discussions` | `{kind, slug, title?, proposal?, related?, work_item_id?}`. The opener becomes the decider. The brief is requested after the commit; a failure shows as `mediator_error` in the `201` body |
| `GET /api/discussions/members` | Active architects, for mentions and transfers |
| `GET /api/discussions/{id}` | Whole view: proposal, impact, brief, thread, positions, history, decision, `can` |
| `POST /api/discussions/{id}/seen`, `/join` | Mark as read; take part |
| `POST /comments`, `PATCH /comments/{cid}`, `POST /comments/{cid}/retract` | Thread. Edits and retractions are kept |
| `PUT /api/discussions/{id}/position` | `{stance: support\|support_with_conditions\|oppose\|abstain, reason}`; a reason is required except for support and abstain. History is kept |
| `PUT /api/discussions/{id}/proposal` | Decider only. Saves the item as a `draft` version (`origin = discussion`). Validator problems are posted by code, not by the model |
| `POST /api/discussions/{id}/impact/refresh` | New impact snapshot |
| `POST /api/discussions/{id}/mediator` | `{mode: brief\|ask\|challenge\|synthesis, question?}` |
| `POST /api/discussions/{id}/transfer`, `/reassign` | Decider hands over; admin reassigns. Both are recorded |
| `POST /api/discussions/{id}/decision` | Decider only: `{outcome, rationale, result_status, responses[], acknowledge_stale?}` |
| `GET /api/catalog/{kind}/{slug}/decisions` | Decision summaries for an item |
| `GET /api/notifications`, `POST /notifications/read-all`, `POST /notifications/{id}/read` | In-app notifications |

**Effect on the catalog.** A proposal is a `draft` version, so the effective catalog (and every
consultation) ignores it. Accepting sets that version to `validated` or `proposed`; a validated
base version stays in force when the result is only `proposed`. A rejected or withdrawn new item
is archived. One open discussion per item.

**Errors.** `409 already_open`, `409 stale` (the item changed after the discussion opened; retry
with `acknowledge_stale`), `422 missing_responses` (every live `oppose` position needs a response;
a database trigger repeats the check), `403`, `404`, `502 llm_output_rejected` (the mediator's
output failed grounding twice, nothing is posted), `503 llm_not_configured`.

**Mediator.** Facts are computed by code and each sentence cites them (`usage`, `dependents`,
`proposal:N`, `impact`, `issue:N`, `position:ID`, `comment:ID`...). The checker rejects unknown
refs, items outside the facts, numbers not in the facts and ranking words. It never decides.
Needs `CHESHIRE_LLM_MEDIATOR_MODEL`.

**Notifications.** In-app only: opened, activity, mention, reassigned, plus `decider_nudge`
(after `CHESHIRE_DISCUSSION_NUDGE_DAYS`, default 7) and `claim_expiring`, derived when read.
