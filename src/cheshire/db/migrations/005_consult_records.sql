-- 005: choice records, reference cases, feedback, exports (docs/data-model.md 4).
-- Choice records, feedback and exports are append-only.

create table choice_records (
  id bigint generated always as identity primary key,
  consultation_id bigint not null references consultations (id),
  revision_id bigint not null references consultation_revisions (id),
  evaluation_id bigint not null references evaluations (id),
  abb_item_id bigint not null,
  abb_kind text not null default 'abb' check (abb_kind = 'abb'),
  kind text not null check (kind in ('chosen', 'decide_later', 'outside_catalog')),
  sbb_item_id bigint,
  sbb_kind text check (sbb_kind = 'sbb'),
  sbb_result text check (sbb_result in ('eligible', 'conditional')),
  sbb_state text check (sbb_state in ('recommended', 'accepted', 'deprecating', 'prohibited')),
  reason text not null default '',
  unresolved_questions jsonb not null default '[]'::jsonb,
  actor_id bigint not null references users (id),
  at timestamptz not null default now(),
  foreign key (abb_item_id, abb_kind) references catalog_items (id, kind),
  foreign key (sbb_item_id, sbb_kind) references catalog_items (id, kind),
  -- only a chosen SBB has an SBB and its result; the others have none
  check (
    (kind = 'chosen' and sbb_item_id is not null and sbb_kind is not null
      and sbb_result is not null and sbb_state is not null)
    or (kind <> 'chosen' and sbb_item_id is null and sbb_kind is null
      and sbb_result is null and sbb_state is null)
  ),
  -- consult.md 3 (region 8): a reason is required when the choice is conditional or deprecating
  check (
    kind <> 'chosen'
    or (sbb_result <> 'conditional' and sbb_state <> 'deprecating')
    or btrim(reason) <> ''
  )
);
create index choice_records_consultation_idx on choice_records (consultation_id, abb_item_id, id);

create table reference_cases (
  id bigint generated always as identity primary key,
  revision_id bigint not null references consultation_revisions (id),
  evaluation_id bigint not null references evaluations (id),
  title text not null check (btrim(title) <> ''),
  pinned_by bigint not null references users (id),
  pinned_at timestamptz not null default now(),
  expected jsonb not null,
  archived_at timestamptz
);
-- a revision is pinned once at a time
create unique index reference_cases_active_uq on reference_cases (revision_id)
  where archived_at is null;

create table feedback (
  id bigint generated always as identity primary key,
  consultation_id bigint not null references consultations (id),
  revision_id bigint not null references consultation_revisions (id),
  evaluation_id bigint references evaluations (id),
  abb_item_id bigint,
  abb_kind text check (abb_kind = 'abb'),
  kind text not null check (kind in ('missing', 'wrong')),
  text text not null check (btrim(text) <> ''),
  author_id bigint not null references users (id),
  at timestamptz not null default now(),
  foreign key (abb_item_id, abb_kind) references catalog_items (id, kind),
  check ((abb_item_id is null) = (abb_kind is null))
);
create index feedback_consultation_idx on feedback (consultation_id, id);

create table exports (
  id bigint generated always as identity primary key,
  consultation_id bigint not null references consultations (id),
  revision_id bigint not null references consultation_revisions (id),
  format text not null check (format in ('markdown', 'json')),
  requested_by bigint not null references users (id),
  at timestamptz not null default now()
);

grant select, insert on choice_records, feedback, exports to cheshire_app;
grant select, insert on reference_cases to cheshire_app;
grant update (title, archived_at) on reference_cases to cheshire_app;
grant usage, select on all sequences in schema public to cheshire_app;
