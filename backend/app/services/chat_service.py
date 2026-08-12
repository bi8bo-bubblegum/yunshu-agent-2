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
from app.services.tool_cards import tool_message_rows
from app.traces.collector import collector
from app.traces.handlers import (StreamEventHandler, ToolCallRecorder,
                                 TraceCallbackHandler, acquire_resume_recorder,
                                 release_resume_recorder)

logger = logging.getLogger(__name__)

# 后台记忆沉淀任务管理：持有引用防 GC（与 summary._bg_title_tasks 同模式）
_bg_mem_tasks: set[asyncio.Task] = set()

# 手动终止收尾任务管理：持有引用防 GC。终止发生在当前请求 task 被 uvicorn 取消后，
# 收尾落库必须放独立 task + 独立 session 执行（见 _abort_cleanup）
_bg_abort_tasks: set[asyncio.Task] = set()


async def _abort_cleanup(conv_id: str, sent_text: str, tool_recorder: ToolCallRecorder | None,
                         trace_id: str) -> None:
    """手动终止 / 客户端断开的收尾落库：半截回答 + 已完成工具卡片 + trace aborted。

    必须用独立 task + 独立 session（SessionLocal）执行：
    1. uvicorn 对客户端断开是 task.cancel()（注入 CancelledError，而非 aclose 的
       GeneratorExit）。CancelledError 注入后当前 task 处于「取消状态」，后续任何
       await（落库/commit）会立即再抛 CancelledError，直接 await 全部失败、trace
       留 running 僵尸（真实事故：curl 断开后图被取消但 trace 保持 running）。
    2. 请求级注入的 self.db 在响应结束后关闭，独立 session 规避。
    失败仅降级记录，不影响图取消本身。"""
    try:
        async with SessionLocal() as db:
            repo = MessageRepository(db)
            text = sent_text.strip()
            if text:
                await repo.add(Message(conversation_id=conv_id, role="assistant", content=text))
            if tool_recorder:
                for tm in tool_message_rows(conv_id, tool_recorder):
                    await repo.add(tm)
            if text or (tool_recorder and tool_recorder.order):
                await repo.commit()
            # 独立 session 无法复用请求内的 trace/conv 对象，直接 UPDATE：
            # aborted 区别于 interrupted（resume 的 fallback 查 status=="interrupted"，
            # 若复用会误恢复已终止的执行）；清 current_trace_id 防 resume 定位到它。
            from sqlalchemy import update
            await db.execute(
                update(ExecutionTrace).where(ExecutionTrace.id == trace_id).values(status="aborted"))
            await db.execute(
                update(Conversation).where(Conversation.id == conv_id).values(current_trace_id=None))
            await db.commit()
    except Exception as e:
        logger.warning("终止收尾落库失败（已降级）: %s", e)

# resume/审批恢复执行整体限时。恢复图执行时 agent 内 LLM 已由 stream_llm 超时兜底（60s），
# 但链路仍可能因多次工具往返/路由超时叠加变长，给恢复执行一个总闸：超时后返回提示
# 而非无限等待（真实事故：resume 恢复后 agent 生成挂起 >170s，前端永不返回）。
RESUME_TIMEOUT = 90.0


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
        # 手动终止 / 客户端断开统一收尾。try 必须覆盖 yield start 之后的所有 await：
        # 前端收到 start 才能点「终止」，其后任意挂起点（记忆装配 / 图启动 / 主循环）
        # 抛 GeneratorExit 都要进入 except BaseException 做取消 + 半截落库，否则 trace
        # 会留 running 僵尸、半截内容不落库（真实时序：start 已发出、图尚未启动时终止）。
        graph_task: asyncio.Task | None = None
        tool_recorder: ToolCallRecorder | None = None
        sent_text = ""
        try:
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
            # 结构化工具卡片收集器：本轮回调记录工具调用（start/end 按 run_id 配对），
            # 图到达终态后由 tool_message_rows 转成 tool 消息一次性落库
            tool_recorder = ToolCallRecorder()
            config = {
                "configurable": {"thread_id": conv_id, "trace_id": trace.id,
                                 "requester_id": user_id, "sse_queue": queue},
                "callbacks": [StreamEventHandler(queue, trace.id, recorder=tool_recorder),
                              TraceCallbackHandler(trace.id)],
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
            # 图执行异常暂存：_run_graph 在后台 task 里吞掉异常（否则 SSE 生成器
            # 拿不到），这里存下来供主流程判断——图崩溃后 aget_state 返回的是崩溃前
            # checkpoint（agent_outputs 无本轮新增），否则 else 分支会回退落上一轮
            # agent_response（真实事故：工具失败崩图 → 前端重复显示上一次的回复）。
            graph_error_holder: dict = {}

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
                    graph_error_holder["v"] = e
                finally:
                    # 哨兵：图执行结束，主循环退出。手动终止时主循环已退出、无人消费，
                    # 若队列满（>500 事件）put 会永久阻塞导致任务泄漏，加超时兜底
                    try:
                        await asyncio.wait_for(queue.put(None), timeout=2)
                    except Exception:
                        pass

            graph_task = asyncio.create_task(_run_graph())
            # 主循环：实时转发队列事件，直到哨兵（图结束）。queue 本身保证实时性，
            # 子图执行期间 token / tool 事件随时可读，不再等 astream 产出。
            # sent_text 累计已推送的 token 文本：用户手动终止/客户端断开时，agent LLM
            # 可能尚未生成完整回复（半截 token 不在 checkpoint，agent_node 未完成），
            # 只有主循环消费到的 token 才能作为「已生成内容」落库。
            while True:
                evt = await queue.get()
                if evt is None:
                    break
                if evt.get("event") == "token":
                    sent_text += str(evt.get("content", ""))
                yield json.dumps(evt, ensure_ascii=False)
            await graph_task
        except BaseException:
            # 手动终止 / 客户端断开（GeneratorExit / uvicorn 取消的 CancelledError）。
            # 两者都继承 BaseException（不是 Exception），_run_graph 内部的
            # except Exception 不会捕获、graph_task 会成为孤儿任务继续跑完图。
            # 1) 取消后台图执行（LangGraph astream 支持 asyncio 取消，
            #    CancelledError 一路穿到子图 PregelLoop）；
            # 2) 收尾落库移入独立 task（_abort_cleanup）：当前 task 已处于取消态，
            #    任何 await 立即再抛 CancelledError，直接 await 落库会全部失败。
            if graph_task and not graph_task.done():
                graph_task.cancel()
            task = asyncio.create_task(_abort_cleanup(conv_id, sent_text, tool_recorder, trace.id))
            _bg_abort_tasks.add(task)
            task.add_done_callback(_bg_abort_tasks.discard)
            raise
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
        # 工具卡片落库：本轮回调收集的工具调用转成 tool 消息，随下方段落 commit 同事务提交
        for tm in tool_message_rows(conv_id, tool_recorder):
            await self.message_repo.add(tm)
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
            graph_error = graph_error_holder.get("v")
            # 本轮是否有 agent 实际执行：route_history 本轮新增部分是否含非 done 路由。
            # supervisor 直接 done（本轮未执行 agent，如用户说「好的」）时允许回退上一轮
            # agent_response（对话继续，无新任务）；agent 执行了但最终无产出段落时，
            # text 是 done_node 回退的旧值——绝不能展示上一次的回复（用户报告的 bug：
            # 工具全部失败 → LLM 输出空白 → 本轮落库重复显示上一轮的回复）。
            prev_routes = (pre_snap.values or {}).get("route_history", []) if pre_snap else []
            new_routes = values.get("route_history", [])[len(prev_routes):]
            agent_executed = any(r != "done" for r in new_routes)
            if graph_error is not None or agent_executed:
                # 两种情况统一落明确失败提示（工具卡片随 commit 一并落库，用户能看到 agent
                # 尝试过什么），绝不回退上一轮 text：
                # 1) 图崩溃（工具失败崩子图 → aget_state 返回崩溃前 checkpoint，segments 空）
                # 2) 图成功但 agent 执行后无实质产出（工具全失败 → LLM 输出空白）
                if graph_error is not None:
                    err_text = f"{type(graph_error).__name__}: {str(graph_error)}"[:200]
                    hint = f"⚠️ 本轮回答失败：{err_text}。请稍后重试。"
                    err_evt = f"本轮回答失败：{err_text}"
                else:
                    hint = "⚠️ 本轮未能完成回答：查询过程中工具调用失败，请稍后重试或换个问法。"
                    err_evt = hint
                await self.message_repo.add(Message(
                    conversation_id=conv_id, role="assistant",
                    content=hint,
                    metadata_={"segment": "final", "failed": True},
                ))
                await self.message_repo.commit()
                trace.status = "failed"
                trace.supervisor_routes = values.get("route_history", [])
                conv.current_trace_id = trace.id
                await self.trace_repo.commit()
                yield json.dumps({"event": "error", "content": err_evt}, ensure_ascii=False)
                return
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
        # 恢复路径无前端 SSE（前端靠轮询拿 DB 新消息）：补挂 StreamEventHandler(None) 只收集。
        # recorder 按 trace_id 跨 resume/审批共享（多级 interrupt 时中间工具卡片不丢失），终态后 release
        resume_recorder = acquire_resume_recorder(trace.id if trace else "")
        resume_config = {"configurable": {
            "thread_id": conv_id,
            "trace_id": trace.id if trace else "",
            "requester_id": user_id,
        },
            "callbacks": [TraceCallbackHandler(trace.id if trace else ""),
                          StreamEventHandler(None, trace.id if trace else "", recorder=resume_recorder)]}
        # 本轮开始前 agent_outputs 长度（interrupted 状态已含本轮 interrupt 前已执行的段落）
        pre_snap = await graph.aget_state(resume_config)
        rl0 = len((pre_snap.values or {}).get("agent_outputs", [])) if pre_snap else 0
        try:
            result = await asyncio.wait_for(
                graph.ainvoke(Command(resume=approved), config=resume_config),
                timeout=RESUME_TIMEOUT)
        except asyncio.TimeoutError:
            # 恢复执行超时：返回提示让前端有响应，不无限等待。
            # 图可能仍挂在 agent LLM（wait_for 已取消 invoke 及其子任务），
            # 但由于 create 等工具纯函数幂等、checkpoint 在节点完成后才写盘，
            # 下次 resume 从最近完成的 checkpoint 重放，不会重复执行副作用操作。
            logger.warning("resume 恢复执行超时(%ss)，返回提示", RESUME_TIMEOUT)
            return {"ok": False, "message": "执行超时，结果可能不完整，请稍后刷新查看", "payload": {"timeout": True}}
        interrupts = result.get("__interrupt__")
        if interrupts:
            # 图内还有后续 interrupt（多级确认），保持挂起
            first = interrupts[0]
            payload = getattr(first, "value", first)
            return {"ok": False, "message": "仍有待确认的操作", "payload": payload}
        text = result.get("agent_response", "")
        # 工具卡片落库：resume 恢复执行期间的工具调用转成 tool 消息，随段落 commit 同事务提交
        for tm in tool_message_rows(conv_id, resume_recorder):
            await self.message_repo.add(tm)
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
        # 终态落库完成，释放共享 recorder（多级 interrupt 场景下 create/publish 已全部收集）
        release_resume_recorder(trace.id if trace else "")
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
