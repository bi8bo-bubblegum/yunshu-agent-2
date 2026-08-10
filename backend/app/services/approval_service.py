# backend/app/services/approval_service.py
import asyncio
import logging
from datetime import datetime, timezone
from fastapi import HTTPException
from app.models.org import User
from app.models.trace import Approval
from app.repositories.trace_repo import ApprovalRepository, TraceRepository
from app.repositories.experience_repo import ExperienceRepository
from app.repositories.user_repo import UserRepository
from app.traces.handlers import TraceCallbackHandler

logger = logging.getLogger(__name__)

# 审批恢复图执行整体限时：与 ChatService.resume 的 RESUME_TIMEOUT 对齐。
# 恢复后 agent 内 LLM 已由 stream_llm(60s) 超时兜底，这里给整体执行一个总闸，
# 防止审批接口因网关挂起无限等待（真实事故：resume 恢复后 agent 生成挂起 >170s）。
RESUME_TIMEOUT = 90.0


class ApprovalService:
    """统一审批中心：列出待办 + decide 按 category 分发后处理。
    - tool_call + sync（critical 工具调用）：更新审批单状态 + 恢复图执行
    - experience_promotion（经验晋升）：更新审批单状态 + 经验层级晋升
    权限：admin 可审批全部；dept_owner 可审批本部门经验晋升（dept 范围）；
    其他角色（member）无审批资格。列表按角色做可见性过滤。"""
    def __init__(self, db):
        self.db = db
        self.approval_repo = ApprovalRepository(db)
        self.trace_repo = TraceRepository(db)
        self.experience_repo = ExperienceRepository(db)
        self.user_repo = UserRepository(db)

    async def list_pending(self, user: User, status: str | None = None, category: str | None = None):
        """审批单列表（pending/approved/rejected），按角色可见性过滤，前端按 status 筛选展示。"""
        rows = await self.approval_repo.list_for_user(
            user.id, user.role_code, user.department_id, status, category)
        return [{"id": a.id, "category": a.category, "risk": a.risk, "mode": a.mode,
                 "title": a.title, "context": a.context, "requester_id": a.requester_id,
                 "status": a.status, "comment": a.comment, "approver_id": a.approver_id,
                 "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
                 "decided_at": a.decided_at.isoformat() if a.decided_at else None} for a in rows]

    async def create_approval(self, category: str, risk: str | None, mode: str,
                              ref_type: str, ref_id: str, title: str,
                              context: dict | None, requester_id: str,
                              approver_role: str | None = None,
                              approval_id: str | None = None) -> str:
        """创建审批单，返回审批单 ID。供 facade.guarded_critical 和 ExperienceService.submit 调用。
        approval_id 用于 critical 工具场景传入确定性 ID（interrupt 恢复重放时幂等，避免重复建单）。"""
        approval = Approval(
            id=approval_id,
            category=category, risk=risk, mode=mode,
            ref_type=ref_type, ref_id=ref_id, title=title,
            context=context, status="pending", requester_id=requester_id,
            approver_role=approver_role,
        )
        await self.approval_repo.add(approval)
        await self.approval_repo.commit()
        return approval.id

    async def decide(self, approval_id: str, user: User, approve: bool, comment: str = ""):
        ap = await self.approval_repo.get(approval_id)
        if not ap or ap.status != "pending":
            raise HTTPException(404, "审批单不存在或已处理")
        if not await self._can_approve(user, ap):
            raise HTTPException(403, "无权审批该审批单")

        # 1. 更新审批单（公共逻辑）
        ap.status = "approved" if approve else "rejected"
        ap.approver_id = user.id
        ap.comment = comment
        ap.decided_at = datetime.now(timezone.utc)
        await self.approval_repo.commit()

        # 2. 按 category 分发后处理
        if ap.category == "tool_call" and ap.mode == "sync":
            # critical 工具调用：恢复 LangGraph 图执行
            await self._resume_graph(ap.id, approve, ap.ref_id)
        elif ap.category == "experience_promotion":
            # 经验晋升：通过则层级晋升
            if approve:
                await self._promote_experience(ap.ref_id, ap.context.get("to_scope", "dept"))
        return {"ok": True}

    async def _can_approve(self, user: User, ap: Approval) -> bool:
        """审批资格：admin 可审批全部；dept_owner 可审批本部门（dept 范围）经验晋升；其余无权。"""
        role = user.role_code or ""
        if role == "admin":
            return True
        if ap.approver_role != "dept_owner" or role != "dept_owner":
            return False
        requester = await self.user_repo.get(ap.requester_id)
        return bool(user.department_id and requester and requester.department_id == user.department_id)

    async def _resume_graph(self, approval_id: str, approved: bool, trace_id: str):
        """审批通过/驳回后恢复图执行，完成后将最终回复落库并更新 trace。"""
        from app.agents.graph import get_graph
        from langgraph.types import Command
        trace = await self.trace_repo.get(trace_id) if trace_id else None
        if not trace or not trace.conversation_id:
            return
        from app.models.chat import Message
        from app.repositories.conversation_repo import ConversationRepository, MessageRepository
        from app.repositories.trace_repo import TraceRepository
        message_repo = MessageRepository(self.db)
        trace_repo = TraceRepository(self.db)
        conv_repo = ConversationRepository(self.db)
        config = {"configurable": {"thread_id": trace.conversation_id,
                                   "trace_id": trace.id,
                                   "requester_id": trace.user_id},
                  "callbacks": [TraceCallbackHandler(trace.id)]}
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
            logger.warning("审批恢复图执行超时(90s)，返回提示，图可能仍挂起")
            return
        # 图内还有后续 interrupt（多级审批），保持挂起
        if result.get("__interrupt__"):
            return
        text = result.get("agent_response", "")
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
        conv = await conv_repo.get(trace.conversation_id)
        if conv:
            conv.current_trace_id = trace.id
            await trace_repo.commit()
        from app.traces.collector import collector
        collector.emit(trace.id, "route", {"routes": trace.supervisor_routes})
        # 与 ChatService.stream_chat 完成路径对齐：偏好提取 / 经验提炼 / 摘要滚动 / 自动标题
        try:
            from app.services.preference_svc import maybe_extract_batch
            from app.services.experience_svc import distill_experience, save_personal_experience
            from app.services.summary import maybe_roll_summary, schedule_title_generation
            all_msgs = await message_repo.list_by_conversation(trace.conversation_id)
            user_msg = next((m.content for m in reversed(all_msgs) if m.role == "user"), "")
            dialog = f"用户：{user_msg}\n助手：{text}"
            await maybe_extract_batch(self.db, trace.user_id, trace.conversation_id)
            exp = await distill_experience(dialog, trace.user_id, trace.id)
            if exp:
                await save_personal_experience(self.db, exp)
            await maybe_roll_summary(self.db, trace.conversation_id)
            # 标题生成走后台任务（独立 Session + 会话级去重），不阻塞审批响应
            schedule_title_generation(trace.conversation_id, user_msg or text[:500])
        except Exception as e:
            logger.warning("审批恢复后记忆沉淀处理失败（已降级）: %s", e)

    async def _promote_experience(self, experience_id: str, to_scope: str):
        """经验层级晋升。"""
        exp = await self.experience_repo.get(experience_id)
        if exp:
            exp.scope = to_scope
            exp.status = "approved"
            await self.experience_repo.commit()
