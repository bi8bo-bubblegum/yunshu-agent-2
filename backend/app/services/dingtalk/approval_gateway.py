# backend/app/services/dingtalk/approval_gateway.py
"""审批对接网关——M4 里程碑实现，当前为占位骨架。

发起推送：本地审批单 → 钉钉 OA 审批（processInstances），写 approval_binding。
结果回写：订阅 bpms_instance_change 事件，更新本地单状态并复用
approval_service._resume_graph_impl 恢复 LangGraph 执行（与本地审批行为一致）。
撤销对接：terminate 接口 + 模板需开启『允许提交人撤销』。
"""
import logging

logger = logging.getLogger(__name__)


async def handle_approval_instance_change(data: dict) -> None:
    """审批实例状态变更（start / finish / terminate）回写入口（M4 实现）。"""
    logger.warning("审批回写待 M4 实现: data=%s", data)
