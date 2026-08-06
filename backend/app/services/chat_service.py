import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_graph
from app.memory.assembly import assemble_memory
from app.models.chat import Conversation, Message
from app.models.trace import ExecutionTrace
from app.repositories.conversation_repo import ConversationRepository, MessageRepository
from app.repositories.trace_repo import TraceRepository
from app.repositories.user_repo import UserRepository
from app.services.experience_svc import distill_experience, save_personal_experience
from app.services.preference_svc import extract_and_save
from app.services.summary import maybe_roll_summary
from app.traces.collector import collector


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)
        self.user_repo = UserRepository(db)
        self.trace_repo = TraceRepository(db)

    async def _ensure_owned(self, conversation_id: str, user_id: str) -> Conversation:
        conv = await self.conversation_repo.get(conversation_id)
        if not conv or conv.user_id != user_id:
            raise HTTPException(status_code=404, detail="会话不存在")
        return conv

    async def stream_chat(self, user_id: str, conv_id: str, message: str):
        """SSE 事件异步生成器：start → token → done。每次聊天创建 trace 并记录路由。
        high 风险工具 interrupt 时发 confirm_required 事件并挂起图（等 /chat/resume）。"""
        conv = await self._ensure_owned(conv_id, user_id)
        # 创建本次对话的执行留痕
        trace = ExecutionTrace(id=str(uuid4()), user_id=user_id,
                               conversation_id=conv_id, status="running", supervisor_routes=[])
        await self.trace_repo.add(trace)
        await self.trace_repo.commit()
        # 用户消息落库
        await self.message_repo.add(Message(conversation_id=conv_id, role="user", content=message))
        await self.message_repo.commit()
        yield json.dumps({"event": "start", "trace_id": trace.id}, ensure_ascii=False)
        # 装配多层记忆
        user = await self.user_repo.get(user_id)
        dep_id = user.department_id if user and user.department_id else None
        mem = await assemble_memory(self.db, user_id, conv_id, dep_id, message)
        graph = await get_graph()
        result = await graph.ainvoke({
            "conversation_id": conv_id, "user_id": user_id,
            "user_message": message, "memory_context": mem,
            "trace_id": trace.id, "messages": [],
        }, config={"configurable": {"thread_id": conv_id, "trace_id": trace.id, "requester_id": user_id}})
        # high 风险工具 interrupt：挂起图，等待前端即时确认
        interrupts = result.get("__interrupt__")
        if interrupts:
            first = interrupts[0]
            payload = getattr(first, "value", first)
            if isinstance(payload, dict):
                payload = dict(payload)
            else:
                payload = {"reason": str(payload)}
            payload.setdefault("conversation_id", conv_id)
            trace.status = "interrupted"
            conv.current_trace_id = trace.id
            await self.trace_repo.commit()
            yield json.dumps({"event": "confirm_required", "payload": payload}, ensure_ascii=False)
            return
        text = result.get("agent_response", "")
        # 助手消息落库
        await self.message_repo.add(Message(conversation_id=conv_id, role="assistant", content=text))
        await self.message_repo.commit()
        # 更新 trace 终态 + 路由历史
        trace.status = "completed"
        trace.supervisor_routes = result.get("route_history", [])
        conv.current_trace_id = trace.id
        await self.trace_repo.commit()
        collector.emit(trace.id, "route", {"routes": trace.supervisor_routes})
        # 偏好提取 / 经验提炼
        dialog = f"用户：{message}\n助手：{text}"
        await extract_and_save(self.db, user_id, dialog)
        exp = await distill_experience(dialog, user_id, trace.id)
        if exp:
            await save_personal_experience(self.db, exp)
        await maybe_roll_summary(self.db, conv_id)
        yield json.dumps({"event": "token", "content": text}, ensure_ascii=False)
        yield json.dumps({"event": "done"}, ensure_ascii=False)

    async def resume(self, user_id: str, conv_id: str, approved: bool) -> dict:
        """high 风险工具即时确认后恢复图执行。
        guarded_high 的 interrupt 值为布尔（True=通过），resume 直接传布尔。
        恢复执行完成后将最终回复落库并更新 trace。"""
        conv = await self._ensure_owned(conv_id, user_id)
        # 恢复时带 trace_id/requester_id：图内后续 critical 工具（guarded_critical）需要
        # 运行时上下文创建审批单，缺失会导致审批单 ref_id 为空
        trace = await self.trace_repo.get(conv.current_trace_id) if conv.current_trace_id else None
        from langgraph.types import Command
        graph = await get_graph()
        result = await graph.ainvoke(Command(resume=approved),
                                     config={"configurable": {
                                         "thread_id": conv_id,
                                         "trace_id": trace.id if trace else "",
                                         "requester_id": user_id,
                                     }})
        interrupts = result.get("__interrupt__")
        if interrupts:
            # 图内还有后续 interrupt（多级确认），保持挂起
            first = interrupts[0]
            payload = getattr(first, "value", first)
            return {"ok": False, "message": "仍有待确认的操作", "payload": payload}
        text = result.get("agent_response", "")
        await self.message_repo.add(Message(conversation_id=conv_id, role="assistant", content=text))
        await self.message_repo.commit()
        trace = await self.trace_repo.get(result.get("trace_id", ""))
        if not trace:
            from app.repositories.trace_repo import TraceRepository
            traces = await TraceRepository(self.db).list_by_user(user_id, limit=10)
            trace = next((t for t in traces if t.conversation_id == conv_id and t.status == "interrupted"), None)
        if trace:
            trace.status = "completed"
            trace.supervisor_routes = result.get("route_history", [])
            conv.current_trace_id = trace.id
            await self.trace_repo.commit()
            collector.emit(trace.id, "route", {"routes": trace.supervisor_routes})
        return {"ok": True, "content": text}
