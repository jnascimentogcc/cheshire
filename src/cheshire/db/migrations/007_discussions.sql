-- 007: discussions, positions, impact snapshots, decisions, notifications
-- (docs/data-model.md sections 7 and 8, docs/features/discussions.md).

create table discussions (
  id bigint generated always as identity primary key,
  item_id bigint not null references catalog_items (id),
  opener_id bigint not null references users (id),
  decider_id bigint not null references users (id),
  status text not null default 'open' check (status in ('open', 'accepted', 'rejected', 'withdrawn')),
  title text not null default '',
  -- the effective version when the discussion opened; null for an item that did not exist yet
  base_version_id bigint references item_versions (id),
  -- the proposal: a `draft` version, so it never affects a consultation before it is decided
  pending_version_id bigint references item_versions (id),
  source_work_item_id bigint references work_items (id),
  opened_at timestamptz not null default now(),
  closed_at timestamptz,
  check ((status = 'open') = (closed_at is null))
);
-- one open discussion per item
create unique index discussions_one_open_uq on discussions (item_id) where status = 'open';
create index discussions_status_idx on discussions (status, id);

create table discussion_related_items (
  discussion_id bigint not null references discussions (id),
  item_id bigint not null references catalog_items (id),
  primary key (discussion_id, item_id)
);

create table discussion_participants (
  discussion_id bigint not null references discussions (id),
  user_id bigint not null references users (id),
  joined_at timestamptz not null default now(),
  -- when the participant last looked, to tell what is new for them
  last_seen_seq int not null default 0,
  primary key (discussion_id, user_id)
);

create table discussion_transfers (
  id bigint generated always as identity primary key,
  discussion_id bigint not null references discussions (id),
  from_user bigint not null references users (id),
  to_user bigint not null references users (id),
  by_user bigint not null references users (id),
  kind text not null check (kind in ('transfer', 'reassign')),
  reason text not null default '',
  at timestamptz not null default now()
);

create table comments (
  id bigint generated always as identity primary key,
  discussion_id bigint not null references discussions (id),
  seq int not null check (seq >= 1),
  kind text not null check (kind in ('comment', 'position', 'mediator', 'system')),
  author_id bigint references users (id),
  body text not null,
  llm_run_id bigint references llm_runs (id),
  -- mediator messages: the sentences with the facts they cite, and the checker's verdict
  grounding jsonb,
  created_at timestamptz not null default now(),
  edited_at timestamptz,
  retracted_at timestamptz,
  unique (discussion_id, seq),
  check (kind in ('mediator', 'system') or author_id is not null)
);

create table comment_edits (
  id bigint generated always as identity primary key,
  comment_id bigint not null references comments (id),
  old_body text not null,
  edited_at timestamptz not null default now()
);

create table positions (
  id bigint generated always as identity primary key,
  discussion_id bigint not null references discussions (id),
  participant_id bigint not null references users (id),
  stance text not null check (stance in ('support', 'support_with_conditions', 'oppose', 'abstain')),
  reason text not null default '',
  comment_id bigint references comments (id),
  created_at timestamptz not null default now(),
  superseded_at timestamptz,
  check (stance in ('support', 'abstain') or btrim(reason) <> '')
);
-- one live position per participant; updating keeps the history
create unique index positions_live_uq on positions (discussion_id, participant_id)
  where superseded_at is null;

create table impact_snapshots (
  id bigint generated always as identity primary key,
  discussion_id bigint not null references discussions (id),
  kind text not null check (kind in ('open', 'refresh', 'decision')),
  snapshot_id bigint references catalog_snapshots (id),
  content jsonb not null,
  computed_at timestamptz not null default now()
);
create index impact_snapshots_discussion_idx on impact_snapshots (discussion_id, id);

create table decisions (
  id bigint generated always as identity primary key,
  discussion_id bigint not null unique references discussions (id),
  decider_id bigint not null references users (id),
  outcome text not null check (outcome in ('accepted', 'accepted_modified', 'rejected', 'withdrawn')),
  resulting_version_id bigint references item_versions (id),
  resulting_status text check (resulting_status in ('proposed', 'validated')),
  rationale text not null default '',
  impact_snapshot_id bigint references impact_snapshots (id),
  decided_at timestamptz not null default now(),
  check ((outcome in ('accepted', 'accepted_modified')) = (resulting_version_id is not null)),
  check (outcome in ('withdrawn') or btrim(rationale) <> '')
);

create table decision_responses (
  decision_id bigint not null references decisions (id),
  position_id bigint not null references positions (id),
  accepted boolean not null,
  response text not null check (btrim(response) <> ''),
  primary key (decision_id, position_id)
);

-- Every `oppose` position that is live when the decision is saved needs a response. The
-- service checks it with a readable message; this trigger is the guarantee underneath.
create function decision_needs_responses() returns trigger language plpgsql as $$
begin
  if exists (
    select 1 from positions p
    where p.discussion_id = new.discussion_id
      and p.superseded_at is null
      and p.stance = 'oppose'
      and new.outcome <> 'withdrawn'
      and not exists (
        select 1 from decision_responses r
        where r.decision_id = new.id and r.position_id = p.id
      )
  ) then
    raise exception 'decision % lacks a response to an opposing position', new.id
      using errcode = '23514';
  end if;
  return null;
end $$;

create constraint trigger decisions_responses_ck
  after insert on decisions
  deferrable initially deferred
  for each row execute function decision_needs_responses();

create table notifications (
  id bigint generated always as identity primary key,
  user_id bigint not null references users (id),
  kind text not null check (kind in (
    'discussion_opened', 'discussion_activity', 'mention', 'decider_nudge',
    'claim_expiring', 'discussion_reassigned'
  )),
  subject_type text not null,
  subject_id bigint not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  read_at timestamptz
);
create index notifications_user_idx on notifications (user_id, read_at);

grant select, insert, update on discussions to cheshire_app;
grant select, insert on discussion_related_items to cheshire_app;
grant select, insert, update on discussion_participants to cheshire_app;
grant select, insert on discussion_transfers to cheshire_app;
grant select, insert, update on comments to cheshire_app;
grant select, insert on comment_edits to cheshire_app;
grant select, insert, update on positions to cheshire_app;
grant select, insert on impact_snapshots to cheshire_app;
grant select, insert on decisions to cheshire_app;
grant select, insert on decision_responses to cheshire_app;
grant select, insert, update on notifications to cheshire_app;
grant usage, select on all sequences in schema public to cheshire_app;
