-- 001: identity and access (docs/data-model.md section 2) and the application role.
create extension if not exists citext;

do $$
begin
  if not exists (select from pg_roles where rolname = 'cheshire_app') then
    create role cheshire_app login;
  end if;
  execute format('grant connect on database %I to cheshire_app', current_database());
end
$$;
grant usage on schema public to cheshire_app;

create table users (
  id bigint generated always as identity primary key,
  email citext not null unique,
  display_name text not null check (display_name <> ''),
  role text not null check (role in ('user', 'architect', 'admin')),
  password_hash text not null,
  active boolean not null default true,
  must_change_password boolean not null default false,
  created_at timestamptz not null default now(),
  deactivated_at timestamptz,
  check ((active and deactivated_at is null) or (not active and deactivated_at is not null))
);

create table invitations (
  id bigint generated always as identity primary key,
  email citext not null,
  role text not null check (role in ('user', 'architect', 'admin')),
  token_hash text not null unique,
  invited_by bigint not null references users (id),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  accepted_at timestamptz
);
create index invitations_email_idx on invitations (email);

create table auth_sessions (
  id text primary key,                       -- sha256 of the cookie token
  user_id bigint not null references users (id),
  csrf_token text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  last_seen_at timestamptz not null default now()
);
create index auth_sessions_user_idx on auth_sessions (user_id);

create table user_preferences (
  user_id bigint primary key references users (id),
  detail_level text not null default 'summary' check (detail_level in ('summary', 'detailed')),
  locale text not null default 'en',
  theme text not null default 'system' check (theme in ('system', 'light', 'dark'))
);

create table login_attempts (
  id bigint generated always as identity primary key,
  email citext not null,
  at timestamptz not null default now(),
  succeeded boolean not null
);
create index login_attempts_email_at_idx on login_attempts (email, at);

create table audit_log (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  actor_id bigint references users (id),
  action text not null,
  subject_type text not null,
  subject_id text not null,
  details jsonb not null default '{}'::jsonb
);

-- Users are deactivated, never deleted. Audit and attempts are append-only.
grant select, insert, update on users to cheshire_app;
grant select, insert, update on invitations to cheshire_app;
grant select, insert, update, delete on auth_sessions to cheshire_app;
grant select, insert, update on user_preferences to cheshire_app;
grant select, insert on login_attempts to cheshire_app;
grant select, insert on audit_log to cheshire_app;
grant usage, select on all sequences in schema public to cheshire_app;
