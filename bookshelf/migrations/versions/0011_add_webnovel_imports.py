"""add webnovel imports

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-24 19:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webnovel_imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("novel_id", sa.String(length=64), nullable=True),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("log", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_id"),
    )
    op.create_index("ix_webnovel_imports_user_id", "webnovel_imports", ["user_id"])
    op.create_index("ix_webnovel_imports_user", "webnovel_imports", ["user_id", "created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_webnovel_imports_user", table_name="webnovel_imports")
    op.drop_index("ix_webnovel_imports_user_id", table_name="webnovel_imports")
    op.drop_table("webnovel_imports")
