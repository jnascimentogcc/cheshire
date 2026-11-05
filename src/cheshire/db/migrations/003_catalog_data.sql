-- 003: per-kind data tables, conditions, derived views, snapshots, import batches
-- (docs/data-model.md 3.3 - 3.6, 9). Data tables are insert-only.
-- `position` columns (not in the first sketch) keep list order so that export
-- reproduces the file exactly.

-- ---- ABB ---------------------------------------------------------------------
create table abb_data (
  version_id bigint primary key,
  kind text not null default 'abb' check (kind = 'abb'),
  name text not null,
  description text not null default '',
  domain text not null,
  cross_cutting boolean not null default false,
  not_applicable_when text not null default '',
  foreign key (version_id, kind) references item_versions (id, kind)
);
create table abb_hints (
  version_id bigint not null references abb_data (version_id),
  position int not null,
  hint text not null,
  primary key (version_id, position)
);

-- ---- Characteristic ----------------------------------------------------------
create table characteristic_data (
  version_id bigint primary key,
  item_id bigint not null,
  kind text not null default 'characteristic' check (kind = 'characteristic'),
  name text not null default '',
  foreign key (version_id, kind) references item_versions (id, kind),
  foreign key (version_id, item_id) references item_versions (id, item_id),
  unique (version_id, item_id)
);
create table characteristic_value_labels (
  version_id bigint not null,
  characteristic_item_id bigint not null,
  value_id bigint not null,
  position int not null,
  label text not null,
  primary key (version_id, value_id),
  foreign key (version_id, characteristic_item_id) references characteristic_data (version_id, item_id),
  foreign key (characteristic_item_id, value_id)
    references characteristic_values (characteristic_item_id, id)
);

-- ---- Attribute ---------------------------------------------------------------
create table attribute_data (
  version_id bigint primary key,
  item_id bigint not null,
  kind text not null default 'attribute' check (kind = 'attribute'),
  layer text not null check (layer in ('core', 'extension')),
  multi boolean not null default false,
  question text not null,
  foreign key (version_id, kind) references item_versions (id, kind),
  foreign key (version_id, item_id) references item_versions (id, item_id),
  unique (version_id, item_id)
);
create table attribute_value_labels (
  version_id bigint not null,
  attribute_item_id bigint not null,
  value_id bigint not null,
  position int not null,
  label text not null,
  primary key (version_id, value_id),
  foreign key (version_id, attribute_item_id) references attribute_data (version_id, item_id),
  foreign key (attribute_item_id, value_id) references attribute_values (attribute_item_id, id)
);
create table attribute_scopes (
  version_id bigint not null references attribute_data (version_id),
  abb_item_id bigint not null,
  abb_kind text not null default 'abb' check (abb_kind = 'abb'),
  position int not null,
  primary key (version_id, abb_item_id),
  foreign key (abb_item_id, abb_kind) references catalog_items (id, kind)
);

-- ---- Lens --------------------------------------------------------------------
create table lens_data (
  version_id bigint primary key,
  kind text not null default 'lens' check (kind = 'lens'),
  name text not null,
  question text not null,
  foreign key (version_id, kind) references item_versions (id, kind)
);
create table lens_feeds (
  version_id bigint not null references lens_data (version_id),
  attribute_item_id bigint not null,
  attr_kind text not null default 'attribute' check (attr_kind = 'attribute'),
  position int not null,
  primary key (version_id, attribute_item_id),
  foreign key (attribute_item_id, attr_kind) references catalog_items (id, kind)
);
create table lens_typical_abbs (
  version_id bigint not null references lens_data (version_id),
  abb_item_id bigint not null,
  abb_kind text not null default 'abb' check (abb_kind = 'abb'),
  position int not null,
  primary key (version_id, abb_item_id),
  foreign key (abb_item_id, abb_kind) references catalog_items (id, kind)
);

-- ---- SBB ---------------------------------------------------------------------
create table sbb_data (
  version_id bigint primary key,
  kind text not null default 'sbb' check (kind = 'sbb'),
  realises_item_id bigint not null,
  realises_kind text not null default 'abb' check (realises_kind = 'abb'),
  name text not null,
  state text not null check (state in ('recommended', 'accepted', 'deprecating', 'prohibited')),
  reason_prohibited text not null default '',
  reason_not_applies text not null default '',
  when_to_choose text not null default '',
  limitations text not null default '',
  owner text not null default '',
  foreign key (version_id, kind) references item_versions (id, kind),
  foreign key (realises_item_id, realises_kind) references catalog_items (id, kind),
  check (state <> 'prohibited' or reason_prohibited <> '')
);
create table sbb_characteristics (
  version_id bigint not null references sbb_data (version_id),
  characteristic_item_id bigint not null,
  value_id bigint not null,
  position int not null,
  primary key (version_id, characteristic_item_id),
  foreign key (characteristic_item_id, value_id)
    references characteristic_values (characteristic_item_id, id)
);

-- ---- Rule --------------------------------------------------------------------
create table rule_data (
  version_id bigint primary key,
  kind text not null default 'rule' check (kind = 'rule'),
  activates_item_id bigint not null,
  activates_kind text not null default 'abb' check (activates_kind = 'abb'),
  strength text not null check (strength in ('requires', 'considers')),
  reason text not null default '',
  foreign key (version_id, kind) references item_versions (id, kind),
  foreign key (activates_item_id, activates_kind) references catalog_items (id, kind)
);

-- ---- Conditions (shared by rules, SBBs and attributes) -----------------------
create table conditions (
  id bigint generated always as identity primary key,
  version_id bigint not null,
  version_kind text not null,
  role text not null check (role in ('when', 'applies_when', 'not_applies_when', 'ask_if')),
  foreign key (version_id, version_kind) references item_versions (id, kind),
  unique (version_id, role),
  check (
    (version_kind = 'rule' and role = 'when')
    or (version_kind = 'sbb' and role in ('applies_when', 'not_applies_when'))
    or (version_kind = 'attribute' and role = 'ask_if')
  )
);
create table condition_tests (
  id bigint generated always as identity primary key,
  condition_id bigint not null references conditions (id),
  position int not null,
  in_except boolean not null default false,
  test_kind text not null check (test_kind in ('attribute', 'abb_present')),
  attribute_item_id bigint,
  attr_kind text not null default 'attribute' check (attr_kind = 'attribute'),
  unique (condition_id, position),
  unique (id, attribute_item_id),
  unique (id, test_kind),
  foreign key (attribute_item_id, attr_kind) references catalog_items (id, kind),
  check ((test_kind = 'attribute') = (attribute_item_id is not null))
);
create table condition_test_values (
  test_id bigint not null,
  attribute_item_id bigint not null,
  value_id bigint not null,
  position int not null,
  primary key (test_id, value_id),
  foreign key (test_id, attribute_item_id) references condition_tests (id, attribute_item_id),
  foreign key (attribute_item_id, value_id) references attribute_values (attribute_item_id, id)
);
create table condition_test_abbs (
  test_id bigint not null,
  test_kind text not null default 'abb_present' check (test_kind = 'abb_present'),
  abb_item_id bigint not null,
  abb_kind text not null default 'abb' check (abb_kind = 'abb'),
  position int not null,
  primary key (test_id, abb_item_id),
  foreign key (test_id, test_kind) references condition_tests (id, test_kind),
  foreign key (abb_item_id, abb_kind) references catalog_items (id, kind)
);

-- ---- Derived views -----------------------------------------------------------
-- Effective version: latest validated, else latest proposed; draft excluded; a
-- newer pending version never replaces a validated one.
create view effective_versions as
select distinct on (v.item_id) v.*
from item_versions v
join catalog_items i on i.id = v.item_id
where i.archived_at is null and v.status in ('validated', 'proposed')
order by v.item_id, (v.status = 'validated') desc, v.number desc;

-- Test-run variant: the latest version of every item, drafts included.
create view effective_versions_with_drafts as
select distinct on (v.item_id) v.*
from item_versions v
join catalog_items i on i.id = v.item_id
where i.archived_at is null
order by v.item_id, v.number desc;

-- Every reference between items, on effective versions.
create view item_refs_v as
select v.item_id as from_item_id, 'realises'::text as ref_kind, d.realises_item_id as to_item_id,
       null::bigint as value_id
  from effective_versions v join sbb_data d on d.version_id = v.id
union all
select v.item_id, 'activates', d.activates_item_id, null
  from effective_versions v join rule_data d on d.version_id = v.id
union all
select v.item_id, 'reads_attribute', t.attribute_item_id, null
  from effective_versions v
  join conditions c on c.version_id = v.id
  join condition_tests t on t.condition_id = c.id
 where t.test_kind = 'attribute'
union all
select v.item_id, 'reads_value', tv.attribute_item_id, tv.value_id
  from effective_versions v
  join conditions c on c.version_id = v.id
  join condition_tests t on t.condition_id = c.id
  join condition_test_values tv on tv.test_id = t.id
union all
select v.item_id, 'abb_present', ta.abb_item_id, null
  from effective_versions v
  join conditions c on c.version_id = v.id
  join condition_tests t on t.condition_id = c.id
  join condition_test_abbs ta on ta.test_id = t.id
union all
select v.item_id, 'uses_characteristic', sc.characteristic_item_id, sc.value_id
  from effective_versions v join sbb_characteristics sc on sc.version_id = v.id
union all
select v.item_id, 'lens_feeds', lf.attribute_item_id, null
  from effective_versions v join lens_feeds lf on lf.version_id = v.id
union all
select v.item_id, 'lens_typical_abb', lt.abb_item_id, null
  from effective_versions v join lens_typical_abbs lt on lt.version_id = v.id
union all
select v.item_id, 'attribute_scope', s.abb_item_id, null
  from effective_versions v join attribute_scopes s on s.version_id = v.id;

-- ---- Snapshots and import batches --------------------------------------------
create table catalog_snapshots (
  id bigint generated always as identity primary key,
  content_hash text not null unique,
  include_drafts boolean not null,
  created_at timestamptz not null default now()
);
create table catalog_snapshot_versions (
  snapshot_id bigint not null references catalog_snapshots (id),
  version_id bigint not null references item_versions (id),
  primary key (snapshot_id, version_id)
);

create table import_batches (
  id bigint generated always as identity primary key,
  user_id bigint not null references users (id),
  filename text not null default '',
  content_hash text not null,
  mode text not null check (mode in ('dry_run', 'applied')),
  report jsonb not null,
  created_at timestamptz not null default now(),
  applied_at timestamptz
);

grant select, insert on abb_data, abb_hints, characteristic_data, characteristic_value_labels,
  attribute_data, attribute_value_labels, attribute_scopes, lens_data, lens_feeds,
  lens_typical_abbs, sbb_data, sbb_characteristics, rule_data, conditions, condition_tests,
  condition_test_values, condition_test_abbs, catalog_snapshots, catalog_snapshot_versions,
  import_batches to cheshire_app;
grant select on effective_versions, effective_versions_with_drafts, item_refs_v to cheshire_app;
grant usage, select on all sequences in schema public to cheshire_app;
