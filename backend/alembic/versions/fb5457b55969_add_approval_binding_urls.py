"""add approval binding urls

Revision ID: fb5457b55969
Revises: a78712a6db47
Create Date: 2026-08-12 16:45:54.462539

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fb5457b55969'
down_revision: Union[str, Sequence[str], None] = 'a78712a6db47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 仅新增 approval_binding 两列跳转地址。
    # 手工剔除 autogenerate 误判的 ix_users_role_code（模型声明 index=True 但历史迁移
    # 386bfa5be3a3 只 add_column 未建索引，属既有偏差，与 M4 无关，不在本迁移处理）。
    op.add_column('approval_binding', sa.Column('mobile_url', sa.String(length=512), nullable=True))
    op.add_column('approval_binding', sa.Column('pc_url', sa.String(length=512), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('approval_binding', 'pc_url')
    op.drop_column('approval_binding', 'mobile_url')
