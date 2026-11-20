"""First-run setup, login and logout."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response

from ..deps import DB, SESSION_COOKIE, AppSettings, OptionalUser, set_session_cookie
from ..services import sessions, users
from ..templating import render

router = APIRouter()


def _safe_next(target: str | None) -> str:
    """Only allow local redirect targets to prevent open redirects."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return "/"


@router.get("/setup")
def setup_page(request: Request, db: DB, settings: AppSettings) -> Response:
    if settings.auth != "password":
        return RedirectResponse("/", status_code=303)
    if users.has_users(db):
        return RedirectResponse("/login", status_code=303)
    return render(request, "setup.html")


@router.post("/setup")
def setup(
    request: Request,
    db: DB,
    settings: AppSettings,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
) -> Response:
    if settings.auth != "password":
        return RedirectResponse("/", status_code=303)
    if users.has_users(db):
        return RedirectResponse("/login", status_code=303)
    error = None
    if password != password_confirm:
        error = "The passwords don’t match."
    else:
        try:
            user = users.create_user(db, username, password=password, is_admin=True)
        except users.UserError as exc:
            error = str(exc)
    if error:
        return render(request, "setup.html", status_code=422, error=error, username=username)

    response = RedirectResponse("/", status_code=303)
    set_session_cookie(response, sessions.create_session(db, user, settings.session_days), settings)
    return response


@router.get("/login")
def login_page(
    request: Request, db: DB, settings: AppSettings, user: OptionalUser, next: str = "/"
) -> Response:
    if settings.auth != "password":  # no login page: signed in automatically or by the proxy
        return RedirectResponse(_safe_next(next), status_code=303)
    if not users.has_users(db):
        return RedirectResponse("/setup", status_code=303)
    if user is not None:
        return RedirectResponse(_safe_next(next), status_code=303)
    return render(request, "login.html", next=_safe_next(next))


@router.post("/login")
def login(
    request: Request,
    db: DB,
    settings: AppSettings,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
) -> Response:
    if settings.auth != "password":
        return RedirectResponse("/", status_code=303)
    user = users.authenticate(db, username, password)
    if user is None:
        return render(
            request,
            "login.html",
            status_code=401,
            error="Wrong username or password.",
            username=username,
            next=_safe_next(next),
        )
    response = RedirectResponse(_safe_next(next), status_code=303)
    set_session_cookie(response, sessions.create_session(db, user, settings.session_days), settings)
    return response


@router.post("/logout")
def logout(request: Request, db: DB) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        sessions.end_session(db, token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
