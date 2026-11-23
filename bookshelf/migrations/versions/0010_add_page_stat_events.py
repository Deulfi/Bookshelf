"""add page stat events

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-23 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('page_stat_events',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('document', sa.String(length=32), nullable=False),
    sa.Column('start_time', sa.Integer(), nullable=False),
    sa.Column('page', sa.Integer(), nullable=False),
    sa.Column('duration', sa.Integer(), nullable=False),
    sa.Column('total_pages', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'document', 'start_time', 'page')
    )


def downgrade() -> None:
    op.drop_table('page_stat_events')
