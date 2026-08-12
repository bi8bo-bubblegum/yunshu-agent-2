# backend/app/services/approval_service.py
import asyncio
import logging
from datetime import datetime, timezone
from app.core.config import settings
from app.models.org import User
from app.models.trace import Approval
from app.models.dingtalk import ApprovalBinding
from app.repositories.trace_repo import ApprovalRepository, TraceRepository
from app.repositories.experience_repo import ExperienceRepository
from app.repositories.dingtalk_repo import ApprovalBindingRepository
from app.repositories.user_repo import UserRepository
from app.services.tool_cards import tool_message_rows
from app.traces.handlers import (StreamEventHandler, TraceCallbackHandler,
                                 acquire_resume_recorder, release_resume_recorder)
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

# 审批恢复图执行整体限时：与 ChatService.resume 的 RESUME_TIMEOUT 对齐。
# 恢复后 agent 内 LLM 已由 stream_llm(60s) 超时兜底，这里给整体执行一个总闸，
# 防止审批接口因网关挂起无限等待（真实事故：resume 恢复后 agent 生成挂起 >170s）。
RESUME_TIMEOUT = 90.0

# 后台审批恢复图执行任务管理：持有引用防 GC（同 chat_service._bg_mem_tasks 模式）
_bg_resume_tasks: set[asyncio.Task] = set()


class ApprovalService:
    """统一审批中心（M4 起全走钉钉 OA 审批，本地审批流程下线）。

    - create_approval：创建本地单 + 同事务推送钉钉 OA（approval_gateway.push_approval_to_dingtalk）
    - apply_decision：审批结果回写入口，按 category 分发后处理：
      - tool_call + sync（critical 工具调用）：更新状态 + 后台恢复 LangGraph 图执行
      - experience_promotion（经验晋升）：更新状态 + 经验层级晋升
    本地无审批按钮；结果全部来自钉钉事件回写（handle_approval_instance_change 调用）。"""
    def __init__(self, db):
        self.db = db
        self.approval_repo = ApprovalRepository(db)
        self.trace_repo = TraceRepository(db)
        self.experience_repo = ExperienceRepository(db)
        self.user_repo = UserRepository(db)
        self.binding_repo = ApprovalBindingRepository(db)

    async def list_pending(self, user: User, status: str | None = None, category: str | None = None):
        """审批单列表（pending/approved/rejected），按角色可见性过滤，前端按 status 筛选展示。
        发起人/审批人附 username（id 不可读，展示用）；补钉钉绑定信息（跳转 URL/推送状态）。"""
        rows = await self.approval_repo.list_for_user(
            user.id, user.role_code, user.department_id, status, category)
        ids = {a.requester_id for a in rows} | {a.approver_id for a in rows if a.approver_id}
        users = {u.id: u.username for u in await self.user_repo.list_by_ids(list(ids))}
        bindings = await self.binding_repo.list_by_approval_ids([a.id for a in rows])
        bmap = {b.approval_id: b for b in bindings}
        items = []
        for a in rows:
            b = bmap.get(a.id)
            items.append({"id": a.id, "category": a.category, "risk": a.risk, "mode": a.mode,
                          "title": a.title, "context": a.context, "requester_id": a.requester_id,
                          "requester_name": users.get(a.requester_id, ""),
                          "status": a.status, "comment": a.comment,
                          "approver_id": a.approver_id,
                          "approver_name": users.get(a.approver_id) if a.approver_id else None,
                          "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
                          "decided_at": a.decided_at.isoformat() if a.decided_at else None,
                          # 钉钉绑定信息（「去钉钉处理」跳转 + 推送状态展示）
                          "process_instance_id": b.process_instance_id if b else None,
                          "push_status": b.status if b else None,
                          "pc_url": b.pc_url if b else None,
                          "mobile_url": b.mobile_url if b else None})
        return items

    async def create_approval(self, category: str, risk: str | None, mode: str,
                              ref_type: str, ref_id: str, title: str,
                              context: dict | None, requester_id: str,
                              approver_role: str | None = None,
                              approval_id: str | None = None) -> str:
        """创建审批单并推送钉钉 OA，返回审批单 ID。

        M4 起全走钉钉审批：本地单创建（add+flush）后同事务推送钉钉（add binding），
        再统一 commit。推送失败抛 HTTPException → 调用方会话回滚（图不冻结/经验回 draft）。
        供 facade.guarded_critical 和 ExperienceService.submit 调用。
        approval_id 用于 critical 工具场景传入确定性 ID（interrupt 恢复重放时幂等，避免重复建单）。
        """
        if approval_id:
            existing = await self.approval_repo.get(approval_id)
            if existing is not None:
                # 重放路径（interrupt 恢复）：复用已存在单；历史遗留无绑定单补推钉钉；
                # 绑定已存在但缺跳转 URL（首推回填失败）时顺带重新回填
                binding = await self.binding_repo.get_by(approval_id=existing.id)
                if binding is None:
                    binding = await self._push_or_raise(existing)
                    await self.approval_repo.commit()
                self._schedule_binding_enrich(binding)
                return existing.id
        approval = Approval(
            id=approval_id,
            category=category, risk=risk, mode=mode,
            ref_type=ref_type, ref_id=ref_id, title=title,
            context=context, status="pending", requester_id=requester_id,
            approver_role=approver_role,
        )
        await self.approval_repo.add(approval)
        binding = await self._push_or_raise(approval)   # add(binding)，推送失败抛异常会话回滚
        await self.approval_repo.commit()               # 审批单 + binding 同事务提交
        self._schedule_binding_enrich(binding)          # 落库后调度回填跳转 URL（独立 session 可见）
        return approval.id

    async def _push_or_raise(self, approval: Approval) -> ApprovalBinding:
        """推送钉钉 OA 返回 binding（懒加载网关避免循环导入：gateway 顶层 import 本模块）。"""
        from app.services.dingtalk.approval_gateway import push_approval_to_dingtalk
        return await push_approval_to_dingtalk(self.db, approval)

    def _schedule_binding_enrich(self, binding: ApprovalBinding | None) -> None:
        """commit 后调度后台回填「去钉钉处理」URL；绑定缺失/已有 URL/未启用钉钉时跳过。

        未启用钉钉（如 mock_dingtalk_push 测试）不调度：回填任务用真实 client 触网，
        会造成测试真实网络请求，且无钉钉实例本就无 URL 可回填。"""
        if binding is None or (binding.mobile_url and binding.pc_url):
            return
        if not settings.dingtalk_enabled:
            return
        from app.services.dingtalk.approval_gateway import schedule_enrich_binding_urls
        schedule_enrich_binding_urls(binding.process_instance_id)

    async def apply_decision(self, approval_id: str, approved: bool, comment: str = "",
                             approver_dingtalk_userid: str | None = None,
                             decided_at: datetime | None = None) -> bool:
        """审批结果回写入口（钉钉事件回写调用），返回 True 表示已处理 / False 幂等跳过。

        更新状态 + 按 category 分发后处理，与旧 decide 行为完全一致：
        - tool_call + sync：后台恢复 LangGraph 图执行（独立 session，decide 入口立即返回）
        - experience_promotion：通过则层级晋升；驳回则恢复审批前状态
        approver_dingtalk_userid 为钉钉审批人 userid，反查本地用户写 approver_id。
        """
        ap = await self.approval_repo.get(approval_id)
        if not ap or ap.status != "pending":
            return False    # 幂等：事件重复/迟到自动跳过
        approver_id = None
        if approver_dingtalk_userid:
            approver = await self.user_repo.get_by(dingtalk_userid=approver_dingtalk_userid)
            approver_id = approver.id if approver else None
        ap.status = "approved" if approved else "rejected"
        if approver_id:
            ap.approver_id = approver_id
        if comment:
            ap.comment = comment
        ap.decided_at = decided_at or datetime.now(timezone.utc)
        await self.approval_repo.commit()

        if ap.category == "tool_call" and ap.mode == "sync":
            # critical 工具调用：恢复 LangGraph 图执行。
            # 后台任务执行：恢复图含 LLM 调用（最长 RESUME_TIMEOUT），若同步 await，
            # 事件处理长时间不返回会拖慢 Stream ack；后台独立 session 恢复，入口立即返回。
            task = asyncio.create_task(_resume_graph_in_background(ap.id, approved, ap.ref_id))
            _bg_resume_tasks.add(task)
            task.add_done_callback(_bg_resume_tasks.discard)
        elif ap.category == "experience_promotion":
            # 经验晋升：通过则层级晋升；驳回则恢复审批前状态（否则经验 status 卡在
            # pending 无法再次晋升，真实事故：晋升被拒后经验永远显示「审批中」）
            if approved:
                await self._promote_experience(ap.ref_id, ap.context.get("to_scope", "dept"))
            else:
                await self._reject_experience_promotion(ap.ref_id, ap.context.get("from_scope", "personal"))
        return True

    async def _promote_experience(self, experience_id: str, to_scope: str):
        """经验层级晋升。"""
        exp = await self.experience_repo.get(experience_id)
        if exp:
            exp.scope = to_scope
            exp.status = "approved"
            await self.experience_repo.commit()

    async def _reject_experience_promotion(self, experience_id: str, from_scope: str):
        """经验晋升被驳回：恢复审批前状态。

        personal 层晋升被拒 → 回草稿（可修改/重新晋升）；
        dept 层晋升公司被拒 → 回已通过（保留部门层可见，仍可再次晋升公司）。"""
        exp = await self.experience_repo.get(experience_id)
        if not exp:
            return
        exp.status = "draft" if from_scope == "personal" else "approved"
        await self.experience_repo.commit()


async def _resume_graph_in_background(approval_id: str, approved: bool, trace_id: str) -> None:
    """审批决定后异步恢复图执行（独立 session，不阻塞 decide 请求）。

    真实事故：decide() 同步 await 恢复图执行（graph.ainvoke 含 LLM，最长
    RESUME_TIMEOUT），decide 请求长时间不返回 → 前端「无反应」；而审批单状态已
    在 decide 里 commit 为 approved，用户再次点击即抛 404「审批单不存在或已处理」。
    改后台任务后 decide 立即返回 ok，图恢复完成后用独立 session 落库。"""
    try:
        async with SessionLocal() as db:
            await _resume_graph_impl(db, approval_id, approved, trace_id)
    except Exception as e:
        logger.warning("审批后台恢复图执行失败（已降级）: %s", e)


async def _resume_graph_impl(db, approval_id: str, approved: bool, trace_id: str) -> None:
    """审批恢复图执行 + 分段落库 + 记忆沉淀（session 由调用方传入，可在后台任务复用）。

    原为 ApprovalService 方法（依赖请求级 self.db），后台化后需要独立 session，
    故抽成模块级函数接收 db 参数。图执行挂起时由 RESUME_TIMEOUT 限时兜底。"""
    from app.agents.graph import get_graph
    from langgraph.types import Command
    from app.models.chat import Message
    from app.repositories.conversation_repo import ConversationRepository, MessageRepository
    from app.repositories.trace_repo import TraceRepository
    trace_repo = TraceRepository(db)
    trace = await trace_repo.get(trace_id) if trace_id else None
    if not trace or not trace.conversation_id:
        return
    message_repo = MessageRepository(db)
    conv_repo = ConversationRepository(db)
    # 审批路径无前端 SSE：补挂 StreamEventHandler(None) 只收集工具调用，终态后落库工具卡片。
    # recorder 按 trace_id 跨 resume/审批共享（多级 interrupt 时中间工具卡片不丢失），终态后 release
    resume_recorder = acquire_resume_recorder(trace.id)
    config = {"configurable": {"thread_id": trace.conversation_id,
                               "trace_id": trace.id,
                               "requester_id": trace.user_id},
              "callbacks": [TraceCallbackHandler(trace.id),
                            StreamEventHandler(None, trace.id, recorder=resume_recorder)]}
    graph = await get_graph()
    # 本轮开始前 agent_outputs 长度：审批恢复后按轮切分段落，与 stream_chat 分段落库一致
    pre_snap = await graph.aget_state(config)
    al0 = len((pre_snap.values or {}).get("agent_outputs", [])) if pre_snap else 0
    try:
        result = await asyncio.wait_for(
            graph.ainvoke(
                Command(resume={"approved": approved, "approval_id": approval_id}),
                config=config,
            ),
            timeout=RESUME_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("审批恢复图执行超时(%.0fs)，图可能仍挂起", RESUME_TIMEOUT)
        return
    # 图内还有后续 interrupt（多级审批），保持挂起
    if result.get("__interrupt__"):
        return
    text = result.get("agent_response", "")
    # 工具卡片落库：审批恢复期间的工具调用转成 tool 消息，随下方 trace_repo.commit() 同事务提交
    for tm in tool_message_rows(trace.conversation_id, resume_recorder):
        await message_repo.add(tm)
    outputs = result.get("agent_outputs", []) or []
    # 只取审批恢复新增的段落 [al0:]；al0 == len(outputs)（恢复后无新增产出）时为空，
    # 避免把历史 agent_outputs 重复落库（与 stream_chat 一致，防止 step 段落重复）。
    segments = outputs[al0:] if al0 is not None and al0 < len(outputs) else []
    # 过滤无实质内容的段落：LLM 输出空白/换行（如 '\n\n'）时不是有效产出，
    # 落库会生成空白气泡（真实事故：scheduling 输出 '\n\n' 被当段落落库）。
    segments = [s for s in segments if (s.get("content") or "").strip()]
    if segments:
        last_i = len(segments) - 1
        for i, seg in enumerate(segments):
            content = seg.get("content") or ""
            if i == last_i:
                # 最终段用 agent_response（权威完整文本）覆盖；agent_response 空白时
                # 保留段落自身内容，避免 final 被覆盖成空内容（真实事故）
                content = text or content
            await message_repo.add(Message(
                conversation_id=trace.conversation_id, role="assistant", content=content,
                metadata_={"agent": seg.get("agent", ""),
                           "segment": "final" if i == last_i else "step"},
            ))
    else:
        await message_repo.add(Message(conversation_id=trace.conversation_id,
                                       role="assistant", content=text))
    trace.status = "completed"
    trace.supervisor_routes = result.get("route_history", [])
    await trace_repo.commit()
    # 终态落库完成，释放共享 recorder（多级 interrupt 场景下 create/publish 已全部收集）
    release_resume_recorder(trace.id)
    conv = await conv_repo.get(trace.conversation_id)
    if conv:
        conv.current_trace_id = trace.id
        await trace_repo.commit()
    from app.traces.collector import collector
    collector.emit(trace.id, "route", {"routes": trace.supervisor_routes})
    # 与 ChatService.stream_chat 完成路径对齐：偏好提取 / 经验提炼 / 摘要滚动 / 自动标题
    try:
        from app.services.preference_svc import maybe_extract_batch
        from app.services.experience_svc import build_experience_dialog, distill_experience, save_personal_experience
        from app.services.summary import maybe_roll_summary, schedule_title_generation
        all_msgs = await message_repo.list_by_conversation(trace.conversation_id)
        user_msg = next((m.content for m in reversed(all_msgs) if m.role == "user"), "")
        await maybe_extract_batch(db, trace.user_id, trace.conversation_id)
        # 经验提炼用多轮上下文（单轮问答缺业务过程，纯查询易误判为经验）
        dialog = await build_experience_dialog(db, trace.conversation_id)
        exp = await distill_experience(dialog, trace.user_id, trace.id)
        if exp:
            await save_personal_experience(db, exp)
        await maybe_roll_summary(db, trace.conversation_id)
        # 标题生成走后台任务（独立 Session + 会话级去重），不阻塞审批响应
        schedule_title_generation(trace.conversation_id, user_msg or text[:500])
    except Exception as e:
        logger.warning("审批恢复后记忆沉淀处理失败（已降级）: %s", e)
