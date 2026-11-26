"""User management for administrators."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from ..deps import DB, AdminUser, AppStorage
from ..models import User
from ..services import sessions, users
from ..templating import render

router = APIRouter(prefix="/admin")


def _render_users(request: Request, db: DB, admin: User, status_code: int = 200, **extra: object):
    return render(
        request,
        "admin_users.html",
        status_code=status_code,
        user=admin,
        nav="admin",
        rows=users.list_users_with_book_counts(db),
        **extra,
    )


def _user_or_404(db: DB, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


@router.get("/users")
def users_page(request: Request, db: DB, admin: AdminUser) -> Response:
    return _render_users(request, db, admin)


@router.post("/users")
def create_user(
    request: Request,
    db: DB,
    admin: AdminUser,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    is_admin: Annotated[bool, Form()] = False,
) -> Response:
    try:
        created = users.create_user(db, username, password=password, is_admin=is_admin)
    except users.UserError as exc:
        return _render_users(
            request, db, admin, status_code=422, error=str(exc), form_username=username
        )
    return _render_users(request, db, admin, notice=f"User “{created.username}” created.")


@router.post("/users/{user_id}/password")
def reset_password(
    request: Request,
    db: DB,
    admin: AdminUser,
    user_id: int,
    password: Annotated[str, Form()] = "",
) -> Response:
    target = _user_or_404(db, user_id)
    try:
        users.set_password(db, target, password)
    except users.UserError as exc:
        return _render_users(request, db, admin, status_code=422, error=str(exc))
    if target.id != admin.id:
        sessions.end_other_sessions(db, target)
    return _render_users(request, db, admin, notice=f"Password for “{target.username}” reset.")


@router.post("/users/{user_id}/delete")
def delete_user(db: DB, admin: AdminUser, storage: AppStorage, user_id: int) -> Response:
    target = _user_or_404(db, user_id)
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="You can’t delete your own account.")
    users.delete_user(db, storage, target)
    return RedirectResponse("/admin/users", status_code=303)
