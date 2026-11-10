"""Account settings: password change and device setup (KOReader sync, OPDS, statistics)."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Body, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from ..deps import DB, SESSION_COOKIE, AdminUser, AppStorage, CurrentUser
from ..models import User
from ..services import library, reader_config, sessions, users
from ..services import scanner as scanner_service
from ..templating import render

router = APIRouter()


def _render_settings(request: Request, db: DB, user: User, status_code: int = 200, **extra: object):
    server_url = str(request.base_url).rstrip("/")
    storage = request.app.state.storage
    config_path = reader_config.user_config_path(storage, user)
    extra.setdefault("reader_config_text", reader_config.user_config_text(storage, user))
    extra.setdefault("reader_file_error", reader_config.user_config_error(storage, user))
    extra.setdefault("reader_config_file", config_path.relative_to(storage.root).as_posix())
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


@router.post("/settings/reader")
def save_reader_config(
    request: Request,
    db: DB,
    user: CurrentUser,
    config: Annotated[str, Form()] = "",
    action: Annotated[str, Form()] = "save",
) -> Response:
    """Save the user's web reader override JSON (or clear it with ``action=reset``)."""
    text = "" if action == "reset" else config
    try:
        reader_config.save_user_config(request.app.state.storage, user, text)
    except reader_config.ReaderConfigError as exc:
        return _render_settings(
            request, db, user, status_code=422, reader_error=str(exc), reader_config_text=config
        )
    return RedirectResponse("/settings?reader=saved#web-reader", status_code=303)


@router.post("/settings/reader/layout")
def save_reader_layout(
    user: CurrentUser, storage: AppStorage, body: Annotated[Any, Body()] = None
) -> JSONResponse:
    """Save the bar editor: ``{"layout": {...}}``, or ``{"layout": null}`` to reset the bars."""
    if not isinstance(body, dict) or "layout" not in body:
        return JSONResponse({"error": "Expected an object with “layout”."}, status_code=422)
    try:
        reader_config.save_user_layout(storage, user, body["layout"])
    except reader_config.ReaderConfigError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    return JSONResponse({"layout": reader_config.effective_config(storage, user)["layout"]})


@router.get("/settings/reader/defaults")
def reader_defaults(_user: CurrentUser, storage: AppStorage) -> Response:
    """The effective configuration without the user's override, as a reference to copy from."""
    config = reader_config.effective_config(storage, None)
    return Response(json.dumps(config, indent=2, ensure_ascii=False), media_type="application/json")


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
