# Data model (draft)

Status: **agreed by the maintainer; open questions closed (section 12).** PostgreSQL 17, `psycopg` 3,
numbered forward-only SQL migrations, two roles (owner; `cheshire_app` without
DDL), per `docs/tech-stack.md`. Derived from the feature specs in
`docs/features/` and from `docs/rule-language.md`. Replaces the sketch in
`docs/architecture.md`.

## 1. Conventions

- Names: `snake_case`, plural tables. Time: `timestamptz` (UTC). Keys:
  `bigint generated always as identity`; catalog items are addressed by a
  **slug** (immutable, unique per kind), everything else by numeric id.
- Enumerations are `text` with `CHECK` constraints (easier to evolve than
  Postgres enums).
- **Catalog content is fully typed** (real columns, real foreign keys). JSONB is
  used only for **stored engine/LLM payloads** (`evaluations`, `rationales`,
  `llm_runs`, impact snapshots...), each carrying a `schema_version` and validated
  by Pydantic/jsonschema before insert.
- Authentication sessions are called `auth_sessions`; a user's consultation is a
  `consultation` (the specs say "session").
- **Append-only** tables get no `UPDATE`/`DELETE` privilege for `cheshire_app`.
- The engine never touches the database: the catalog layer builds a `Catalog`
  object from the effective versions (section 3) and stores the engine's output.
- Catalog items are referenced everywhere by **item id (foreign key)**; slugs
  live only in `catalog_items` and in import/export files.

## 2. Identity and access

| Table | Key columns | Notes |
|---|---|---|
| `users` | id, email (unique, citext), display_name, role (`user`/`architect`/`admin`), password_hash (argon2), active, created_at, deactivated_at, must_change_password | Never deleted, only deactivated (D26). `admin` includes architect rights |
| `invitations` | id, email, role, token_hash, invited_by, created_at, expires_at, accepted_at | Invite-only registration |
| `auth_sessions` | id (hash of cookie token), user_id, created_at, expires_at, last_seen_at | Server-side sessions |
| `user_preferences` | user_id (pk), detail_level (`summary`/`detailed`), locale, theme (`system`/`light`/`dark`) | Persisted server-side so preferences follow the user (ui-spec 11, consult 4) |
| `login_attempts` | id, email, at, succeeded | Rate limiting |
| `audit_log` | id, at, actor_id, action, subject_type, subject_id, details jsonb | Append-only: role changes, deactivation, reassignment, imports |

## 3. Catalog (versioned, typed)

### 3.1 Identity and versions (common to all kinds)

```sql
catalog_items (
  id bigint pk,
  kind text check (kind in ('abb','sbb','rule','attribute','characteristic','lens')),
  slug text not null,                           -- immutable
  archived_at timestamptz, archived_by bigint references users,
  created_at timestamptz, created_by bigint references users,
  unique (kind, slug), unique (id, kind)
)

item_versions (
  id bigint pk, item_id bigint, kind text,
  number int not null,                          -- 1, 2, 3 ... per item
  status text check (status in ('draft','proposed','validated')),
  validated_by bigint references users, validated_at timestamptz,
  author_id bigint references users, created_at timestamptz,
  change_note text,
  origin text check (origin in ('manual','interview','import','discussion','feedback','restore')),
  origin_ref bigint,                            -- suggestion / import batch / discussion ...
  foreign key (item_id, kind) references catalog_items (id, kind),
  unique (item_id, number), unique (id, kind)
)

item_version_events (id, version_id, from_status, to_status, actor_id, at)   -- append-only
```

Every save creates a new `item_versions` row plus its data rows in **one
transaction**. Versions are immutable: `cheshire_app` may `UPDATE` only
`item_versions.status, validated_by, validated_at` (column-level grant); all data
tables below are insert-only.

### 3.2 Vocabulary values (stable identity, not versioned)

```sql
attribute_values (
  id bigint pk, attribute_item_id bigint, attr_kind text default 'attribute' check (attr_kind = 'attribute'),
  key text not null,                            -- immutable, e.g. 'personal'
  archived_at timestamptz,
  foreign key (attribute_item_id, attr_kind) references catalog_items (id, kind),
  unique (attribute_item_id, key), unique (attribute_item_id, id)
)
characteristic_values (... same shape, for characteristics ...)
```

Labels are versioned (below) but keys never change, so **renaming a value never
cascades**: it is a new attribute version with a new label. Archiving a value is
allowed only when nothing non-archived references it.

### 3.3 Per-kind data (insert-only, keyed by `version_id`)

Each data table has `(version_id, kind)` with a `CHECK` on the kind and a
composite foreign key to `item_versions (id, kind)`; references to other items
use `(item_id, kind)` composite foreign keys, so the database rejects e.g. an
SBB that "realises" a rule.

| Kind | Tables and columns |
|---|---|
| ABB | `abb_data` (name, description, domain, cross_cutting, not_applicable_when); `abb_hints` (position, hint) |
| SBB | `sbb_data` (realises_item_id -> abb, name, state, reason_prohibited, reason_not_applies, when_to_choose, limitations, owner_user_id); `sbb_characteristics` (characteristic_item_id, value_id; composite FK to `characteristic_values`). `CHECK`: `state = 'prohibited'` requires `reason_prohibited` |
| Rule | `rule_data` (activates_item_id -> abb, strength in `requires`/`considers`, reason) |
| Attribute | `attribute_data` (layer `core`/`extension`, multi, question); `attribute_value_labels` (value_id, position, label); `attribute_scopes` (abb_item_id, for extensions: asked when this ABB is present) |
| Characteristic | `characteristic_data` (name); `characteristic_value_labels` (value_id, position, label) |
| Lens | `lens_data` (name, question); `lens_feeds` (attribute_item_id); `lens_typical_abbs` (abb_item_id) |

### 3.4 Conditions (shared by rules, SBBs and attributes)

```sql
conditions      (id pk, version_id, role in ('when','applies_when','not_applies_when','ask_if'), unique (version_id, role))
condition_tests (id pk, condition_id, position, in_except bool default false,
                 test_kind in ('attribute','abb_present'), attribute_item_id null)
condition_test_values (test_id, attribute_item_id, value_id,
                       primary key (test_id, value_id),
                       foreign key (attribute_item_id, value_id) references attribute_values (attribute_item_id, id))
condition_test_abbs   (test_id, abb_item_id, primary key (test_id, abb_item_id))
```

Semantics are those of `docs/rule-language.md`: tests with `in_except = false`
are AND-ed; tests with `in_except = true` form the single nested `except`
condition, which must evaluate to false. The composite foreign key guarantees
that a value belongs to the tested attribute. Role by kind (`when` only on
rules, `applies_when`/`not_applies_when` only on SBBs, `ask_if` only on
attributes) is checked by a constraint trigger.

### 3.5 Derived views

- `effective_versions`: for each non-archived item, the latest `validated`
  version, else the latest `proposed`; `draft` excluded; a newer pending version
  never replaces a validated one (`docs/rule-language.md`, *Effective catalog*).
  A test-run variant includes drafts.
- `item_refs_v`: every reference between items, derived by joining the foreign
  keys above on effective versions (`realises`, `activates`, `reads_attribute`,
  `reads_value`, `abb_present`, `uses_characteristic`, `lens_feeds`,
  `attribute_scope`). It powers *Connections*, dependents, the impact radius and
  "can this value be archived?". There is no separate refs table to keep in sync.

### 3.6 Catalog snapshots (reproducibility)

```sql
catalog_snapshots (id, content_hash text unique, include_drafts bool, created_at)
catalog_snapshot_versions (snapshot_id, version_id references item_versions, primary key (snapshot_id, version_id))
```

An evaluation points to the snapshot it used; an identical catalog state reuses
the same snapshot (matched by `content_hash` over the sorted version ids). The
full list is stored so any past result can be rebuilt exactly without replaying
history.

### 3.7 Repository rule

One repository module per kind (insert version, load effective, export), with
Pydantic models as the contract between YAML, API and database. Required tests:
**round trip** `catalog/*.yaml` -> database -> `Catalog` -> YAML is identical,
and the engine returns the same results from either loader. Import creates items
in dependency order (attributes and characteristics with their values, ABBs,
lenses, SBBs, rules) in two passes so references inside one batch resolve.

## 4. Consultations

| Table | Key columns | Notes |
|---|---|---|
| `consultations` | id, owner_id, title, created_at, archived_at | Visible to owner and architects |
| `consultation_revisions` | id, consultation_id, number, requirement_text, created_by, created_at | New revision when the text is rewritten |
| `consultation_facts` | id, revision_id, attribute_item_id, source (`stated`/`inferred`/`answered`/`edited`/`unknown`), span jsonb, actor_id, at | **Append-only**; the value(s) live in `fact_values (fact_id, attribute_item_id, value_id)` with a composite FK to `attribute_values` (no rows for `unknown`); current = latest fact per attribute (view) |
| `consultation_abb_events` | id, revision_id, abb_item_id, origin (`interpreter`/`user_added`/`user_removed`), span jsonb, actor_id, at | Append-only; current identified set = fold of events |
| `llm_runs` | id, purpose (`interpreter`/`writer`/`interviewer`/`mediator`), provider, model, prompt_version, input jsonb, output jsonb, status (`ok`/`rejected`/`error`), attempts, tokens_in, tokens_out, latency_ms, at, requested_by | Debugging and reproducibility. Retention open (section 10) |
| `evaluations` | id, revision_id, snapshot_id, inputs_hash, input jsonb, result jsonb, trace jsonb, trigger (`analyze`/`answer`/`edit`/`catalog_change`), created_at | Engine output. `result`/`trace` carry `schema_version` |
| `evaluation_item_uses` | evaluation_id, item_id, role (`abb`/`sbb`/`rule`), outcome (`confirmed`/`eligible`/`conditional`/`excluded`/`gap`...) | Feeds item *Usage* statistics cheaply |
| `rationales` | id, evaluation_id, llm_run_id, content jsonb (sentences with refs), checker jsonb, status (`ok`/`warnings`/`failed`), created_at | *Outdated* = not for the latest evaluation of the revision |
| `choice_records` | id, consultation_id, revision_id, evaluation_id, abb_item_id, kind (`chosen`/`decide_later`/`outside_catalog`), sbb_item_id, sbb_result (`eligible`/`conditional`), sbb_state, reason, unresolved_questions jsonb, actor_id, at | Append-only; latest per ABB is current. `reason` required when `sbb_result = conditional` or `sbb_state = deprecating` (CHECK) |
| `reference_cases` | id, revision_id, evaluation_id, title, pinned_by, pinned_at, expected jsonb, archived_at | Pinned consultations used by the impact preview |
| `feedback` | id, consultation_id, revision_id, evaluation_id, abb_item_id null, kind (`missing`/`wrong`), text, author_id, at | Creates a work item |
| `exports` | id, consultation_id, revision_id, format, requested_by, at | Optional audit of exports |

Every evaluation is stored (decision D30), so any past result can be shown
without recomputation.

## 5. Work queue

```sql
work_items (
  id, kind text check (kind in ('gap','unrecognised','feedback','draft_review',
                                'validation_backlog','validator_finding')),
  dedupe_key text,                     -- e.g. 'gap:channel-sms'; unique while open
  subject_item_id bigint references catalog_items null,
  payload jsonb,
  status text check (status in ('open','claimed','done','dismissed')),
  claimed_by bigint references users, claimed_at timestamptz, claim_expires_at timestamptz,
  resolved_by bigint references users, resolved_at timestamptz, resolution text,
  created_at
)  -- partial unique index (dedupe_key) where status in ('open','claimed')

work_item_occurrences (work_item_id, consultation_id, feedback_id null, at)   -- counts "N sessions"
```

- Created by events: a gap or unrecognised requirement found by an evaluation;
  feedback submitted; a version saved as `draft` (kind `draft_review`) or
  `proposed` (kind `validation_backlog`); a validator finding. Closed
  automatically when the condition disappears (e.g. status changes).
- A scheduled job releases expired claims (`claim_expires_at`, default 7 days).

## 6. Guided capture

| Table | Key columns |
|---|---|
| `interviews` | id, subject_item_id null, started_by, started_at, status (`open`/`closed`) |
| `interview_messages` | id, interview_id, seq, role (`user`/`assistant`), lens_item_id null, text, llm_run_id null, at |
| `suggestions` | id, interview_id, kind (`sbb`/`rule`/`abb`/`attribute_value`), payload jsonb, status (`pending`/`accepted`/`rejected`/`depends`), follow_up text, decided_by, decided_at, resulting_version_id null |

Accepting a suggestion creates an `item_versions` row (`origin='interview'`,
`origin_ref = suggestions.id`) with status `proposed`.

## 7. Discussions

```sql
discussions (
  id, item_id bigint references catalog_items not null,   -- a new item starts as a draft item
  opener_id bigint references users, decider_id bigint references users,
  status text check (status in ('open','accepted','rejected','withdrawn')),
  base_version_id bigint references item_versions,        -- effective version when opened
  pending_version_id bigint references item_versions,     -- the proposal
  opened_at, closed_at
)  -- unique index (item_id) where status = 'open'

discussion_related_items (discussion_id, item_id)
discussion_participants  (discussion_id, user_id, joined_at)
discussion_transfers     (id, discussion_id, from_user, to_user, by_user, kind in ('transfer','reassign'), reason, at)

comments (id, discussion_id, seq, kind in ('comment','position','mediator','system'),
          author_id null, body, llm_run_id null, grounding jsonb null,
          created_at, edited_at, retracted_at)
comment_edits (id, comment_id, old_body, edited_at)

positions (id, discussion_id, participant_id, stance in ('support','support_with_conditions','oppose','abstain'),
           reason, comment_id, created_at, superseded_at)
           -- unique index (discussion_id, participant_id) where superseded_at is null

impact_snapshots (id, discussion_id, kind in ('open','refresh','decision'), snapshot_id, content jsonb, computed_at)

decisions (id, discussion_id unique, decider_id, outcome in ('accepted','accepted_modified','rejected','withdrawn'),
           resulting_version_id null, resulting_status null, rationale text,
           impact_snapshot_id, decided_at)
decision_responses (decision_id, position_id, accepted bool, response text not null)
```

Invariants (service layer inside one transaction; the last one also guarded by a
constraint trigger):
- Only the current `decider_id` may edit the proposal or decide.
- A decision requires one `decision_responses` row for every current `oppose`
  position; saving without them fails.
- Accepting sets the pending version to the chosen status (`validated` records
  `validated_by = decider`) and closes the discussion.
- A closed discussion accepts no new comments, positions or edits.
- Non-architects get a read model limited to `decisions` summary fields
  (decider, outcome, rationale, date) through a dedicated query/view.

## 8. Notifications

`notifications (id, user_id, kind, subject_type, subject_id, payload jsonb, created_at, read_at)`.
Kinds: `discussion_opened` (all architects, with impact summary),
`discussion_activity`, `mention`, `decider_nudge`, `claim_expiring`,
`discussion_reassigned`. In-application only (D29).

## 9. Import and export

`import_batches (id, user_id, filename, content_hash, mode in ('dry_run','applied'), report jsonb, created_at, applied_at)`.
Imported versions use `origin='import'`, status `proposed`, and
`origin_ref = import_batches.id`. Export reads the effective catalog (or a
chosen selection and statuses) into the YAML/JSON schema of `catalog/*.yaml`.

## 10. Privacy, retention and growth

- Requirement text can be sensitive, and `llm_runs` stores prompts and outputs.
  Everything is **kept by default**; an optional retention setting
  (`CHESHIRE_LLM_RUN_RETENTION_DAYS`) prunes old runs.
  When pruned, the structured results (facts, evaluations, rationales, choices)
  remain.
- Nothing about a user is deleted when they are deactivated; their name stays on
  the records they authored.
- Expected volume is small (an internal tool); indexes cover foreign keys,
  `(item_id, number)`, the partial uniques above, `work_items(status, kind)`,
  `consultations(owner_id, created_at)`, `notifications(user_id, read_at)`.

## 11. Migration order (by milestone)

| Migration | Milestone | Contents |
|---|---|---|
| 001 | M2 | users, user_preferences, invitations, auth_sessions, login_attempts, audit_log, roles/grants |
| 002 | M2 | catalog_items, item_versions, item_version_events, attribute_values, characteristic_values |
| 003 | M2 | per-kind data tables, conditions and tests, `effective_versions`, `item_refs_v`, catalog_snapshots (+versions), import_batches |
| 004 | M3 | llm_runs, consultations, revisions, facts, abb_events, evaluations, evaluation_item_uses, rationales |
| 005 | M4 | choice_records, reference_cases, feedback, exports |
| 006 | M5 | work_items (+occurrences), interviews, interview_messages, suggestions |
| 007 | M6 | discussions and all related tables, notifications |

## 12. Decisions on the former open questions

1. **Typed tables** per kind instead of generic JSONB versions (maintainer's
   choice): stronger database constraints. Cost accepted: more tables, a
   multi-row transaction per save, a two-pass import; mitigated by the
   repository rule in 3.7.
2. Slugs are immutable; display names and value labels are editable.
3. `llm_runs` inputs and outputs are kept by default, with optional retention.
4. Every evaluation is stored.
5. Snapshots store the full list of version ids (my choice, asked by the
   maintainer): exact reproduction without replaying history, cheap because a
   snapshot is shared by every evaluation that sees the same catalog state.

## 13. Implementation notes (M2)

Migrations 001-003 follow sections 2, 3 and 9 with these deliberate differences:

- `position` columns were added wherever a list order matters (hints, value labels,
  scopes, lens links, SBB characteristics, condition test values and ABBs), so that
  export reproduces the file and the round-trip test can compare catalogs for equality.
- Value labels are stored equal to the value key: the `catalog/*.yaml` format has no
  labels yet. `characteristic_data.name` is likewise a placeholder.
- `sbb_data.owner` is free text (the file format has an e-mail string) instead of
  `owner_user_id`.
- `auth_sessions.csrf_token` stores the session's CSRF token.
- `attribute`, `characteristic` and `lens` models carry a `status` (default
  `validated`) like ABBs, SBBs and rules, because every kind is versioned.
- `import_batches` is insert-only for the application role: the report is written
  with the row, and dry runs are recorded as their own rows.
- The ten per-kind repository modules of 3.7 are one module, `cheshire.db.catalog_repo`,
  with a function per kind; `cheshire.db.catalog_import` holds the import.
- `except` holds one level only (a nested `except` is rejected by the validator and
  by the repository), because tests are stored flat with `in_except`.
- `must_change_password` exists but nothing enforces it yet (no admin password reset
  in v1).

## 14. Implementation notes (M3, migration 004)

Follows section 4 for `llm_runs`, `consultations`, `consultation_revisions`,
`consultation_facts` (+ `fact_values`), `consultation_abb_events`, `evaluations`,
`evaluation_item_uses` and `rationales`, with these differences:

- `llm_runs` also stores `error` and `problems` (validation findings of rejected
  attempts); one row per agent invocation, `attempts` counts the retry. Failed runs are
  stored too.
- `consultation_revisions.unrecognised` marks a revision where the Interpreter found no
  ABB (the app role may update only that column); the M5 work queue reads it.
- Facts and ABB events point to the `llm_run` that produced them; `evaluations` and
  `rationales` record `created_by`.
- `evaluations.trace` holds the addressable trace entries (`abb:`, `rule:`, `sbb:`,
  `question:` references) that the Writer may cite; `result` holds the engine output.
  Both carry `schema_version`. An evaluation with the same `inputs_hash` as the latest
  one of the revision is reused instead of stored again.
- `evaluation_item_uses.outcome` is the coverage for ABBs (`gap`, `blocked`, ...), the
  result for SBBs and `applied`/`undecided` for rules.
- The Writer is given the catalog as it was in the evaluation's snapshot, not the
  current one.

## 15. Implementation notes (M4, migration 005)

Follows section 4 for `choice_records`, `reference_cases`, `feedback` and `exports`, with
these differences:

- `choice_records` CHECKs that a `chosen` record carries an SBB with its result and state
  and the others carry none, and that a reason is present when the result is `conditional`
  or the state is `deprecating`. The app role can only insert.
- `reference_cases` has a partial unique index: a revision is pinned once at a time
  (`archived_at is null`); unpinning sets `archived_at`. `expected` stores per ABB the
  coverage and the SBB results at pin time.
- `feedback` keeps `revision_id` and the latest `evaluation_id`; it does not create a work
  item yet. The work queue (M5, migration 006) will read these rows.
- `user_preferences` (migration 001) is written through `GET/PUT /api/preferences`; the app
  role selects, inserts and updates it.


## 16. Implementation notes (M5, migration 006)

Follows sections 5 and 6, with these differences:

- `work_items` is *derived*: `maintenance.queue.refresh` recomputes the entries on every read
  (gaps from the latest evaluation of each consultation's latest revision, checked against the
  current catalog; unrecognised revisions; feedback rows; items whose latest version is `draft`
  or `proposed`; validator findings) and closes entries whose cause is gone
  (`resolved_by` null). Only claims, dismissals and manual resolutions are human state. An entry
  closed by a person (`resolved_by` set) returns only if a newer occurrence appears.
  `work_item_occurrences` counts sessions. There is no scheduled job: expired claims are
  released at the start of every refresh.
- `suggestions` also stores `source_message_id`; `payload` carries the item in the open format
  plus the `quote` and `why` of the model. `interview_messages` follows the model; the
  assistant's questions come from the lenses, not from the model.
- The `CHESHIRE_CLAIM_TTL_DAYS` period (default 7) and the warning threshold are settings.
- No "conflicts" counter in the health strip: v1 has no conflict concept beyond validator
  findings. The lens "not used" flag of section 11 is not modelled yet (the file format has no
  such field).

## 17. Implementation notes (M6, migration 007)

- `discussions` (one open per item: partial unique index; `source_work_item_id`; `title`),
  `discussion_related_items`, `discussion_participants` (`last_seen_seq`),
  `discussion_transfers`, `comments` with `comment_edits`, `positions` (reason required except
  support/abstain; one live row per participant), `impact_snapshots` (`open`, `refresh`,
  `decision`), `decisions` with `decision_responses`, and `notifications`.
- The proposal is a `draft` item version with `origin = 'discussion'` and `origin_ref` = the
  discussion id; accepting changes its status. No second copy of the item exists.
- A deferred constraint trigger `decision_needs_responses` refuses a decision when a live
  `oppose` position has no response.
- Impact snapshots reuse the M5 impact preview with the candidate treated as `validated`.
- Comments, positions, decisions and snapshots are append-only for the app role.
- Nudges and expiring claims are derived on read; there is no scheduled job.
