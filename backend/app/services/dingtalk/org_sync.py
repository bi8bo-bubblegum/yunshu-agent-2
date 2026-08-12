# backend/app/services/dingtalk/org_sync.py
"""组织架构同步（部门 / 用户）——M3 里程碑实现，当前为占位骨架。

全量同步：递归拉取部门树 + 按部门分页拉取用户，按 dingtalk_dept_id /
dingtalk_userid 幂等 upsert 到本地库。
增量同步：Stream 事件驱动单条 upsert；删除事件软删除（status=inactive）。
定时兜底：lifespan 后台任务按 DINGTALK_SYNC_INTERVAL_MINUTES 对账。
"""
import logging

logger = logging.getLogger(__name__)


async def handle_user_change_event(dt_client, event_type: str, data: dict) -> None:
    """员工入职 / 变更 / 离职事件的增量同步入口（M3 实现）。"""
    logger.warning("组织用户增量同步待 M3 实现: type=%s data=%s", event_type, data)


async def handle_dept_change_event(dt_client, event_type: str, data: dict) -> None:
    """部门新增 / 变更 / 删除事件的增量同步入口（M3 实现）。"""
    logger.warning("组织部门增量同步待 M3 实现: type=%s data=%s", event_type, data)
