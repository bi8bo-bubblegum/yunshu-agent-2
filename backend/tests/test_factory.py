# backend/tests/test_factory.py
import pytest
from app.llm.factory import ModelFactory

def test_get_llm_by_key():
    assert ModelFactory.get_llm("default") is not None

def test_get_llm_streaming_enabled():
    """LLM 必须开启流式：LangGraph stream_mode="messages" 依赖底层流式能力，
    未开启时 agent 回复作为完整 chunk 一次性到达，前端表现为「路由后直接一大段」。"""
    llm = ModelFactory.get_llm("marketing")
    assert getattr(llm, "streaming", False) is True

def test_get_embedding():
    assert ModelFactory.get_embedding() is not None
