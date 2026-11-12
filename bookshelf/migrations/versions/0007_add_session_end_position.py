"""add session end position

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-12 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Sessions recorded before this column resume at their end percentage instead.
    with op.batch_alter_table('reading_sessions') as batch_op:
        batch_op.add_column(sa.Column('end_position', sa.Text(), nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('reading_sessions') as batch_op:
        batch_op.drop_column('end_position')
