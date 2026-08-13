# backend/app/services/dingtalk/stream.py
"""钉钉 Stream 模式事件订阅（常驻 WebSocket，无需公网域名/HTTPS 回调）。

基于官方 dingtalk-stream SDK：DingTalkStreamClient.start() 内置断线自动重连
（网络异常 sleep 10 后重连），FastAPI lifespan 中 create_task 常驻即可，
模式同现有 trace_writer_loop。

事件分发：EventHandler.process 按 headers.event_type 路由：
- 通讯录用户/部门变更 → 组织增量同步（M3）
- 审批实例状态变更 bpms_instance_change → 审批回写（M4）
  实例级事件（start/finish/terminate/delete）是审批最终结果依据——多级/会签模板
  下任务级 bpms_task_change 不作为回写依据；Stream 订阅按 processCode+type 精确
  订阅，钉钉后台需为每个审批模板编码配置实例事件订阅。

事件处理全部幂等；处理失败仅记日志（仍返回 200 ack 避免钉钉反复重推），
由定时兜底对账同步补偿。
"""
import logging

import dingtalk_stream
from dingtalk_stream import AckMessage, DingTalkStreamClient, EventHandler, EventMessage

from app.core.config import settings
from app.services.dingtalk.client import DingTalkClient, dingtalk_client

logger = logging.getLogger(__name__)

# 订阅的通讯录 / 审批事件清单（按 headers.event_type 匹配）
EVENT_USER_ADD = "user_add_org"               # 员工入职
EVENT_USER_MODIFY = "user_modify_org"         # 员工信息变更
EVENT_USER_LEAVE = "user_leave_org"           # 员工离职
EVENT_DEPT_CREATE = "org_dept_create"         # 部门新增
EVENT_DEPT_MODIFY = "org_dept_modify"         # 部门变更
EVENT_DEPT_REMOVE = "org_dept_remove"         # 部门删除
EVENT_APPROVAL_INSTANCE = "bpms_instance_change"  # 审批实例状态变更


class DingTalkStreamSubscriber(EventHandler):
    """Stream 事件处理器：按事件类型分发到对应业务处理函数。"""

    def __init__(self, dt_client: DingTalkClient):
        self.dt_client = dt_client
        super().__init__()

    async def process(self, event: EventMessage):
        """处理单个事件；统一应答 200，业务失败只记日志（定时兜底补偿）。

        注意：SDK EventHandler 约定 process 返回 (code, message) 元组，
        raw_process 会解包后构造 AckMessage；返回 AckMessage 对象会抛
        「cannot unpack non-iterable AckMessage object」，导致确认帧
        发不出去、钉钉反复重推事件（真实日志实证）。"""
        event_type = event.headers.event_type
        data = event.data or {}
        logger.info("收到钉钉事件: type=%s corp=%s", event_type, event.headers.event_corp_id)
        try:
            if event_type == EVENT_APPROVAL_INSTANCE:
                await self._handle_approval_instance(data)
            elif event_type in (EVENT_USER_ADD, EVENT_USER_MODIFY, EVENT_USER_LEAVE):
                await self._handle_user_change(event_type, data)
            elif event_type in (EVENT_DEPT_CREATE, EVENT_DEPT_MODIFY, EVENT_DEPT_REMOVE):
                await self._handle_dept_change(event_type, data)
            else:
                logger.debug("未订阅事件类型: %s", event_type)
        except Exception as e:
            logger.warning("钉钉事件处理失败 type=%s: %s", event_type, e)
        return AckMessage.STATUS_OK, "OK"

    # ---- M4 审批回写（approval_gateway 实现）----
    async def _handle_approval_instance(self, data: dict) -> None:
        from app.services.dingtalk.approval_gateway import handle_approval_instance_change
        await handle_approval_instance_change(data)

    # ---- M3 组织增量同步（org_sync 实现）----
    async def _handle_user_change(self, event_type: str, data: dict) -> None:
        from app.services.dingtalk.org_sync import handle_user_change_event
        await handle_user_change_event(self.dt_client, event_type, data)

    async def _handle_dept_change(self, event_type: str, data: dict) -> None:
        from app.services.dingtalk.org_sync import handle_dept_change_event
        await handle_dept_change_event(self.dt_client, event_type, data)


async def start_stream_subscriber() -> None:
    """启动 Stream 事件订阅常驻任务（SDK 内部无限重连，直至任务取消）。

    供 FastAPI lifespan 调用；本函数持有连接直至被取消，因此需 create_task 包裹。
    """
    credential = dingtalk_stream.Credential(
        settings.DINGTALK_CLIENT_ID, settings.DINGTALK_CLIENT_SECRET)
    client = DingTalkStreamClient(credential)
    client.register_all_event_handler(DingTalkStreamSubscriber(dingtalk_client))
    logger.info("钉钉 Stream 事件订阅启动（WebSocket 常驻）")
    await client.start()
