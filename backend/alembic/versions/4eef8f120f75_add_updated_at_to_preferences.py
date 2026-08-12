"""add updated_at to preferences

Revision ID: 4eef8f120f75
Revises: f2c5606fd1fb
Create Date: 2026-08-12

偏好注入排序依赖「最近确认时间」。preferences 原只有 created_at（只增不删、只强不弱），
无法反映偏好演化。新增 updated_at（server_default=now() 回填已有行，onupdate 由 ORM
merge 显式赋值兜底），驱动「新鲜 × confidence」排序 + Top-N 截断注入。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4eef8f120f75'
down_revision: Union[str, Sequence[str], None] = 'f2c5606fd1fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('preferences', sa.Column(
        'updated_at', sa.DateTime(timezone=True),
        server_default=sa.text('now()'), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('preferences', 'updated_at')
