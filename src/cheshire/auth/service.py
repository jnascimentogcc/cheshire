"""Users, invitations, sessions, login rate limiting and the audit log."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from cheshire.settings import Settings

Conn = psycopg.Connection[Any]
_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("not-a-real-password")  # equalises timing for unknown e-mails


class AuthError(Exception):
    """Base class; `code` is stable for the API."""

    code = "auth_error"


class InvalidCredentials(AuthError):
    code = "invalid_credentials"


class RateLimited(AuthError):
    code = "rate_limited"


class InvalidInvitation(AuthError):
    code = "invalid_invitation"


class WeakPassword(AuthError):
    code = "weak_password"


class Conflict(AuthError):
    code = "conflict"


@dataclass(frozen=True)
class User:
    id: int
    email: str
    display_name: str
    role: str
    active: bool
    must_change_password: bool


_USER_COLS = "id, email::text, display_name, role, active, must_change_password"


def _user(row: tuple[Any, ...]) -> User:
    return User(*row)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def check_password_strength(password: str, settings: Settings) -> None:
    if len(password) < settings.min_password_length:
        raise WeakPassword(f"password must have at least {settings.min_password_length} characters")


def audit(
    conn: Conn,
    actor_id: int | None,
    action: str,
    subject_type: str,
    subject_id: object,
    details: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "insert into audit_log (actor_id, action, subject_type, subject_id, details)"
        " values (%s, %s, %s, %s, %s::jsonb)",
        (actor_id, action, subject_type, str(subject_id), json.dumps(details or {})),
    )


# ---------------------------------------------------------------------- users


def create_admin(
    conn: Conn, settings: Settings, email: str, display_name: str, password: str
) -> User:
    """`cheshire create-admin`: the first admin (nobody can register on their own)."""
    check_password_strength(password, settings)
    if conn.execute("select 1 from users where email = %s", (email,)).fetchone():
        raise Conflict(f"user {email} already exists")
    row = conn.execute(
        f"insert into users (email, display_name, role, password_hash)"
        f" values (%s, %s, 'admin', %s) returning {_USER_COLS}",
        (email, display_name, hash_password(password)),
    ).fetchone()
    assert row is not None
    user = _user(row)
    audit(conn, user.id, "user.create_admin", "user", user.id)
    return user


def list_users(conn: Conn) -> list[User]:
    return [_user(r) for r in conn.execute(f"select {_USER_COLS} from users order by id")]


def get_user(conn: Conn, user_id: int) -> User | None:
    row = conn.execute(f"select {_USER_COLS} from users where id = %s", (user_id,)).fetchone()
    return _user(row) if row else None


def _active_admins(conn: Conn) -> int:
    row = conn.execute("select count(*) from users where role = 'admin' and active").fetchone()
    assert row is not None
    return int(row[0])


def set_role(conn: Conn, actor: User, user_id: int, role: str) -> User:
    """Only an admin assigns roles (the API enforces it); the last admin cannot be demoted."""
    target = get_user(conn, user_id)
    if target is None:
        raise Conflict("unknown user")
    if target.role == "admin" and role != "admin" and target.active and _active_admins(conn) <= 1:
        raise Conflict("cannot demote the last active admin")
    conn.execute("update users set role = %s where id = %s", (role, user_id))
    audit(conn, actor.id, "user.role_change", "user", user_id, {"from": target.role, "to": role})
    updated = get_user(conn, user_id)
    assert updated is not None
    return updated


def set_active(conn: Conn, actor: User, user_id: int, active: bool) -> User:
    """Users are deactivated, never deleted, so decision history stays readable."""
    target = get_user(conn, user_id)
    if target is None:
        raise Conflict("unknown user")
    if not active and target.role == "admin" and target.active and _active_admins(conn) <= 1:
        raise Conflict("cannot deactivate the last active admin")
    conn.execute(
        "update users set active = %s,"
        " deactivated_at = case when %s then null else now() end where id = %s",
        (active, active, user_id),
    )
    if not active:
        conn.execute("delete from auth_sessions where user_id = %s", (user_id,))
    audit(conn, actor.id, "user.activate" if active else "user.deactivate", "user", user_id)
    updated = get_user(conn, user_id)
    assert updated is not None
    return updated


# ---------------------------------------------------------------- invitations


def invite(conn: Conn, settings: Settings, inviter: User, email: str, role: str) -> tuple[str, Any]:
    """Create an invitation. Returns (token, expires_at); the token is shown once."""
    if conn.execute("select 1 from users where email = %s", (email,)).fetchone():
        raise Conflict(f"user {email} already exists")
    token = secrets.token_urlsafe(32)
    row = conn.execute(
        "insert into invitations (email, role, token_hash, invited_by, expires_at)"
        " values (%s, %s, %s, %s, now() + make_interval(days => %s)) returning expires_at",
        (email, role, _digest(token), inviter.id, settings.invitation_ttl_days),
    ).fetchone()
    assert row is not None
    audit(conn, inviter.id, "user.invite", "invitation", email, {"role": role})
    return token, row[0]


def accept_invitation(
    conn: Conn, settings: Settings, token: str, display_name: str, password: str
) -> User:
    check_password_strength(password, settings)
    inv = conn.execute(
        "select id, email::text, role from invitations where token_hash = %s"
        " and accepted_at is null and expires_at > now() for update",
        (_digest(token),),
    ).fetchone()
    if inv is None:
        raise InvalidInvitation("invitation is invalid, used or expired")
    if conn.execute("select 1 from users where email = %s", (inv[1],)).fetchone():
        raise Conflict("user already exists")
    row = conn.execute(
        f"insert into users (email, display_name, role, password_hash)"
        f" values (%s, %s, %s, %s) returning {_USER_COLS}",
        (inv[1], display_name, inv[2], hash_password(password)),
    ).fetchone()
    assert row is not None
    conn.execute("update invitations set accepted_at = now() where id = %s", (inv[0],))
    user = _user(row)
    audit(conn, user.id, "user.accept_invitation", "user", user.id)
    return user


# ------------------------------------------------------------------- sessions


def login(conn: Conn, settings: Settings, email: str, password: str) -> tuple[str, str, User]:
    """Verify credentials with rate limiting. Returns (session token, csrf token, user)."""
    failures = conn.execute(
        "select count(*) from login_attempts where email = %s and not succeeded"
        " and at > now() - make_interval(mins => %s)"
        " and at > coalesce((select max(at) from login_attempts"
        "   where email = %s and succeeded), '-infinity')",
        (email, settings.login_window_minutes, email),
    ).fetchone()
    assert failures is not None
    if failures[0] >= settings.login_max_failures:
        raise RateLimited("too many failed attempts; try again later")

    row = conn.execute(
        f"select {_USER_COLS}, password_hash from users where email = %s",
        (email,),
    ).fetchone()
    stored_hash = row[6] if row else _DUMMY_HASH
    ok = verify_password(stored_hash, password) and row is not None and row[4]
    conn.execute("insert into login_attempts (email, succeeded) values (%s, %s)", (email, bool(ok)))
    if not ok or row is None:
        conn.commit()  # keep the failed attempt even though the request ends in an error
        raise InvalidCredentials("invalid e-mail or password")

    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    conn.execute(
        "insert into auth_sessions (id, user_id, csrf_token, expires_at)"
        " values (%s, %s, %s, now() + make_interval(hours => %s))",
        (_digest(token), row[0], csrf, settings.session_ttl_hours),
    )
    conn.execute("delete from auth_sessions where expires_at < now()")
    return token, csrf, _user(row[:6])


def authenticate(conn: Conn, token: str) -> tuple[User, str] | None:
    """The user and CSRF token of a live session, or None."""
    row = conn.execute(
        "select u.id, u.email::text, u.display_name, u.role, u.active, u.must_change_password,"
        " s.csrf_token from auth_sessions s join users u on u.id = s.user_id"
        " where s.id = %s and s.expires_at > now() and u.active",
        (_digest(token),),
    ).fetchone()
    if row is None:
        return None
    return _user(row[:6]), row[6]


def csrf_matches(expected: str, supplied: str | None) -> bool:
    return supplied is not None and hmac.compare_digest(expected, supplied)


def logout(conn: Conn, token: str) -> None:
    conn.execute("delete from auth_sessions where id = %s", (_digest(token),))


def change_password(conn: Conn, settings: Settings, user: User, current: str, new: str) -> None:
    check_password_strength(new, settings)
    row = conn.execute("select password_hash from users where id = %s", (user.id,)).fetchone()
    if row is None or not verify_password(row[0], current):
        raise InvalidCredentials("current password is wrong")
    conn.execute(
        "update users set password_hash = %s, must_change_password = false where id = %s",
        (hash_password(new), user.id),
    )
    conn.execute("delete from auth_sessions where user_id = %s", (user.id,))
    audit(conn, user.id, "user.change_password", "user", user.id)
