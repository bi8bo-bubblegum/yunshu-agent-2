# backend/app/repositories/dingtalk_repo.py
"""钉钉对接专用仓库：审批实例绑定 / 同步状态。"""
from sqlalchemy import select

from app.models import ApprovalBinding, DingTalkSyncState
from app.repositories.base import BaseRepository


class ApprovalBindingRepository(BaseRepository[ApprovalBinding]):
    """本地审批单 ↔ 钉钉审批实例绑定关系（M4 审批对接）。"""

    model = ApprovalBinding

    async def get_by_process_instance_id(self, process_instance_id: str) -> ApprovalBinding | None:
        """按钉钉审批实例 ID 查绑定（事件回写用）。"""
        return await self.get_by(process_instance_id=process_instance_id)

    async def list_by_approval_ids(self, approval_ids: list[str]) -> list[ApprovalBinding]:
        """按本地审批单 ID 批量查绑定（审批列表补充跳转 URL 用）。"""
        if not approval_ids:
            return []
        return list((await self.db.scalars(
            select(ApprovalBinding).where(ApprovalBinding.approval_id.in_(approval_ids))
        )).all())


class DingTalkSyncStateRepository(BaseRepository[DingTalkSyncState]):
    """组织同步游标/时间戳（定时兜底判定用）。"""

    model = DingTalkSyncState

    async def get_by_sync_type(self, sync_type: str) -> DingTalkSyncState | None:
        return await self.get_by(sync_type=sync_type)
