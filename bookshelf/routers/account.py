"""Account settings: password change and device setup (KOReader sync, OPDS, statistics)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response

from ..deps import DB, SESSION_COOKIE, AdminUser, CurrentUser
from ..models import User
from ..services import library, sessions, users
from ..services import scanner as scanner_service
from ..templating import render

router = APIRouter()


def _render_settings(request: Request, db: DB, user: User, status_code: int = 200, **extra: object):
    server_url = str(request.base_url).rstrip("/")
    return render(
        request,
        "settings.html",
        status_code=status_code,
        user=user,
        nav="settings",
        server_url=server_url,
        opds_url=f"{server_url}/opds",
        webdav_url=f"{server_url}/webdav",
        sync_feeds=[
            ("sync-marked", "Marked books", f"{server_url}/opds/sync"),
            ("sync-all", "All books", f"{server_url}/opds/books?sort=recent"),
            ("sync-unread", "Unread books", f"{server_url}/opds/books?status=unread&sort=recent"),
        ],
        device_count=library.count_device_books(db, user),
        scanner=request.app.state.scanner,
        scan_choices=scanner_service.INTERVAL_CHOICES,
        **extra,
    )


@router.get("/settings")
def settings_page(request: Request, db: DB, user: CurrentUser) -> Response:
    return _render_settings(request, db, user)


@router.post("/settings/password")
def change_password(
    request: Request,
    db: DB,
    user: CurrentUser,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    new_password_confirm: Annotated[str, Form()],
) -> Response:
    error = None
    if users.authenticate(db, user.username, current_password) is None:
        error = "Your current password is incorrect."
    elif new_password != new_password_confirm:
        error = "The new passwords don’t match."
    else:
        try:
            users.set_password(db, user, new_password)
        except users.UserError as exc:
            error = str(exc)
    if error:
        return _render_settings(request, db, user, status_code=422, password_error=error)

    sessions.end_other_sessions(db, user, keep_token=request.cookies.get(SESSION_COOKIE))
    return _render_settings(
        request,
        db,
        user,
        password_notice="Password changed. Remember to log in again on your KOReader devices.",
    )


@router.post("/settings/scan")
def scan_library(request: Request, _admin: AdminUser) -> Response:
    request.app.state.scanner.scan_in_background()
    return RedirectResponse("/settings#library-folder", status_code=303)


@router.post("/settings/scan-interval")
def set_scan_interval(
    request: Request, _admin: AdminUser, minutes: Annotated[int, Form()]
) -> Response:
    try:
        request.app.state.scanner.set_interval(minutes)
    except ValueError:
        return Response("Unsupported interval.", status_code=422)
    return RedirectResponse("/settings#library-folder", status_code=303)
