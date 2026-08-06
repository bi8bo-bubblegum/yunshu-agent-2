# backend/tests/test_checkpoint.py
"""任务 36：验证 checkpointer 已编译进主图。
注：需要数据库可用，否则跳过。"""
import pytest
from app.agents.graph import get_graph


@pytest.mark.asyncio
async def test_graph_compiled_with_checkpointer():
    """graph 在应用事件循环中懒初始化，编译时携带 checkpointer。"""
    graph = await get_graph()
    assert graph is not None
    assert getattr(graph, "checkpointer", None) is not None
