"""add web reading time

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-11 16:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('web_reading_time',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('document', sa.String(length=32), nullable=False),
    sa.Column('hour', sa.Integer(), nullable=False),
    sa.Column('seconds', sa.Integer(), nullable=False),
    sa.Column('last_read', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'document', 'hour')
    )


def downgrade() -> None:
    op.drop_table('web_reading_time')
