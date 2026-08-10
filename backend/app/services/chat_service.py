# backend/app/services/chat_service.py —— 聊天业务
import json
import asyncio
import logging
from uuid import uuid4

from fastapi import HTTPException
from langchain_core.messages import HumanMessage
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
from app.services.summary import maybe_roll_summary, schedule_title_generation
from app.traces.collector import collector
from app.traces.handlers import StreamEventHandler, TraceCallbackHandler

logger = logging.getLogger(__name__)

# 后台记忆沉淀任务管理：持有引用防 GC（与 summary._bg_title_tasks 同模式）
_bg_mem_tasks: set[asyncio.Task] = set()


def schedule_memory_postprocess(user_id: str, conv_id: str, dialog: str, trace_id: str) -> None:
    """异步调度记忆沉淀（偏好提取 / 经验提炼 / 摘要滚动），不阻塞 SSE 关键路径。

    这三段后处理各含 LLM 调用（偏好分析、经验提炼+embed、滚动摘要），网关慢时
    单个最多挂到 timeout（120s）。旧实现把它们放在 yield answer/done 之前串行
    await，SSE 流迟迟不结束，前端一直显示「Agent 思考中…」转圈（真实事故：
    主图 1.9s 完成但收尾占 13.7s）。移出后 answer/done 立即返回，收尾在后台
    用独立 session 完成（请求结束后依赖注入的 db 已关闭，不能复用 self.db）。
    失败仅降级记录，不影响聊天主流程。"""
    async def _run():
        try:
            async with SessionLocal() as db:
                await maybe_extract_batch(db, user_id, conv_id)
                exp = await distill_experience(dialog, user_id, trace_id)
                if exp:
                    await save_personal_experience(db, exp)
                await maybe_roll_summary(db, conv_id)
        except Exception as e:
            logger.warning("后台记忆沉淀失败（已降级）: %s", e)

    task = asyncio.create_task(_run())
    _bg_mem_tasks.add(task)
    task.add_done_callback(_bg_mem_tasks.discard)


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
        # 注意：不再从 DB 回灌历史消息进图。历史由 LangGraph checkpointer
        # （thread_id=conversation_id）维护，messages channel 是 add 追加语义，
        # 若同时注入 DB 历史会与 checkpoint 累积的历史重复合并，逐轮翻倍膨胀，
        # 导致 agent 上下文错乱、复读用户消息。DB messages 表仅用于前端展示。
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

        def _on_title(title: str | None):
            if title:
                _title_result["title"] = title

        schedule_title_generation(conv_id, message, on_done=_on_title)
        yield json.dumps({"event": "start", "trace_id": trace.id}, ensure_ascii=False)
        # 装配多层记忆
        user = await self.user_repo.get(user_id)
        dep_id = user.department_id if user and user.department_id else None
        mem = await assemble_memory(self.db, user_id, conv_id, dep_id, message)
        graph = await get_graph()
        # 请求级事件队列：回调与图节点把过程事件放入队列，SSE 生成器实时转发。
        # 重要：图在后台 task 运行——LangGraph 父图 stream_mode="messages" 不穿透
        # 编译子图内部，子图内 LLM token 由 agent_node 经注入的 sse_queue 直接推送；
        # 主循环只从 queue 实时读取，避免「astream 无事件产出时队列堆积、
        # 子图结束后一次性刷出」导致的非流式观感。
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        config = {
            "configurable": {"thread_id": conv_id, "trace_id": trace.id,
                             "requester_id": user_id, "sse_queue": queue},
            "callbacks": [StreamEventHandler(queue, trace.id), TraceCallbackHandler(trace.id)],
        }
        inputs = {
            "conversation_id": conv_id, "user_id": user_id,
            "user_message": message, "memory_context": mem,
            "trace_id": trace.id,
            # 只注入本轮用户消息，历史由 checkpointer 按 thread_id 累积恢复
            "messages": [HumanMessage(content=message)],
        }
        # 本轮开始前的 agent_outputs 长度：agent_outputs 是跨轮累积的 add 通道，
        # 本轮结束后取 [l0:] 即本轮各 agent 产出段落（分段落库，方案 B）。
        pre_snap = await graph.aget_state(config)
        l0 = len((pre_snap.values or {}).get("agent_outputs", [])) if pre_snap else 0

        stream_interrupts_holder: dict = {}

        async def _run_graph():
            """后台执行图：路由/中断事件入队；agent 输出 token 由 agent_node 直接推送。"""
            try:
                async for item in graph.astream(inputs, config, stream_mode=["messages", "updates"]):
                    if not isinstance(item, tuple):
                        continue
                    mode, chunk = item
                    if mode == "updates":
                        # langgraph 1.x：interrupt 以 updates 顶层 __interrupt__ 块出现
                        if isinstance(chunk, dict) and "__interrupt__" in chunk:
                            stream_interrupts_holder["v"] = chunk["__interrupt__"]
                            continue
                        sv = chunk.get("supervisor") if isinstance(chunk, dict) else None
                        if sv and sv.get("pending_agent"):
                            queue.put_nowait({"event": "route", "agent": sv["pending_agent"]})
                        continue
                    # messages 模式不转发：子图内部不穿透（agent_node 已直接推送 token），
                    # supervisor 路由文本不需要展示，避免与 agent_node 推送重复。
            except Exception as e:
                logger.warning("图执行异常: %s", e)
            finally:
                await queue.put(None)  # 哨兵：图执行结束，主循环退出

        graph_task = asyncio.create_task(_run_graph())
        # 主循环：实时转发队列事件，直到哨兵（图结束）。queue 本身保证实时性，
        # 子图执行期间 token / tool 事件随时可读，不再等 astream 产出。
        while True:
            evt = await queue.get()
            if evt is None:
                break
            yield json.dumps(evt, ensure_ascii=False)
        await graph_task
        stream_interrupts = stream_interrupts_holder.get("v")

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
        text = values.get("agent_response", "")
        # 助手消息落库（分段落库）：本轮各 agent 产出各存一条 assistant（metadata 标记 agent/段位），
        # 最后一段为 final（完整最终文本，用 agent_response 覆盖保证）。单 agent 退化为 1 条，
        # 与旧行为完全一致；多 agent（如 marketing→sales）时中间产出不再丢失（方案 B）。
        outputs = values.get("agent_outputs", []) or []
        # 只取本轮新增的段落 [l0:]。l0 == len(outputs)（本轮无新增，如 supervisor 直接 done、
        # 或 agent 未产出快照）时 segments 为空，避免把全部历史 agent_outputs 重复落库
        # （真实事故：无产出轮次把前面所有 step 段落重放一遍，前端刷新后中间消息重复/错乱）。
        segments = outputs[l0:] if l0 is not None and l0 < len(outputs) else []
        # 过滤无实质内容的段落：LLM 输出空白/换行（如 '\n\n'）时不是有效产出，
        # 落库会生成空白气泡（真实事故：scheduling 输出 '\n\n'，final 被覆盖成空白，
        # 实质内容全在 step 段落里，前端外部气泡空白、内容全在「查看执行步骤」）。
        segments = [s for s in segments if (s.get("content") or "").strip()]
        if segments:
            last_i = len(segments) - 1
            for i, seg in enumerate(segments):
                content = seg.get("content") or ""
                if i == last_i:
                    # 最终段用 agent_response（权威完整文本）覆盖；agent_response 空白时
                    # 保留段落自身内容，避免 final 被覆盖成空内容（真实事故）
                    content = text or content
                await self.message_repo.add(Message(
                    conversation_id=conv_id, role="assistant", content=content,
                    metadata_={"agent": seg.get("agent", ""),
                               "segment": "final" if i == last_i else "step"},
                ))
            await self.message_repo.commit()
        else:
            await self.message_repo.add(Message(conversation_id=conv_id, role="assistant", content=text))
            await self.message_repo.commit()
        # 更新 trace 终态 + 路由历史
        trace.status = "completed"
        trace.supervisor_routes = values.get("route_history", [])
        conv.current_trace_id = trace.id
        await self.trace_repo.commit()
        collector.emit(trace.id, "route", {"routes": trace.supervisor_routes})
        # 记忆沉淀（偏好/经验/摘要）移出 SSE 关键路径：这三段各含 LLM 调用，
        # 网关慢时串行 await 会让 answer/done 迟迟不发出，前端一直转圈。
        # 改为后台任务（独立 session），answer/done 立即返回。
        dialog = f"用户：{message}\n助手：{text}"
        schedule_memory_postprocess(user_id, conv_id, dialog, trace.id)
        # answer 携带完整最终文本（前端在无 token 流式时兜底填充，已流式时跳过避免重复）
        yield json.dumps({"event": "answer", "content": text}, ensure_ascii=False)
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
        resume_config = {"configurable": {
            "thread_id": conv_id,
            "trace_id": trace.id if trace else "",
            "requester_id": user_id,
        },
            "callbacks": [TraceCallbackHandler(trace.id if trace else "")]}
        # 本轮开始前 agent_outputs 长度（interrupted 状态已含本轮 interrupt 前已执行的段落）
        pre_snap = await graph.aget_state(resume_config)
        rl0 = len((pre_snap.values or {}).get("agent_outputs", [])) if pre_snap else 0
        result = await graph.ainvoke(Command(resume=approved), config=resume_config)
        interrupts = result.get("__interrupt__")
        if interrupts:
            # 图内还有后续 interrupt（多级确认），保持挂起
            first = interrupts[0]
            payload = getattr(first, "value", first)
            return {"ok": False, "message": "仍有待确认的操作", "payload": payload}
        text = result.get("agent_response", "")
        # 分段落库（与 stream_chat 一致，方案 B）：interrupt 前已执行的段落 + 恢复后段落
        outputs = result.get("agent_outputs", []) or []
        # 只取恢复执行新增的段落 [rl0:]；rl0 == len(outputs)（恢复后无新增产出）时为空，
        # 避免把历史 agent_outputs 重复落库（与 stream_chat 一致，防止 step 段落重复）。
        segments = outputs[rl0:] if rl0 is not None and rl0 < len(outputs) else []
        # 过滤无实质内容的段落：LLM 输出空白/换行时不是有效产出（与 stream_chat 一致）。
        segments = [s for s in segments if (s.get("content") or "").strip()]
        if segments:
            last_i = len(segments) - 1
            for i, seg in enumerate(segments):
                content = seg.get("content") or ""
                if i == last_i:
                    # 最终段用 agent_response 覆盖；agent_response 空白时保留段落自身内容
                    content = text or content
                await self.message_repo.add(Message(
                    conversation_id=conv_id, role="assistant", content=content,
                    metadata_={"agent": seg.get("agent", ""),
                               "segment": "final" if i == last_i else "step"},
                ))
            await self.message_repo.commit()
        else:
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
        # 记忆沉淀（偏好/经验/摘要）异步化：各含 LLM 调用，阻塞会让恢复响应迟迟不返回。
        # 改为后台任务（独立 session），response 立即返回。
        all_msgs = await self.message_repo.list_by_conversation(conv_id)
        user_msg = next((m.content for m in reversed(all_msgs) if m.role == "user"), "")
        dialog = f"用户：{user_msg}\n助手：{text}"
        schedule_memory_postprocess(user_id, conv_id, dialog, trace.id if trace else "")
        # 标题生成兜底：stream_chat 被中断时其后台标题任务可能已取消，
        # 在 resume 中重试以确保最终一定能生成标题
        schedule_title_generation(conv_id, user_msg if user_msg else (text[:500]))
        return {"ok": True, "content": text}
