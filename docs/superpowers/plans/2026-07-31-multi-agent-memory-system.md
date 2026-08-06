# 多 Agent 智能协作系统实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现 supervisor 统一意图分发 + 四层记忆管理（短期/偏好/经验/知识）+ 全链路留痕 + 风险分级审批（high 即时确认 / critical 统一审批中心）的多 Agent 系统，Python 3.11 + LangGraph + PostgreSQL + SQLAlchemy + FastAPI 全异步。

**架构：** FastAPI 异步层 → LangGraph 主图（Supervisor 循环路由）→ Agent 子图（营销助手/经营分析/调度优化）→ 记忆装配层（四层记忆注入 prompt）→ 数据门面（内置工具 + MCP）。状态用 langgraph-checkpoint-postgres 持久化；高风险工具按风险分级处理（high interrupt 即时确认 / critical 进统一审批中心）；留痕用异步队列批量落库不阻塞主流程。

**技术栈：** Python 3.11、FastAPI、SQLAlchemy 2.0 async（asyncpg）、Alembic、LangGraph、langgraph-checkpoint-postgres、pgvector、langchain-openai（OpenAI 兼容多模型）、langchain-mcp-adapters、sse-starlette、pytest。

**规格来源：** `docs/superpowers/specs/2026-07-31-multi-agent-memory-system-design.md`

---

## 文件结构总览

```
backend/
├── pyproject.toml              # 依赖与工具配置
├── .env.example                # 环境变量模板
├── docker-compose.yml          # postgres/pgvector + 后端
├── alembic.ini
├── alembic/env.py              # async 迁移引擎
├── alembic/versions/           # 迁移脚本
├── app/
│   ├── main.py                 # FastAPI 入口，注册全部路由
│   ├── core/
│   │   ├── config.py           # pydantic-settings 配置
│   │   ├── database.py         # async engine + session 工厂 + Base
│   │   ├── security.py         # JWT 签发/校验 + 密码哈希
│   │   └── deps.py             # 依赖注入（当前用户、DB session）
│   ├── models/                 # SQLAlchemy 模型（按域拆分）
│   │   ├── __init__.py
│   │   ├── org.py              # User / Department / Role
│   │   ├── chat.py             # Conversation / Message
│   │   ├── preferences.py      # Preference
│   │   ├── experience.py       # Experience
│   │   ├── knowledge.py        # Document / Chunk
│   │   ├── trace.py            # ExecutionTrace / TraceEvent / Approval（统一审批中心）
│   │   ├── configs.py          # McpServer, AgentMcpBinding
│   ├── repositories/           # ★ 数据访问层：原子 CRUD（每实体一个 repo）
│   │   ├── base.py             # BaseRepository（通用 get/add/update/delete/list）
│   │   ├── user_repo.py / department_repo.py / role_repo.py
│   │   ├── conversation_repo.py / message_repo.py
│   │   ├── preference_repo.py / experience_repo.py
│   │   ├── document_repo.py / chunk_repo.py
│   │   ├── trace_repo.py / event_repo.py / approval_repo.py
│   │   └── config_repo.py
│   ├── schemas/                # Pydantic 请求/响应模型
│   ├── api/                    # ★ 接口层：薄路由，只做参数校验+调 service
│   ├── services/               # ★ 业务层：组合 repository 与业务规则
│   │   ├── auth_service.py     # 注册/登录/JWT
│   │   ├── chat_service.py     # 会话+消息+记忆装配+图执行
│   │   ├── knowledge_service.py# 文档上传解析/RAG
│   │   ├── experience_service.py  # 经验提炼/晋升
│   │   ├── approval_service.py    # 统一审批中心（tool_call + experience_promotion）
│   │   ├── trace_service.py       # 留痕查询
│   │   ├── document_parser.py  # PDF/Word/Markdown 解析+切分
│   │   ├── embedding.py        # embedding 客户端封装
│   │   ├── preference_svc.py   # 偏好提取/合并去重
│   │   ├── summary.py          # 对话滚动摘要
│   │   └── seed.py             # 种子数据
│   ├── agents/
│   │   ├── state.py            # AgentState（含 messages 工作状态）
│   │   ├── graph.py            # 主图装配 + Supervisor 循环（子图嵌入）
│   │   ├── supervisor.py       # 路由节点（结构化输出）
│   │   ├── registry.py         # AgentRegistry 动态装配
│   │   ├── marketing/agent.py  # 营销助手子图（内部构建：节点+ToolNode+路由）
│   │   ├── sales_analysis/agent.py
│   │   └── scheduling/agent.py
│   ├── memory/
│   │   ├── assembly.py         # MemoryAssembly 统一装配
│   │   ├── short_term.py
│   │   ├── preferences.py
│   │   ├── experiences.py
│   │   └── knowledge.py
│   ├── tools/
│   │   ├── facade.py           # DataFacade 统一门面（Tool 类 + DataFacade 类 + facade 单例）
│   │   ├── loader.py           # load_tools 共享工具加载（内置 + MCP）
│   │   ├── risk.py             # 风险评估器
│   │   ├── builtin/__init__.py # register_builtin_tools 统一注册
│   │   ├── builtin/query_sales_data.py
│   │   ├── builtin/query_marketing_campaigns.py
│   │   ├── builtin/query_schedule.py
│   │   ├── builtin/create_marketing_campaign.py
│   │   ├── builtin/adjust_schedule.py
│   │   ├── builtin/publish_campaign.py
│   │   ├── builtin/delete_order.py
│   │   └── mcp_adapter.py
│   ├── traces/
│   │   ├── collector.py        # 留痕采集器（队列+批量落库）
│   │   └── handlers.py         # AsyncCallbackHandler + 节点包装器
│   └── llm/factory.py          # ModelFactory 多模型工厂
├── scripts/seed.py             # 种子数据脚本
└── tests/
    ├── conftest.py
    ├── test_auth.py / test_org.py / test_chat.py / test_summary.py
    ├── test_memory.py / test_experience.py / test_knowledge.py
    ├── test_supervisor.py / test_traces.py / test_approvals.py
```

---

## 里程碑 M1：基础设施与数据层

### 任务 1：项目骨架与依赖

**文件：**
- 创建：`backend/pyproject.toml`
- 创建：`backend/.env.example`
- 创建：`backend/docker-compose.yml`
- 创建：`backend/app/__init__.py`、`backend/app/core/__init__.py`

- [ ] **步骤 1：编写 pyproject.toml**

```toml
[project]
name = "yunshu-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "langgraph>=0.2.0",
    "langgraph-checkpoint-postgres>=2.0.0",
    "langchain-core>=0.3.0",
    "langchain-openai>=0.2.0",
    "langchain-mcp-adapters>=0.1.0",
    "langchain-text-splitters>=0.2.0",
    "pgvector>=0.3.0",
    "pyjwt>=2.9",
    "bcrypt>=4.1",
    "pypdf>=4.2",
    "python-docx>=1.1",
    "sse-starlette>=2.1",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8.2", "pytest-asyncio>=0.23", "pytest-cov>=5.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["app*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **步骤 2：编写 .env.example 与 docker-compose.yml**

```bash
# backend/.env.example
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/yunshu
JWT_SECRET=change-me
JWT_EXPIRE_MINUTES=10080
DEFAULT_MODEL=doubao-pro
EMBEDDING_MODEL=text-embedding-v3
MODEL_API_BASE=https://api.example.com/v1
MODEL_API_KEY=sk-xxx
FRONTEND_ORIGINS=http://localhost:5173
```

```yaml
# backend/docker-compose.yml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: yunshu
    ports: ["5432:5432"]
    volumes: [db_data:/var/lib/postgresql/data]
volumes:
  db_data:
```

- [ ] **步骤 3：编写 core/config.py 与 core/database.py**

```python
# app/core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_EXPIRE_MINUTES: int = 10080
    DEFAULT_MODEL: str = "doubao-pro"
    EMBEDDING_MODEL: str = "text-embedding-v3"
    MODEL_API_BASE: str
    MODEL_API_KEY: str
    FRONTEND_ORIGINS: str = "http://localhost:5173"

    model_config = {"env_file": ".env"}

settings = Settings()
```

```python
# app/core/database.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

class Base(DeclarativeBase):
    pass

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

- [ ] **步骤 4：验证项目可导入**

运行：`cd backend && python -c "from app.core.config import settings; print(settings.DATABASE_URL[:20])"`
预期：输出 `postgresql+asyncpg://`

- [ ] **步骤 5：Commit**

```bash
git add backend/pyproject.toml backend/.env.example backend/docker-compose.yml backend/app
git commit -m "chore: 项目骨架与依赖配置"
```

---

### 任务 2：Alembic + pgvector 扩展

**文件：**
- 创建：`backend/alembic.ini`、`backend/alembic/env.py`、`backend/alembic/script.py.mako`

- [ ] **步骤 1：初始化 Alembic**

```bash
cd backend && alembic init alembic
```

- [ ] **步骤 2：配置异步 env.py（替换自动生成内容）**

```python
# backend/alembic/env.py
import asyncio
from logging.config import fileConfig
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from app.core.config import settings
from app.core.database import Base
import app.models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("+asyncpg", ""))
fileConfig(config.config_file_name)
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations() -> None:
    connectable = async_engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **步骤 3：启动数据库并生成初始迁移**

```bash
cd backend && docker compose up -d db && sleep 3 && alembic revision -m "init" --autogenerate
```

在生成的迁移 `upgrade()` 顶部追加（任务 3-6 完成后重跑生成完整表结构，此扩展语句保留）：

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
```

- [ ] **步骤 4：执行迁移**

运行：`cd backend && alembic upgrade head`
预期：`Running upgrade ... -> ..., done`

- [ ] **步骤 5：Commit**

```bash
git add backend/alembic backend/alembic.ini
git commit -m "chore: alembic 异步迁移与 pgvector 扩展"
```

---

### 任务 3：组织模型（User/Department/Role）

**文件：**
- 创建：`backend/app/models/org.py`、`backend/app/models/__init__.py`
- 创建：`backend/tests/conftest.py`、`backend/tests/test_org.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/conftest.py
import asyncio
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.database import Base

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def db_session():
    engine = create_async_engine("postgresql+asyncpg://postgres:postgres@localhost:5432/yunshu_test")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()
```

```python
# backend/tests/test_org.py
import pytest
from app.models.org import Department, Role, User

@pytest.mark.asyncio
async def test_create_user_with_department(db_session):
    dept = Department(name="市场部")
    db_session.add(dept)
    await db_session.flush()
    role = Role(code="member", name="成员")
    db_session.add(role)
    await db_session.flush()
    user = User(username="alice", password_hash="x", department_id=dept.id, role_code=role.code, display_name="爱丽丝")
    db_session.add(user)
    await db_session.flush()
    # 不使用 relationship，通过 department_id 手动查关联
    result = await db_session.get(User, user.id)
    assert result.department_id == dept.id
    dept_result = await db_session.get(Department, result.department_id)
    assert dept_result.name == "市场部"
    role_result = await db_session.get(Role, result.role_code)
    assert role_result.code == "member"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_org.py -v`
预期：FAIL，`ImportError: cannot import name 'Department'`

- [ ] **步骤 3：实现模型**

```python
# backend/app/models/org.py
from datetime import datetime
from uuid import uuid4
from sqlalchemy import UUID, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

# 全项目约定：不使用物理外键（数据库不建 FOREIGN KEY 约束）；
# 全库主键统一 UUID 字符串（应用层 uuid4 生成），关联列用普通 String(36) + index；
# 不使用 relationship，关联查询在 repo/service 层用 id 手动查。

class Role(Base):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))

class Department(Base):
    __tablename__ = "departments"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128), unique=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), index=True)  # 逻辑外键

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    department_id: Mapped[str | None] = mapped_column(String(36), index=True)  # 逻辑外键
    role_code: Mapped[str | None] = mapped_column(String(32), index=True)      # 逻辑外键，关联 Role.code
    display_name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

```python
# backend/app/models/__init__.py
from app.models.org import User, Department, Role
__all__ = ["User", "Department", "Role"]
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_org.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app/models backend/tests
git commit -m "feat: 组织模型 User/Department/Role"
```

---

### 任务 4：聊天模型（Conversation/Message）

**文件：**
- 创建：`backend/app/models/chat.py`
- 创建：`backend/tests/test_chat_models.py`
- 修改：`backend/app/models/__init__.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_chat_models.py
import pytest
from sqlalchemy import select
from app.models.chat import Conversation, Message
from app.models.org import User

@pytest.mark.asyncio
async def test_conversation_with_messages(db_session):
    user = User(username="bob", password_hash="x", display_name="Bob")
    db_session.add(user)
    await db_session.flush()
    conv = Conversation(user_id=user.id, title="国庆营销")
    db_session.add(conv)
    await db_session.flush()
    db_session.add(Message(conversation_id=conv.id, role="user", content="策划国庆方案"))
    await db_session.commit()
    # 不使用 relationship，通过 conversation_id 手动查消息
    result = await db_session.get(Conversation, conv.id)
    messages = (await db_session.scalars(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )).all()
    assert len(messages) == 1
    assert messages[0].role == "user"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_chat_models.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现模型**

```python
# backend/app/models/chat.py
from datetime import datetime
from uuid import uuid4
from sqlalchemy import UUID, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    title: Mapped[str] = mapped_column(String(128), default="新对话")
    summary: Mapped[str | None] = mapped_column(Text)
    current_trace_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

```python
# backend/app/models/__init__.py 追加
from app.models.chat import Conversation, Message
__all__ += ["Conversation", "Message"]
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_chat_models.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app/models backend/tests
git commit -m "feat: 会话与消息模型"
```

---

### 任务 5：经验与知识模型（含 pgvector 向量）

**文件：**
- 创建：`backend/app/models/experience.py`、`backend/app/models/knowledge.py`
- 创建：`backend/tests/test_models_vector.py`
- 修改：`backend/app/models/__init__.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_models_vector.py
import pytest
from sqlalchemy import select
from app.models.experience import Experience
from app.models.knowledge import Document, Chunk

@pytest.mark.asyncio
async def test_experience_with_embedding(db_session):
    exp = Experience(
        owner_id="u1", scope="personal", status="approved",
        title="国庆大促策略", summary="满减+直播", content="详情",
        event_time="2025-10-01", result_metrics={"gmv": 320, "roi": 3.2},
        embedding=[0.1, 0.2, 0.3],
    )
    db_session.add(exp)
    await db_session.commit()
    result = await db_session.scalar(select(Experience))
    assert result.title == "国庆大促策略"
    assert result.result_metrics["gmv"] == 320
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_models_vector.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现模型（Vector(1024) 与 EMBEDDING_DIM 保持一致）**

```python
# backend/app/models/experience.py
from datetime import date, datetime
from uuid import uuid4
from sqlalchemy import UUID, Date, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from app.core.database import Base

class Experience(Base):
    __tablename__ = "experiences"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    scope: Mapped[str] = mapped_column(String(16))  # personal/dept/company
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft/pending/approved/rejected
    title: Mapped[str] = mapped_column(String(128))
    summary: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    event_time: Mapped[date | None] = mapped_column(Date)
    result_metrics: Mapped[dict | None] = mapped_column(JSONB)
    department_id: Mapped[str | None] = mapped_column(String(36), index=True)  # 逻辑外键
    source_trace_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))

# ExperienceApproval 已删除，统一审批中心 Approval 模型定义在 trace.py 中（见任务 6）
```

```python
# backend/app/models/knowledge.py
from datetime import datetime
from uuid import uuid4
from sqlalchemy import UUID, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from app.core.database import Base

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(256))
    file_path: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="parsing")  # parsing/ready/failed
    uploader_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    department_id: Mapped[str | None] = mapped_column(String(36), index=True)  # 逻辑外键
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    seq: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    meta_: Mapped[dict | None] = mapped_column("meta", JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
```

```python
# backend/app/models/__init__.py 追加
from app.models.experience import Experience
from app.models.knowledge import Document, Chunk
__all__ += ["Experience", "Document", "Chunk"]
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_models_vector.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app/models backend/tests
git commit -m "feat: 经验与知识模型（pgvector 向量列）"
```

---

### 任务 6：留痕与配置模型

**文件：**
- 创建：`backend/app/models/trace.py`、`backend/app/models/configs.py`
- 创建：`backend/tests/test_trace_models.py`
- 修改：`backend/app/models/__init__.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_trace_models.py
import pytest
from sqlalchemy import select
from app.models.trace import ExecutionTrace, TraceEvent, Approval
from app.models.configs import McpServer

@pytest.mark.asyncio
async def test_trace_event_flow(db_session):
    trace = ExecutionTrace(user_id="u1", status="running", supervisor_routes=[{"agent": "marketing"}])
    db_session.add(trace)
    await db_session.flush()
    db_session.add(TraceEvent(trace_id=trace.id, type="llm_call", payload={"model": "x", "tokens": 100}))
    db_session.add(Approval(category="tool_call", risk="critical", mode="sync", ref_type="trace",
                            ref_id=trace.id, title="删除文件", context={"path": "/tmp/x"},
                            status="pending", requester_id="u1"))
    await db_session.commit()
    # 不使用 relationship，通过 ref_id 手动查关联
    result = await db_session.get(ExecutionTrace, trace.id)
    assert result.supervisor_routes[0]["agent"] == "marketing"
    events = (await db_session.scalars(
        select(TraceEvent).where(TraceEvent.trace_id == trace.id)
    )).all()
    assert len(events) == 1
    approvals = (await db_session.scalars(
        select(Approval).where(Approval.ref_id == trace.id)
    )).all()
    assert approvals[0].status == "pending"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_trace_models.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现模型**

```python
# backend/app/models/trace.py
from datetime import datetime
from uuid import uuid4
from sqlalchemy import UUID, BigInteger, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class ExecutionTrace(Base):
    __tablename__ = "execution_traces"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    conversation_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running/completed/interrupted/failed
    supervisor_routes: Mapped[list | None] = mapped_column(JSONB, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class TraceEvent(Base):
    __tablename__ = "trace_events"
    # 全库唯一自增主键特例：留痕为高频批量写入，顺序自增比 UUID 更省索引与页分裂
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    type: Mapped[str] = mapped_column(String(16))  # route/llm/tool/memory/approval
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Approval(Base):
    """统一审批中心。合并原 HitlTask + ExperienceApproval。
    - high 风险工具调用：interrupt 即时确认，不进审批中心（不创建本表记录）
    - critical 风险工具调用：创建本表记录，interrupt 冻结图等管理者审批
    - 经验晋升：创建本表记录，不阻塞图，等管理者审批"""
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    category: Mapped[str] = mapped_column(String(32), index=True)  # tool_call / experience_promotion
    risk: Mapped[str | None] = mapped_column(String(16))           # high / critical（仅 tool_call 有值）
    mode: Mapped[str] = mapped_column(String(16))                  # sync（阻塞图）/ async（不阻塞）
    ref_type: Mapped[str] = mapped_column(String(32))              # trace / experience
    ref_id: Mapped[str] = mapped_column(String(36), index=True)    # 关联对象 ID
    title: Mapped[str] = mapped_column(String(200))
    context: Mapped[dict | None] = mapped_column(JSONB)            # 工具参数 / 经验摘要
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/approved/rejected
    requester_id: Mapped[str] = mapped_column(String(36), index=True)   # 发起人
    approver_id: Mapped[str | None] = mapped_column(String(36), index=True)  # 审批人
    approver_role: Mapped[str | None] = mapped_column(String(32))  # 要求的审批角色（admin/dept_owner）
    comment: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

```python
# backend/app/models/configs.py
from datetime import datetime
from uuid import uuid4
from sqlalchemy import UUID, Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class McpServer(Base):
    __tablename__ = "mcp_servers"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(String(512))
    auth_type: Mapped[str] = mapped_column(String(16), default="none")
    # config 为 MCP 服务级通用 JSONB 配置，目前用于存工具风险覆盖：
    #   {"tool_risks": {"delete_order": "critical", "adjust_schedule": "high"}}
    # 注册时为空 {}，由管理员通过"查看工具 → 配置风险"两步操作写入（任务 38.6）
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    default_risk: Mapped[str] = mapped_column(String(16), default="medium")  # 服务级默认风险：low/medium/high/critical

class AgentMcpBinding(Base):
    """agent 与 MCP 服务的绑定关系，运行时动态加载。内置工具仍由 agent 硬编码声明。"""
    __tablename__ = "agent_mcp_bindings"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    agent_code: Mapped[str] = mapped_column(String(32), index=True)   # marketing/sales_analysis/scheduling
    mcp_server_name: Mapped[str] = mapped_column(String(64))           # 关联 mcp_servers.name
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

```python
# backend/app/models/__init__.py 追加
from app.models.trace import ExecutionTrace, TraceEvent, Approval
from app.models.configs import McpServer, AgentMcpBinding
__all__ += ["ExecutionTrace", "TraceEvent", "Approval", "McpServer", "AgentMcpBinding"]
```

- [ ] **步骤 4：全部模型测试通过并生成迁移**

运行：`cd backend && pytest tests -v && alembic revision -m "models" --autogenerate && alembic upgrade head`
预期：全部 PASS；迁移 `Running upgrade ... done`

- [ ] **步骤 5：Commit**

```bash
git add backend/app/models backend/tests backend/alembic
git commit -m "feat: 留痕与配置模型 + 全量迁移"
```

---

### 任务 7：认证基础件（JWT + 密码哈希 + 依赖注入）

> 只做基础件，不写业务路由；`api/auth.py`（薄路由）与 API 集成测试放到任务 7.5 一并按三层实现，避免先写直查 DB 的路由再推翻。

**文件：**
- 创建：`backend/app/core/security.py`、`backend/app/core/deps.py`
- 创建：`backend/app/schemas/auth.py`、`backend/app/main.py`
- 创建：`backend/tests/test_security.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_security.py
import pytest
from app.core.security import hash_password, verify_password, create_access_token, decode_token

def test_hash_and_verify():
    h = hash_password("pass123")
    assert h != "pass123"
    assert verify_password("pass123", h)
    assert not verify_password("wrong", h)

def test_token_roundtrip():
    token = create_access_token("u1", "alice")
    payload = decode_token(token)
    assert payload["sub"] == "u1" and payload["username"] == "alice"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_security.py -v`
预期：FAIL，`ModuleNotFoundError: app.core.security`

- [ ] **步骤 3：实现 security / deps / schemas / main**

```python
# backend/app/core/security.py
import jwt
from datetime import datetime, timedelta, timezone
from bcrypt import hashpw, gensalt, checkpw
from app.core.config import settings

def hash_password(plain: str) -> str:
    return hashpw(plain.encode(), gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return checkpw(plain.encode(), hashed.encode())

def create_access_token(user_id: str, username: str) -> str:
    payload = {"sub": str(user_id), "username": username,
               "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
```

```python
# backend/app/core/deps.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import SessionLocal
from app.core.security import decode_token
from app.models.org import User

bearer = HTTPBearer(auto_error=False)

async def get_db():
    async with SessionLocal() as session:
        yield session

async def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: AsyncSession = Depends(get_db)) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未认证")
    try:
        payload = decode_token(creds.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token 无效")
    user = await db.scalar(select(User).where(User.id == payload["sub"]))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user
```

```python
# backend/app/schemas/auth.py
from pydantic import BaseModel

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    department_id: str | None = None
    role_code: str | None = None
    model_config = {"from_attributes": True}
```

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

app = FastAPI(title="云书 Agent")
app.add_middleware(CORSMiddleware, allow_origins=settings.FRONTEND_ORIGINS.split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
# 业务路由随各任务逐步 include_router（auth 路由在任务 7.5 注册）
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_security.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 认证基础件（JWT + 密码哈希 + 依赖注入）"
```

---

### 任务 7.5：三层架构范式（BaseRepository + 认证域改造）

> **全项目架构约定**：`router（薄，只校验参数）→ service（组合业务）→ repository（原子 CRUD）`。本任务建立范式：BaseRepository + UserRepository + AuthService + 薄路由（认证域一步到位三层化，不写直查 DB 的路由）。**后续所有 API 任务一律遵循此三层**。

**文件：**
- 创建：`backend/app/repositories/base.py`、`backend/app/repositories/user_repo.py`
- 创建：`backend/app/services/auth_service.py`
- 创建：`backend/app/api/auth.py`（薄路由，一步到位）
- 创建：`backend/tests/test_auth.py`、`backend/tests/test_auth_service.py`
- 修改：`backend/app/core/deps.py`（get_current_user 改走 UserRepository）、`backend/app/main.py`（注册 auth 路由）

- [ ] **步骤 1：编写失败的测试（API 集成 + repository/service 单测）**

```python
# backend/tests/test_auth.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_register_and_login():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/auth/register", json={"username": "alice", "password": "pass123", "display_name": "Alice"})
        assert r.status_code == 200
        r = await client.post("/api/auth/login", json={"username": "alice", "password": "pass123"})
        assert r.status_code == 200 and "access_token" in r.json()
        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
        assert me.json()["username"] == "alice"
```

```python
# backend/tests/test_auth_service.py
import pytest
from fastapi import HTTPException
from app.services.auth_service import AuthService

@pytest.mark.asyncio
async def test_register_and_login_service(db_session):
    svc = AuthService(db_session)
    user = await svc.register("alice", "pass123", "Alice")
    assert user.username == "alice"
    token = await svc.login("alice", "pass123")
    assert token

@pytest.mark.asyncio
async def test_login_wrong_password(db_session):
    svc = AuthService(db_session)
    await svc.register("bob", "pass123", "Bob")
    with pytest.raises(HTTPException) as e:
        await svc.login("bob", "wrong")
    assert e.value.status_code == 401
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_auth.py tests/test_auth_service.py -v`
预期：FAIL，`ModuleNotFoundError: app.services.auth_service` / 路由 404

- [ ] **步骤 3：实现 Repository 层（BaseRepository + UserRepository）**

```python
# backend/app/repositories/base.py
from typing import ClassVar, Generic, Type, TypeVar
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")

class BaseRepository(Generic[ModelType]):
    """通用原子 CRUD：一个方法一个数据库操作，不自行 commit（保证 service 层事务原子性）。
    service 层组合多个 repo 操作后统一调用 db.commit()。"""
    model: ClassVar[Type[ModelType]]  # 子类指定

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, pk) -> ModelType | None:
        return (await self.db.scalars(select(self.model).where(self.model.id == pk))).first()

    async def get_by(self, **filters) -> ModelType | None:
        return (await self.db.scalars(select(self.model).filter_by(**filters))).first()

    async def list(self, **filters) -> list[ModelType]:
        return list((await self.db.scalars(select(self.model).filter_by(**filters))).all())

    async def add(self, obj: ModelType) -> None:
        """加入会话并 flush（拿到 id），不 commit。"""
        self.db.add(obj)
        await self.db.flush()

    async def add_all(self, objs: list[ModelType]) -> None:
        self.db.add_all(objs)
        await self.db.flush()

    async def delete(self, obj: ModelType) -> None:
        await self.db.delete(obj)
        await self.db.flush()

    async def commit(self) -> None:
        """service 组合多个 repo 操作后统一提交事务。"""
        await self.db.commit()

    async def count(self, **filters) -> int:
        stmt = select(func.count()).select_from(self.model)
        if filters:
            stmt = stmt.where(*[getattr(self.model, k) == v for k, v in filters.items()])
        return (await self.db.scalar(stmt)) or 0
```

```python
# backend/app/repositories/user_repo.py
from app.models.org import User
from app.repositories.base import BaseRepository

class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_username(self, username: str) -> User | None:
        return await self.get_by(username=username)
```

- [ ] **步骤 4：实现 Service 层（AuthService）**

```python
# backend/app/services/auth_service.py
from fastapi import HTTPException
from app.models.org import User
from app.repositories.user_repo import UserRepository
from app.core.security import hash_password, verify_password, create_access_token

class AuthService:
    """业务组合：注册去重 + 密码校验 + 签发 token，数据库操作委托 repository。"""
    def __init__(self, db):
        self.user_repo = UserRepository(db)

    async def register(self, username: str, password: str, display_name: str) -> User:
        if await self.user_repo.get_by_username(username):
            raise HTTPException(400, "用户名已存在")
        user = User(username=username, password_hash=hash_password(password), display_name=display_name)
        await self.user_repo.add(user)
        await self.user_repo.commit()
        return user

    async def login(self, username: str, password: str) -> str:
        user = await self.user_repo.get_by_username(username)
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(401, "用户名或密码错误")
        return create_access_token(user.id, user.username)
```

- [ ] **步骤 5：创建薄路由 + 改造 deps 走 UserRepository + 注册 main**

```python
# backend/app/api/auth.py —— 薄路由：只校验参数、调 service
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserOut
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/auth", tags=["auth"])

def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)

@router.post("/register", response_model=UserOut)
async def register(body: RegisterRequest, svc: AuthService = Depends(get_auth_service)):
    return await svc.register(body.username, body.password, body.display_name)

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, svc: AuthService = Depends(get_auth_service)):
    return TokenResponse(access_token=await svc.login(body.username, body.password))

@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
```

```python
# backend/app/core/deps.py 修改：get_current_user 改走 UserRepository（去掉直查 select）
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import SessionLocal
from app.core.security import decode_token
from app.models.org import User
from app.repositories.user_repo import UserRepository

async def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: AsyncSession = Depends(get_db)) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未认证")
    try:
        payload = decode_token(creds.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token 无效")
    user = await UserRepository(db).get(payload["sub"])
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user
```

```python
# backend/app/main.py 追加
from app.api import auth
app.include_router(auth.router)
```

- [ ] **步骤 6：运行全部认证测试验证通过**

运行：`cd backend && pytest tests/test_auth.py tests/test_auth_service.py -v`
预期：全部 PASS（认证 API 三层化，行为一致）

- [ ] **步骤 7：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 三层架构范式(Repository/Service/Router)与认证域改造"
```

---

### 任务 8：组织架构 API（三层）

**文件：**
- 创建：`backend/app/repositories/department_repo.py`、`backend/app/services/org_service.py`
- 创建：`backend/app/api/org.py`（薄层）、`backend/app/schemas/org.py`
- 创建：`backend/tests/test_org_api.py`、`backend/tests/test_org_service.py`
- 修改：`backend/app/main.py`

- [ ] **步骤 1：编写失败的测试（service 单测 + API 测试）**

```python
# backend/tests/test_org_service.py
import pytest
from app.services.org_service import OrgService

@pytest.mark.asyncio
async def test_create_and_list_department(db_session):
    svc = OrgService(db_session)
    dept = await svc.create_department("市场部")
    assert dept.name == "市场部"
    depts = await svc.list_departments()
    assert any(d.id == dept.id for d in depts)
```

```python
# backend/tests/test_org_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_department_crud():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "root", "password": "x123456", "display_name": "Root"})
        r = await c.post("/api/auth/login", json={"username": "root", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/departments", json={"name": "市场部"}, headers=h)
        assert r.status_code == 200
        dept_id = r.json()["id"]
        r = await c.get("/api/departments", headers=h)
        assert any(d["id"] == dept_id for d in r.json())
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_org_service.py -v`
预期：FAIL，ModuleNotFoundError

- [ ] **步骤 3：实现 Repository 层（DepartmentRepository）**

```python
# backend/app/repositories/department_repo.py
from app.models.org import Department
from app.repositories.base import BaseRepository

class DepartmentRepository(BaseRepository[Department]):
    model = Department
```

- [ ] **步骤 4：实现 Service 层（OrgService）**

```python
# backend/app/services/org_service.py
from app.models.org import Department, User
from app.repositories.department_repo import DepartmentRepository
from app.repositories.user_repo import UserRepository

class OrgService:
    def __init__(self, db):
        self.dept_repo = DepartmentRepository(db)
        self.user_repo = UserRepository(db)

    async def create_department(self, name: str) -> Department:
        dept = Department(name=name)
        await self.dept_repo.add(dept)
        await self.dept_repo.commit()
        return dept

    async def list_departments(self) -> list[Department]:
        return await self.dept_repo.list()

    async def list_users(self) -> list[User]:
        return await self.user_repo.list()
```

- [ ] **步骤 5：实现薄路由并在 main.py 注册**

```python
# backend/app/schemas/org.py
from pydantic import BaseModel

class DepartmentCreate(BaseModel):
    name: str

class DepartmentOut(BaseModel):
    id: str
    name: str
    owner_id: str | None = None
    model_config = {"from_attributes": True}
```

```python
# backend/app/api/org.py —— 薄路由
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.schemas.auth import UserOut
from app.schemas.org import DepartmentCreate, DepartmentOut
from app.services.org_service import OrgService

router = APIRouter(tags=["org"])

def get_org_service(db: AsyncSession = Depends(get_db)) -> OrgService:
    return OrgService(db)

@router.post("/api/departments", response_model=DepartmentOut)
async def create_department(body: DepartmentCreate, svc: OrgService = Depends(get_org_service), _: User = Depends(get_current_user)):
    return await svc.create_department(body.name)

@router.get("/api/departments", response_model=list[DepartmentOut])
async def list_departments(svc: OrgService = Depends(get_org_service), _: User = Depends(get_current_user)):
    return await svc.list_departments()

@router.get("/api/users", response_model=list[UserOut])
async def list_users(svc: OrgService = Depends(get_org_service), _: User = Depends(get_current_user)):
    return await svc.list_users()
```

```python
# backend/app/main.py 追加
from app.api import org
app.include_router(org.router)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_org_api.py tests/test_org_service.py -v`
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 组织架构 API"
```

---

### 任务 9：种子数据（角色 + 默认 Agent 配置）

**文件：**
- 创建：`backend/app/services/seed.py`、`backend/scripts/seed.py`
- 创建：`backend/tests/test_seed.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_seed.py
import pytest
from sqlalchemy import select
from app.models.org import Role
from app.services.seed import seed_roles

@pytest.mark.asyncio
async def test_seed_creates_defaults(db_session):
    await seed_roles(db_session)
    roles = (await db_session.scalars(select(Role))).all()
    assert {r.code for r in roles} >= {"member", "dept_owner", "admin"}
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_seed.py -v`
预期：FAIL，ModuleNotFoundError

- [ ] **步骤 3：实现种子服务与脚本**

```python
# backend/app/services/seed.py —— 种子业务也只走 repo，不直查 DB
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.org import Role
from app.repositories.base import BaseRepository

class RoleRepository(BaseRepository[Role]):
    model = Role

ROLES = [("member", "成员"), ("dept_owner", "部门负责人"), ("admin", "公司管理员")]

async def seed_roles(db: AsyncSession) -> None:
    roles = RoleRepository(db)
    for code, name in ROLES:
        if not await roles.get_by(code=code):
            await roles.add(Role(code=code, name=name))
    await roles.commit()
```

```python
# backend/scripts/seed.py
import asyncio
from app.core.database import SessionLocal
from app.services.seed import seed_roles

async def main():
    async with SessionLocal() as db:
        await seed_roles(db)
    print("seeded")

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_seed.py -v && python -m scripts.seed`
预期：PASS；输出 `seeded`

- [ ] **步骤 5：Commit**

```bash
git add backend/app/services backend/scripts backend/tests
git commit -m "feat: 种子数据（角色与默认 agent 配置）"
```

---

## 里程碑 M2：聊天核心链路（短期记忆）

### 任务 10：会话与消息 API（三层）

**文件：**
- 创建：`backend/app/repositories/conversation_repo.py`
- 创建：`backend/app/services/conversation_service.py`
- 创建：`backend/app/api/conversations.py`（薄层）、`backend/app/schemas/chat.py`
- 创建：`backend/tests/test_conversations_api.py`
- 修改：`backend/app/main.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_conversations_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_conversation_flow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "carol", "password": "x123456", "display_name": "Carol"})
        r = await c.post("/api/auth/login", json={"username": "carol", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/conversations", json={"title": "测试"}, headers=h)
        assert r.status_code == 200
        conv_id = r.json()["id"]
        r = await c.get(f"/api/conversations/{conv_id}/messages", headers=h)
        assert r.json() == []
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_conversations_api.py -v`
预期：FAIL，404

- [ ] **步骤 3：实现路由**

```python
# backend/app/schemas/chat.py
from pydantic import BaseModel
from datetime import datetime

class ConversationCreate(BaseModel):
    title: str = "新对话"

class ConversationOut(BaseModel):
    id: str
    title: str
    summary: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}

class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    model_config = {"from_attributes": True}
```

```python
# backend/app/repositories/conversation_repo.py
from sqlalchemy import select, func
from app.models.chat import Conversation, Message
from app.repositories.base import BaseRepository

class ConversationRepository(BaseRepository[Conversation]):
    model = Conversation

    async def list_by_user(self, user_id: str) -> list[Conversation]:
        return (await self.db.scalars(
            select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.created_at.desc())
        )).all()

class MessageRepository(BaseRepository[Message]):
    model = Message

    async def list_by_conversation(self, conversation_id: str) -> list[Message]:
        return (await self.db.scalars(
            select(Message).where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )).all()

    async def list_recent(self, conversation_id: str, limit: int = 20) -> list[Message]:
        return (await self.db.scalars(
            select(Message).where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc()).limit(limit)
        )).all()
```

```python
# backend/app/services/conversation_service.py
from fastapi import HTTPException
from app.models.chat import Conversation
from app.repositories.conversation_repo import ConversationRepository, MessageRepository

class ConversationService:
    def __init__(self, db):
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)

    async def create(self, user_id: str, title: str) -> Conversation:
        conv = Conversation(user_id=user_id, title=title)
        await self.conversation_repo.add(conv)
        await self.conversation_repo.commit()
        return conv

    async def list_by_user(self, user_id: str) -> list[Conversation]:
        return await self.conversation_repo.list_by_user(user_id)

    async def list_messages(self, user_id: str, conv_id: str):
        conv = await self.conversation_repo.get(conv_id)
        if not conv or conv.user_id != user_id:
            raise HTTPException(404, "会话不存在")
        return await self.message_repo.list_by_conversation(conv_id)
```

```python
# backend/app/api/conversations.py —— 薄路由
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.schemas.chat import ConversationCreate, ConversationOut, MessageOut
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

def get_conv_service(db: AsyncSession = Depends(get_db)) -> ConversationService:
    return ConversationService(db)

@router.post("", response_model=ConversationOut)
async def create_conversation(body: ConversationCreate, svc: ConversationService = Depends(get_conv_service), user: User = Depends(get_current_user)):
    return await svc.create(user.id, body.title)

@router.get("", response_model=list[ConversationOut])
async def list_conversations(svc: ConversationService = Depends(get_conv_service), user: User = Depends(get_current_user)):
    return await svc.list_by_user(user.id)

@router.get("/{conv_id}/messages", response_model=list[MessageOut])
async def list_messages(conv_id: str, svc: ConversationService = Depends(get_conv_service), user: User = Depends(get_current_user)):
    return await svc.list_messages(user.id, conv_id)
```

- [ ] **步骤 4：main.py 注册并运行测试**

运行：`cd backend && pytest tests/test_conversations_api.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 会话与消息 API"
```

---

### 任务 11：模型工厂 ModelFactory

**文件：**
- 创建：`backend/app/llm/factory.py`
- 创建：`backend/tests/test_factory.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_factory.py
import pytest
from app.llm.factory import ModelFactory

def test_get_llm_by_key():
    assert ModelFactory.get_llm("default") is not None

def test_get_embedding():
    assert ModelFactory.get_embedding() is not None
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_factory.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现工厂（OpenAI 兼容多模型映射）**

```python
# backend/app/llm/factory.py
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from app.core.config import settings

MODEL_MAP = {
    "default": "doubao-pro",
    "marketing": "doubao-pro",
    "sales_analysis": "deepseek-v3",
    "scheduling": "doubao-lite",
}

class ModelFactory:
    @classmethod
    def get_llm(cls, model_key: str = "default"):
        return ChatOpenAI(
            model=MODEL_MAP.get(model_key, MODEL_MAP["default"]),
            base_url=settings.MODEL_API_BASE,
            api_key=settings.MODEL_API_KEY,
            temperature=0.3,
        )

    @classmethod
    def get_embedding(cls):
        return OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            base_url=settings.MODEL_API_BASE,
            api_key=settings.MODEL_API_KEY,
        )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_factory.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: ModelFactory 多模型工厂"
```

---

### 任务 12：短期记忆读取（最近 N 轮 + 摘要）

**文件：**
- 创建：`backend/app/memory/short_term.py`
- 创建：`backend/tests/test_short_term.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_short_term.py
import pytest
from app.models.chat import Conversation, Message
from app.memory.short_term import build_context

@pytest.mark.asyncio
async def test_build_context_recent_n(db_session):
    conv = Conversation(user_id="u1", title="t")
    db_session.add(conv)
    await db_session.flush()
    for i in range(8):
        db_session.add(Message(conversation_id=conv.id, role="user" if i % 2 == 0 else "assistant", content=f"msg{i}"))
    await db_session.commit()
    context = await build_context(db_session, conv.id, recent_rounds=3)
    assert "msg7" in context
    assert "msg0" not in context
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_short_term.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现短期记忆读取**

```python
# backend/app/memory/short_term.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.conversation_repo import ConversationRepository, MessageRepository

async def build_context(db: AsyncSession, conversation_id: str, recent_rounds: int = 10) -> str:
    # 查询全部委托 repository，本层只做上下文拼装
    conv_repo = ConversationRepository(db)
    msg_repo = MessageRepository(db)
    conv = await conv_repo.get(conversation_id)
    if not conv:
        return ""
    msgs = await msg_repo.list_recent(conversation_id, recent_rounds * 2)
    msgs.reverse()
    lines = [f"{m.role}: {m.content}" for m in msgs]
    prefix = f"[历史摘要] {conv.summary}\n" if conv.summary else ""
    return prefix + "\n".join(lines)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_short_term.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 短期记忆读取（最近 N 轮+摘要）"
```

---

### 任务 13：滚动摘要（超出窗口 LLM 压缩）

**文件：**
- 创建：`backend/app/services/summary.py`
- 创建：`backend/tests/test_summary.py`

- [ ] **步骤 1：编写失败的测试（monkeypatch LLM）**

```python
# backend/tests/test_summary.py
import pytest
from app.services.summary import maybe_roll_summary

@pytest.mark.asyncio
async def test_maybe_roll_summary_updates(db_session, monkeypatch):
    from app.models.chat import Conversation
    conv = Conversation(user_id="u1", title="t", summary=None)
    db_session.add(conv)
    await db_session.commit()
    async def fake_summarize(text):
        return "压缩后的摘要"
    monkeypatch.setattr("app.services.summary.summarize_text", fake_summarize)
    await maybe_roll_summary(db_session, conv.id, force=True)
    await db_session.refresh(conv)
    assert conv.summary == "压缩后的摘要"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_summary.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现摘要服务**

```python
# backend/app/services/summary.py
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.conversation_repo import ConversationRepository, MessageRepository
from app.llm.factory import ModelFactory

class SummaryOutput(BaseModel):
    """对话摘要结构化输出"""
    summary: str = Field(description="简洁的中文摘要，保留关键决策、数字与结论")

async def summarize_text(messages_text: str) -> str:
    llm = ModelFactory.get_llm().with_structured_output(SummaryOutput)
    result = await llm.ainvoke(
        f"将以下对话压缩为简洁的中文摘要，保留关键决策、数字与结论：\n{messages_text}"
    )
    return result.summary

async def maybe_roll_summary(db: AsyncSession, conversation_id: str, force: bool = False, max_messages: int = 20) -> None:
    # 数据库操作委托 repository
    conv_repo = ConversationRepository(db)
    msg_repo = MessageRepository(db)
    conv = await conv_repo.get(conversation_id)
    count = await msg_repo.count(conversation_id=conversation_id)
    if not force and count < max_messages:
        return
    recent = await msg_repo.list_recent(conversation_id, 10)
    text = "\n".join(f"{m.role}: {m.content}" for m in reversed(recent))
    old = f"已有摘要：{conv.summary}\n" if conv.summary else ""
    conv.summary = await summarize_text(old + text)
    await conv_repo.commit()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_summary.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 对话滚动摘要"
```

---

### 任务 14：LangGraph 主图骨架 + SSE 流式聊天

**文件：**
- 创建：`backend/app/agents/state.py`、`backend/app/agents/graph.py`、`backend/app/agents/supervisor.py`
- 创建：`backend/app/api/chat.py`
- 创建：`backend/tests/test_chat_api.py`
- 修改：`backend/app/main.py`

- [ ] **步骤 1：编写失败的测试（先验证 SSE 接口可达）**

```python
# backend/tests/test_chat_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_chat_sse_streams():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "dave", "password": "x123456", "display_name": "Dave"})
        r = await c.post("/api/auth/login", json={"username": "dave", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/conversations", json={}, headers=h)
        conv_id = r.json()["id"]
        r = await c.post("/api/chat/completions",
                         json={"conversation_id": conv_id, "message": "你好"},
                         headers=h)
        assert r.status_code == 200
        assert "data:" in r.text
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_chat_api.py -v`
预期：FAIL，404

- [ ] **步骤 3：实现 AgentState 与主图骨架（echo 节点先行）**

```python
# backend/app/agents/state.py
from typing import Annotated, TypedDict
from operator import add
from langchain_core.messages import BaseMessage

class AgentState(TypedDict, total=False):
    conversation_id: str
    user_id: str
    user_message: str
    history: str
    memory_context: str          # 记忆装配结果
    messages: Annotated[list[BaseMessage], add]  # 子图 ReAct 循环的工作消息
    tool_rounds: Annotated[int, add]             # 子图工具调用轮次计数（防死循环）
    agent_response: str
    route_history: Annotated[list[str], add]  # 已路由过的 agent，防死循环
    pending_agent: str           # supervisor 本次路由目标
    approval_result: dict | None  # 审批结果（critical 工具调用恢复时携带）
    trace_id: str
```

```python
# backend/app/agents/graph.py
from langgraph.graph import StateGraph, END
from app.agents.state import AgentState

def build_graph():
    g = StateGraph(AgentState)

    async def echo_node(state: AgentState) -> dict:
        return {"agent_response": f"收到：{state.get('user_message', '')}"}

    g.add_node("echo", echo_node)
    g.set_entry_point("echo")
    g.add_edge("echo", END)
    return g.compile()

graph = build_graph()
```

- [ ] **步骤 4：实现 ChatService（业务层）与薄路由**

```python
# backend/app/services/chat_service.py
import json
from fastapi import HTTPException
from app.models.chat import Conversation, Message
from app.repositories.conversation_repo import ConversationRepository, MessageRepository
from app.agents.graph import graph

class ChatService:
    """聊天业务：校验归属 + 持久化消息 + 执行图 + 产出 SSE 事件（后续任务 15/30/35 在此扩展）。"""
    def __init__(self, db):
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)

    async def _ensure_owned(self, user_id: str, conv_id: str) -> Conversation:
        conv = await self.conversation_repo.get(conv_id)
        if not conv or conv.user_id != user_id:
            raise HTTPException(404, "会话不存在")
        return conv

    async def stream_chat(self, user_id: str, conv_id: str, message: str):
        """SSE 事件异步生成器：start → token → done。"""
        await self._ensure_owned(user_id, conv_id)
        await self.message_repo.add(Message(conversation_id=conv_id, role="user", content=message))
        await self.message_repo.commit()
        yield json.dumps({"event": "start"}, ensure_ascii=False)
        result = await graph.ainvoke({
            "conversation_id": conv_id, "user_id": user_id,
            "user_message": message, "messages": [],
        })
        text = result.get("agent_response", "")
        await self.message_repo.add(Message(conversation_id=conv_id, role="assistant", content=text))
        await self.message_repo.commit()
        yield json.dumps({"event": "token", "content": text}, ensure_ascii=False)
        yield json.dumps({"event": "done"}, ensure_ascii=False)
```

```python
# backend/app/api/chat.py —— 薄路由：只包装 SSE 流式响应
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.services.chat_service import ChatService

router = APIRouter(prefix="/api/chat", tags=["chat"])

class ChatRequest(BaseModel):
    conversation_id: str
    message: str

def get_chat_service(db: AsyncSession = Depends(get_db)) -> ChatService:
    return ChatService(db)

@router.post("/completions")
async def chat_completions(body: ChatRequest, svc: ChatService = Depends(get_chat_service), user: User = Depends(get_current_user)):
    async def event_stream():
        try:
            async for evt in svc.stream_chat(user.id, body.conversation_id, body.message):
                yield f"data: {evt}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'event': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **步骤 5：main.py 注册 chat 路由并运行测试**

运行：`cd backend && pytest tests/test_chat_api.py -v`
预期：PASS（`data:` 前缀存在）

- [ ] **步骤 6：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: LangGraph 主图骨架 + SSE 流式聊天"
```

---

### 任务 15：短期记忆接入聊天 + 消息持久化

**文件：**
- 修改：`backend/app/agents/graph.py`、`backend/app/api/chat.py`
- 创建：`backend/tests/test_chat_persist.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_chat_persist.py
import pytest
from sqlalchemy import select
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.chat import Message

@pytest.mark.asyncio
async def test_messages_persisted_after_chat(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "erin", "password": "x123456", "display_name": "Erin"})
        r = await c.post("/api/auth/login", json={"username": "erin", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/conversations", json={}, headers=h)
        conv_id = r.json()["id"]
        await c.post("/api/chat/completions", json={"conversation_id": conv_id, "message": "hello"}, headers=h)
    msgs = (await db_session.scalars(select(Message))).all()
    assert len(msgs) == 2  # user + assistant
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_chat_persist.py -v`
预期：FAIL，`len(msgs) == 0`

- [ ] **步骤 3：改造 ChatService：短期记忆装配 + 滚动摘要（router 保持薄层）**

```python
# backend/app/services/chat_service.py 关键改造
from app.memory.short_term import build_context
from app.services.summary import maybe_roll_summary

class ChatService:
    def __init__(self, db):
        self.db = db
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)

    async def stream_chat(self, user_id: str, conv_id: str, message: str):
        await self._ensure_owned(user_id, conv_id)
        await self.message_repo.add(Message(conversation_id=conv_id, role="user", content=message))
        await self.message_repo.commit()
        yield json.dumps({"event": "start"}, ensure_ascii=False)
        history = await build_context(self.db, conv_id, recent_rounds=10)  # 短期记忆装配
        result = await graph.ainvoke({
            "conversation_id": conv_id, "user_id": user_id,
            "user_message": message, "history": history, "messages": [],
        })
        text = result.get("agent_response", "")
        await self.message_repo.add(Message(conversation_id=conv_id, role="assistant", content=text))
        await self.message_repo.commit()
        await maybe_roll_summary(self.db, conv_id)  # 消息超阈值滚动摘要
        yield json.dumps({"event": "token", "content": text}, ensure_ascii=False)
        yield json.dumps({"event": "done"}, ensure_ascii=False)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_chat_persist.py tests/test_chat_api.py -v`
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 短期记忆接入聊天与消息持久化"
```

---

## 里程碑 M3：知识中心与偏好中心

### 任务 16：embedding 服务封装

**文件：**
- 创建：`backend/app/services/embedding.py`
- 创建：`backend/tests/test_embedding.py`

- [ ] **步骤 1：编写失败的测试（monkeypatch 向量调用）**

```python
# backend/tests/test_embedding.py
import pytest
from app.services.embedding import embed_texts

@pytest.mark.asyncio
async def test_embed_texts(monkeypatch):
    monkeypatch.setattr("app.services.embedding.ModelFactory.get_embedding", lambda: FakeEmb())
    vecs = await embed_texts(["hello", "world"])
    assert len(vecs) == 2 and len(vecs[0]) == 3

class FakeEmb:
    async def aembed_documents(self, texts):
        return [[1.0, 0.0, 0.0]] * len(texts)
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_embedding.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现 embedding 服务**

```python
# backend/app/services/embedding.py
from app.llm.factory import ModelFactory

async def embed_texts(texts: list[str]) -> list[list[float]]:
    emb = ModelFactory.get_embedding()
    return await emb.aembed_documents(texts)

async def embed_query(text: str) -> list[float]:
    emb = ModelFactory.get_embedding()
    return await emb.aembed_query(text)
```

> **Rerank 服务**：向量召回后再用 LLM 精排，提高检索准确率。在任务 16 之后新增。

```python
# backend/app/services/rerank.py
from pydantic import BaseModel, Field
from app.llm.factory import ModelFactory

class RerankItem(BaseModel):
    """单条候选相关性评分"""
    score: float = Field(description="相关性评分 0~1")
    reason: str = Field(description="评分理由")

class RerankOutput(BaseModel):
    """rerank 结构化输出"""
    items: list[RerankItem] = Field(description="与输入candidates顺序一致的评分列表")

async def rerank(query: str, candidates: list[str]) -> list[float]:
    """LLM 对每条候选打分，返回与 candidates 等长的分数列表（0~1，越高越相关）。
    两阶段检索：向量 over-fetch → rerank 精排 → 截断 top_k。"""
    if not candidates:
        return []
    llm = ModelFactory.get_llm().with_structured_output(RerankOutput)
    numbered = "\n".join(f"{i}. {c[:500]}" for i, c in enumerate(candidates))
    result = await llm.ainvoke(
        f"根据用户问题对以下候选内容逐一打分（0~1，越高越相关）。\n"
        f"问题：{query}\n候选：\n{numbered}"
    )
    return [item.score for item in result.items]
```

```python
# backend/tests/test_rerank.py
import pytest
from app.services.rerank import rerank, RerankOutput

@pytest.mark.asyncio
async def test_rerank_returns_scores(monkeypatch):
    class FakeLLM:
        def with_structured_output(self, schema):
            return self
        async def ainvoke(self, prompt):
            return RerankOutput(items=[
                RerankItem(score=0.9, reason="高度相关"),
                RerankItem(score=0.3, reason="弱相关"),
            ])
    monkeypatch.setattr("app.services.rerank.ModelFactory.get_llm", lambda: FakeLLM())
    scores = await rerank("国庆营销", ["国庆大促方案", "春节红包活动"])
    assert len(scores) == 2
    assert scores[0] > scores[1]

@pytest.mark.asyncio
async def test_rerank_empty():
    scores = await rerank("test", [])
    assert scores == []
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_embedding.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: embedding 服务封装"
```

---

### 任务 17：文档解析与切分（LangChain 现成组件）

> 切分直接用现成 `RecursiveCharacterTextSplitter`（按段落/句子边界递归切分，支持重叠），不手写字符切片。解析保留 pypdf / python-docx（与 langchain loader 底层同源，但免去文件路径接口，便于 bytes 流测试）；若文档为扫描件/图片 PDF，后续可再接入云文档智能 OCR API。

**文件：**
- 修改：`backend/pyproject.toml`（追加 `langchain-text-splitters>=0.2.0`）
- 创建：`backend/app/services/document_parser.py`
- 创建：`backend/tests/test_document_parser.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_document_parser.py
from app.services.document_parser import parse_text, split_chunks

def test_split_chunks_basic():
    text = "段落一。" * 200
    chunks = split_chunks(text, chunk_size=100)
    assert len(chunks) > 1
    assert "段落一" in chunks[0]

def test_short_text_not_split():
    chunks = split_chunks("简短文本", chunk_size=500)
    assert len(chunks) == 1

def test_parse_markdown():
    assert "标题" in parse_text("# 标题\n正文", "md")

def test_markdown_header_split():
    text = "# 第一章\n## 第一节\n内容A\n## 第二节\n内容B"
    chunks = split_chunks(text, ext="md")
    assert len(chunks) >= 2
    assert "第一章" in chunks[0]
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_document_parser.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现解析与切分（RecursiveCharacterTextSplitter + MarkdownHeaderTextSplitter）**

```python
# backend/app/services/document_parser.py
import io
from pypdf import PdfReader
from docx import Document as DocxDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter

def parse_text(content: bytes, ext: str) -> str:
    ext = ext.lower().lstrip(".")
    if ext == "pdf":
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    if ext in ("docx", "doc"):
        doc = DocxDocument(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)
    # md/txt：文本原样返回，标题结构由 split_chunks 按格式处理
    return content.decode("utf-8", errors="ignore")

def split_chunks(text: str, chunk_size: int = 500, overlap: int = 50, ext: str = "txt") -> list[str]:
    if ext in ("md", "markdown"):
        # Markdown 按标题层级切分，标题链作为上下文注入每个 chunk
        splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3")])
        docs = splitter.split_text(text)
        return [
            (" ".join(f"{k}: {v}" for k, v in d.metadata.items()) + "\n" + d.page_content) if d.metadata else d.page_content
            for d in docs
        ]
    # 其他格式按中文语义边界递归切分（优先段落/句子，退化为字符）
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
    )
    return splitter.split_text(text)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_document_parser.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 文档解析与切分"
```

---

### 任务 18：文档上传 API + 向量入库（三层）

**文件：**
- 创建：`backend/app/repositories/document_repo.py`
- 创建：`backend/app/services/knowledge_service.py`
- 创建：`backend/app/api/documents.py`（薄层）
- 创建：`backend/tests/test_documents_api.py`
- 修改：`backend/app/main.py`

- [ ] **步骤 1：编写失败的测试（用内存 mock 跳过真实 embedding）**

```python
# backend/tests/test_documents_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_upload_and_search(monkeypatch):
    async def fake_embed(texts):
        return [[0.1, 0.2, 0.3]] * len(texts)
    monkeypatch.setattr("app.services.knowledge_service.embed_texts", fake_embed)
    monkeypatch.setattr("app.services.knowledge_service.embed_query", lambda t: [0.1, 0.2, 0.3])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "frank", "password": "x123456", "display_name": "Frank"})
        r = await c.post("/api/auth/login", json={"username": "frank", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        files = {"file": ("制度.md", b"# 考勤制度\n迟到扣款 50 元", "text/markdown")}
        r = await c.post("/api/documents", files=files, headers=h)
        assert r.status_code == 200
        doc_id = r.json()["id"]
        r = await c.post("/api/kb/search", json={"query": "考勤"}, headers=h)
        assert r.status_code == 200
        assert len(r.json()["results"]) >= 1
        assert doc_id is not None
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_documents_api.py -v`
预期：FAIL，404

- [ ] **步骤 3：实现 Repository / Service / 薄路由三层**

```python
# backend/app/repositories/document_repo.py
from sqlalchemy.sql import text as sqltext
from app.models.knowledge import Document, Chunk
from app.repositories.base import BaseRepository

class DocumentRepository(BaseRepository[Document]):
    model = Document

class ChunkRepository(BaseRepository[Chunk]):
    model = Chunk

    async def vector_search(self, query_vec: list[float], top_k: int = 5) -> list[dict]:
        """pgvector 相似度检索（service/memory 层不再直接执行 SQL）。"""
        rows = (await self.db.execute(
            sqltext(
                "SELECT id, content, document_id, 1 - (embedding <=> :q) AS score "
                "FROM chunks WHERE embedding IS NOT NULL ORDER BY embedding <=> :q LIMIT :k"
            ),
            {"q": query_vec, "k": top_k},
        )).all()
        return [{"id": r.id, "content": r.content, "document_id": r.document_id, "score": round(r.score, 4)} for r in rows]
```

```python
# backend/app/services/knowledge_service.py
import os
from uuid import uuid4
from fastapi import HTTPException
from app.models.knowledge import Document, Chunk
from app.repositories.document_repo import DocumentRepository, ChunkRepository
from app.services.document_parser import parse_text, split_chunks
from app.services.embedding import embed_texts, embed_query

UPLOAD_DIR = "storage/documents"

class KnowledgeService:
    """知识库业务：上传→解析→切分→embedding→入库；语义检索。数据库操作全部委托 repository。"""
    def __init__(self, db):
        self.document_repo = DocumentRepository(db)
        self.chunk_repo = ChunkRepository(db)

    async def upload(self, uploader_id: str, filename: str, content: bytes) -> Document:
        ext = filename.rsplit(".", 1)[-1]
        doc_id = str(uuid4())
        path = os.path.join(UPLOAD_DIR, f"{doc_id}.{ext}")
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        doc = Document(id=doc_id, title=filename, file_path=path, status="parsing", uploader_id=uploader_id)
        await self.document_repo.add(doc)
        try:
            text = parse_text(content, ext)
            chunks = split_chunks(text, ext=ext)
            vecs = await embed_texts(chunks)
            await self.chunk_repo.add_all([
                Chunk(document_id=doc_id, seq=i, content=t, embedding=v)
                for i, (t, v) in enumerate(zip(chunks, vecs))
            ])
            doc.status = "ready"
            await self.document_repo.commit()
        except Exception as e:
            doc.status = "failed"
            await self.document_repo.commit()
            raise HTTPException(500, f"解析失败: {e}")
        return doc

    async def search(self, query: str, top_k: int = 5) -> dict:
        query_vec = await embed_query(query)
        return {"results": await self.chunk_repo.vector_search(query_vec, top_k)}
```

```python
# backend/app/api/documents.py —— 薄路由
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.services.knowledge_service import KnowledgeService

router = APIRouter(tags=["knowledge"])

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5

def get_knowledge_service(db: AsyncSession = Depends(get_db)) -> KnowledgeService:
    return KnowledgeService(db)

@router.post("/api/documents")
async def upload_document(file: UploadFile = File(...), svc: KnowledgeService = Depends(get_knowledge_service), user: User = Depends(get_current_user)):
    content = await file.read()
    return await svc.upload(user.id, file.filename, content)

@router.post("/api/kb/search")
async def search_kb(body: SearchRequest, svc: KnowledgeService = Depends(get_knowledge_service), _: User = Depends(get_current_user)):
    return await svc.search(body.query, body.top_k)
```

- [ ] **步骤 4：main.py 注册并运行测试**

运行：`cd backend && pytest tests/test_documents_api.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 文档上传与知识检索（RAG 入库）"
```

---

### 任务 19：知识检索装配（注入 prompt）

**文件：**
- 创建：`backend/app/memory/knowledge.py`
- 创建：`backend/tests/test_knowledge_assembly.py`

- [ ] **步骤 1：编写失败的测试（monkeypatch 检索）**

```python
# backend/tests/test_knowledge_assembly.py
import pytest
from app.memory.knowledge import retrieve_knowledge

@pytest.mark.asyncio
async def test_retrieve_knowledge_format(monkeypatch):
    async def fake_search(db, query, k):
        return [{"content": "迟到扣款 50 元", "document_id": "d1", "score": 0.9}]
    monkeypatch.setattr("app.memory.knowledge.search_chunks", fake_search)
    result = await retrieve_knowledge(None, "考勤规则", top_k=3)
    assert "迟到扣款" in result
    assert "d1" in result
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_knowledge_assembly.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现知识检索装配**

```python
# backend/app/memory/knowledge.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.document_repo import ChunkRepository
from app.services.embedding import embed_query
from app.services.rerank import rerank

async def search_chunks(db: AsyncSession, query: str, top_k: int = 5) -> list[dict]:
    # 两阶段检索：向量 over-fetch → rerank 精排 → 截断 top_k
    query_vec = await embed_query(query)
    hits = await ChunkRepository(db).vector_search(query_vec, top_k=20)  # over-fetch 20条
    if not hits:
        return []
    texts = [h["content"] for h in hits]
    scores = await rerank(query, texts)  # rerank 精排
    for i, h in enumerate(hits):
        h["score"] = scores[i]
    hits.sort(key=lambda x: -x["score"])
    return [{"id": h["id"], "content": h["content"], "document_id": h["document_id"]} for h in hits[:top_k]]

async def retrieve_knowledge(db: AsyncSession, query: str, top_k: int = 5) -> str:
    hits = await search_chunks(db, query, top_k)
    if not hits:
        return ""
    parts = [f"- [{h['document_id']}] {h['content']}" for h in hits]
    return "【知识库参考】\n" + "\n".join(parts)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_knowledge_assembly.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 知识检索装配"
```

---

### 任务 20：偏好提取与合并去重

**文件：**
- 创建：`backend/app/models/preferences.py`
- 创建：`backend/app/repositories/preference_repo.py`
- 创建：`backend/app/services/preference_svc.py`
- 创建：`backend/app/memory/preferences.py`
- 创建：`backend/tests/test_preferences.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_preferences.py
import pytest
from sqlalchemy import select
from app.models.preferences import Preference
from app.services.preference_svc import merge_preference

@pytest.mark.asyncio
async def test_merge_dedupe(db_session):
    await merge_preference(db_session, user_id="u1", category="style", content="回答简洁", confidence=0.8, source="s1")
    await merge_preference(db_session, user_id="u1", category="style", content="回答简洁", confidence=0.9, source="s2")
    rows = (await db_session.scalars(select(Preference).where(Preference.user_id == "u1"))).all()
    assert len(rows) == 1
    assert rows[0].confidence == 0.9
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_preferences.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现模型与偏好服务**

```python
# backend/app/models/preferences.py
from datetime import datetime
from uuid import uuid4
from sqlalchemy import UUID, DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class Preference(Base):
    __tablename__ = "preferences"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    category: Mapped[str] = mapped_column(String(16))  # style/decision/habit
    content: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    source: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

```python
# backend/app/repositories/preference_repo.py
from sqlalchemy import select
from app.models.preferences import Preference
from app.repositories.base import BaseRepository

class PreferenceRepository(BaseRepository[Preference]):
    model = Preference

    async def list_by_user(self, user_id: str) -> list[Preference]:
        return (await self.db.scalars(select(Preference).where(Preference.user_id == user_id))).all()

    async def merge(self, user_id: str, category: str, content: str, confidence: float, source: str) -> None:
        """相同 category+content 的偏好合并（取更高 confidence），只 flush 不 commit。"""
        existing = (await self.db.scalars(
            select(Preference).where(Preference.user_id == user_id, Preference.category == category, Preference.content == content)
        )).first()
        if existing:
            existing.confidence = max(existing.confidence, confidence)
        else:
            self.db.add(Preference(user_id=user_id, category=category, content=content, confidence=confidence, source=source))
        await self.db.flush()
```

```python
# backend/app/services/preference_svc.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.preference_repo import PreferenceRepository

async def merge_preference(db: AsyncSession, user_id: str, category: str, content: str, confidence: float, source: str) -> None:
    await PreferenceRepository(db).merge(user_id, category, content, confidence, source)
```

```python
# backend/app/services/preference_svc.py 追加：LLM 结构化提取
from typing import Literal
from pydantic import BaseModel, Field
from app.llm.factory import ModelFactory

class PreferenceItem(BaseModel):
    """单条用户偏好"""
    category: Literal["style", "decision", "habit"] = Field(description="偏好类别")
    content: str = Field(description="偏好描述")
    confidence: float = Field(description="置信度 0~1")

class PreferenceOutput(BaseModel):
    """用户偏好提取结果"""
    preferences: list[PreferenceItem] = Field(default_factory=list, description="提取到的偏好列表，没有则为空")

async def extract_preferences(text: str) -> list[PreferenceItem]:
    llm = ModelFactory.get_llm().with_structured_output(PreferenceOutput)
    result = await llm.ainvoke(
        f"你是用户偏好分析器。根据对话提取用户偏好，提取偏好类别（style/decision/habit）、"
        f"偏好内容和置信度。没有偏好时返回空列表。\n对话：{text}"
    )
    return result.preferences

async def extract_and_save(db: AsyncSession, user_id: str, text: str) -> None:
    repo = PreferenceRepository(db)
    prefs = await extract_preferences(text)
    for p in prefs:
        await repo.merge(user_id, p.category, p.content, p.confidence, "auto")
    if prefs:
        await repo.commit()
```

```python
# backend/app/memory/preferences.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.preference_repo import PreferenceRepository

async def build_context(db: AsyncSession, user_id: str) -> str:
    rows = await PreferenceRepository(db).list_by_user(user_id)
    if not rows:
        return ""
    parts = [f"- ({p.category}) {p.content}" for p in rows]
    return "【个人偏好】\n" + "\n".join(parts)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_preferences.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 偏好提取与合并去重"
```

---

## 里程碑 M4：经验中心

### 任务 21：经验提炼与个人层自动入库

**文件：**
- 创建：`backend/app/repositories/experience_repo.py`
- 创建：`backend/app/services/experience_svc.py`
- 创建：`backend/tests/test_experience_extract.py`

- [ ] **步骤 1：编写失败的测试（monkeypatch LLM 与 embedding）**

```python
# backend/tests/test_experience_extract.py
import pytest
from sqlalchemy import select
from app.models.experience import Experience
from app.services.experience_svc import distill_experience, save_personal_experience, DistillOutput

@pytest.mark.asyncio
async def test_distill_and_save(db_session, monkeypatch):
    class FakeLLM:
        def with_structured_output(self, schema):
            return self
        async def ainvoke(self, prompt):
            return DistillOutput(
                title="国庆大促", summary="满减+直播", content="详情",
                tags=["营销"], event_time="2025-10-01", result_metrics={"gmv": 320}
            )
    monkeypatch.setattr("app.services.experience_svc.ModelFactory.get_llm", lambda: FakeLLM())
    monkeypatch.setattr("app.services.experience_svc.embed_texts", lambda t: [[0.1, 0.2, 0.3]])

    exp = await distill_experience("用户：策划国庆营销方案\n助手：建议满减+直播", user_id="u1", trace_id="t1")
    assert exp is not None
    assert exp.title == "国庆大促"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_experience_extract.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现经验提炼服务与 Repository**

```python
# backend/app/repositories/experience_repo.py
from sqlalchemy.sql import text as sqltext
from app.models.experience import Experience
from app.repositories.base import BaseRepository

class ExperienceRepository(BaseRepository[Experience]):
    model = Experience

    async def vector_search(self, query_vec: list[float], limit: int = 30) -> list[Experience]:
        """按向量相似度召回候选经验（service/memory 层不直接执行 SQL）。"""
        rows = (await self.db.execute(
            sqltext("SELECT id FROM experiences WHERE embedding IS NOT NULL ORDER BY embedding <=> :q LIMIT :k"),
            {"q": query_vec, "k": limit},
        )).all()
        result = []
        for r in rows:
            obj = await self.get(r.id)
            if obj:
                result.append(obj)
        return result
```

```python
# backend/app/services/experience_svc.py
from datetime import date
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.experience import Experience
from app.repositories.experience_repo import ExperienceRepository
from app.services.embedding import embed_texts
from app.llm.factory import ModelFactory

class DistillOutput(BaseModel):
    """经验提炼结构化输出"""
    title: str | None = Field(default=None, description="标题，无价值时为 null")
    summary: str = Field(default="", description="要点摘要")
    content: str = Field(default="", description="完整决策过程")
    tags: list[str] = Field(default_factory=list, description="业务标签")
    event_time: date | None = Field(default=None, description="事件日期 YYYY-MM-DD，营销/策略类必填")
    result_metrics: dict | None = Field(default=None, description="效果指标，营销/策略类必填")

async def distill_experience(text: str, user_id: str, trace_id: str) -> Experience | None:
    llm = ModelFactory.get_llm().with_structured_output(DistillOutput)
    result = await llm.ainvoke(
        f"你是企业经验提炼器。从对话中提炼有价值的历史决策/策略/教训。"
        f"营销/策略类必须包含 event_time 和 result_metrics，否则视为无价值将 title 设为 null。\n对话：{text[:6000]}"
    )
    if not result.title:
        return None
    vec = (await embed_texts([f"{result.title} {result.summary}"]))[0]
    return Experience(
        owner_id=user_id, scope="personal", status="draft",
        title=result.title, summary=result.summary, content=result.content,
        tags=result.tags, event_time=result.event_time, result_metrics=result.result_metrics,
        source_trace_id=trace_id, embedding=vec,
    )

async def save_personal_experience(db: AsyncSession, exp: Experience) -> None:
    repo = ExperienceRepository(db)
    await repo.add(exp)
    await repo.commit()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_experience_extract.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 经验提炼与个人层自动入库"
```

---

### 任务 22：经验向量检索（含后处理加权）

**文件：**
- 创建：`backend/app/memory/experiences.py`
- 创建：`backend/tests/test_experience_retrieve.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_experience_retrieve.py
import pytest
from sqlalchemy import select
from app.models.experience import Experience
from app.memory.experiences import build_experience_context

@pytest.mark.asyncio
async def test_build_experience_context(db_session, monkeypatch):
    db_session.add(Experience(owner_id="u1", scope="personal", status="approved", title="国庆大促",
                              summary="满减+直播", event_time="2025-10-01", embedding=[0.1, 0.2, 0.3]))
    await db_session.commit()
    monkeypatch.setattr("app.memory.experiences.embed_query", lambda t: [0.1, 0.2, 0.3])
    monkeypatch.setattr("app.memory.experiences.rerank", lambda q, c: [0.9] * len(c))
    ctx = await build_experience_context(db_session, user_id="u1", department_id=None, query="国庆营销")
    assert "国庆大促" in ctx
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_experience_retrieve.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现经验检索（可见范围过滤 → rerank 精排 → 同期加权）**

```python
# backend/app/memory/experiences.py
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.experience_repo import ExperienceRepository
from app.services.embedding import embed_query
from app.services.rerank import rerank

async def build_experience_context(db: AsyncSession, user_id: str, department_id: str | None, query: str, top_k: int = 5) -> str:
    # 第1步：向量召回（over-fetch 30条候选）
    qv = await embed_query(query)
    candidates = await ExperienceRepository(db).vector_search(qv, 30)
    # 第2步：可见范围过滤（先过滤再 rerank，减少 LLM 打分数量）
    visible = []
    for exp in candidates:
        if exp.scope == "personal" and exp.owner_id != user_id:
            continue
        if exp.scope == "dept" and (department_id is None or exp.department_id != department_id):
            continue
        visible.append(exp)
    if not visible:
        return ""
    # 第3步：rerank 精排（LLM 对每条候选打分）
    texts = [f"{e.title} {e.summary}" for e in visible]
    scores = await rerank(query, texts)
    # 第4步：同期加权叠加
    now_month = datetime.now().month
    scored = []
    for i, exp in enumerate(visible):
        final = scores[i]
        if exp.event_time and exp.event_time.month == now_month:
            final += 0.1  # 同期加权（叠加在 rerank 分数上）
        scored.append((final, exp))
    scored.sort(key=lambda x: -x[0])  # 按最终分数降序
    selected = [e for _, e in scored[:top_k]]
    if not selected:
        return ""
    parts = [f"- [{e.scope}] {e.title}：{e.summary}（{e.event_time or '无日期'}）" for e in selected]
    return "【相关历史经验】\n" + "\n".join(parts)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_experience_retrieve.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 经验向量检索与加权"
```

---

### 任务 23：经验中心 API（三层：分层视图 + 提交审批）

**文件：**
- 修改：`backend/app/repositories/experience_repo.py`（追加 list_visible，任务 21 已建 ExperienceRepository）
- 创建：`backend/app/services/experience_service.py`
- 创建：`backend/app/api/experiences.py`（薄层）
- 创建：`backend/tests/test_experiences_api.py`
- 修改：`backend/app/main.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_experiences_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_submit_experience_for_approval(monkeypatch):
    monkeypatch.setattr("app.api.experiences.save_personal_experience", lambda db, e: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "gary", "password": "x123456", "display_name": "Gary"})
        r = await c.post("/api/auth/login", json={"username": "gary", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/experiences", json={
            "title": "国庆大促", "summary": "满减+直播", "content": "详情",
            "tags": ["营销"], "event_time": "2025-10-01", "result_metrics": {"gmv": 320},
        }, headers=h)
        assert r.status_code == 200
        exp_id = r.json()["id"]
        r = await c.post(f"/api/experiences/{exp_id}/submit", json={"to_scope": "dept"}, headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "pending"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_experiences_api.py -v`
预期：FAIL，404

- [ ] **步骤 3：实现经验路由**

```python
# backend/app/repositories/experience_repo.py 修改：ExperienceRepository 类内追加 list_visible（任务 21 已建类）
from sqlalchemy import select
from app.models.experience import Experience
from app.repositories.base import BaseRepository

async def list_visible(self, user_id: str, department_id: str | None) -> list[Experience]:
    """个人层本人 + 部门层同部门 + 公司层全员。"""
    return (await self.db.scalars(
        select(Experience).where(
            (Experience.owner_id == user_id)
            | (Experience.scope == "company")
            | ((Experience.scope == "dept") & (Experience.department_id == department_id))
        ).order_by(Experience.created_at.desc())
    )).all()

ExperienceRepository.list_visible = list_visible  # 类内追加
```

```python
# backend/app/services/experience_service.py
from fastapi import HTTPException
from app.models.experience import Experience
from app.models.trace import Approval
from app.repositories.experience_repo import ExperienceRepository
from app.repositories.trace_repo import ApprovalRepository
from app.services.embedding import embed_texts

class ExperienceService:
    def __init__(self, db):
        self.experience_repo = ExperienceRepository(db)
        self.approval_repo = ApprovalRepository(db)

    async def create(self, user_id: str, department_id: str | None, data) -> Experience:
        vec = (await embed_texts([f"{data.title} {data.summary}"]))[0]
        exp = Experience(owner_id=user_id, scope="personal", status="draft", title=data.title,
                         summary=data.summary, content=data.content, tags=data.tags,
                         event_time=data.event_time, result_metrics=data.result_metrics,
                         department_id=department_id, embedding=vec)
        await self.experience_repo.add(exp)
        await self.experience_repo.commit()
        return exp

    async def submit(self, user_id: str, exp_id: str, to_scope: str) -> Experience:
        exp = await self.experience_repo.get(exp_id)
        if not exp or exp.owner_id != user_id or exp.scope != "personal":
            raise HTTPException(404, "经验不存在或不可提交")
        if to_scope not in ("dept", "company"):
            raise HTTPException(400, "目标层级无效")
        exp.status = "pending"
        # 创建统一审批单（经验晋升，非阻塞）
        approver_role = "dept_owner" if to_scope == "dept" else "admin"
        await self.approval_repo.add(Approval(
            category="experience_promotion", mode="async",
            ref_type="experience", ref_id=exp.id,
            title=f"经验晋升：{exp.title}",
            context={"experience_id": exp.id, "from_scope": "personal", "to_scope": to_scope},
            status="pending", requester_id=user_id, approver_role=approver_role,
        ))
        await self.approval_repo.commit()
        return exp

    async def list_visible(self, user_id: str, department_id: str | None) -> list[Experience]:
        return await self.experience_repo.list_visible(user_id, department_id)
```

```python
# backend/app/api/experiences.py —— 薄路由
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.services.experience_svc import ExperienceService

router = APIRouter(prefix="/api/experiences", tags=["experiences"])


class ExperienceCreate(BaseModel):
    title: str
    summary: str
    content: str = ""
    tags: list[str] = []
    event_time: str | None = None
    result_metrics: dict | None = None


class SubmitRequest(BaseModel):
    to_scope: str  # dept/company


def get_exp_service(db: AsyncSession = Depends(get_db)) -> ExperienceService:
    return ExperienceService(db)


@router.post("")
async def create_experience(body: ExperienceCreate, svc: ExperienceService = Depends(get_exp_service),
                            user: User = Depends(get_current_user)):
    return await svc.create(user.id, user.department_id, body)


@router.post("/{exp_id}/submit")
async def submit_experience(exp_id: str, body: SubmitRequest, svc: ExperienceService = Depends(get_exp_service),
                            user: User = Depends(get_current_user)):
    return await svc.submit(user.id, exp_id, body.to_scope)


@router.get("")
async def list_experiences(svc: ExperienceService = Depends(get_exp_service), user: User = Depends(get_current_user)):
    rows = await svc.list_visible(user.id, user.department_id)
    return [{"id": e.id, "title": e.title, "scope": e.scope, "status": e.status, "summary": e.summary} for e in rows]
```

- [ ] **步骤 4：main.py 注册并运行测试**

运行：`cd backend && pytest tests/test_experiences_api.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 经验中心 API（分层视图+提交审批）"
```

---

### 任务 24：统一审批中心 API（三层：审批中心 + decide 分发）

> **统一审批中心：** 合并原 HITL 审批（任务 33）与经验审批。`approvals` 表通过 `category` 区分审批类型（tool_call / experience_promotion），`mode` 区分阻塞/非阻塞（sync/async）。`decide` 方法按 `category` 分发后处理：tool_call + sync → 恢复图执行；experience_promotion → 经验层级晋升。

**文件：**
- 创建：`backend/app/services/approval_service.py`
- 创建：`backend/app/api/approvals.py`（薄层）
- 创建：`backend/tests/test_approvals_api.py`
- 修改：`backend/app/main.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_approvals_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.experience import Experience
from app.models.trace import Approval

@pytest.mark.asyncio
async def test_approve_experience_promotion(db_session, monkeypatch):
    """经验晋升审批：通过后经验层级晋升。"""
    monkeypatch.setattr("app.services.experience_service.embed_texts", lambda t: [[0.1, 0.2, 0.3]])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "owner", "password": "x123456", "display_name": "Owner"})
        r = await c.post("/api/auth/login", json={"username": "owner", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        # 创建待审批经验
        r = await c.post("/api/experiences", json={"title": "t", "summary": "s"}, headers=h)
        exp_id = r.json()["id"]
        await c.post(f"/api/experiences/{exp_id}/submit", json={"to_scope": "dept"}, headers=h)
        # 审批中心查看待办
        r = await c.get("/api/approvals?status=pending", headers=h)
        assert len(r.json()) >= 1
        ap_id = r.json()[0]["id"]
        # 审批通过
        r = await c.post(f"/api/approvals/{ap_id}/decide", json={"approve": True, "comment": "ok"}, headers=h)
        assert r.status_code == 200
        exp = await db_session.get(Experience, exp_id)
        assert exp.scope == "dept" and exp.status == "approved"

@pytest.mark.asyncio
async def test_list_approvals_by_category(db_session):
    """按 category 筛选审批单。"""
    db_session.add(Approval(category="tool_call", risk="critical", mode="sync", ref_type="trace",
                            ref_id="t1", title="删除文件", status="pending", requester_id="u1"))
    db_session.add(Approval(category="experience_promotion", mode="async", ref_type="experience",
                            ref_id="e1", title="经验晋升", status="pending", requester_id="u2"))
    await db_session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "admin", "password": "x123456", "display_name": "Admin"})
        r = await c.post("/api/auth/login", json={"username": "admin", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.get("/api/approvals?status=pending&category=tool_call", headers=h)
        assert len(r.json()) == 1
        assert r.json()[0]["category"] == "tool_call"
        r = await c.get("/api/approvals?status=pending&category=experience_promotion", headers=h)
        assert len(r.json()) == 1
        assert r.json()[0]["category"] == "experience_promotion"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_approvals_api.py -v`
预期：FAIL，404

- [ ] **步骤 3：实现统一审批中心 Service + 路由**

```python
# backend/app/services/approval_service.py
from datetime import datetime, timezone
from fastapi import HTTPException
from app.models.trace import Approval
from app.repositories.trace_repo import ApprovalRepository, TraceRepository
from app.repositories.experience_repo import ExperienceRepository

class ApprovalService:
    """统一审批中心：列出待办 + decide 按 category 分发后处理。
    - tool_call + sync（critical 工具调用）：更新审批单状态 + 恢复图执行
    - experience_promotion（经验晋升）：更新审批单状态 + 经验层级晋升"""
    def __init__(self, db):
        self.approval_repo = ApprovalRepository(db)
        self.trace_repo = TraceRepository(db)
        self.experience_repo = ExperienceRepository(db)

    async def list_pending(self, category: str | None = None):
        rows = await self.approval_repo.list_pending(category)
        return [{"id": a.id, "category": a.category, "risk": a.risk, "mode": a.mode,
                 "title": a.title, "context": a.context, "requester_id": a.requester_id,
                 "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None} for a in rows]

    async def decide(self, approval_id: str, approver_id: str, approve: bool, comment: str = ""):
        ap = await self.approval_repo.get(approval_id)
        if not ap or ap.status != "pending":
            raise HTTPException(404, "审批单不存在或已处理")

        # 1. 更新审批单（公共逻辑）
        ap.status = "approved" if approve else "rejected"
        ap.approver_id = approver_id
        ap.comment = comment
        ap.decided_at = datetime.now(timezone.utc)
        await self.approval_repo.commit()

        # 2. 按 category 分发后处理
        if ap.category == "tool_call" and ap.mode == "sync":
            # critical 工具调用：恢复 LangGraph 图执行
            await self._resume_graph(ap.id, approve, ap.ref_id)
        elif ap.category == "experience_promotion":
            # 经验晋升：通过则层级晋升
            if approve:
                await self._promote_experience(ap.ref_id, ap.context.get("to_scope", "dept"))
        return {"ok": True}

    async def _resume_graph(self, approval_id: str, approved: bool, trace_id: str):
        """审批通过/驳回后恢复图执行。"""
        from langgraph.types import Command
        from app.agents.graph import graph
        trace = await self.trace_repo.get(trace_id)
        if trace and trace.conversation_id:
            config = {"configurable": {"thread_id": trace.conversation_id}}
            await graph.ainvoke(
                Command(resume={"approved": approved, "approval_id": approval_id}),
                config=config,
            )

    async def _promote_experience(self, experience_id: str, to_scope: str):
        """经验层级晋升。"""
        exp = await self.experience_repo.get(experience_id)
        if exp:
            exp.scope = to_scope
            exp.status = "approved"
            await self.experience_repo.commit()
```

```python
# backend/app/api/approvals.py —— 薄路由
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.services.approval_service import ApprovalService

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

class DecideRequest(BaseModel):
    approve: bool
    comment: str = ""

def get_approval_service(db: AsyncSession = Depends(get_db)) -> ApprovalService:
    return ApprovalService(db)

@router.get("")
async def list_approvals(
    status: str | None = Query(None),
    category: str | None = Query(None),
    svc: ApprovalService = Depends(get_approval_service),
    _: User = Depends(get_current_user),
):
    return await svc.list_pending(category)

@router.post("/{approval_id}/decide")
async def decide_approval(approval_id: str, body: DecideRequest, svc: ApprovalService = Depends(get_approval_service), user: User = Depends(get_current_user)):
    return await svc.decide(approval_id, user.id, body.approve, body.comment)
```

- [ ] **步骤 4：main.py 注册并运行测试**

运行：`cd backend && pytest tests/test_approvals_api.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 统一审批中心（tool_call + experience_promotion）"
```

---

## 里程碑 M4.5：记忆统一装配

### 任务 25：MemoryAssembly 统一装配

**文件：**
- 创建：`backend/app/memory/assembly.py`
- 创建：`backend/tests/test_assembly.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_assembly.py
import pytest
from app.memory.assembly import assemble_memory

@pytest.mark.asyncio
async def test_assembly_sections(monkeypatch):
    monkeypatch.setattr("app.memory.assembly.build_context", lambda db, cid, **k: "[短期]")
    monkeypatch.setattr("app.memory.assembly.build_pref_context", lambda db, uid: "[偏好]")
    monkeypatch.setattr("app.memory.assembly.build_experience_context", lambda db, uid, dept, q: "[经验]")
    monkeypatch.setattr("app.memory.assembly.retrieve_knowledge", lambda db, q: "[知识]")
    ctx = await assemble_memory(None, user_id="u1", conversation_id="c1", department_id="d1", query="国庆营销")
    assert "短期" in ctx and "偏好" in ctx and "经验" in ctx and "知识" in ctx
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_assembly.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现统一装配**

```python
# backend/app/memory/assembly.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.memory import short_term, preferences as pref_mem, experiences as exp_mem, knowledge

async def assemble_memory(
    db: AsyncSession, user_id: str, conversation_id: str,
    department_id: str | None, query: str,
) -> str:
    sections = []
    sections.append(await short_term.build_context(db, conversation_id))
    sections.append(await pref_mem.build_context(db, user_id))
    sections.append(await exp_mem.build_experience_context(db, user_id, department_id, query))
    sections.append(await knowledge.retrieve_knowledge(db, query))
    return "\n\n".join(s for s in sections if s)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_assembly.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: MemoryAssembly 四层记忆统一装配"
```

---

## 里程碑 M5：完整 Agent 编排

### 任务 26：Supervisor 循环路由

**文件：**
- 修改：`backend/app/agents/supervisor.py`、`backend/app/agents/graph.py`
- 创建：`backend/tests/test_supervisor.py`

- [ ] **步骤 1：编写失败的测试（monkeypatch LLM 路由）**

```python
# backend/tests/test_supervisor.py
import pytest
from app.agents.supervisor import route_decision, RouteDecision, ROUTE_SCHEMA

def test_route_schema_fields():
    assert {"agent", "reason", "confidence"} <= set(ROUTE_SCHEMA["properties"].keys())

@pytest.mark.asyncio
async def test_route_decision_parses(monkeypatch):
    class FakeLLM:
        def with_structured_output(self, schema):
            return self
        async def ainvoke(self, prompt):
            return RouteDecision(agent="marketing", reason="营销策划", confidence=0.9)
    monkeypatch.setattr("app.agents.supervisor.ModelFactory.get_llm", lambda k: FakeLLM())
    decision = await route_decision("策划国庆营销方案", ["marketing", "sales_analysis", "scheduling", "done"])
    assert decision["agent"] == "marketing"

@pytest.mark.asyncio
async def test_route_decision_done(monkeypatch):
    """验证 supervisor 可返回 done 终止循环。"""
    class FakeLLM:
        def with_structured_output(self, schema):
            return self
        async def ainvoke(self, prompt):
            return RouteDecision(agent="done", reason="任务已完成", confidence=0.95)
    monkeypatch.setattr("app.agents.supervisor.ModelFactory.get_llm", lambda k: FakeLLM())
    decision = await route_decision("已完成", ["marketing", "sales_analysis", "scheduling", "done"])
    assert decision["agent"] == "done"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_supervisor.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现 Supervisor 路由**

```python
# backend/app/agents/supervisor.py
from pydantic import BaseModel, Field
from app.llm.factory import ModelFactory

class RouteDecision(BaseModel):
    """意图路由结构化输出。agent 可选：注册的 agent 代码 + done（终止循环）。"""
    agent: str = Field(description="目标 agent 编码，从可选列表中选择；任务完成时返回 done")
    reason: str = Field(description="路由理由")
    confidence: float = Field(description="置信度 0~1")

ROUTE_SCHEMA = RouteDecision.model_json_schema()
AGENT_CODES = ["marketing", "sales_analysis", "scheduling", "general"]

async def route_decision(message: str, agents: list[str], model_key: str = "default") -> dict:
    """LLM 判断目标 agent，可选列表包含所有注册的 agent + done。
    agent 完成后再次调用此函数决定是否需要其他 agent 协作或结束。"""
    llm = ModelFactory.get_llm(model_key).with_structured_output(RouteDecision)
    try:
        result = await llm.ainvoke(
            f"你是意图路由器。根据用户消息和对话历史，判断下一步交给哪个 agent，"
            f"可选：{agents}。如果任务已完成，返回 done。\n消息：{message}"
        )
        data = result.model_dump()
    except Exception:
        return {"agent": "done", "reason": "解析失败，默认结束", "confidence": 0.1}
    if data.get("agent") not in agents:
        data["agent"] = "done"
    return data
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_supervisor.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: Supervisor 循环路由（支持 done 终止）"
```

---

### 任务 26.5：DataFacade 基础门面 + Mock 内置工具

> **目标：** 在 agent 子图（任务 27/28）之前提供可用的工具门面和 Mock 工具，确保 agent 能直接加载工具进行 ReAct 循环。本阶段只实现基础门面（注册、获取、转 LangChain Tool）和 Mock 工具；**风险分级包装、MCP 工具加载在任务 31 中增强。**

**文件：**
- 创建：`backend/app/tools/facade.py`
- 创建：`backend/app/tools/builtin/__init__.py`
- 创建：`backend/app/tools/builtin/query_sales_data.py`、`query_marketing_campaigns.py`、`query_schedule.py`、`create_marketing_campaign.py`、`adjust_schedule.py`、`publish_campaign.py`、`delete_order.py`
- 创建：`backend/tests/test_facade.py`

- [ ] **步骤 1：编写失败的测试**

```python
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
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_facade.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现基础门面 + Mock 工具**

```python
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
```

```python
# backend/app/tools/builtin/query_sales_data.py
"""Mock 工具：查询销售指标。不连真实数据库，返回固定 mock 数据。"""
from pydantic import BaseModel, Field

class QuerySalesDataArgs(BaseModel):
    metric: str = Field(description="指标类型：revenue（营收）/ orders（订单量）/ customers（客户数）")
    period: str = Field(description="时间范围：7d / 30d / 90d")

DESCRIPTION = "查询企业销售指标（营收/订单/客户）。返回指定时间范围的汇总数据与环比变化。供经营分析 agent 使用。"

def query_sales_data(metric: str, period: str) -> dict:
    base = {"revenue": 1280000, "orders": 3420, "customers": 856}
    factor = {"7d": 0.25, "30d": 1.0, "90d": 2.8}[period]
    total = int(base[metric] * factor)
    return {"metric": metric, "period": period, "total": total,
            "prev_period": int(total * 0.92), "change_pct": 8.7}

# backend/app/tools/builtin/query_marketing_campaigns.py
from pydantic import BaseModel, Field

class QueryMarketingCampaignsArgs(BaseModel):
    status: str = Field(description="活动状态：active（进行中）/ scheduled（待发布）/ ended（已结束）")

DESCRIPTION = "查询营销活动列表。返回活动的名称、渠道、预算、状态等概要信息。供营销助手 agent 使用。"

def query_marketing_campaigns(status: str) -> list[dict]:
    all_campaigns = [
        {"id": "C001", "name": "618大促", "channel": "全渠道", "budget": 50000, "status": "ended"},
        {"id": "C002", "name": "会员日营销", "channel": "短信+邮件", "budget": 12000, "status": "active"},
        {"id": "C003", "name": "新品预热", "channel": "社交媒体", "budget": 28000, "status": "scheduled"},
        {"id": "C004", "name": "老客回流", "channel": "推送", "budget": 8000, "status": "active"},
    ]
    return [c for c in all_campaigns if c["status"] == status]

# backend/app/tools/builtin/query_schedule.py
from pydantic import BaseModel, Field

class QueryScheduleArgs(BaseModel):
    department: str = Field(description="部门名称，如 '仓储部' / '配送部' / '客服部'")
    date: str = Field(description="查询日期，格式 YYYY-MM-DD")

DESCRIPTION = "查询指定部门某天的排班情况。返回班次、人员、时间段等信息。供调度优化 agent 使用。"

def query_schedule(department: str, date: str) -> list[dict]:
    return [
        {"shift_id": "S001", "employee": "张三", "time": "08:00-16:00", "role": "早班", "department": department},
        {"shift_id": "S002", "employee": "李四", "time": "16:00-24:00", "role": "晚班", "department": department},
        {"shift_id": "S003", "employee": "王五", "time": "08:00-16:00", "role": "早班", "department": department},
    ]

# backend/app/tools/builtin/create_marketing_campaign.py
from pydantic import BaseModel, Field

class CreateMarketingCampaignArgs(BaseModel):
    name: str = Field(description="活动名称")
    budget: float = Field(description="预算金额（元）")
    channel: str = Field(description="投放渠道")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")

DESCRIPTION = "创建新的营销活动。Mock 返回创建结果，不写真实数据库。"

def create_marketing_campaign(name: str, budget: float, channel: str, start_date: str, end_date: str) -> dict:
    return {"campaign_id": f"C{int(budget):05d}", "name": name, "budget": budget,
            "channel": channel, "start_date": start_date, "end_date": end_date, "status": "created"}

# backend/app/tools/builtin/adjust_schedule.py
from pydantic import BaseModel, Field

class AdjustScheduleArgs(BaseModel):
    shift_id: str = Field(description="要调整的班次 ID")
    employee_id: str = Field(description="员工 ID")
    new_date: str = Field(description="调整后的日期 YYYY-MM-DD")
    new_time: str = Field(description="调整后的时间段，如 '08:00-16:00'")

DESCRIPTION = "调整员工排班班次。Mock 返回调整结果，不写真实数据库。"

def adjust_schedule(shift_id: str, employee_id: str, new_date: str, new_time: str) -> dict:
    return {"shift_id": shift_id, "employee_id": employee_id,
            "new_date": new_date, "new_time": new_time, "status": "adjusted"}

# backend/app/tools/builtin/publish_campaign.py
from pydantic import BaseModel, Field

class PublishCampaignArgs(BaseModel):
    campaign_id: str = Field(description="要发布的活动 ID")
    channels: list[str] = Field(description="发布渠道列表")

DESCRIPTION = "正式发布营销活动到指定渠道。Mock 返回发布结果。"

def publish_campaign(campaign_id: str, channels: list[str]) -> dict:
    return {"campaign_id": campaign_id, "channels": channels,
            "status": "published", "published_at": "2026-08-01T10:00:00Z"}

# backend/app/tools/builtin/delete_order.py
from pydantic import BaseModel, Field

class DeleteOrderArgs(BaseModel):
    order_id: str = Field(description="要删除的订单 ID")
    reason: str = Field(description="删除原因")

DESCRIPTION = "删除指定订单。Mock 返回删除结果。"

def delete_order(order_id: str, reason: str) -> dict:
    return {"order_id": order_id, "reason": reason, "status": "deleted"}
```

```python
# backend/app/tools/builtin/__init__.py
from app.tools.facade import DataFacade, Tool
from app.tools.builtin.query_sales_data import QuerySalesDataArgs, query_sales_data, DESCRIPTION as QUERY_SALES_DESC
from app.tools.builtin.query_marketing_campaigns import QueryMarketingCampaignsArgs, query_marketing_campaigns, DESCRIPTION as QUERY_CAMP_DESC
from app.tools.builtin.query_schedule import QueryScheduleArgs, query_schedule, DESCRIPTION as QUERY_SCHED_DESC
from app.tools.builtin.create_marketing_campaign import CreateMarketingCampaignArgs, create_marketing_campaign, DESCRIPTION as CREATE_CAMP_DESC
from app.tools.builtin.adjust_schedule import AdjustScheduleArgs, adjust_schedule, DESCRIPTION as ADJUST_SCHED_DESC
from app.tools.builtin.publish_campaign import PublishCampaignArgs, publish_campaign, DESCRIPTION as PUBLISH_CAMP_DESC
from app.tools.builtin.delete_order import DeleteOrderArgs, delete_order, DESCRIPTION as DELETE_ORDER_DESC

def register_builtin_tools(f: DataFacade) -> None:
    # risk 字段先声明，任务 31 增强时用于风险分级包装
    f.register(Tool("query_sales_data", query_sales_data, "low", QUERY_SALES_DESC, QuerySalesDataArgs))
    f.register(Tool("query_marketing_campaigns", query_marketing_campaigns, "low", QUERY_CAMP_DESC, QueryMarketingCampaignsArgs))
    f.register(Tool("query_schedule", query_schedule, "low", QUERY_SCHED_DESC, QueryScheduleArgs))
    f.register(Tool("create_marketing_campaign", create_marketing_campaign, "high", CREATE_CAMP_DESC, CreateMarketingCampaignArgs))
    f.register(Tool("adjust_schedule", adjust_schedule, "high", ADJUST_SCHED_DESC, AdjustScheduleArgs))
    f.register(Tool("publish_campaign", publish_campaign, "critical", PUBLISH_CAMP_DESC, PublishCampaignArgs))
    f.register(Tool("delete_order", delete_order, "critical", DELETE_ORDER_DESC, DeleteOrderArgs))
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_facade.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: DataFacade 基础门面 + Mock 内置工具"
```

---

### 任务 27：营销助手 agent 子图

**文件：**
- 创建：`backend/app/agents/marketing/agent.py`
- 创建：`backend/tests/test_marketing_agent.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_marketing_agent.py
import pytest
from langchain_core.messages import AIMessage
from app.agents.marketing.agent import build_marketing_agent, TOOL_NAMES, MAX_TOOL_ROUNDS

@pytest.mark.asyncio
async def test_marketing_agent_subgraph():
    """营销助手模块声明自己的工具并构建编译子图（供父图嵌入）。"""
    assert TOOL_NAMES == ["query_marketing_campaigns", "create_marketing_campaign", "publish_campaign"]
    assert await build_marketing_agent() is not None

@pytest.mark.asyncio
async def test_marketing_subgraph_stops_after_max_rounds(monkeypatch):
    """LLM 持续要求调用工具时，子图在 MAX_TOOL_ROUNDS 后强制结束，不抛异常。"""
    class LoopLLM:
        def bind_tools(self, tools):
            return self
        async def ainvoke(self, messages):
            return AIMessage(content="", tool_calls=[{
                "name": "query_marketing_campaigns", "args": {"status": "active"}, "id": f"c{len(messages)}", "type": "tool_call",
            }])

    monkeypatch.setattr("app.agents.marketing.agent.ModelFactory.get_llm", lambda k: LoopLLM())
    g = await build_marketing_agent()
    result = await g.ainvoke({"user_message": "循环", "memory_context": "", "messages": []})
    assert result["tool_rounds"] == MAX_TOOL_ROUNDS  # 达到上限强制结束
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_marketing_agent.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现营销助手子图（声明工具 + 构建 ReAct 子图）**

> 子图在营销助手模块内部直接构建（agent 节点 + ToolNode + 路由），后续可差异化演进；工具经 `facade.to_langchain_tool` 获得（任务 26.5 已实现基础门面）。

```python
# backend/app/agents/marketing/agent.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from app.llm.factory import ModelFactory
from app.tools.facade import facade
from app.agents.state import AgentState

SYSTEM_PROMPT = (
    "你是营销助手。结合【记忆上下文】中的个人偏好、历史经验、知识库与企业数据，"
    "为用户策划营销方案。营销策略需包含目标、渠道、预算、预期效果。回答用中文。"
)

# 营销助手声明自己需要的内置工具（工具在任务 26.5 注册到 facade）
# MCP 服务绑定待任务 38.5 动态化后由 load_tools 统一加载
TOOL_NAMES = ["query_marketing_campaigns", "create_marketing_campaign", "publish_campaign"]

MAX_TOOL_ROUNDS = 6  # 工具调用最大轮次，防 LLM 死循环（每子 agent 可配置不同值）

async def build_marketing_agent():
    """营销助手子图：agent ↔ ToolNode 的 ReAct 循环，编译后作为节点嵌入父图。
    子图在模块内部独立构建，后续可差异化演进（换节点、加记忆节点、改路由等）。"""
    tools = [facade.to_langchain_tool(n) for n in TOOL_NAMES]

    async def agent_node(state: AgentState) -> dict:
        llm = ModelFactory.get_llm("marketing").bind_tools(tools)
        msgs = [
            SystemMessage(SYSTEM_PROMPT + "\n" + state.get("memory_context", "")),
            HumanMessage(state.get("user_message", "")),
        ] + state.get("messages", [])
        resp = await llm.ainvoke(msgs)
        return {"messages": [resp], "tool_rounds": 1}  # add reducer 自动累加

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return "end"
        # 达到最大轮次即使仍要调工具也强制结束，防死循环
        return "tools" if state.get("tool_rounds", 0) < MAX_TOOL_ROUNDS else "end"

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(tools))
    g.set_entry_point("agent")
    g.add_edge("tools", "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    return g.compile()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_marketing_agent.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 营销助手 agent 子图"
```

---

### 任务 28：经营分析 / 调度优化 agent 子图

**文件：**
- 创建：`backend/app/agents/sales_analysis/agent.py`、`backend/app/agents/scheduling/agent.py`
- 创建：`backend/tests/test_agents_extra.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_agents_extra.py
import pytest
from langchain_core.messages import AIMessage
from app.agents.sales_analysis.agent import build_sales_agent, TOOL_NAMES as SALES_TOOLS, MAX_TOOL_ROUNDS
from app.agents.scheduling.agent import build_scheduling_agent, TOOL_NAMES as SCHEDULING_TOOLS

@pytest.mark.asyncio
async def test_sales_agent_subgraph():
    assert SALES_TOOLS == ["query_sales_data", "delete_order"]
    assert await build_sales_agent() is not None

@pytest.mark.asyncio
async def test_scheduling_agent_subgraph():
    assert SCHEDULING_TOOLS == ["query_schedule", "adjust_schedule"]
    assert await build_scheduling_agent() is not None

@pytest.mark.asyncio
async def test_sales_subgraph_stops_after_max_rounds(monkeypatch):
    """经营分析子图同样具备工具轮次上限保护。"""
    class LoopLLM:
        def bind_tools(self, tools):
            return self
        async def ainvoke(self, messages):
            return AIMessage(content="", tool_calls=[{
                "name": "query_sales_data", "args": {"metric": "revenue", "period": "7d"}, "id": f"c{len(messages)}", "type": "tool_call",
            }])

    monkeypatch.setattr("app.agents.sales_analysis.agent.ModelFactory.get_llm", lambda k: LoopLLM())
    g = await build_sales_agent()
    result = await g.ainvoke({"user_message": "循环", "memory_context": "", "messages": []})
    assert result["tool_rounds"] == MAX_TOOL_ROUNDS
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_agents_extra.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现两个 agent 节点**

```python
# backend/app/agents/sales_analysis/agent.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from app.llm.factory import ModelFactory
from app.tools.facade import facade
from app.agents.state import AgentState

SYSTEM_PROMPT = (
    "你是经营分析专家。结合记忆上下文与企业数据（可调用 query_sales_data 查询销售指标），"
    "给出量化分析结论，指出趋势与风险。回答用中文。"
)

# 经营分析声明自己需要的内置工具
# MCP 服务绑定待任务 38.5 动态化后由 load_tools 统一加载
TOOL_NAMES = ["query_sales_data", "delete_order"]

MAX_TOOL_ROUNDS = 6  # 工具调用最大轮次，防 LLM 死循环

async def build_sales_agent():
    """经营分析子图：agent ↔ ToolNode 的 ReAct 循环，编译后作为节点嵌入父图。
    子图在模块内部独立构建，后续可差异化演进。"""
    # 本阶段仅加载内置工具；MCP 待任务 37/38 接入后改为 load_tools(db, ...)
    tools = [facade.to_langchain_tool(n) for n in TOOL_NAMES]

    async def agent_node(state: AgentState) -> dict:
        llm = ModelFactory.get_llm("sales_analysis").bind_tools(tools)
        msgs = [
            SystemMessage(SYSTEM_PROMPT + "\n" + state.get("memory_context", "")),
            HumanMessage(state.get("user_message", "")),
        ] + state.get("messages", [])
        resp = await llm.ainvoke(msgs)
        return {"messages": [resp], "tool_rounds": 1}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return "end"
        return "tools" if state.get("tool_rounds", 0) < MAX_TOOL_ROUNDS else "end"

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(tools))
    g.set_entry_point("agent")
    g.add_edge("tools", "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    return g.compile()
```

```python
# backend/app/agents/scheduling/agent.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from app.llm.factory import ModelFactory
from app.tools.facade import facade
from app.agents.state import AgentState

SYSTEM_PROMPT = (
    "你是调度优化专家。结合记忆上下文与资源约束，给出排期/调度优化建议，"
    "包含时间线、资源分配、风险点。回答用中文。"
)

# 调度优化声明自己需要的内置工具
# MCP 服务绑定待任务 38.5 动态化后由 load_tools 统一加载
TOOL_NAMES = ["query_schedule", "adjust_schedule"]

MAX_TOOL_ROUNDS = 6  # 工具调用最大轮次，防 LLM 死循环

async def build_scheduling_agent():
    """调度优化子图：agent ↔ ToolNode 的 ReAct 循环，编译后作为节点嵌入父图。
    子图在模块内部独立构建，后续可差异化演进。"""
    # 本阶段仅加载内置工具；MCP 待任务 37/38 接入后改为 load_tools(db, ...)
    tools = [facade.to_langchain_tool(n) for n in TOOL_NAMES]

    async def agent_node(state: AgentState) -> dict:
        llm = ModelFactory.get_llm("scheduling").bind_tools(tools)
        msgs = [
            SystemMessage(SYSTEM_PROMPT + "\n" + state.get("memory_context", "")),
            HumanMessage(state.get("user_message", "")),
        ] + state.get("messages", [])
        resp = await llm.ainvoke(msgs)
        return {"messages": [resp], "tool_rounds": 1}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return "end"
        return "tools" if state.get("tool_rounds", 0) < MAX_TOOL_ROUNDS else "end"

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(tools))
    g.set_entry_point("agent")
    g.add_edge("tools", "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    return g.compile()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_agents_extra.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 经营分析与调度优化 agent 子图"
```

---

### 任务 29：AgentRegistry 动态注册 + 主图装配（Supervisor 多轮循环）

**文件：**
- 创建：`backend/app/agents/registry.py`
- 修改：`backend/app/agents/graph.py`
- 创建：`backend/tests/test_registry.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_registry.py
import pytest
from app.agents.registry import AgentRegistry

def test_register_and_list():
    reg = AgentRegistry()
    reg.register("marketing", lambda s: {"agent_response": "m"})
    reg.register("sales_analysis", lambda s: {"agent_response": "s"})
    assert set(reg.list()) == {"marketing", "sales_analysis"}

@pytest.mark.asyncio
async def test_multi_round_loop(monkeypatch):
    """验证 supervisor 多轮循环：agent 完成后回到 supervisor，直到 done。"""
    from app.agents.graph import build_graph
    from app.agents.registry import AgentRegistry

    # 模拟 route_decision：先选 marketing，再选 done
    decisions = iter([
        {"agent": "marketing", "reason": "营销分析", "confidence": 0.9},
        {"agent": "done", "reason": "任务完成", "confidence": 0.95},
    ])

    async def fake_route(message, agents):
        return next(decisions)

    monkeypatch.setattr("app.agents.graph.route_decision", fake_route)

    reg = AgentRegistry()
    reg.register("marketing", lambda s: {"agent_response": "营销结果"})
    reg.register("sales_analysis", lambda s: {"agent_response": "分析结果"})

    g = build_graph(reg)
    result = await g.ainvoke({
        "user_message": "帮我做营销分析",
        "pending_agent": "", "route_history": [], "messages": [],
    })
    assert result["agent_response"] == "营销结果"
    assert len(result["route_history"]) == 2  # marketing + done
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_registry.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现注册中心并装配主图（Supervisor 多轮循环）**

```python
# backend/app/agents/registry.py
from collections.abc import Callable
from typing import Any

class AgentRegistry:
    def __init__(self):
        self._nodes: dict[str, Callable[..., Any]] = {}

    def register(self, code: str, node: Callable[..., Any]) -> None:
        self._nodes[code] = node

    def get(self, code: str) -> Callable[..., Any]:
        return self._nodes[code]

    def list(self) -> list[str]:
        return list(self._nodes.keys())
```

```python
# backend/app/agents/graph.py 重写：Supervisor 多轮循环主图，子 agent 子图作为节点嵌入
import asyncio
from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.registry import AgentRegistry
from app.agents.supervisor import route_decision
from app.agents.marketing.agent import build_marketing_agent
from app.agents.sales_analysis.agent import build_sales_agent
from app.agents.scheduling.agent import build_scheduling_agent

MAX_ROUTES = 4  # 循环上限，防死循环

async def _build_registry() -> AgentRegistry:
    """异步构建注册中心：子 agent 构建时需动态加载 MCP 工具（远端 HTTP 调用）。"""
    registry = AgentRegistry()
    registry.register("marketing", await build_marketing_agent())       # 编译后的子图直接作节点
    registry.register("sales_analysis", await build_sales_agent())
    registry.register("scheduling", await build_scheduling_agent())
    return registry

def build_graph(registry: AgentRegistry):
    """根据已构建的注册中心装配主图。

    流程：supervisor(意图识别) → agent(执行) → supervisor(再判断) → ... → done
    agent 完成后回到 supervisor，由 supervisor 决定是否继续路由其他 agent 或结束。
    """
    g = StateGraph(AgentState)

    async def supervisor_node(state: AgentState) -> dict:
        # 可选列表 = 所有注册的 agent + done（终止循环）
        agents_with_done = registry.list() + ["done"]
        # 拼接上下文：用户消息 + 已有对话历史（供 LLM 判断是否完成）
        context = state.get("user_message", "")
        msgs = state.get("messages", [])
        if msgs:
            last_msg = msgs[-1].content if hasattr(msgs[-1], "content") else str(msgs[-1])
            context += f"\n\n上一轮 agent 输出：{last_msg}"
        decision = await route_decision(context, agents_with_done)
        return {"pending_agent": decision["agent"], "route_history": [decision["agent"]]}

    def router(state: AgentState) -> str:
        agent = state.get("pending_agent", "done")
        # 循环超限 → 强制结束
        if len(state.get("route_history", [])) >= MAX_ROUTES:
            return "done"
        # supervisor 判断 done → 结束
        if agent == "done":
            return "done"
        # 路由到目标 agent
        return agent if agent in registry.list() else "done"

    async def done_node(state: AgentState) -> dict:
        msgs = state.get("messages", [])
        text = msgs[-1].content if msgs else state.get("agent_response", "")
        return {"agent_response": text or "已完成"}

    g.add_node("supervisor", supervisor_node)
    for code in registry.list():
        g.add_node(code, registry.get(code))  # 子图嵌入父图
    g.add_node("done", done_node)
    g.set_entry_point("supervisor")
    # supervisor → agent 或 done
    g.add_conditional_edges("supervisor", router, {**{c: c for c in registry.list()}, "done": "done"})
    # agent → supervisor（多轮循环：agent 完成后回到 supervisor 再判断）
    for code in registry.list():
        g.add_edge(code, "supervisor")
    g.add_edge("done", END)
    return g.compile()

# 模块级初始化：异步构建注册中心 + 编译主图
registry = asyncio.run(_build_registry())
graph = build_graph(registry)
```

> 注：`pending_agent` 需要加入 `AgentState`。循环限定 MAX_ROUTES=4 防死循环；agent 完成后回到 supervisor，由 supervisor 判断是否继续协作或结束（返回 done）。
> **async 适配：** 因子 agent 构建时需动态加载 MCP 工具（`get_mcp_tools` 为远端 HTTP 调用），`build_xxx_agent()` 改为 async，`_build_registry()` 用 `asyncio.run()` 在模块加载时同步等待异步构建完成。

- [ ] **步骤 4：运行测试验证通过（含既有 chat 测试）**

运行：`cd backend && pytest tests/test_registry.py tests/test_chat_api.py -v`
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: AgentRegistry 动态注册与 Supervisor 主图"
```

---

### 任务 30：记忆装配接入主图

**文件：**
- 修改：`backend/app/agents/graph.py`、`backend/app/api/chat.py`
- 创建：`backend/tests/test_assembly_in_graph.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_assembly_in_graph.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_chat_with_memory(monkeypatch):
    async def fake_route(message, agents):
        return {"agent": "marketing", "reason": "r", "confidence": 0.9}
    monkeypatch.setattr("app.agents.graph.route_decision", fake_route)
    monkeypatch.setattr("app.agents.marketing.agent.ModelFactory.get_llm", lambda k: FakeLLM())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "ivan", "password": "x123456", "display_name": "Ivan"})
        r = await c.post("/api/auth/login", json={"username": "ivan", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/conversations", json={}, headers=h)
        conv_id = r.json()["id"]
        r = await c.post("/api/chat/completions", json={"conversation_id": conv_id, "message": "策划国庆营销"}, headers=h)
        assert "营销" in r.text

class FakeLLM:
    async def ainvoke(self, prompt):
        class R:
            content = "营销方案已生成"
        return R()
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_assembly_in_graph.py -v`
预期：FAIL（图尚无记忆装配，营销节点未调用）

- [ ] **步骤 3：改造 ChatService：记忆装配 + 偏好/经验沉淀（router 保持薄层）**

```python
# backend/app/services/chat_service.py 关键改造
from app.memory.assembly import assemble_memory
from app.services.experience_svc import distill_experience, save_personal_experience
from app.services.preference_svc import extract_and_save
from app.services.summary import maybe_roll_summary
from app.repositories.user_repo import UserRepository

class ChatService:
    def __init__(self, db):
        self.db = db
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)
        self.user_repo = UserRepository(db)

    async def stream_chat(self, user_id: str, conv_id: str, message: str):
        await self._ensure_owned(conv_id, user_id)
        await self.message_repo.add(Message(conversation_id=conv_id, role="user", content=message))
        await self.message_repo.commit()
        yield json.dumps({"event": "start"}, ensure_ascii=False)
        user = await self.user_repo.get(user_id)
        mem = await assemble_memory(self.db, user_id, conv_id, user.department_id, message)  # 四层记忆装配
        result = await graph.ainvoke({
            "conversation_id": conv_id, "user_id": user_id,
            "user_message": message, "memory_context": mem, "messages": [],
        })
        text = result.get("agent_response", "")
        await self.message_repo.add(Message(conversation_id=conv_id, role="assistant", content=text))
        await self.message_repo.commit()
        # 对话结束：偏好提取 + 经验提炼 + 滚动摘要（fire-and-forget）
        dialog = f"用户：{message}\n助手：{text}"
        await extract_and_save(self.db, user_id, dialog)
        exp = await distill_experience(dialog, user_id, result.get("trace_id", ""))
        if exp:
            await save_personal_experience(self.db, exp)
        await maybe_roll_summary(self.db, conv_id)  # 消息超阈值滚动摘要
        yield json.dumps({"event": "token", "content": text}, ensure_ascii=False)
        yield json.dumps({"event": "done"}, ensure_ascii=False)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_assembly_in_graph.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 四层记忆装配接入聊天主链路"
```

---

### 任务 31：DataFacade 增强 —— 风险分级包装 + load_tools

> **目标：** 在任务 26.5 基础门面之上，增加风险分级包装（`to_langchain_tool` 按 risk 分流为 direct / interrupt / 审批中心）和 `load_tools` 统一加载函数。**Mock 工具和 `register_builtin_tools` 已在任务 26.5 实现，本任务不再重复。**

**修改文件：**
- 修改：`backend/app/tools/facade.py`（增强 `to_langchain_tool`，加风险分级包装）
- 创建：`backend/app/tools/loader.py`（`load_tools` 统一加载内置 + MCP 工具）
- 修改：`backend/tests/test_facade.py`（追加风险分级测试）

- [ ] **步骤 1：编写失败的测试（追加风险分级测试）**

```python
# backend/tests/test_facade.py 追加
from langgraph.types import interrupt

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
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_facade.py -v`
预期：FAIL，`to_langchain_tool` 未实现风险分级

- [ ] **步骤 3：增强 facade.py —— 风险分级包装**

```python
# backend/app/tools/facade.py —— 在任务 26.5 基础上增强 to_langchain_tool
from langgraph.types import interrupt

class DataFacade:
    # ... register / list_tools / get / execute 保持不变 ...

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
            async def guarded_high(**kwargs):
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
            async def guarded_critical(**kwargs):
                from app.services.approval_service import ApprovalService
                from app.core.deps import get_db_context
                async with get_db_context() as db:
                    svc = ApprovalService(db)
                    approval_id = await svc.create_approval(
                        category="tool_call", risk="critical", mode="sync",
                        ref_type="trace", ref_id=trace_id,
                        title=f"{name} - {tool.description}",
                        context={"tool": name, "args": kwargs, "reason": tool.description},
                        requester_id=requester_id, approver_role="admin",
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
            coroutine=fn, name=tool.name, description=tool.description,
            args_schema=tool.args_schema,
        )
```

- [ ] **步骤 4：实现 loader.py —— load_tools 统一加载**

```python
# backend/app/tools/loader.py
from app.tools.facade import facade
from app.tools.mcp_adapter import mcp_registry, get_mcp_tools

async def load_tools(builtin_names: list[str], mcp_server_names: list[str]) -> list:
    """加载内置工具 + MCP 工具，返回 LangChain Tool 列表。
    各子 agent 构建子图时调用，避免重复的工具加载逻辑。
    风险分级由 facade.to_langchain_tool 内部处理。"""
    # 1. 内置工具（带风险分级包装）
    tools = [facade.to_langchain_tool(n) for n in builtin_names]
    # 2. MCP 工具（动态发现，服务未注册时跳过）
    for server_name in mcp_server_names:
        if server_name in mcp_registry.list():
            mcp_tools = await get_mcp_tools(server_name)
            tools.extend(mcp_tools)
    return tools
```

> **迁移说明：** 任务 27/28 中各 agent 目前使用 `[facade.to_langchain_tool(n) for n in TOOL_NAMES]` 直接加载内置工具。`load_tools` + MCP 适配器实现后，需将各 agent 的工具加载行改为 `tools = await load_tools(TOOL_NAMES, MCP_SERVER_NAMES)`，并声明 `MCP_SERVER_NAMES`。此迁移在任务 37（MCP 适配器）完成后统一执行。

- [ ] **步骤 5：运行测试验证通过**

运行：`cd backend && pytest tests/test_facade.py -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: DataFacade 风险分级包装 + load_tools"
```

---

### 任务 32：风险评估器（风险等级判定）

**文件：**
- 创建：`backend/app/tools/risk.py`
- 创建：`backend/tests/test_risk.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_risk.py
from app.tools.risk import needs_confirmation, needs_approval

def test_high_risk_needs_confirmation():
    """high：需即时确认（interrupt），不进审批中心。"""
    assert needs_confirmation("high") is True
    assert needs_approval("high") is False

def test_critical_risk_needs_approval():
    """critical：需进审批中心正式审批。"""
    assert needs_confirmation("critical") is False
    assert needs_approval("critical") is True

def test_low_medium_skips():
    """low/medium：直接执行。"""
    assert needs_confirmation("low") is False
    assert needs_approval("low") is False
    assert needs_confirmation("medium") is False
    assert needs_approval("medium") is False
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_risk.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现风险评估器**

```python
# backend/app/tools/risk.py
def needs_confirmation(risk: str) -> bool:
    """high 风险：interrupt 即时确认（不进审批中心）。"""
    return risk == "high"

def needs_approval(risk: str) -> bool:
    """critical 风险：创建审批单，进审批中心等管理者审批。"""
    return risk == "critical"

# 注：风险分流在 facade.to_langchain_tool（任务 31）中实现：
#   low/medium → 直接执行
#   high       → interrupt 即时确认
#   critical   → 创建 Approval 审批单 + interrupt 冻结图
# 本模块提供风险等级判定供工具注册与 facade 复用。
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_risk.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 风险评估器（high 即时确认 / critical 审批中心）"
```

---

### 任务 32.5：DataFacade 工具桥接验证（to_langchain_tool）

> 每个子 agent 在自己的模块内直接构建子图（节点、ToolNode、路由各自实现，保留差异化演进空间），公共部分仅 `facade.to_langchain_tool`（DataFacade 工具 → LangChain StructuredTool + 按风险等级分流包装，任务 31 已实现）。本任务验证该桥接可用。

**文件：**
- 创建：`backend/tests/test_bridge.py`

- [ ] **步骤 1：编写失败的测试**

```python
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
    assert "interrupt" in inspect.getsource(tool.func)
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_bridge.py -v`
预期：FAIL，`AttributeError: 'DataFacade' object has no attribute 'to_langchain_tool'`

- [ ] **步骤 3：确认实现（任务 31 已完成）**

运行：`cd backend && pytest tests/test_bridge.py -v`
预期：PASS（`to_langchain_tool` 已在任务 31 的 facade.py 中实现）

- [ ] **步骤 4：Commit**

```bash
git add backend/tests
git commit -m "test: DataFacade 工具桥接与高风险 interrupt 包装验证"
```

---

### 任务 33：已删除（合并入任务 24 统一审批中心）

> 原 HITL 审批 API（`/api/hitl/*`、`HitlService`、`HitlTask`）已合并入任务 24 统一审批中心。`HitlTask` 表删除，统一使用 `Approval` 表；`HitlService` 删除，统一使用 `ApprovalService`；`/api/hitl/*` 路由删除，统一使用 `/api/approvals/*`。

---

### 任务 33.5：子图嵌入父图 + 端到端验证

> 任务 29 已将三个子 agent 的编译子图作为节点嵌入父图。本任务补充验证：父图节点包含各子图，且 mock 路由后能端到端执行（supervisor → 子图 ReAct → 最终回答）。

**文件：**
- 创建：`backend/tests/test_graph_embed.py`

- [ ] **步骤 1：编写验证测试**

```python
# backend/tests/test_graph_embed.py
import pytest
from langchain_core.messages import AIMessage
from app.agents.graph import graph

def test_main_graph_contains_subagent_nodes():
    """父图节点应包含 supervisor、各子 agent 子图与 done。"""
    nodes = set(graph.get_graph().nodes)
    assert {"supervisor", "marketing", "sales_analysis", "scheduling", "done"} <= nodes

@pytest.mark.asyncio
async def test_end_to_end_route_and_respond(monkeypatch):
    """端到端：supervisor 路由到营销子图 → 子图内 ReAct 调用工具 → 最终回答。"""
    async def fake_route(message, agents):
        return {"agent": "marketing", "reason": "营销策划", "confidence": 0.9}
    monkeypatch.setattr("app.agents.graph.route_decision", fake_route)
    monkeypatch.setattr("app.agents.marketing.agent.ModelFactory.get_llm", lambda key: FakeLLM())
    result = await graph.ainvoke({"user_message": "策划国庆营销", "memory_context": "", "messages": []})
    assert result["agent_response"]

class FakeLLM:
    def bind_tools(self, tools):
        self._tools = tools
        return self
    async def ainvoke(self, messages):
        if len(messages) == 2:
            return AIMessage(content="", tool_calls=[{
                "name": "query_marketing_campaigns", "args": {"status": "active"}, "id": "c1", "type": "tool_call",
            }])
        return AIMessage(content="营销方案已生成")
```

- [ ] **步骤 2：运行测试验证通过（回归验证，任务 29 已装配）**

运行：`cd backend && pytest tests/test_graph_embed.py -v`
预期：PASS（子图已嵌入父图且端到端可执行）

- [ ] **步骤 3：Commit**

```bash
git add backend/tests
git commit -m "test: 子图嵌入父图与端到端路由执行验证"
```

---

### 任务 34：全链路留痕采集器（队列 + 批量落库）

**文件：**
- 创建：`backend/app/traces/collector.py`、`backend/app/traces/handlers.py`
- 创建：`backend/tests/test_traces.py`
- 修改：`backend/app/main.py`（启动/关闭 writer 任务）

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_traces.py
import pytest
from app.traces.collector import TraceCollector

@pytest.mark.asyncio
async def test_collector_emit_and_drain():
    collector = TraceCollector()
    collector.emit("t1", "llm_call", {"model": "x"})
    assert collector.queue.qsize() == 1
    events = collector.drain()
    assert len(events) == 1 and events[0]["type"] == "llm_call"

def test_collector_drop_on_full(monkeypatch):
    import asyncio
    c = TraceCollector(maxsize=2)
    c.emit("t", "a", {})
    c.emit("t", "b", {})
    c.emit("t", "c", {})  # 满时丢弃，不阻塞
    assert c.queue.qsize() == 2
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_traces.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现采集器（emit 不阻塞、drop 保业务）**

```python
# backend/app/traces/collector.py
import asyncio
from datetime import datetime, timezone

class TraceCollector:
    def __init__(self, maxsize: int = 1000):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)

    def emit(self, trace_id: str, type_: str, payload: dict) -> None:
        """同步内存入队；队列满直接丢弃，绝不阻塞主流程。"""
        try:
            self.queue.put_nowait({
                "trace_id": trace_id, "type": type_, "payload": payload,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except asyncio.QueueFull:
            pass

    def drain(self) -> list[dict]:
        events = []
        while not self.queue.empty():
            try:
                events.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events

collector = TraceCollector()
```

```python
# backend/app/traces/handlers.py
from langchain_core.callbacks import AsyncCallbackHandler
from app.traces.collector import collector

class TraceCallbackHandler(AsyncCallbackHandler):
    def __init__(self, trace_id: str):
        self.trace_id = trace_id

    async def on_llm_start(self, serialized, prompts, **kwargs):
        collector.emit(self.trace_id, "llm_call", {"event": "start", "prompt": prompts[0][:2000]})

    async def on_llm_end(self, response, **kwargs):
        text = getattr(response, "text", "")[:2000]
        collector.emit(self.trace_id, "llm_call", {"event": "end", "output": text})

    async def on_tool_start(self, serialized, input_str, **kwargs):
        collector.emit(self.trace_id, "tool_call", {"event": "start", "name": serialized.get("name"), "args": input_str[:2000]})

    async def on_tool_end(self, output, **kwargs):
        collector.emit(self.trace_id, "tool_call", {"event": "end", "output": str(output)[:2000]})
```

```python
# backend/app/traces/writer.py —— 后台批量落库任务
import asyncio
from sqlalchemy import insert
from app.core.database import SessionLocal
from app.models.trace import TraceEvent
from app.traces.collector import collector

async def trace_writer_loop(interval: float = 1.0, batch: int = 100) -> None:
    while True:
        await asyncio.sleep(interval)
        events = collector.drain()
        if not events:
            continue
        for i in range(0, len(events), batch):
            chunk = events[i : i + batch]
            try:
                async with SessionLocal() as db:
                    await db.execute(insert(TraceEvent), chunk)
                    await db.commit()
            except Exception:
                pass  # 降级：业务不中断
```

- [ ] **步骤 4：main.py 挂载 writer 生命周期并运行测试**

```python
# backend/app/main.py 追加
from contextlib import asynccontextmanager
import asyncio
from app.traces.writer import trace_writer_loop

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(trace_writer_loop())
    yield
    task.cancel()

app = FastAPI(title="云书 Agent", lifespan=lifespan)
```

运行：`cd backend && pytest tests/test_traces.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 全链路留痕采集器（零阻塞）"
```

---

### 任务 35：留痕接入主图 + 路由/记忆事件

**文件：**
- 修改：`backend/app/agents/graph.py`、`backend/app/agents/supervisor.py`、`backend/app/api/chat.py`
- 创建：`backend/tests/test_trace_integration.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_trace_integration.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_trace_created_per_chat(monkeypatch):
    from app.models.trace import ExecutionTrace
    async def fake_route(message, agents):
        return {"agent": "marketing", "reason": "r", "confidence": 0.9}
    monkeypatch.setattr("app.agents.graph.route_decision", fake_route)
    monkeypatch.setattr("app.agents.marketing.agent.ModelFactory.get_llm", lambda k: FakeLLM())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "kevin", "password": "x123456", "display_name": "Kevin"})
        r = await c.post("/api/auth/login", json={"username": "kevin", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/conversations", json={}, headers=h)
        conv_id = r.json()["id"]
        await c.post("/api/chat/completions", json={"conversation_id": conv_id, "message": "策划营销"}, headers=h)
        r = await c.get("/api/traces", headers=h)
        assert len(r.json()) >= 1
        assert r.json()[0]["conversation_id"] == conv_id
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_trace_integration.py -v`
预期：FAIL，404（/api/traces 不存在）

- [ ] **步骤 3：改造 ChatService 创建 trace + 实现 trace_service 与监测路由**

```python
# backend/app/repositories/trace_repo.py
from sqlalchemy import select
from app.models.trace import ExecutionTrace, TraceEvent, Approval
from app.repositories.base import BaseRepository

class TraceRepository(BaseRepository[ExecutionTrace]):
    model = ExecutionTrace

    async def list_by_user(self, user_id: str, limit: int = 50) -> list[ExecutionTrace]:
        return (await self.db.scalars(
            select(ExecutionTrace).where(ExecutionTrace.user_id == user_id)
            .order_by(ExecutionTrace.started_at.desc()).limit(limit)
        )).all()

class EventRepository(BaseRepository):
    model = TraceEvent

    async def list_by_trace(self, trace_id: str) -> list[TraceEvent]:
        return (await self.db.scalars(
            select(TraceEvent).where(TraceEvent.trace_id == trace_id).order_by(TraceEvent.id)
        )).all()

class ApprovalRepository(BaseRepository[Approval]):
    """统一审批中心 Repository，替代原 HitlRepository + 经验 ApprovalRepository。"""
    model = Approval

    async def list_pending(self, category: str | None = None) -> list[Approval]:
        q = select(Approval).where(Approval.status == "pending")
        if category:
            q = q.where(Approval.category == category)
        return (await self.db.scalars(q.order_by(Approval.submitted_at.desc()))).all()
```

```python
# backend/app/services/chat_service.py 关键改造：每次聊天创建 trace 并记录路由
from uuid import uuid4
from app.models.trace import ExecutionTrace
from app.repositories.trace_repo import TraceRepository
from app.traces.collector import collector

    def __init__(self, db):
        self.db = db
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)
        self.trace_repo = TraceRepository(db)

    async def stream_chat(self, user_id: str, conv_id: str, message: str):
        await self._ensure_owned(user_id, conv_id)
        conv = await self.conversation_repo.get(conv_id)
        trace = ExecutionTrace(id=str(uuid4()), user_id=user_id, conversation_id=conv_id, status="running", supervisor_routes=[])
        await self.trace_repo.add(trace)
        yield json.dumps({"event": "start", "trace_id": trace.id}, ensure_ascii=False)
        await self.message_repo.add(Message(conversation_id=conv_id, role="user", content=message))
        mem = await assemble_memory(self.db, user_id, conv_id, conv.department_id, message)
        result = await graph.ainvoke({
            "conversation_id": conv_id, "user_id": user_id,
            "user_message": message, "memory_context": mem, "trace_id": trace.id, "messages": [],
        })
        text = result.get("agent_response", "")
        await self.message_repo.add(Message(conversation_id=conv_id, role="assistant", content=text))
        trace.status = "completed"
        trace.supervisor_routes = result.get("route_history", [])
        conv.current_trace_id = trace.id
        await self.trace_repo.commit()  # 事务提交走 repository
        collector.emit(trace.id, "route", {"routes": trace.supervisor_routes})
        # 偏好提取 / 经验提炼同任务 30
        yield json.dumps({"event": "token", "content": text}, ensure_ascii=False)
        yield json.dumps({"event": "done"}, ensure_ascii=False)
```

```python
# backend/app/services/trace_service.py —— 监测查询业务（只组合 repo，不直查 DB）
from app.models.trace import TraceEvent
from app.repositories.trace_repo import TraceRepository, EventRepository

class TraceService:
    def __init__(self, db):
        self.trace_repo = TraceRepository(db)
        self.event_repo = EventRepository(db)

    async def list_by_user(self, user_id: str, limit: int = 50):
        return await self.trace_repo.list_by_user(user_id, limit)

    async def events(self, trace_id: str) -> list[TraceEvent]:
        return await self.event_repo.list_by_trace(trace_id)
```

```python
# backend/app/api/traces.py —— 薄路由：监测查询 API
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.services.trace_service import TraceService

router = APIRouter(prefix="/api/traces", tags=["traces"])

def get_trace_service(db: AsyncSession = Depends(get_db)) -> TraceService:
    return TraceService(db)

@router.get("")
async def list_traces(svc: TraceService = Depends(get_trace_service), user: User = Depends(get_current_user)):
    rows = await svc.list_by_user(user.id)
    return [{"id": t.id, "status": t.status, "conversation_id": t.conversation_id, "supervisor_routes": t.supervisor_routes} for t in rows]

@router.get("/{trace_id}/events")
async def trace_events(trace_id: str, svc: TraceService = Depends(get_trace_service), _: User = Depends(get_current_user)):
    return [{"type": e.type, "payload": e.payload, "created_at": e.created_at} for e in await svc.events(trace_id)]
```

- [ ] **步骤 4：main.py 注册 traces 路由并运行测试**

运行：`cd backend && pytest tests/test_trace_integration.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 留痕接入聊天链路与监测查询 API"
```

---

### 任务 36：checkpoint 持久化（langgraph-checkpoint-postgres）

**文件：**
- 修改：`backend/app/agents/graph.py`、`backend/app/api/chat.py`
- 创建：`backend/tests/test_checkpoint.py`

- [ ] **步骤 1：编写失败的测试（验证线程状态持久化）**

```python
# backend/tests/test_checkpoint.py
import pytest
from app.agents.graph import graph

@pytest.mark.asyncio
async def test_graph_compiled_with_checkpointer():
    assert getattr(graph, "checkpointer", None) is not None
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_checkpoint.py -v`
预期：FAIL，`assert None is not None`

- [ ] **步骤 3：接入 PostgresSaver**

```python
# backend/app/agents/graph.py 关键改造（在任务 29 基础上追加 checkpointer）
from langgraph.checkpoint.postgres import PostgresSaver
from app.core.config import settings

def build_graph(registry: AgentRegistry):
    ...  # 同任务 29
    # 用 checkpointer 编译，thread_id = conversation_id
    from sqlalchemy.engine import make_url
    from psycopg_pool import AsyncConnectionPool
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    pg_url = settings.DATABASE_URL.replace("+asyncpg", "")
    pool = AsyncConnectionPool(pg_url, max_size=10, kwargs={"autocommit": True})
    checkpointer = AsyncPostgresSaver(pool)
    return g.compile(checkpointer=checkpointer)

# 模块级初始化（同任务 29，build_graph 签名已改为接收 registry）
registry = asyncio.run(_build_registry())
graph = build_graph(registry)
```

> 依赖：`psycopg[binary]`、`psycopg-pool`（加入 pyproject）。`graph.ainvoke(input, config={"configurable": {"thread_id": conversation_id}})` 即为每会话独立状态；chat.py 中 ainvoke 需传 config。

```python
# backend/app/api/chat.py 关键改造：ainvoke 传 config
result = await graph.ainvoke(
    {...},
    config={"configurable": {"thread_id": conv.id}},
)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_checkpoint.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/pyproject.toml
git commit -m "feat: PostgreSQL checkpoint 状态持久化"
```

---

## 里程碑 M6：MCP 接入与配置管理

### 任务 37：MCP 适配器（mcp_servers 动态接入）

**文件：**
- 创建：`backend/app/tools/mcp_adapter.py`
- 创建：`backend/tests/test_mcp_adapter.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_mcp_adapter.py
from app.tools.mcp_adapter import load_mcp_servers, MCPRegistry

def test_mcp_registry_empty_init():
    reg = MCPRegistry()
    assert reg.list() == []

def test_register_mcp_config():
    reg = MCPRegistry()
    reg.register({"name": "erp", "url": "http://localhost:8001/mcp", "enabled": True})
    assert "erp" in reg.list()
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_mcp_adapter.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现 MCP 注册与动态工具绑定**

```python
# backend/app/tools/mcp_adapter.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.configs import McpServer

class MCPRegistry:
    def __init__(self):
        self._servers: dict[str, dict] = {}

    def register(self, server: dict) -> None:
        if server.get("enabled", True):
            self._servers[server["name"]] = server

    def unregister(self, name: str) -> None:
        self._servers.pop(name, None)

    def list(self) -> list[str]:
        return list(self._servers.keys())

mcp_registry = MCPRegistry()

async def load_mcp_servers(db: AsyncSession) -> None:
    rows = (await db.scalars(select(McpServer))).all()
    for row in rows:
        mcp_registry.register({"name": row.name, "url": row.url, "auth_type": row.auth_type, "config": row.config, "enabled": row.enabled})

async def get_mcp_tools(server_name: str) -> list:
    """通过 langchain-mcp-adapters 把远端 MCP 工具转为 LangChain Tool。"""
    from langchain_mcp_adapters.client import MultiServerMCPClient
    cfg = mcp_registry._servers[server_name]
    client = MultiServerMCPClient({server_name: {"url": cfg["url"], "transport": "streamable_http"}})
    return await client.get_tools(server_name)
```

> **MCP 工具集成到子 agent（任务 27/28 初始硬编码 → 任务 38.5 动态化）：** 任务 27/28 各子 agent 模块初始声明 `MCP_SERVER_NAMES` 硬编码绑定；任务 38.5 将绑定关系迁入数据库（`AgentMcpBinding` 表），`build_xxx_agent(db)` 通过 `load_mcp_tools_by_agent(db, agent_code)` 读取已启用的 MCP 服务名，再调用 `get_mcp_tools()` 动态发现工具并加入 `tools` 列表，与内置工具统一供 `bind_tools` 和 `ToolNode` 使用。新增/移除 MCP 绑定只需 API 操作 + 重启，无需改 agent 代码。

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_mcp_adapter.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: MCP 服务注册与动态工具接入"
```

---

### 任务 38：配置管理 API（三层：mcp-servers）

**文件：**
- 创建：`backend/app/repositories/config_repo.py`
- 创建：`backend/app/services/config_service.py`
- 创建：`backend/app/api/configs.py`（薄层）
- 创建：`backend/tests/test_configs_api.py`
- 修改：`backend/app/main.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_configs_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_mcp_config_crud():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "leah", "password": "x123456", "display_name": "Leah"})
        r = await c.post("/api/auth/login", json={"username": "leah", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/mcp-servers", json={"name": "erp", "url": "http://x/mcp"}, headers=h)
        assert r.status_code == 200
        r = await c.get("/api/mcp-servers", headers=h)
        assert any(m["name"] == "erp" for m in r.json())
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_configs_api.py -v`
预期：FAIL，404

- [ ] **步骤 3：实现配置路由**

```python
# backend/app/repositories/config_repo.py
from app.models.configs import McpServer
from app.repositories.base import BaseRepository

class McpServerRepository(BaseRepository[McpServer]):
    model = McpServer
```

```python
# backend/app/services/config_service.py
from app.models.configs import McpServer
from app.repositories.config_repo import McpServerRepository
from app.tools.mcp_adapter import mcp_registry

class ConfigService:
    """配置业务：mcp-server 增查；新增 MCP 时同步注册到运行时注册表。"""
    def __init__(self, db):
        self.mcp_repo = McpServerRepository(db)

    async def create_mcp(self, name: str, url: str, auth_type: str, config: dict) -> McpServer:
        row = McpServer(name=name, url=url, auth_type=auth_type, config=config)
        await self.mcp_repo.add(row)
        await self.mcp_repo.commit()
        mcp_registry.register({"name": row.name, "url": row.url, "auth_type": row.auth_type, "config": row.config, "enabled": True})
        return row

    async def list_mcps(self) -> list[McpServer]:
        return await self.mcp_repo.list()
```

```python
# backend/app/api/configs.py —— 薄路由
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.services.config_service import ConfigService

router = APIRouter(tags=["configs"])

class McpIn(BaseModel):
    name: str
    url: str
    auth_type: str = "none"
    config: dict = {}

def get_config_service(db: AsyncSession = Depends(get_db)) -> ConfigService:
    return ConfigService(db)

@router.post("/api/mcp-servers")
async def create_mcp(body: McpIn, svc: ConfigService = Depends(get_config_service), _: User = Depends(get_current_user)):
    return await svc.create_mcp(body.name, body.url, body.auth_type, body.config)

@router.get("/api/mcp-servers")
async def list_mcp(svc: ConfigService = Depends(get_config_service), _: User = Depends(get_current_user)):
    return await svc.list_mcps()
```

- [ ] **步骤 4：main.py 注册并运行测试**

运行：`cd backend && pytest tests/test_configs_api.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: agents/mcp-servers 配置管理 API"
```

---

### 任务 38.5：Agent MCP 绑定动态化（AgentMcpBinding）

> **目标：** 将 agent 与 MCP 服务的绑定关系从硬编码（`MCP_SERVER_NAMES`）改为数据库配置。新增 MCP 服务给 agent 使用只需 API 操作 + 重启，无需改 agent 代码。内置工具仍由 agent 硬编码 `TOOL_NAMES` 声明（新增内置工具本身就需要写代码）。

**文件：**
- 修改：`backend/app/tools/loader.py`（追加 `load_mcp_tools_by_agent`）
- 修改：`backend/app/repositories/config_repo.py`（追加 `AgentMcpBindingRepository`）
- 修改：`backend/app/services/config_service.py`（追加 agent MCP 绑定 CRUD）
- 修改：`backend/app/api/configs.py`（追加 agent MCP 绑定路由）
- 修改：`backend/app/services/seed.py`（追加 `seed_agent_mcp_bindings`）
- 修改：`backend/app/agents/marketing/agent.py`、`sales_analysis/agent.py`、`scheduling/agent.py`
- 修改：`backend/app/agents/graph.py`
- 创建：`backend/tests/test_agent_mcp_binding.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_agent_mcp_binding.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.tools.loader import load_mcp_tools_by_agent

@pytest.mark.asyncio
async def test_load_mcp_tools_by_agent(db_session):
    """从数据库读取 agent 的 MCP 绑定并加载 MCP 服务名列表。"""
    from app.services.seed import seed_agent_mcp_bindings
    await seed_agent_mcp_bindings(db_session)
    mcp_server_names = await load_mcp_tools_by_agent(db_session, "marketing")
    assert "erp" in mcp_server_names

@pytest.mark.asyncio
async def test_agent_mcp_binding_api():
    """通过 API 管理 agent MCP 绑定。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "admin1", "password": "x123456", "display_name": "Admin"})
        r = await c.post("/api/auth/login", json={"username": "admin1", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        # 查看默认绑定
        r = await c.get("/api/agents/marketing/mcp-bindings", headers=h)
        assert r.status_code == 200
        assert len(r.json()) > 0
        # 新增绑定
        r = await c.post("/api/agents/marketing/mcp-bindings", json={"mcp_server_name": "crm"}, headers=h)
        assert r.status_code == 200
        assert r.json()["mcp_server_name"] == "crm"
        # 移除
        binding_id = r.json()["id"]
        r = await c.delete(f"/api/agents/marketing/mcp-bindings/{binding_id}", headers=h)
        assert r.status_code == 200
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_agent_mcp_binding.py -v`
预期：FAIL，ImportError / 404

- [ ] **步骤 3：实现 loader 追加 + repo + service + API**

```python
# backend/app/tools/loader.py 追加
from sqlalchemy.ext.asyncio import AsyncSession

async def load_mcp_tools_by_agent(db: AsyncSession, agent_code: str) -> list[str]:
    """从数据库读取 agent 的 MCP 绑定，返回已启用的 MCP 服务名列表。
    agent 模块用此列表替代硬编码的 MCP_SERVER_NAMES。"""
    from app.repositories.config_repo import AgentMcpBindingRepository
    repo = AgentMcpBindingRepository(db)
    bindings = await repo.list_by_agent(agent_code)
    return [b.mcp_server_name for b in bindings if b.enabled]
```

```python
# backend/app/repositories/config_repo.py 追加
from app.models.configs import AgentMcpBinding

class AgentMcpBindingRepository(BaseRepository[AgentMcpBinding]):
    model = AgentMcpBinding

    async def list_by_agent(self, agent_code: str) -> list[AgentMcpBinding]:
        return list((await self.db.scalars(
            select(AgentMcpBinding).where(AgentMcpBinding.agent_code == agent_code)
        )).all())
```

```python
# backend/app/services/config_service.py 追加
from app.models.configs import AgentMcpBinding
from app.repositories.config_repo import AgentMcpBindingRepository

class ConfigService:
    def __init__(self, db):
        self.mcp_repo = McpServerRepository(db)
        self.binding_repo = AgentMcpBindingRepository(db)

    # ... 既有 create_mcp / list_mcps 不变 ...

    async def list_agent_bindings(self, agent_code: str) -> list[AgentMcpBinding]:
        return await self.binding_repo.list_by_agent(agent_code)

    async def add_agent_binding(self, agent_code: str, mcp_server_name: str) -> AgentMcpBinding:
        row = AgentMcpBinding(agent_code=agent_code, mcp_server_name=mcp_server_name)
        await self.binding_repo.add(row)
        await self.binding_repo.commit()
        return row

    async def remove_agent_binding(self, binding_id: str) -> None:
        row = await self.binding_repo.get(binding_id)
        if row:
            await self.binding_repo.delete(row)
            await self.binding_repo.commit()
```

```python
# backend/app/api/configs.py 追加
class AgentMcpBindingIn(BaseModel):
    mcp_server_name: str

@router.get("/api/agents/{agent_code}/mcp-bindings")
async def list_agent_bindings(agent_code: str, svc: ConfigService = Depends(get_config_service), _: User = Depends(get_current_user)):
    return await svc.list_agent_bindings(agent_code)

@router.post("/api/agents/{agent_code}/mcp-bindings")
async def add_agent_binding(agent_code: str, body: AgentMcpBindingIn, svc: ConfigService = Depends(get_config_service), _: User = Depends(get_current_user)):
    return await svc.add_agent_binding(agent_code, body.mcp_server_name)

@router.delete("/api/agents/{agent_code}/mcp-bindings/{binding_id}")
async def remove_agent_binding(agent_code: str, binding_id: str, svc: ConfigService = Depends(get_config_service), _: User = Depends(get_current_user)):
    await svc.remove_agent_binding(binding_id)
    return {"ok": True}
```

- [ ] **步骤 4：实现 seed 追加默认 MCP 绑定**

```python
# backend/app/services/seed.py 追加
from app.models.configs import AgentMcpBinding
from app.repositories.config_repo import AgentMcpBindingRepository

# 各 agent 默认绑定的 MCP 服务
AGENT_MCP_BINDINGS = [
    ("marketing", "erp"),
    ("sales_analysis", "erp"),
    ("scheduling", "erp"),
]

async def seed_agent_mcp_bindings(db: AsyncSession) -> None:
    repo = AgentMcpBindingRepository(db)
    for agent_code, mcp_server_name in AGENT_MCP_BINDINGS:
        if not await repo.get_by(agent_code=agent_code, mcp_server_name=mcp_server_name):
            await repo.add(AgentMcpBinding(agent_code=agent_code, mcp_server_name=mcp_server_name))
    await repo.commit()
```

```python
# backend/scripts/seed.py 追加
from app.services.seed import seed_roles, seed_agent_mcp_bindings

async def main():
    async with SessionLocal() as db:
        await seed_roles(db)
        await seed_agent_mcp_bindings(db)
    print("seeded")
```

- [ ] **步骤 5：重构子 agent，MCP 绑定从数据库读取**

```python
# backend/app/agents/marketing/agent.py 重构
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from app.llm.factory import ModelFactory
from app.tools.loader import load_tools, load_mcp_tools_by_agent
from app.agents.state import AgentState
from sqlalchemy.ext.asyncio import AsyncSession

SYSTEM_PROMPT = (
    "你是营销助手。结合【记忆上下文】中的个人偏好、历史经验、知识库与企业数据，"
    "为用户策划营销方案。营销策略需包含目标、渠道、预算、预期效果。回答用中文。"
)

# 内置工具仍硬编码（新增内置工具本身就需要写代码）
TOOL_NAMES = ["query_marketing_campaigns", "create_marketing_campaign", "publish_campaign"]
AGENT_CODE = "marketing"
MAX_TOOL_ROUNDS = 6

async def build_marketing_agent(db: AsyncSession):
    """营销助手子图。内置工具硬编码声明，MCP 绑定从数据库动态读取。"""
    # 1. 内置工具（硬编码）
    # 2. MCP 绑定（从数据库读取，替代硬编码的 MCP_SERVER_NAMES）
    mcp_server_names = await load_mcp_tools_by_agent(db, AGENT_CODE)
    tools = await load_tools(TOOL_NAMES, mcp_server_names)

    async def agent_node(state: AgentState) -> dict:
        llm = ModelFactory.get_llm("marketing").bind_tools(tools)
        msgs = [
            SystemMessage(SYSTEM_PROMPT + "\n" + state.get("memory_context", "")),
            HumanMessage(state.get("user_message", "")),
        ] + state.get("messages", [])
        resp = await llm.ainvoke(msgs)
        return {"messages": [resp], "tool_rounds": 1}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return "end"
        return "tools" if state.get("tool_rounds", 0) < MAX_TOOL_ROUNDS else "end"

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(tools))
    g.set_entry_point("agent")
    g.add_edge("tools", "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    return g.compile()
```

> `sales_analysis/agent.py` 和 `scheduling/agent.py` 同理重构：保留各自 `TOOL_NAMES` 硬编码，`build_xxx_agent(db: AsyncSession)` 接收 db 参数，调用 `load_mcp_tools_by_agent(db, AGENT_CODE)` 获取 MCP 服务名，再调用 `load_tools(TOOL_NAMES, mcp_server_names)`。

- [ ] **步骤 6：重构 graph.py，传 db 给各 agent**

```python
# backend/app/agents/graph.py 重写
import asyncio
from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.registry import AgentRegistry
from app.agents.supervisor import route_decision
from app.agents.marketing.agent import build_marketing_agent
from app.agents.sales_analysis.agent import build_sales_agent
from app.agents.scheduling.agent import build_scheduling_agent
from app.core.database import SessionLocal

MAX_ROUTES = 4

async def _build_registry(db) -> AgentRegistry:
    """异步构建注册中心：从数据库加载各 agent 的 MCP 绑定并构建子图。"""
    registry = AgentRegistry()
    registry.register("marketing", await build_marketing_agent(db))
    registry.register("sales_analysis", await build_sales_agent(db))
    registry.register("scheduling", await build_scheduling_agent(db))
    return registry

def build_graph(registry: AgentRegistry):
    """根据已构建的注册中心装配主图。"""
    g = StateGraph(AgentState)

    async def supervisor_node(state: AgentState) -> dict:
        decision = await route_decision(state.get("user_message", ""), registry.list())
        return {"pending_agent": decision["agent"], "route_history": [decision["agent"]]}

    def router(state: AgentState) -> str:
        agent = state.get("pending_agent", "done")
        if len(state.get("route_history", [])) >= MAX_ROUTES:
            return "done"
        return agent if agent in registry.list() else "done"

    async def done_node(state: AgentState) -> dict:
        msgs = state.get("messages", [])
        text = msgs[-1].content if msgs else state.get("agent_response", "")
        return {"agent_response": text or "已完成"}

    g.add_node("supervisor", supervisor_node)
    for code in registry.list():
        g.add_node(code, registry.get(code))
    g.add_node("done", done_node)
    g.set_entry_point("supervisor")
    g.add_conditional_edges("supervisor", router, {**{c: c for c in registry.list()}, "done": "done"})
    for code in registry.list():
        g.add_edge(code, "done")
    g.add_edge("done", END)
    return g.compile()

# 模块级初始化：从数据库加载 MCP 绑定 + 构建子图 + 编译主图
async def _init():
    async with SessionLocal() as db:
        reg = await _build_registry(db)
    return build_graph(reg)

graph = asyncio.run(_init())
```

> **注：** `graph.py` 模块加载时从数据库读取 MCP 绑定构建子图。新增/移除 MCP 绑定后需重启应用生效。后续可扩展为热重载机制。

- [ ] **步骤 7：更新既有测试适配 db 参数**

> 任务 27/28 的测试中 `build_marketing_agent()` / `build_sales_agent()` / `build_scheduling_agent()` 需改为 `await build_marketing_agent(db_session)` 等，传入 db_session。测试 fixture 需先调用 `seed_agent_mcp_bindings(db_session)` 初始化默认绑定。

- [ ] **步骤 8：生成迁移并运行测试**

运行：`cd backend && alembic revision --autogenerate -m "add agent_mcp_bindings" && alembic upgrade head && pytest tests/test_agent_mcp_binding.py tests/test_marketing_agent.py tests/test_agents_extra.py -v`
预期：全部 PASS

- [ ] **步骤 9：Commit**

```bash
git add backend/app backend/tests backend/alembic
git commit -m "feat: agent MCP 绑定动态化，MCP 服务绑定存库管理"
```

---

### 任务 38.6：MCP 工具风险等级配置（default_risk + tool_risks）

> **目标：** 为 MCP 工具动态注入风险等级，使 MCP 工具与内置工具一样能触发 high（即时确认）/ critical（审批中心）分流。MCP 工具的 risk 不能在代码里硬编码（工具是运行时从远端服务发现的），因此采用「服务级默认 + 工具级覆盖」两级配置：
>
> - **服务级默认** `McpServer.default_risk`：注册 MCP 服务时设定，对该服务下所有工具生效（默认 `medium`）。
> - **工具级覆盖** `McpServer.config["tool_risks"]`：管理员查看工具清单后，按需为特定工具指定更高/更低的 risk，覆盖服务级默认。
>
> **config 字段写入时机（关键）：** 注册 MCP 服务时 `config = {}`（空）；管理员通过 `GET /api/mcp-servers/{name}/tools` 实时连接 MCP 服务发现工具清单 → 通过 `PUT /api/mcp-servers/{name}/tool-risks` 提交风险配置 → 写入 `config["tool_risks"]` → 运行时 `load_mcp_tools_with_risk` 读取做风险判定。运行时只读不写。
>
> **风险判定优先级：** `config.tool_risks[tool_name]` > `default_risk` > `"medium"` 兜底。

**文件：**
- 修改：`backend/app/tools/risk.py`（追加 `get_mcp_risk`）
- 修改：`backend/app/tools/loader.py`（改造 `load_tools` 接收 db；追加 `load_mcp_tools_with_risk`）
- 修改：`backend/app/services/config_service.py`（追加 `update_tool_risks`）
- 修改：`backend/app/api/configs.py`（追加 `list_mcp_tools` / `update_tool_risks` 路由）
- 修改：`backend/app/agents/marketing/agent.py`、`sales_analysis/agent.py`、`scheduling/agent.py`（`load_tools` 调用同步加 db 参数）
- 创建：`backend/tests/test_mcp_tool_risk.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_mcp_tool_risk.py
import pytest
from app.tools.risk import get_mcp_risk

def test_get_mcp_risk_tool_level_overrides_default():
    """工具级覆盖优先于服务级默认。"""
    config = {"tool_risks": {"delete_order": "critical"}}
    assert get_mcp_risk("delete_order", "medium", config) == "critical"

def test_get_mcp_risk_falls_back_to_server_default():
    """无工具级覆盖时回退到服务级 default_risk。"""
    assert get_mcp_risk("query_order", "high", {}) == "high"

def test_get_mcp_risk_falls_back_to_medium():
    """服务级默认为空时兜底 medium。"""
    assert get_mcp_risk("query_order", "", {}) == "medium"
    assert get_mcp_risk("query_order", None, None) == "medium"

@pytest.mark.asyncio
async def test_update_tool_risks_api(client_with_auth):
    """通过 API 更新 MCP 服务的工具风险配置。"""
    async with client_with_auth as c:
        h = {"Authorization": f"Bearer {await _login(c)}"}
        # 先注册一个 MCP 服务
        await c.post("/api/mcp-servers", json={"name": "erp", "url": "http://localhost:8001/mcp"}, headers=h)
        # 更新工具风险
        r = await c.put("/api/mcp-servers/erp/tool-risks", json={
            "tool_risks": {"delete_order": "critical", "adjust_schedule": "high"}
        }, headers=h)
        assert r.status_code == 200
        assert r.json()["tool_risks"]["delete_order"] == "critical"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_mcp_tool_risk.py -v`
预期：FAIL，ImportError / 404

- [ ] **步骤 3：实现 risk.py 追加 get_mcp_risk**

```python
# backend/app/tools/risk.py 追加

def get_mcp_risk(tool_name: str, server_default_risk: str, server_config: dict) -> str:
    """判定 MCP 工具的风险等级（运行时动态注入）。
    优先级：工具级覆盖 config.tool_risks > 服务级 default_risk > "medium" 兜底。
    内置工具的 risk 在注册时硬编码声明，不走本函数。"""
    tool_risks = (server_config or {}).get("tool_risks", {})
    return tool_risks.get(tool_name, server_default_risk or "medium")
```

- [ ] **步骤 4：改造 loader.py，load_tools 接收 db + 追加 load_mcp_tools_with_risk**

```python
# backend/app/tools/loader.py 重写
from sqlalchemy.ext.asyncio import AsyncSession
from app.tools.facade import facade, Tool
from app.tools.mcp_adapter import mcp_registry, get_mcp_tools
from app.tools.risk import get_mcp_risk

async def load_mcp_tools_with_risk(db: AsyncSession, server_name: str) -> list[Tool]:
    """连接 MCP 服务发现工具，注入风险等级，包装为 DataFacade.Tool。
    - 风险来源：get_mcp_risk(tool_name, server.default_risk, server.config)
    - 工具名加前缀 mcp_{server_name}_ 防与内置工具重名"""
    from app.repositories.config_repo import McpServerRepository

    # 1. 服务未注册则跳过
    if server_name not in mcp_registry.list():
        return []

    # 2. 查数据库获取风险配置
    mcp_repo = McpServerRepository(db)
    server = await mcp_repo.get(server_name)
    if not server or not server.enabled:
        return []

    # 3. 连接 MCP 服务，发现所有工具（返回 LangChain Tool 列表）
    raw_tools = await get_mcp_tools(server_name)

    # 4. 注入 risk，包装为 DataFacade.Tool
    result = []
    for t in raw_tools:
        risk = get_mcp_risk(t.name, server.default_risk, server.config)
        result.append(Tool(
            name=f"mcp_{server_name}_{t.name}",
            fn=t.func,
            risk=risk,
            description=t.description,
            args_schema=t.args_schema,
        ))
    return result

async def load_tools(db: AsyncSession, builtin_names: list[str], mcp_server_names: list[str]) -> list:
    """统一加载内置工具 + MCP 工具，返回 LangChain Tool 列表。
    - 内置工具：risk 在注册时硬编码声明（facade.get_risk）
    - MCP 工具：risk 从数据库 default_risk + config.tool_risks 动态注入
    各子 agent 构建子图时调用。"""
    # 1. 内置工具（从 facade 单例获取，risk 已硬编码）
    tools = [facade.to_langchain_tool(n) for n in builtin_names]
    # 2. MCP 工具（动态发现 + 注入 risk）
    for server_name in mcp_server_names:
        mcp_tools = await load_mcp_tools_with_risk(db, server_name)
        tools.extend([facade.to_langchain_tool(t.name) for t in mcp_tools])
    return tools
```

> **注：** `load_tools` 签名从 `(builtin_names, mcp_server_names)` 改为 `(db, builtin_names, mcp_server_names)`，因为 MCP 工具的风险等级需从数据库读取。任务 27/28/38.5 中所有 `load_tools(...)` 调用需同步改为 `load_tools(db, ...)`。

- [ ] **步骤 5：实现 config_service.py 追加 update_tool_risks**

```python
# backend/app/services/config_service.py 追加
from fastapi import HTTPException

class ConfigService:
    # ... 既有 create_mcp / list_mcps / agent binding 方法不变 ...

    async def update_tool_risks(self, name: str, tool_risks: dict[str, str]) -> dict:
        """更新 MCP 服务的 config.tool_risks，覆盖特定工具的风险等级。
        config 在注册时为空，由管理员调用本方法写入。"""
        server = await self.mcp_repo.get(name)
        if not server:
            raise HTTPException(404, "MCP 服务不存在")
        config = server.config or {}
        config["tool_risks"] = tool_risks
        server.config = config
        await self.mcp_repo.commit()
        return {"ok": True, "tool_risks": tool_risks}
```

- [ ] **步骤 6：实现 api/configs.py 追加两个路由**

```python
# backend/app/api/configs.py 追加
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

class ToolRisksUpdate(BaseModel):
    tool_risks: dict[str, str]  # {"delete_order": "critical", "adjust_schedule": "high"}

@router.get("/api/mcp-servers/{name}/tools")
async def list_mcp_tools(name: str, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    """连接 MCP 服务，返回已发现的所有工具列表（含当前 risk）。
    供管理员查看后按需通过 tool-risks 接口配置风险等级。"""
    from app.tools.mcp_adapter import mcp_registry, get_mcp_tools
    from app.repositories.config_repo import McpServerRepository
    from app.tools.risk import get_mcp_risk

    if name not in mcp_registry.list():
        raise HTTPException(404, "MCP 服务未注册")

    # 连接 MCP 服务发现工具
    raw_tools = await get_mcp_tools(name)

    # 查风险配置
    mcp_repo = McpServerRepository(db)
    server = await mcp_repo.get(name)

    return [
        {
            "name": t.name,
            "description": t.description,
            "risk": get_mcp_risk(t.name, server.default_risk, server.config),
        }
        for t in raw_tools
    ]

@router.put("/api/mcp-servers/{name}/tool-risks")
async def update_tool_risks(name: str, body: ToolRisksUpdate, svc: ConfigService = Depends(get_config_service), _: User = Depends(get_current_user)):
    """更新 MCP 服务的 config.tool_risks，覆盖特定工具的风险等级。
    管理员先通过 GET .../tools 查看工具清单，再调用本接口配置风险。"""
    return await svc.update_tool_risks(name, body.tool_risks)
```

- [ ] **步骤 7：同步更新子 agent 的 load_tools 调用**

> 任务 27/28/38.5 中各子 agent 的 `load_tools(TOOL_NAMES, mcp_server_names)` 调用全部改为 `load_tools(db, TOOL_NAMES, mcp_server_names)`。以 marketing 为例：

```python
# backend/app/agents/marketing/agent.py 同步修改
async def build_marketing_agent(db: AsyncSession):
    mcp_server_names = await load_mcp_tools_by_agent(db, AGENT_CODE)
    tools = await load_tools(db, TOOL_NAMES, mcp_server_names)  # 加 db 参数
    # ... 其余不变 ...
```

> `sales_analysis/agent.py` 和 `scheduling/agent.py` 同理修改 `load_tools` 调用。

- [ ] **步骤 8：生成迁移并运行测试**

运行：`cd backend && alembic revision --autogenerate -m "add default_risk to mcp_servers" && alembic upgrade head && pytest tests/test_mcp_tool_risk.py tests/test_risk.py tests/test_agent_mcp_binding.py -v`
预期：全部 PASS

- [ ] **步骤 9：Commit**

```bash
git add backend/app backend/tests backend/alembic
git commit -m "feat: MCP 工具风险等级动态配置（default_risk + config.tool_risks）"
```

---

## 里程碑 M7：前端（分三阶段）

### 任务 39：前端骨架 + 登录页（阶段 1 之基）

**文件：**
- 创建：`frontend/package.json`、`frontend/vite.config.ts`、`frontend/tsconfig.json`
- 创建：`frontend/src/main.ts`、`frontend/src/App.vue`、`frontend/src/router.ts`、`frontend/src/views/Login.vue`
- 创建：`frontend/src/api/client.ts`（axios 封装，注入 JWT）

- [ ] **步骤 1：初始化 Vite + Vue3 + TS**

```bash
cd frontend && npm create vite@latest . -- --template vue-ts && npm i vue-router axios ant-design-vue
```

- [ ] **步骤 2：编写 api client（JWT 拦截器）**

```ts
// frontend/src/api/client.ts
import axios from 'axios'

const client = axios.create({ baseURL: '/api' })
client.interceptors.request.use(cfg => {
  const token = localStorage.getItem('token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})
export default client
```

- [ ] **步骤 3：实现登录页与路由守卫**

```vue
<!-- frontend/src/views/Login.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import client from '../api/client'

const username = ref('')
const password = ref('')
const router = useRouter()

async function login() {
  const { data } = await client.post('/auth/login', { username: username.value, password: password.value })
  localStorage.setItem('token', data.access_token)
  router.push('/chat')
}
</script>

<template>
  <a-form layout="vertical" style="max-width: 360px; margin: 80px auto">
    <a-form-item label="用户名"><a-input v-model:value="username" /></a-form-item>
    <a-form-item label="密码"><a-input-password v-model:value="password" /></a-form-item>
    <a-button type="primary" block @click="login">登录</a-button>
  </a-form>
</template>
```

- [ ] **步骤 4：运行前端并验证可启动**

运行：`cd frontend && npm run dev`
预期：`VITE ready` 且 `http://localhost:5173` 可访问登录页

- [ ] **步骤 5：Commit**

```bash
git add frontend
git commit -m "feat: 前端骨架与登录页"
```

---

### 任务 40：聊天界面（SSE 流式 + 会话列表 + 即时确认浮层）

**文件：**
- 创建：`frontend/src/views/Chat.vue`、`frontend/src/views/ConfirmPanel.vue`
- 创建：`frontend/src/api/chat.ts`

- [ ] **步骤 1：编写 SSE 流式消费工具**

```ts
// frontend/src/api/chat.ts
import client from './client'

export async function streamChat(conversationId: string, message: string, onEvent: (e: any) => void) {
  const resp = await fetch('/api/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${localStorage.getItem('token')}`,
    },
    body: JSON.stringify({ conversation_id: conversationId, message }),
  })
  const reader = resp.body!.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() ?? ''
    for (const part of parts) {
      const line = part.split('\n').find(l => l.startsWith('data: '))
      if (line) onEvent(JSON.parse(line.slice(6)))
    }
  }
}
```

- [ ] **步骤 2：实现 Chat.vue（消息列表 + 流式渲染 + 会话切换）**

```vue
<!-- frontend/src/views/Chat.vue（核心结构） -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import client from '../api/client'
import { streamChat } from '../api/chat'

const convs = ref<any[]>([])
const currentId = ref('')
const messages = ref<any[]>([])
const input = ref('')
const streaming = ref(false)

onMounted(loadConvs)

async function loadConvs() {
  const { data } = await client.get('/conversations')
  convs.value = data
}

async function newConv() {
  const { data } = await client.post('/conversations', {})
  convs.value.unshift(data)
  currentId.value = data.id
  messages.value = []
}

async function loadMessages() {
  const { data } = await client.get(`/conversations/${currentId.value}/messages`)
  messages.value = data
}

async function send() {
  const text = input.value
  input.value = ''
  messages.value.push({ role: 'user', content: text })
  streaming.value = true
  let acc = ''
  await streamChat(currentId.value, text, (e: any) => {
    if (e.event === 'token') {
      acc += e.content
      const last = messages.value[messages.value.length - 1]
      if (last?.role === 'assistant') last.content = acc
      else messages.value.push({ role: 'assistant', content: acc })
    }
    if (e.event === 'done') streaming.value = false
  })
}
</script>
```

- [ ] **步骤 3：实现即时确认浮层（high 风险工具的 interrupt 确认）**

> high 风险工具调用时 interrupt 冻结图，前端通过 SSE 事件收到需确认通知，弹窗让当班人即时确认。critical 风险工具不在此处理，而是进入审批中心（任务 42）。

```vue
<!-- frontend/src/views/ConfirmPanel.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import client from '../api/client'

const visible = ref(false)
const pending = ref<any>(null)

// 监听 SSE 事件中的 confirm_required 事件
window.addEventListener('confirm_required', (e: any) => {
  pending.value = e.detail
  visible.value = true
})

async function decide(approved: boolean) {
  // 通过 chat API 恢复图执行（传 resume 值）
  await client.post('/chat/resume', { approved, thread_id: pending.value.thread_id })
  visible.value = false
}
</script>

<template>
  <a-modal v-model:open="visible" title="高风险操作确认" :closable="false">
    <p>{{ pending?.reason }}</p>
    <p>工具：{{ pending?.tool }} 参数：{{ JSON.stringify(pending?.args) }}</p>
    <template #footer>
      <a-button type="primary" @click="decide(true)">确认执行</a-button>
      <a-button danger @click="decide(false)">驳回</a-button>
    </template>
  </a-modal>
</template>
```

- [ ] **步骤 4：验证页面可交互**

运行：`cd frontend && npm run dev`，登录后创建会话并发消息
预期：消息流式渲染；后端运行 `cd backend && uvicorn app.main:app --reload` 提供 API（vite proxy 代理 `/api` 到 `http://localhost:8000`）

- [ ] **步骤 5：Commit**

```bash
git add frontend
git commit -m "feat: 聊天界面（SSE 流式+会话+即时确认浮层）"
```

---

### 任务 41：知识库管理与经验中心界面（阶段 2）

**文件：**
- 创建：`frontend/src/views/Knowledge.vue`、`frontend/src/views/Experiences.vue`

- [ ] **步骤 1：知识库页（上传 + 检索测试）**

```vue
<!-- frontend/src/views/Knowledge.vue 核心 -->
<script setup lang="ts">
import { ref } from 'vue'
import client from '../api/client'

const docs = ref<any[]>([])
const query = ref('')
const results = ref<any[]>([])

async function upload(e: Event) {
  const file = (e.target as HTMLInputElement).files![0]
  const form = new FormData()
  form.append('file', file)
  await client.post('/documents', form)
  await loadDocs()
}

async function loadDocs() { const { data } = await client.get('/documents'); docs.value = data }
async function search() {
  const { data } = await client.post('/kb/search', { query: query.value })
  results.value = data.results
}
</script>
```

- [ ] **步骤 2：经验中心页（分层视图 + 提交审批）**

```vue
<!-- frontend/src/views/Experiences.vue 核心 -->
<script setup lang="ts">
import { ref } from 'vue'
import client from '../api/client'

const items = ref<any[]>([])

async function load() { const { data } = await client.get('/experiences'); items.value = data }
async function submit(id: string, toScope: string) {
  await client.post(`/experiences/${id}/submit`, { to_scope: toScope })
  load()
}
</script>
```

> 注：`GET /api/documents` 列表接口在本阶段补充（任务 18 仅实现上传与检索，需补 list/delete 路由，代码同 org 列表模式）。

- [ ] **步骤 3：路由与侧边栏接入**

在 `router.ts` 注册 `/knowledge`、`/experiences` 路由；App.vue 加菜单导航。

- [ ] **步骤 4：验证页面可交互**

运行：`cd frontend && npm run dev`
预期：知识库上传后可在检索测试中命中；经验中心可见个人层经验并可提交

- [ ] **步骤 5：Commit**

```bash
git add frontend
git commit -m "feat: 知识库管理与经验中心界面"
```

---

### 任务 42：管理界面（阶段 3：组织架构 + 配置 + 审批中心 + 监测）

**文件：**
- 创建：`frontend/src/views/Org.vue`、`frontend/src/views/Configs.vue`、`frontend/src/views/Approvals.vue`、`frontend/src/views/Traces.vue`

- [ ] **步骤 1：组织架构页**：复用 `GET/POST /api/departments`、`/api/users`，部门列表 + 用户列表 + 新建部门表单
- [ ] **步骤 2：配置页**：MCP 服务列表 + 新建 MCP 表单（调用任务 38 的 API）；Agent MCP 绑定管理（调用任务 38.5 的 API，选择 agent → 查看/新增/移除 MCP 绑定）
- [ ] **步骤 3：审批中心页**：`GET /api/approvals?status=pending` 列表，按 category 分组展示（工具调用 / 经验晋升），每条显示标题、类型、风险等级、发起人、提交时间；通过/驳回按钮 + 审批意见输入框，调用 `POST /api/approvals/{id}/decide`
- [ ] **步骤 4：监测页**：`GET /api/traces` 列表 + 点击行展示 `GET /api/traces/{id}/events` 时间线（按 type 着色：route=蓝 / llm=紫 / tool=橙 / approval=红）
- [ ] **步骤 5：验证页面可交互**

运行：`cd frontend && npm run dev`
预期：四页均能调用对应 API 并展示数据

- [ ] **步骤 6：Commit**

```bash
git add frontend
git commit -m "feat: 组织架构/配置/审批中心/监测管理界面"
```

---

## 里程碑 M8：收尾

### 任务 43：全量回归 + docker-compose 联调

**文件：**
- 修改：`backend/docker-compose.yml`（增加 backend 服务）

- [ ] **步骤 1：全量测试回归**

运行：`cd backend && pytest tests -v`
预期：全部 PASS

- [ ] **步骤 2：补充 docker-compose backend 服务**

```yaml
# backend/docker-compose.yml 追加
  backend:
    build: .
    env_file: .env
    ports: ["8000:8000"]
    depends_on: [db]
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- [ ] **步骤 3：端到端冒烟验证（国庆营销场景）**

```bash
cd backend && docker compose up -d --build
curl -X POST localhost:8000/api/auth/register -d '{"username":"demo","password":"x123456","display_name":"Demo"}'
curl -X POST localhost:8000/api/auth/login -d '{"username":"demo","password":"x123456"}'
# 上传知识文档 → 创建会话 → 发送"今年国庆策划一个营销方案"
```

预期：SSE 流式返回营销方案；`/api/traces` 出现本次执行的完整留痕；偏好/经验表出现自动沉淀数据

- [ ] **步骤 4：Commit**

```bash
git add backend/docker-compose.yml
git commit -m "feat: docker-compose 联调与冒烟验证"
```

---

## 计划自检

**1. 规格覆盖度对照：**

| 规格章节 | 对应任务 |
|---|---|
| §2 总体架构 / Supervisor 循环 | 26, 29 |
| §2.3 全链路留痕 | 34, 35 |
| §3.3 短期记忆（N 轮+滚动摘要） | 12, 13, 15 |
| §3.4 偏好中心（自动提取+去重） | 20 |
| §3.5/3.6 经验中心（三级+审批+向量） | 21, 22, 23, 24 |
| §3.7 知识中心 RAG | 16, 17, 18, 19 |
| §4 数据库（全部表 + pgvector + Alembic） | 2, 3, 4, 5, 6 |
| §5 子Agent子图（内部构建 ToolNode ReAct）嵌入父图 | 27, 28, 29, 33.5 |
| §5 Agent 注册 / DataFacade / MCP / 风险 | 31, 32, 32.5, 37 |
| §5 Agent MCP 绑定动态化 | 38.5 |
| §6 API（认证/聊天/审批中心/知识/经验/组织/监测/配置） | 7, 7.5, 8, 10, 14, 15, 18, 23, 24, 35, 38, 38.5 |
| §6 三层架构（router→service→repository） | 7.5（范式）+ 8, 10, 14, 15, 18, 23, 24, 35, 38, 38.5 |
| §7 技术决策（异步/checkpoint/多模型/部署） | 1, 11, 36, 43 |
| 风险分级 + 统一审批中心 | 31, 32, 32.5, 24 |
| 前端三阶段 | 39, 40, 41, 42 |

**2. 占位符扫描**：无 TODO/待定；任务 36 中 `... # 同任务 29` 为明确的复用指引（主图装配代码已在任务 29 完整给出）。

**3. 类型一致性**：
- `AgentState` 统一在任务 14 定义；含 `pending_agent`、`tool_rounds` 字段
- 记忆模块命名统一：`build_context`（短期）、`build_pref_context`（偏好，任务 20 中实际名为 `build_context`，任务 25 测试 mock 名为 `build_pref_context`——**执行时以 `app.memory.preferences.build_context` 为准**，任务 25 的 monkeypatch 目标需相应调整）
- `embed_texts / embed_query` 在任务 16 定义，被 18/21/22/23 复用，签名一致
- **物理外键约定**：全项目模型一律不使用 `ForeignKey`（任务 3/4/5/6/20 已按"逻辑外键"改写）——关联列用普通列 `String(36) + index`；不使用 relationship，关联查询在 repo/service 层用 id 手动查
- **三层架构约定**（任务 7.5 范式）：`router` 只做参数校验并调用 service（薄层）；`service` 组合业务规则与多个 repository；`repository` 继承 `BaseRepository` 只做原子 CRUD。禁止在 router 中直接执行 SQL / 组装业务。已按此改造：任务 8/10/14/15/18/23/24/33/35/38

**4. 执行顺序提示**：任务 25 的测试 monkeypatch 路径与任务 20 命名存在一处不一致（`build_pref_context` vs `build_context`），实现时以任务 20 的实际函数名为准修正测试。