-- 002: catalog identity, versions and vocabulary values (docs/data-model.md 3.1, 3.2).

create table catalog_items (
  id bigint generated always as identity primary key,
  kind text not null check (kind in ('abb', 'sbb', 'rule', 'attribute', 'characteristic', 'lens')),
  slug text not null check (slug ~ '^[A-Za-z0-9][A-Za-z0-9_.-]*$'),
  archived_at timestamptz,
  archived_by bigint references users (id),
  created_at timestamptz not null default now(),
  created_by bigint references users (id),
  unique (kind, slug),
  unique (id, kind)
);

create table item_versions (
  id bigint generated always as identity primary key,
  item_id bigint not null,
  kind text not null,
  number int not null check (number >= 1),
  status text not null check (status in ('draft', 'proposed', 'validated')),
  validated_by bigint references users (id),
  validated_at timestamptz,
  author_id bigint references users (id),
  created_at timestamptz not null default now(),
  change_note text not null default '',
  origin text not null default 'manual'
    check (origin in ('manual', 'interview', 'import', 'discussion', 'feedback', 'restore')),
  origin_ref bigint,
  foreign key (item_id, kind) references catalog_items (id, kind),
  unique (item_id, number),
  unique (id, kind),
  unique (id, item_id),
  check (status <> 'validated' or (validated_by is not null and validated_at is not null))
);
create index item_versions_item_status_idx on item_versions (item_id, status, number desc);

create table item_version_events (
  id bigint generated always as identity primary key,
  version_id bigint not null references item_versions (id),
  from_status text,
  to_status text not null,
  actor_id bigint references users (id),
  at timestamptz not null default now()
);

create table attribute_values (
  id bigint generated always as identity primary key,
  attribute_item_id bigint not null,
  attr_kind text not null default 'attribute' check (attr_kind = 'attribute'),
  key text not null check (key <> ''),
  archived_at timestamptz,
  foreign key (attribute_item_id, attr_kind) references catalog_items (id, kind),
  unique (attribute_item_id, key),
  unique (attribute_item_id, id)
);

create table characteristic_values (
  id bigint generated always as identity primary key,
  characteristic_item_id bigint not null,
  char_kind text not null default 'characteristic' check (char_kind = 'characteristic'),
  key text not null check (key <> ''),
  archived_at timestamptz,
  foreign key (characteristic_item_id, char_kind) references catalog_items (id, kind),
  unique (characteristic_item_id, key),
  unique (characteristic_item_id, id)
);

grant select, insert on catalog_items, item_versions, item_version_events,
  attribute_values, characteristic_values to cheshire_app;
grant update (archived_at, archived_by) on catalog_items to cheshire_app;
-- Versions are immutable except for their review status.
grant update (status, validated_by, validated_at) on item_versions to cheshire_app;
grant update (archived_at) on attribute_values, characteristic_values to cheshire_app;
grant usage, select on all sequences in schema public to cheshire_app;
