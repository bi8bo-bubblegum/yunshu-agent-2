# backend/tests/test_search_knowledge_tool.py —— search_knowledge 工具（agent 主动检索知识库）
import asyncio
import importlib

import pytest

# 显式取子模块对象：builtin/__init__ 里的函数 search_knowledge 会遮蔽同名子模块，
# 普通 import 绑定到函数而非模块，故用 importlib 保证拿到模块再 setattr
kb_mod = importlib.import_module("app.tools.builtin.search_knowledge")
from app.tools.builtin.search_knowledge import search_knowledge, KB_SEARCH_TIMEOUT


def _patch_hits(monkeypatch, fake):
    monkeypatch.setattr(kb_mod, "search_chunks", fake)


class _FakeHits:
    """fake search_chunks：返回结构化命中。"""

    def __init__(self, hits, delay=0.0):
        self._hits = hits
        self._delay = delay

    async def __call__(self, db, query, top_k=5):
        await asyncio.sleep(self._delay)
        return self._hits


class _HangHits:
    """外部 API 挂起模拟：检索超过 KB_SEARCH_TIMEOUT 不返回。

    真实事故模式：embed/rerank 网关挂起，agent 调工具会卡住 ReAct 循环。
    工具必须限时降级返回空结果 + 提示，不让外部 API 问题拖垮对话。"""

    async def __call__(self, db, query, top_k=5):
        await asyncio.sleep(KB_SEARCH_TIMEOUT + 5)


@pytest.mark.asyncio
async def test_search_knowledge_returns_hits(monkeypatch):
    """命中：返回结构化 results（来源文档 + 内容），agent 可直接整合进回答。"""
    _patch_hits(monkeypatch, _FakeHits([
        {"id": "c1", "document_id": "d1", "content": "公司报销制度：差旅费需在 30 天内提交。"},
        {"id": "c2", "document_id": "d2", "content": "病假需提前一天申请。"},
    ]))
    result = await search_knowledge("公司报销制度", top_k=2)
    assert result["count"] == 2
    assert result["results"][0]["document_id"] == "d1"
    assert "报销制度" in result["results"][0]["content"]


@pytest.mark.asyncio
async def test_search_knowledge_no_hits(monkeypatch):
    """无命中：返回空 results（知识库为空或无关，agent 得知查无内容）。"""
    _patch_hits(monkeypatch, _FakeHits([]))
    result = await search_knowledge("无关话题")
    assert result == {"results": [], "count": 0}


@pytest.mark.asyncio
async def test_search_knowledge_timeout_degrade(monkeypatch):
    """外部 API 挂起：限时超时降级返回提示，不抛异常、不无限阻塞。"""
    _patch_hits(monkeypatch, _HangHits())
    result = await search_knowledge("公司制度")
    assert result["count"] == 0
    assert "超时" in result.get("error", "")
