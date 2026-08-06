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
        """DataFacade 工具 → LangChain StructuredTool；按风险等级分流：
        - low/medium：直接执行（包装为原生函数）
        - high：interrupt 即时确认（不进审批中心）
        - critical：创建审批单 + interrupt 冻结图，等审批中心处理"""
        tool = self._tools[name]

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
                        await svc.create_approval(
                            category="tool_call", risk="critical", mode="sync",
                            ref_type="trace", ref_id=eff_trace_id,
                            title=f"{name} - {tool.description}",
                            context={"tool": name, "args": kwargs, "reason": tool.description},
                            requester_id=eff_requester, approver_role="admin",
                            approval_id=approval_id,
                        )
                # interrupt 冻结图，等待审批中心 decide 后 resume
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
