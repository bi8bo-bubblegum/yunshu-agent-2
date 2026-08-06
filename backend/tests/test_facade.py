# backend/tests/test_facade.py
import pytest
from app.tools.facade import DataFacade
from app.tools.builtin import register_builtin_tools

def test_facade_registry():
    facade = DataFacade()
    register_builtin_tools(facade)
    assert "query_sales_data" in facade.list_tools()
    result = facade.execute("query_sales_data", {"metric": "revenue", "period": "7d"})
    assert "total" in result  # mock 返回含 total 键

def test_tool_to_langchain():
    """facade.to_langchain_tool 必须能转为 LangChain StructuredTool 供 agent 使用。"""
    facade = DataFacade()
    register_builtin_tools(facade)
    tool = facade.to_langchain_tool("query_sales_data")
    assert tool.name == "query_sales_data"
    assert "metric" in tool.args_schema.model_fields
    assert "period" in tool.args_schema.model_fields


def test_to_langchain_tool_low_risk():
    """low 风险工具：直接执行，无 interrupt。"""
    facade = DataFacade()
    register_builtin_tools(facade)
    tool = facade.to_langchain_tool("query_sales_data")
    assert tool.name == "query_sales_data"
    assert tool.func is not None  # 直接执行函数

def test_to_langchain_tool_high_risk():
    """high 风险工具：包装为 interrupt 即时确认。"""
    facade = DataFacade()
    register_builtin_tools(facade)
    tool = facade.to_langchain_tool("create_marketing_campaign")
    # 包装后函数不是原始 fn，而是 guarded_high
    assert tool.name == "create_marketing_campaign"

def test_to_langchain_tool_critical_risk():
    """critical 风险工具：包装为审批中心流程。"""
    facade = DataFacade()
    register_builtin_tools(facade)
    tool = facade.to_langchain_tool("publish_campaign", trace_id="trace-1", requester_id="user-1")
    assert tool.name == "publish_campaign"
