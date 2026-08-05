# backend/app/tools/facade.py
from typing import Awaitable, Callable
from pydantic import BaseModel
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

    def to_langchain_tool(self, name: str) -> StructuredTool:
        """基础版：直接转为 LangChain StructuredTool，不做风险分级包装。
        风险分级（interrupt/审批中心）在任务 31 增强时实现。"""
        tool = self._tools[name]
        return StructuredTool.from_function(
            coroutine=tool.fn, name=tool.name, description=tool.description,
            args_schema=tool.args_schema,
        )

facade = DataFacade()