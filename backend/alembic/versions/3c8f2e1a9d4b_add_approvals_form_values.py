"""add approvals form_values

Revision ID: 3c8f2e1a9d4b
Revises: fb5457b55969
Create Date: 2026-08-13 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c8f2e1a9d4b'
down_revision: Union[str, Sequence[str], None] = 'fb5457b55969'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('approvals', sa.Column('form_values', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('approvals', 'form_values')
