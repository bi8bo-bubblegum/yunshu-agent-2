"""当前日期上下文注入。"""
from app.llm.date_context import current_date_context


def test_current_date_context_format():
    s = current_date_context()
    assert "当前日期：" in s
    assert "年" in s and "月" in s and "日" in s
    assert "星期" in s
