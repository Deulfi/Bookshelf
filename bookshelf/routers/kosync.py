"""KOReader progress sync protocol (compatible with koreader/koreader-sync-server).

KOReader authenticates every request with the headers ``x-auth-user`` and ``x-auth-key``
(the key is ``md5(password)``). Response shapes and error codes must stay compatible with
the official server, because the KOReader plugin depends on them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..deps import DB, AppSettings
from ..models import User
from ..services import progress, users

router = APIRouter(tags=["koreader-sync"])

MAX_DOCUMENT_LENGTH = 128  # the ReadingProgress.document column
MAX_PROGRESS_LENGTH = 4096  # an XPointer is a few hundred characters at most


class KosyncError(Exception):
    def __init__(self, status_code: int, code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def unauthorized() -> KosyncError:
    return KosyncError(401, 2001, "Unauthorized")


async def kosync_error_handler(_request: Request, exc: KosyncError) -> JSONResponse:
    return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.status_code)


def sync_user(
    db: DB,
    x_auth_user: Annotated[str | None, Header()] = None,
    x_auth_key: Annotated[str | None, Header()] = None,
) -> User:
    if not x_auth_user or not x_auth_key:
        raise unauthorized()
    user = users.authenticate_sync_key(db, x_auth_user, x_auth_key)
    if user is None:
        raise unauthorized()
    return user


SyncUser = Annotated[User, Depends(sync_user)]


class RegisterRequest(BaseModel):
    username: str = ""
    password: str = ""  # md5(password), as sent by KOReader


class ProgressRequest(BaseModel):
    document: str = ""
    progress: str | int | float = ""  # an XPointer for reflowable books, a page number for PDFs
    percentage: float = 0.0
    device: str = ""
    device_id: str = ""


@router.post("/users/create", status_code=201)
def register(payload: RegisterRequest, db: DB, settings: AppSettings) -> dict:
    if not settings.allow_registration:
        raise KosyncError(402, 2005, "User registration is disabled.")
    if not payload.username or not payload.password:
        raise KosyncError(403, 2003, "Invalid request")
    if users.get_by_username(db, payload.username):
        raise KosyncError(402, 2002, "Username is already registered.")
    try:
        user = users.create_user(db, payload.username, sync_key=payload.password)
    except users.UserError as exc:
        raise KosyncError(403, 2003, "Invalid request") from exc
    return {"username": user.username}


@router.get("/users/auth")
def authorize(user: SyncUser) -> dict:
    return {"authorized": "OK"}


@router.put("/syncs/progress")
def update_progress(payload: ProgressRequest, user: SyncUser, db: DB) -> dict:
    if not payload.document:
        raise KosyncError(403, 2004, "Field 'document' not provided.")
    if (
        len(payload.document) > MAX_DOCUMENT_LENGTH
        or len(str(payload.progress)) > MAX_PROGRESS_LENGTH
    ):
        raise KosyncError(403, 2003, "Invalid request")
    record = progress.save_progress(
        db,
        user.id,
        payload.document,
        progress=str(payload.progress),
        percentage=payload.percentage,
        device=payload.device,
        device_id=payload.device_id,
    )
    return {"document": record.document, "timestamp": record.timestamp}


@router.get("/syncs/progress/{document}")
def get_progress(document: str, user: SyncUser, db: DB) -> dict:
    record = progress.get_progress(db, user.id, document)
    if record is None:
        return {}
    return {
        "document": record.document,
        "progress": record.progress,
        "percentage": record.percentage,
        "device": record.device,
        "device_id": record.device_id,
        "timestamp": record.timestamp,
    }


@router.get("/healthcheck")
def healthcheck() -> dict:
    return {"state": "OK"}
