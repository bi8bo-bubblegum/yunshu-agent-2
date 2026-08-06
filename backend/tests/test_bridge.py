# backend/tests/test_bridge.py
import inspect
from app.tools.facade import facade

def test_bridge_tool_schema():
    tool = facade.to_langchain_tool("query_sales_data")
    assert tool.name == "query_sales_data"
    assert "metric" in tool.args_schema.model_fields
    assert "period" in tool.args_schema.model_fields

def test_bridge_critical_risk_wrapped():
    """critical 风险工具必须被 interrupt() 审批中心包装。"""
    tool = facade.to_langchain_tool("delete_order")
    # guarded_critical 是 async 包装函数，存于 coroutine 属性
    assert "interrupt" in inspect.getsource(tool.coroutine)
