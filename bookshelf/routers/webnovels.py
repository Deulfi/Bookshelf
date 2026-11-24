"""The Web novels tab: fetch novels from a remote lncrawl server and keep them updated.

Thin HTTP layer over ``services.webnovels``. Adding a novel submits a crawl and returns at
once; the tab polls ``/webnovels/{id}/status`` (htmx, every 30s) to advance each import and
render its banner, so no work blocks a request for long."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from ..deps import DB, AppSettings, AppStorage, CurrentUser
from ..services import webnovels
from ..templating import render

router = APIRouter()


def _configured(settings: AppSettings) -> bool:
    return bool(settings.lncrawl_url and settings.lncrawl_token)


def _page(
    request: Request,
    db: DB,
    user: CurrentUser,
    settings: AppSettings,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    return render(
        request,
        "webnovels.html",
        status_code=status_code,
        user=user,
        nav="webnovels",
        configured=_configured(settings),
        imports=webnovels.list_imports(db, user),
        error=error,
    )


@router.get("/webnovels")
def webnovels_page(request: Request, db: DB, user: CurrentUser, settings: AppSettings) -> Response:
    return _page(request, db, user, settings)


@router.post("/webnovels")
def add_webnovel(
    request: Request,
    db: DB,
    user: CurrentUser,
    settings: AppSettings,
    url: Annotated[str, Form()] = "",
) -> Response:
    try:
        webnovels.start_import(db, settings, user, url)
    except webnovels.WebnovelError as exc:
        return _page(request, db, user, settings, error=str(exc), status_code=422)
    return RedirectResponse("/webnovels", status_code=303)


@router.get("/webnovels/{import_id}/status")
def webnovel_status(
    request: Request,
    db: DB,
    user: CurrentUser,
    storage: AppStorage,
    settings: AppSettings,
    import_id: int,
) -> Response:
    """Advance one import and return its card (htmx polling target)."""
    record = webnovels.get_import(db, user, import_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Web novel not found.")
    webnovels.advance(db, storage, settings, user, record)
    return render(request, "partials/webnovel_card.html", item=record)


@router.post("/webnovels/{import_id}/refresh")
def refresh_webnovel(
    request: Request,
    db: DB,
    user: CurrentUser,
    settings: AppSettings,
    import_id: int,
) -> Response:
    record = webnovels.get_import(db, user, import_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Web novel not found.")
    try:
        webnovels.start_refresh(db, settings, user, record)
    except webnovels.WebnovelError as exc:
        return _page(request, db, user, settings, error=str(exc), status_code=422)
    return RedirectResponse("/webnovels", status_code=303)


@router.post("/webnovels/{import_id}/delete")
def delete_webnovel(db: DB, user: CurrentUser, import_id: int) -> Response:
    record = webnovels.get_import(db, user, import_id)
    if record is not None:
        webnovels.delete_import(db, record)
    return RedirectResponse("/webnovels", status_code=303)
