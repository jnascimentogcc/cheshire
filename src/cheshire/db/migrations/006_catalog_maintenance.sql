-- 006: work queue, guided capture (docs/data-model.md sections 5 and 6).

create table work_items (
  id bigint generated always as identity primary key,
  kind text not null check (kind in (
    'gap', 'unrecognised', 'feedback', 'draft_review', 'validation_backlog', 'validator_finding'
  )),
  -- e.g. 'gap:channel-sms'; unique while the entry is open or claimed
  dedupe_key text not null check (btrim(dedupe_key) <> ''),
  subject_item_id bigint references catalog_items (id),
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'open' check (status in ('open', 'claimed', 'done', 'dismissed')),
  claimed_by bigint references users (id),
  claimed_at timestamptz,
  claim_expires_at timestamptz,
  resolved_by bigint references users (id),
  resolved_at timestamptz,
  resolution text not null default '',
  created_at timestamptz not null default now(),
  check (status <> 'claimed' or (claimed_by is not null and claim_expires_at is not null)),
  check (status <> 'dismissed' or btrim(resolution) <> '')
);
create unique index work_items_open_uq on work_items (dedupe_key)
  where status in ('open', 'claimed');
create index work_items_status_kind_idx on work_items (status, kind);

-- "N sessions": one row per consultation that made the entry appear
create table work_item_occurrences (
  id bigint generated always as identity primary key,
  work_item_id bigint not null references work_items (id),
  consultation_id bigint references consultations (id),
  feedback_id bigint references feedback (id),
  at timestamptz not null default now(),
  unique (work_item_id, consultation_id, feedback_id)
);

create table interviews (
  id bigint generated always as identity primary key,
  subject_item_id bigint references catalog_items (id),
  started_by bigint not null references users (id),
  started_at timestamptz not null default now(),
  status text not null default 'open' check (status in ('open', 'closed'))
);

create table interview_messages (
  id bigint generated always as identity primary key,
  interview_id bigint not null references interviews (id),
  seq int not null check (seq >= 1),
  role text not null check (role in ('user', 'assistant')),
  lens_item_id bigint references catalog_items (id),
  text text not null,
  llm_run_id bigint references llm_runs (id),
  at timestamptz not null default now(),
  unique (interview_id, seq)
);

create table suggestions (
  id bigint generated always as identity primary key,
  interview_id bigint not null references interviews (id),
  kind text not null check (kind in ('sbb', 'rule', 'abb', 'attribute_value')),
  payload jsonb not null,
  source_message_id bigint references interview_messages (id),
  status text not null default 'pending'
    check (status in ('pending', 'accepted', 'rejected', 'depends')),
  follow_up text not null default '',
  decided_by bigint references users (id),
  decided_at timestamptz,
  resulting_version_id bigint references item_versions (id),
  created_at timestamptz not null default now()
);
create index suggestions_interview_idx on suggestions (interview_id, id);

grant select, insert, update on work_items to cheshire_app;
grant select, insert on work_item_occurrences to cheshire_app;
grant select, insert, update on interviews to cheshire_app;
grant select, insert on interview_messages to cheshire_app;
grant select, insert, update on suggestions to cheshire_app;
grant usage, select on all sequences in schema public to cheshire_app;
