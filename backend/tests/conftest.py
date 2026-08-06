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
