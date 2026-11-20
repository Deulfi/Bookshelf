"""Command line interface: ``python -m bookshelf [serve|create-user|set-password]``."""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from .config import Settings
from .db import init_database
from .services import users


def _password(args: argparse.Namespace) -> str:
    if args.password:
        return args.password
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords don't match.")
    return password


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bookshelf", description=__doc__)
    commands = parser.add_subparsers(dest="command")

    serve = commands.add_parser("serve", help="run the web server (default)")
    serve.add_argument("--host", default=os.environ.get("BOOKSHELF_HOST", "0.0.0.0"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("BOOKSHELF_PORT", "8080")))
    serve.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")

    create = commands.add_parser("create-user", help="create a user account")
    create.add_argument("username")
    create.add_argument("--admin", action="store_true", help="grant administrator rights")
    create.add_argument("--password", help="password (prompted if omitted)")

    reset = commands.add_parser("set-password", help="set a user's password")
    reset.add_argument("username")
    reset.add_argument("--password", help="password (prompted if omitted)")

    args = parser.parse_args(argv)

    if args.command in (None, "serve"):
        import uvicorn

        uvicorn.run(
            "bookshelf.main:create_server",
            factory=True,
            host=getattr(args, "host", "0.0.0.0"),
            port=getattr(args, "port", 8080),
            reload=getattr(args, "reload", False),
            proxy_headers=False,  # create_server handles them (it keeps the peer address)
            server_header=False,
        )
        return

    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with init_database(settings.database_url)() as db:
        try:
            if args.command == "create-user":
                user = users.create_user(
                    db, args.username, password=_password(args), is_admin=args.admin
                )
                print(f"Created user '{user.username}'.")
            elif args.command == "set-password":
                user = users.get_by_username(db, args.username)
                if user is None:
                    sys.exit(f"No such user: {args.username}")
                users.set_password(db, user, _password(args))
                print(f"Password for '{user.username}' updated.")
        except users.UserError as exc:
            sys.exit(str(exc))


if __name__ == "__main__":
    main()
