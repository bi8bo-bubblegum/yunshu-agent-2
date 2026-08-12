# backend/app/services/dingtalk/approval_gateway.py
"""审批对接网关（M4）：本地审批单 → 钉钉 OA 审批 → 结果回写恢复图执行。

发起推送：ApprovalService.create_approval 创建本地单后（同事务）调用 push_approval_to_dingtalk，
  用发起人钉钉账号调 POST /v1.0/workflow/processInstances 建钉钉审批实例，写 approval_binding。
  全走钉钉审批：推送失败抛 HTTPException，调用方会话回滚（图不冻结 / 经验回 draft），不做本地兜底。

结果回写：Stream 订阅 bpms_instance_change 事件 → handle_approval_instance_change 按
  processInstanceId 查 binding → 幂等更新本地单状态 → 复用 approval_service.apply_decision
  恢复 LangGraph 图执行（与本地审批行为完全一致）。

撤销对接（本期不做）：terminate 接口由钉钉侧发起时，事件 type=terminate 视为驳回处理。
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import ApprovalBinding
from app.repositories.department_repo import DepartmentRepository
from app.repositories.dingtalk_repo import ApprovalBindingRepository
from app.repositories.user_repo import UserRepository
from app.services.dingtalk.client import DingTalkError, dingtalk_client

logger = logging.getLogger(__name__)

# 钉钉审批模板控件约定：模板须含同名两个控件，否则钉钉返回 formConverterError。
# 控件 name 即模板 label（管理员在钉钉 OA 后台建模板时按此约定命名）。
CONTROL_TITLE = "审批标题"      # TextField：审批单标题
CONTROL_DETAIL = "审批详情"     # TextareaField：工具参数/经验摘要 JSON

# 后台任务引用持有（防 GC）：URL 回填 / 事件恢复图执行
_bg_tasks: set[asyncio.Task] = set()


def build_form_values(approval) -> list[dict]:
    """把本地审批单映射成钉钉表单值（context 序列化 JSON 展示工具参数/经验摘要）。"""
    return [
        {"name": CONTROL_TITLE, "value": approval.title, "componentType": "TextField"},
        {"name": CONTROL_DETAIL,
         "value": json.dumps(approval.context or {}, ensure_ascii=False, indent=2),
         "componentType": "TextareaField"},
    ]


async def push_approval_to_dingtalk(db, approval) -> ApprovalBinding:
    """把本地审批单推送到钉钉 OA 审批，返回 binding（由调用方 commit，与审批单同事务）。

    全走钉钉审批：未配置/推送失败直接抛 HTTPException，不降级本地审批——
    本地 pending 单无人审批，图会永久冻结，报错让调用方回滚更安全。
    """
    process_code = settings.DINGTALK_OA_PROCESS_CODES.get(approval.category)
    if not settings.dingtalk_enabled or not process_code:
        raise HTTPException(
            400,
            "钉钉审批未配置（缺少凭证或审批模板编码），无法发起审批，"
            "请管理员配置 DINGTALK_CLIENT_ID/SECRET 与 DINGTALK_OA_PROCESS_CODES 后重试",
        )
    requester = await UserRepository(db).get(approval.requester_id)
    originator_user_id = requester.dingtalk_userid if requester else None
    if not originator_user_id:
        raise HTTPException(400, "发起人未绑定钉钉账号（dingtalk_userid 为空），无法发起审批")
    # deptId：不指定 approvers 时必填；无部门/无钉钉部门映射 → 根部门 -1
    dept_id = -1
    if requester.department_id:
        dept = await DepartmentRepository(db).get(requester.department_id)
        if dept and dept.dingtalk_dept_id is not None:
            dept_id = dept.dingtalk_dept_id
    microapp_agent_id = int(settings.DINGTALK_AGENT_ID) if settings.DINGTALK_AGENT_ID else None
    try:
        instance_id = await dingtalk_client.create_process_instance(
            originator_user_id=originator_user_id, process_code=process_code,
            dept_id=dept_id, form_component_values=build_form_values(approval),
            microapp_agent_id=microapp_agent_id)
    except DingTalkError as e:
        raise HTTPException(502, f"钉钉审批发起失败：{e.message}") from e
    binding = ApprovalBinding(approval_id=approval.id, process_code=process_code,
                              process_instance_id=instance_id, status="pushed")
    db.add(binding)
    # 注：URL 回填由调用方在 commit 之后调度（schedule_enrich_binding_urls），
    # 因为回填任务用独立 session，commit 前调度查不到未落库的 binding（真实竞态）。
    return binding


# ------------------------------------------------------------------
# 「去钉钉处理」跳转 URL 回填（后台任务，失败降级为无 URL，前端可刷新重试）
# ------------------------------------------------------------------

def schedule_enrich_binding_urls(process_instance_id: str) -> None:
    """调度后台回填「去钉钉处理」跳转 URL（由调用方在 binding 落库 commit 后调用）。"""
    task = asyncio.create_task(_enrich_binding_urls(process_instance_id))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def _enrich_binding_urls(process_instance_id: str) -> None:
    """后台拉审批实例详情，回填 binding.mobile_url / pc_url。

    独立 session；失败仅记日志（前端对无 URL 的单显示「已推送」，刷新后重试回填）。
    """
    try:
        async with SessionLocal() as db:
            binding = await ApprovalBindingRepository(db).get_by_process_instance_id(process_instance_id)
            if not binding:
                return
            result = await dingtalk_client.get_process_instance(process_instance_id)
            tasks = (result or {}).get("tasks") or []
            if tasks:
                binding.mobile_url = tasks[0].get("mobileUrl")
                binding.pc_url = tasks[0].get("pcUrl")
                await db.commit()
    except Exception as e:
        logger.warning("回填审批实例 URL 失败（已降级）: pid=%s err=%s", process_instance_id, e)


# ------------------------------------------------------------------
# 事件回写：bpms_instance_change
# ------------------------------------------------------------------

async def handle_approval_instance_change(data: dict) -> None:
    """审批实例状态变更事件回写（start / finish / terminate），幂等，失败仅记日志。

    事件 data 字段（按钉钉官方文档，待用户确认后校正）：
      processInstanceId 审批实例 ID（必）
      type             start / finish / terminate
      result           agree / refuse（type=finish 时有值）
      staffId          操作者（审批人）钉钉 userid
    start 不改状态（此时仍 pending，等待审批）；finish 按 result 判定；terminate 视为驳回。
    """
    try:
        await _handle_approval_change_inner(data)
    except Exception as e:
        # Stream 事件回调不允许抛异常（会中断订阅）；兜底记日志，前端刷新后重试
        logger.warning("审批事件回写处理失败（已降级）: data=%s err=%s", data, e)


async def _handle_approval_change_inner(data: dict) -> None:
    """事件回写具体逻辑（拆出以便整体兜底异常捕获）。"""
    pid = data.get("processInstanceId")
    if not pid:
        logger.warning("审批事件缺少 processInstanceId: data=%s", data)
        return
    event_type = data.get("type", "finish")
    result = data.get("result", "")
    staff_id = data.get("staffId")
    async with SessionLocal() as db:
        binding = await ApprovalBindingRepository(db).get_by_process_instance_id(pid)
        if not binding:
            logger.warning("审批事件未匹配本地 binding，忽略: pid=%s", pid)
            return
        if event_type == "start":
            logger.info("审批实例启动（等待审批）: approval_id=%s pid=%s", binding.approval_id, pid)
            return
        if event_type == "terminate":
            approved, comment = False, "钉钉审批实例已终止（钉钉侧取消）"
        else:  # finish
            approved = (result == "agree")
            comment = "钉钉审批通过" if approved else "钉钉审批驳回"
        # 复用统一审批服务：幂等（已处理过返回 False）+ 按 category 恢复图/晋升经验
        from app.services.approval_service import ApprovalService
        svc = ApprovalService(db)
        applied = await svc.apply_decision(
            binding.approval_id, approved=approved, comment=comment,
            approver_dingtalk_userid=staff_id, decided_at=datetime.now(timezone.utc))
        if applied:
            binding.status = "synced"
            await db.commit()
            logger.info("审批回写完成: approval_id=%s approved=%s", binding.approval_id, approved)
