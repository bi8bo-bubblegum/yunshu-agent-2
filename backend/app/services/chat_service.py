# backend/app/services/chat_service.py —— 聊天业务
import json
import asyncio
import logging
from uuid import uuid4

from fastapi import HTTPException
from langchain_core.messages import AIMessage, AIMessageChunk
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_graph
from app.core.database import SessionLocal
from app.memory.assembly import assemble_memory
from app.models.chat import Conversation, Message
from app.models.trace import ExecutionTrace
from app.repositories.conversation_repo import ConversationRepository, MessageRepository
from app.repositories.trace_repo import TraceRepository
from app.repositories.user_repo import UserRepository
from app.services.experience_svc import distill_experience, save_personal_experience
from app.services.preference_svc import maybe_extract_batch
from app.services.summary import generate_title, maybe_roll_summary
from app.traces.collector import collector
from app.traces.handlers import StreamEventHandler, TraceCallbackHandler

logger = logging.getLogger(__name__)


async def _auto_title_async(conv_id: str, message: str) -> str | None:
    """后台标题生成通用方法：从独立 session 调用 LLM 生成并写入 DB。
    仅在当前标题仍为默认值时写入，避免覆盖已有标题。
    返回生成的标题（可能是 None），供 SSE done 事件携带给前端。"""
    try:
        new_title = await generate_title(message)
        if not new_title or new_title == "新对话":
            return None
        async with SessionLocal() as db:
            repo = ConversationRepository(db)
            conv = await repo.get(conv_id)
            if conv and conv.title in ("新对话", "", None):
                conv.title = new_title
                await repo.commit()
                return new_title
    except Exception as e:
        logger.warning("后台标题生成失败（已降级）: %s", e)
    return None


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
        流式过程事件：route（路由分发）/ tool_start / tool_end / token（agent 输出）。
        high/critical 风险工具 interrupt 时发 confirm_required 事件并挂起图（等 /chat/resume 或审批中心）。"""
        conv = await self._ensure_owned(conv_id, user_id)
        # 创建本次对话的执行留痕
        trace = ExecutionTrace(id=str(uuid4()), user_id=user_id,
                               conversation_id=conv_id, status="running", supervisor_routes=[])
        await self.trace_repo.add(trace)
        await self.trace_repo.commit()
        # 用户消息落库
        await self.message_repo.add(Message(conversation_id=conv_id, role="user", content=message))
        await self.message_repo.commit()
        # 后台标题生成：用户消息落库后立即开跑，与图执行并行互不阻塞。
        # done 事件携带标题，前端收到后只 patch 列表对应项，不影响消息区。
        _title_result: dict[str, str] = {}

        async def _auto_title():
            title = await _auto_title_async(conv_id, message)
            if title:
                _title_result["title"] = title

        asyncio.create_task(_auto_title())
        yield json.dumps({"event": "start", "trace_id": trace.id}, ensure_ascii=False)
        # 装配多层记忆
        user = await self.user_repo.get(user_id)
        dep_id = user.department_id if user and user.department_id else None
        mem = await assemble_memory(self.db, user_id, conv_id, dep_id, message)
        graph = await get_graph()
        # 请求级事件队列：回调与图节点把过程事件放入队列，SSE 生成器实时转发
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        config = {
            "configurable": {"thread_id": conv_id, "trace_id": trace.id, "requester_id": user_id},
            "callbacks": [StreamEventHandler(queue, trace.id), TraceCallbackHandler(trace.id)],
        }
        inputs = {
            "conversation_id": conv_id, "user_id": user_id,
            "user_message": message, "memory_context": mem,
            "trace_id": trace.id, "messages": [],
        }
        agent_parts: list[str] = []
        stream_interrupts = None

        async def _drain_queue():
            while True:
                try:
                    evt = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                yield json.dumps(evt, ensure_ascii=False)

        # 双流模式：messages 实时吐 agent token，updates 提供路由决策节点状态
        async for item in graph.astream(inputs, config, stream_mode=["messages", "updates"]):
            async for evt in _drain_queue():
                yield evt
            if not isinstance(item, tuple):
                continue
            mode, chunk = item
            if mode == "updates":
                # langgraph 1.x：interrupt 以 updates 顶层 __interrupt__ 块出现
                if isinstance(chunk, dict) and "__interrupt__" in chunk:
                    stream_interrupts = chunk["__interrupt__"]
                    continue
                sv = chunk.get("supervisor") if isinstance(chunk, dict) else None
                if sv and sv.get("pending_agent"):
                    yield json.dumps({"event": "route", "agent": sv["pending_agent"]}, ensure_ascii=False)
                continue
            if mode != "messages":
                continue
            msg, meta = chunk
            node = (meta or {}).get("langgraph_node") or ""
            # 只转发 agent 的输出 token；supervisor 路由文本/工具结果消息不直接展示
            if node not in ("supervisor", "tools") and isinstance(msg, (AIMessage, AIMessageChunk)):
                content = msg.content
                if isinstance(content, list):
                    text = "".join(
                        b.get("text", "") if isinstance(b, dict) and b.get("type") == "text" else ""
                        for b in content
                    )
                else:
                    text = content or ""
                if text:
                    agent_parts.append(text)
                    yield json.dumps({"event": "token", "content": text}, ensure_ascii=False)
        async for evt in _drain_queue():
            yield evt

        # 取最终状态：interrupt 挂起 / agent_response 终文
        snap = await graph.aget_state(config)
        values = snap.values if snap else {}
        interrupts = stream_interrupts or values.get("__interrupt__")
        if interrupts:
            # high/critical 风险工具 interrupt：挂起图，等待前端即时确认/审批中心
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
        text = values.get("agent_response", "") or "".join(agent_parts)
        # 助手消息落库
        await self.message_repo.add(Message(conversation_id=conv_id, role="assistant", content=text))
        await self.message_repo.commit()
        # 更新 trace 终态 + 路由历史
        trace.status = "completed"
        trace.supervisor_routes = values.get("route_history", [])
        conv.current_trace_id = trace.id
        await self.trace_repo.commit()
        collector.emit(trace.id, "route", {"routes": trace.supervisor_routes})
        # 偏好提取 / 经验提炼 / 摘要滚动：失败仅降级，不影响 SSE 正常收尾
        try:
            dialog = f"用户：{message}\n助手：{text}"
            await maybe_extract_batch(self.db, user_id, conv_id)
            exp = await distill_experience(dialog, user_id, trace.id)
            if exp:
                await save_personal_experience(self.db, exp)
            await maybe_roll_summary(self.db, conv_id)
        except Exception as e:
            logger.warning("记忆沉淀后处理失败（已降级）: %s", e)
        # done 事件携带标题，前端收到后只 patch 会话列表对应项，不影响消息区
        yield json.dumps({"event": "done", "title": _title_result.get("title")}, ensure_ascii=False)

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
                                     },
                                         "callbacks": [TraceCallbackHandler(trace.id if trace else "")]})
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
        # 偏好提取 / 经验提炼 / 摘要滚动：失败仅降级，不影响 SSE 正常收尾
        try:
            all_msgs = await self.message_repo.list_by_conversation(conv_id)
            user_msg = next((m.content for m in reversed(all_msgs) if m.role == "user"), "")
            dialog = f"用户：{user_msg}\n助手：{text}"
            await maybe_extract_batch(self.db, user_id, conv_id)
            exp = await distill_experience(dialog, user_id, trace.id if trace else "")
            if exp:
                await save_personal_experience(self.db, exp)
            await maybe_roll_summary(self.db, conv_id)
        except Exception as e:
            logger.warning("resume 后记忆沉淀处理失败（已降级）: %s", e)
        # 标题生成兜底：stream_chat 被中断时其后台标题任务可能已取消，
        # 在 resume 中重试以确保最终一定能生成标题
        asyncio.create_task(_auto_title_async(conv_id, user_msg if user_msg else (text[:500])))
        return {"ok": True, "content": text}
