"""User accounts: creation, authentication and password management."""

from __future__ import annotations

import re
import secrets

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import security
from ..models import Book, User
from ..storage import Storage

USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._@-]{0,63}$")
MIN_PASSWORD_LENGTH = 6


class UserError(ValueError):
    """A validation error with a user-facing message."""


def normalize_username(username: str) -> str:
    return username.strip().lower()


def get_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == normalize_username(username)))


def has_users(db: Session) -> bool:
    return db.scalar(select(User.id).limit(1)) is not None


def list_users_with_book_counts(db: Session) -> list[tuple[User, int]]:
    counts = select(Book.user_id, func.count(Book.id).label("n")).group_by(Book.user_id).subquery()
    rows = db.execute(
        select(User, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.user_id == User.id)
        .order_by(User.username)
    )
    return [(user, count) for user, count in rows]


def create_user(
    db: Session,
    username: str,
    *,
    password: str | None = None,
    sync_key: str | None = None,
    is_admin: bool = False,
) -> User:
    """Create a user from a plain password (web) or a KOReader md5 key (sync registration)."""
    name = normalize_username(username)
    if not USERNAME_PATTERN.match(name):
        raise UserError(
            "Usernames are 1–64 characters: letters, digits and . _ @ - "
            "(starting with a letter or digit)."
        )
    if get_by_username(db, name):
        raise UserError("This username is already taken.")
    if password is not None:
        _validate_password(password)
        password_hash = security.hash_password(password)
    elif sync_key:
        password_hash = security.hash_sync_key(sync_key)
    else:
        raise UserError("A password is required.")

    user = User(username=name, password_hash=password_hash, is_admin=is_admin)
    db.add(user)
    db.commit()
    return user


def _random_password() -> str:
    """For accounts made without a login form; the device password is set in the settings."""
    return secrets.token_urlsafe(24)


def single_user(db: Session) -> User:
    """The account used when the web UI has no login (``BOOKSHELF_AUTH=none``): the first
    administrator, or a new "admin" account on first start."""
    user = db.scalar(select(User).where(User.is_admin).order_by(User.id).limit(1))
    if user is None:
        user = db.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        user = create_user(db, "admin", password=_random_password(), is_admin=True)
    return user


def proxy_user(db: Session, username: str) -> User:
    """The account named by the reverse proxy (``BOOKSHELF_AUTH=header``), created on first
    visit. The first account becomes an administrator, like the one made on the setup page."""
    user = get_by_username(db, username)
    if user is None:
        try:
            user = create_user(
                db, username, password=_random_password(), is_admin=not has_users(db)
            )
        except IntegrityError:  # two first requests at once: the other one created it
            db.rollback()
            user = get_by_username(db, username)
            if user is None:
                raise
    return user


def set_password(db: Session, user: User, password: str) -> None:
    _validate_password(password)
    user.password_hash = security.hash_password(password)
    db.commit()


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = get_by_username(db, username)
    if user and security.verify_password(password, user.password_hash):
        return user
    return None


def authenticate_sync_key(db: Session, username: str, key: str) -> User | None:
    user = get_by_username(db, username)
    if user and key and security.verify_sync_key(key, user.password_hash):
        return user
    return None


def delete_user(db: Session, storage: Storage, user: User) -> None:
    for book in user.books:
        storage.delete_book_files(book)
    storage.delete_user_dir(user.id)
    storage.user_reader_config(user.id, user.username).unlink(missing_ok=True)
    db.delete(user)
    db.commit()


def _validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise UserError(f"Passwords need at least {MIN_PASSWORD_LENGTH} characters.")
