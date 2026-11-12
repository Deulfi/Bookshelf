"""add reading sessions

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-11 22:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('reading_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('document', sa.String(length=32), nullable=False),
    sa.Column('device', sa.String(length=200), nullable=False),
    sa.Column('device_id', sa.String(length=200), nullable=False),
    sa.Column('started_at', sa.Integer(), nullable=False),
    sa.Column('ended_at', sa.Integer(), nullable=False),
    sa.Column('seconds', sa.Integer(), nullable=False),
    sa.Column('start_fraction', sa.Double(), nullable=False),
    sa.Column('end_fraction', sa.Double(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_reading_sessions_book', 'reading_sessions', ['user_id', 'document', 'ended_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_reading_sessions_book', table_name='reading_sessions')
    op.drop_table('reading_sessions')
