"""Request dependencies: database connection, current user, CSRF, permissions."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated, Any

import psycopg
from fastapi import Depends, HTTPException, Request
from psycopg_pool import ConnectionPool

from cheshire.auth import service
from cheshire.auth.permissions import Permission, allowed
from cheshire.auth.service import User
from cheshire.settings import Settings

SESSION_COOKIE = "cheshire_session"
CSRF_HEADER = "x-csrf-token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_conn(request: Request) -> Iterator[psycopg.Connection[Any]]:
    """One transaction per request: commit on success, roll back on any error."""
    pool: ConnectionPool[psycopg.Connection[Any]] | None = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(503, "database not available")
    with pool.connection() as conn:
        yield conn


Conn = Annotated[psycopg.Connection[Any], Depends(get_conn)]
Config = Annotated[Settings, Depends(get_settings)]


class Session:
    def __init__(self, user: User, csrf_token: str, token: str) -> None:
        self.user = user
        self.csrf_token = csrf_token
        self.token = token


def current_session(request: Request, conn: Conn) -> Session:
    token = request.cookies.get(SESSION_COOKIE)
    found = service.authenticate(conn, token) if token else None
    if found is None or token is None:
        raise HTTPException(401, "authentication required")
    user, csrf = found
    if request.method not in _SAFE_METHODS and not service.csrf_matches(
        csrf, request.headers.get(CSRF_HEADER)
    ):
        raise HTTPException(403, "missing or invalid CSRF token")
    return Session(user, csrf, token)


CurrentSession = Annotated[Session, Depends(current_session)]


def current_user(session: CurrentSession) -> User:
    return session.user


CurrentUser = Annotated[User, Depends(current_user)]


def require(permission: Permission) -> Callable[[User], User]:
    def dependency(user: CurrentUser) -> User:
        if not allowed(user.role, permission):
            raise HTTPException(403, f"requires permission {permission}")
        return user

    return dependency
