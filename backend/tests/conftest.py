# backend/tests/conftest.py
"""测试公共设施。

关键约定：
1. 必须在 import app 之前将 DATABASE_URL 指向 yunshu_test 测试库，
   保证 API 集成测试（ASGITransport）与 db_session fixture 写同一隔离库，
   不影响运行中的开发库（yunshu）与 8090 服务。
2. 每个测试前 drop_all + create_all，保证测试隔离（含 API 测试之间的残留数据）。
3. 事件循环采用 session 级作用域（pyproject.toml 配置），
   避免 SQLAlchemy async 连接池 / AsyncPostgresSaver 跨事件循环报错。
"""
import os

os.environ["DATABASE_URL"] = "postgresql+asyncpg://yunshu:change_me@localhost:5432/yunshu_test"

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.database import Base


async def _prepare_schema(engine) -> None:
    """启用 pgvector 扩展并重建表结构。"""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture(scope="session", autouse=True)
async def _schema_ready():
    """session 级建表：get_graph() 等不依赖 db_session 的测试也需要表结构。"""
    engine = create_async_engine(os.environ["DATABASE_URL"])
    await _prepare_schema(engine)
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_db(_schema_ready):
    """每个测试前清空并重建表，保证测试隔离。"""
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _prepare_schema(engine)
    await engine.dispose()
    yield


@pytest.fixture
async def db_session():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def mock_dingtalk_push(monkeypatch):
    """把钉钉审批推送替换为无操作：仅落一条 binding，不触网、不校验钉钉配置/账号。

    M4 全走钉钉审批后，create_approval 会调用 approval_gateway.push_approval_to_dingtalk；
    非钉钉专项测试（审批列表/经验晋升/聊天 critical 流程）用它隔离推送，
    专注本地行为。binding.process_instance_id 由审批单 ID 确定性生成，测试据此触发事件回写。
    """
    from app.models.dingtalk import ApprovalBinding

    async def _fake_push(db, approval):
        pid = f"inst_{approval.id.replace('-', '')[:24]}"
        binding = ApprovalBinding(approval_id=approval.id, process_code="TEST_PROC",
                                  process_instance_id=pid, status="pushed")
        db.add(binding)
        return binding

    monkeypatch.setattr("app.services.dingtalk.approval_gateway.push_approval_to_dingtalk", _fake_push)
