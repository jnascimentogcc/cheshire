"""Authentication and user-management endpoints."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr

from cheshire.api.deps import (
    SESSION_COOKIE,
    Config,
    Conn,
    CurrentSession,
    require,
)
from cheshire.auth import service
from cheshire.auth.service import AuthError, User

router = APIRouter(prefix="/api")

_STATUS = {
    "invalid_credentials": 401,
    "rate_limited": 429,
    "invalid_invitation": 400,
    "weak_password": 422,
    "conflict": 409,
}


def auth_error(exc: AuthError) -> HTTPException:
    return HTTPException(_STATUS.get(exc.code, 400), {"code": exc.code, "message": str(exc)})


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    role: str
    active: bool
    must_change_password: bool

    @classmethod
    def of(cls, user: User) -> UserOut:
        return cls(**user.__dict__)


class LoginIn(BaseModel):
    email: str
    password: str


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str


@router.post("/auth/login", response_model=SessionOut)
def login(body: LoginIn, response: Response, conn: Conn, settings: Config) -> SessionOut:
    try:
        token, csrf, user = service.login(conn, settings, body.email, body.password)
    except AuthError as exc:
        raise auth_error(exc) from exc
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return SessionOut(user=UserOut.of(user), csrf_token=csrf)


@router.post("/auth/logout", status_code=204)
def logout(response: Response, session: CurrentSession, conn: Conn) -> None:
    service.logout(conn, session.token)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/auth/me", response_model=SessionOut)
def me(session: CurrentSession) -> SessionOut:
    return SessionOut(user=UserOut.of(session.user), csrf_token=session.csrf_token)


class PasswordIn(BaseModel):
    current: str
    new: str


@router.post("/auth/password", status_code=204)
def change_password(
    body: PasswordIn, response: Response, session: CurrentSession, conn: Conn, settings: Config
) -> None:
    try:
        service.change_password(conn, settings, session.user, body.current, body.new)
    except AuthError as exc:
        raise auth_error(exc) from exc
    response.delete_cookie(SESSION_COOKIE, path="/")  # every session is closed; log in again


class AcceptIn(BaseModel):
    token: str
    display_name: str
    password: str


@router.post("/auth/accept-invitation", response_model=UserOut, status_code=201)
def accept_invitation(body: AcceptIn, conn: Conn, settings: Config) -> UserOut:
    try:
        user = service.accept_invitation(
            conn, settings, body.token, body.display_name, body.password
        )
    except AuthError as exc:
        raise auth_error(exc) from exc
    return UserOut.of(user)


# ------------------------------------------------------------- user management

Admin = Annotated[User, Depends(require("users.manage"))]


@router.get("/users", response_model=list[UserOut])
def users(_: Admin, conn: Conn) -> list[UserOut]:
    return [UserOut.of(u) for u in service.list_users(conn)]


class InviteIn(BaseModel):
    email: EmailStr
    role: Literal["user", "architect", "admin"]


class InviteOut(BaseModel):
    token: str  # shown once; delivered by the admin (no e-mail in v1)
    expires_at: Any


@router.post("/users/invitations", response_model=InviteOut, status_code=201)
def invite(body: InviteIn, admin: Admin, conn: Conn, settings: Config) -> InviteOut:
    try:
        token, expires = service.invite(conn, settings, admin, str(body.email), body.role)
    except AuthError as exc:
        raise auth_error(exc) from exc
    return InviteOut(token=token, expires_at=expires)


class UserPatch(BaseModel):
    role: Literal["user", "architect", "admin"] | None = None
    active: bool | None = None


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(user_id: int, body: UserPatch, admin: Admin, conn: Conn) -> UserOut:
    try:
        updated: User | None = None
        if body.role is not None:
            updated = service.set_role(conn, admin, user_id, body.role)
        if body.active is not None:
            updated = service.set_active(conn, admin, user_id, body.active)
    except AuthError as exc:
        raise auth_error(exc) from exc
    if updated is None:
        raise HTTPException(422, "nothing to change")
    return UserOut.of(updated)
