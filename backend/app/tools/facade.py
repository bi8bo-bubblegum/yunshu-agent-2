# backend/app/tools/facade.py
import inspect
from typing import Awaitable, Callable

from langgraph.types import interrupt
from pydantic import BaseModel
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool

ToolFunc = Callable[..., Awaitable | object]

class Tool:
    def __init__(self, name: str, fn: ToolFunc, risk: str = "low", description: str = "",
                 args_schema: type[BaseModel] | None = None):
        self.name, self.fn, self.risk, self.description = name, fn, risk, description
        self.args_schema = args_schema or BaseModel

class DataFacade:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def execute(self, name: str, kwargs: dict):
        return self._tools[name].fn(**kwargs)

    def get_risk(self, name: str) -> str:
        return self._tools[name].risk

    def to_langchain_tool(self, name: str, trace_id: str = "", requester_id: str = "") -> StructuredTool:
        """按名称取已注册工具并转换（内置工具路径）。"""
        return self.to_langchain_tool_from(self._tools[name], trace_id, requester_id)

    def to_langchain_tool_from(self, tool: Tool, trace_id: str = "", requester_id: str = "") -> StructuredTool:
        """DataFacade 工具 → LangChain StructuredTool；按风险等级分流：
        - low/medium：直接执行（包装为原生函数）
        - high：interrupt 即时确认（不进审批中心）
        - critical：创建审批单 + interrupt 冻结图，等审批中心处理"""
        name = tool.name

        if tool.risk in ("low", "medium"):
            fn = tool.fn
        elif tool.risk == "high":
            # 即时确认：interrupt 冻结，当班人确认后执行
            async def guarded_high(config: RunnableConfig, **kwargs):
                approved = interrupt({
                    "tool": name, "args": kwargs,
                    "reason": f"高风险操作：{tool.description}",
                })
                if approved is not True:
                    return {"error": "操作被驳回"}
                result = tool.fn(**kwargs)
                return await result if hasattr(result, "__await__") else result

            fn = guarded_high
        elif tool.risk == "critical":
            # 审批中心：创建审批单，interrupt 冻结图等管理者审批
            async def guarded_critical(config: RunnableConfig, **kwargs):
                from app.services.approval_service import ApprovalService
                from app.core.database import SessionLocal
                import json as _json
                import uuid as _uuid
                # trace_id / requester_id 通过 RunnableConfig 注入（运行时上下文）
                cfg = (config or {}).get("configurable", {})
                eff_trace_id = cfg.get("trace_id", "") or trace_id
                eff_requester = cfg.get("requester_id", "") or requester_id
                # LangGraph 恢复时会重放 interrupt() 之前的代码：审批单 ID 用
                # trace+工具+参数的确定性 UUID，重放时直接复用已存在的审批单，
                # 避免“审批通过→重放→重复建单→再审批”的循环。
                stable_key = f"{eff_trace_id}:{name}:{_json.dumps(kwargs, sort_keys=True, ensure_ascii=False)}"
                approval_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, stable_key))
                async with SessionLocal() as db:
                    svc = ApprovalService(db)
                    if await svc.approval_repo.get(approval_id) is None:
                        # 审批单标题友好化：活动创建类工具带 name 参数时展示活动名，
                        # 否则回退「工具名 - 描述」（描述可能很长，截断 200 展示用）
                        title = f"{name} - {tool.description}"[:200]
                        if isinstance(kwargs, dict) and kwargs.get("name"):
                            title = f"创建营销活动：{kwargs['name']}"[:200]
                        await svc.create_approval(
                            category="tool_call", risk="critical", mode="sync",
                            ref_type="trace", ref_id=eff_trace_id,
                            title=title,
                            context={"tool": name, "args": kwargs, "reason": tool.description},
                            requester_id=eff_requester, approver_role="admin",
                            approval_id=approval_id,
                            push_dingtalk=False,  # 手动模式：不自动推送钉钉，由用户确认提交后调用 submit_to_dingtalk
                        )
                # interrupt 冻结图，等待钉钉 OA 审批事件回写（handle_approval_instance_change）后 resume
                result = interrupt({
                    "approval_id": approval_id, "stage": "review",
                })
                if result.get("approved"):
                    r = tool.fn(**kwargs)
                    return await r if hasattr(r, "__await__") else r
                return {"error": "审批未通过"}

            fn = guarded_critical

        return StructuredTool.from_function(
            coroutine=fn if inspect.iscoroutinefunction(fn) else None,
            func=None if inspect.iscoroutinefunction(fn) else fn,
            name=tool.name, description=tool.description,
            args_schema=tool.args_schema,
        )

facade = DataFacade()
