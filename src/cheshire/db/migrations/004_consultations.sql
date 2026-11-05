-- 004: LLM runs, consultations, facts, evaluations, rationales (docs/data-model.md 4).
-- Facts, ABB events, evaluations and rationales are append-only.

create table llm_runs (
  id bigint generated always as identity primary key,
  purpose text not null check (purpose in ('interpreter', 'writer', 'interviewer', 'mediator')),
  provider text not null,
  model text not null,
  prompt_version text not null,
  input jsonb not null,
  output jsonb,
  status text not null check (status in ('ok', 'rejected', 'error')),
  attempts int not null default 1,
  tokens_in int not null default 0,
  tokens_out int not null default 0,
  latency_ms int not null default 0,
  error text not null default '',
  problems jsonb not null default '[]'::jsonb,
  at timestamptz not null default now(),
  requested_by bigint references users (id)
);

create table consultations (
  id bigint generated always as identity primary key,
  owner_id bigint not null references users (id),
  title text not null default '',
  created_at timestamptz not null default now(),
  archived_at timestamptz
);
create index consultations_owner_idx on consultations (owner_id, created_at);

create table consultation_revisions (
  id bigint generated always as identity primary key,
  consultation_id bigint not null references consultations (id),
  number int not null check (number >= 1),
  requirement_text text not null check (requirement_text <> ''),
  created_by bigint not null references users (id),
  created_at timestamptz not null default now(),
  -- the Interpreter found no ABB: an "unrecognised requirement" for the architects (M5 queue)
  unrecognised boolean not null default false,
  unique (consultation_id, number)
);

create table consultation_facts (
  id bigint generated always as identity primary key,
  revision_id bigint not null references consultation_revisions (id),
  attribute_item_id bigint not null,
  attr_kind text not null default 'attribute' check (attr_kind = 'attribute'),
  source text not null check (source in ('stated', 'inferred', 'answered', 'edited', 'unknown')),
  span jsonb,
  llm_run_id bigint references llm_runs (id),
  actor_id bigint references users (id),
  at timestamptz not null default now(),
  foreign key (attribute_item_id, attr_kind) references catalog_items (id, kind),
  unique (id, attribute_item_id)
);
create index consultation_facts_revision_idx on consultation_facts (revision_id, attribute_item_id, id);

-- No rows for `unknown`. The composite keys make the database reject a value that does
-- not belong to the attribute.
create table fact_values (
  fact_id bigint not null,
  attribute_item_id bigint not null,
  value_id bigint not null,
  primary key (fact_id, value_id),
  foreign key (fact_id, attribute_item_id) references consultation_facts (id, attribute_item_id),
  foreign key (attribute_item_id, value_id) references attribute_values (attribute_item_id, id)
);

create table consultation_abb_events (
  id bigint generated always as identity primary key,
  revision_id bigint not null references consultation_revisions (id),
  abb_item_id bigint not null,
  abb_kind text not null default 'abb' check (abb_kind = 'abb'),
  origin text not null check (origin in ('interpreter', 'user_added', 'user_removed')),
  span jsonb,
  llm_run_id bigint references llm_runs (id),
  actor_id bigint references users (id),
  at timestamptz not null default now(),
  foreign key (abb_item_id, abb_kind) references catalog_items (id, kind)
);
create index consultation_abb_events_revision_idx on consultation_abb_events (revision_id, id);

create table evaluations (
  id bigint generated always as identity primary key,
  revision_id bigint not null references consultation_revisions (id),
  snapshot_id bigint not null references catalog_snapshots (id),
  inputs_hash text not null,
  input jsonb not null,
  result jsonb not null,      -- carries schema_version
  trace jsonb not null,       -- the addressable entries the Writer may cite
  trigger text not null check (trigger in ('analyze', 'answer', 'edit', 'catalog_change')),
  created_by bigint references users (id),
  created_at timestamptz not null default now()
);
create index evaluations_revision_idx on evaluations (revision_id, id);

create table evaluation_item_uses (
  evaluation_id bigint not null references evaluations (id),
  item_id bigint not null references catalog_items (id),
  role text not null check (role in ('abb', 'sbb', 'rule')),
  outcome text not null,
  primary key (evaluation_id, item_id, role)
);
create index evaluation_item_uses_item_idx on evaluation_item_uses (item_id, outcome);

create table rationales (
  id bigint generated always as identity primary key,
  evaluation_id bigint not null references evaluations (id),
  llm_run_id bigint references llm_runs (id),
  content jsonb not null,
  checker jsonb not null,
  status text not null check (status in ('ok', 'warnings', 'failed')),
  created_by bigint references users (id),
  created_at timestamptz not null default now()
);
create index rationales_evaluation_idx on rationales (evaluation_id, id);

grant select, insert on llm_runs, consultation_revisions, consultation_facts, fact_values,
  consultation_abb_events, evaluations, evaluation_item_uses, rationales to cheshire_app;
grant select, insert on consultations to cheshire_app;
grant update (title, archived_at) on consultations to cheshire_app;
grant update (unrecognised) on consultation_revisions to cheshire_app;
grant usage, select on all sequences in schema public to cheshire_app;
