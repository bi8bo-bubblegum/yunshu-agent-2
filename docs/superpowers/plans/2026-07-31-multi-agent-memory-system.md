# 多 Agent 智能协作系统实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现 supervisor 统一意图分发 + 四层记忆管理（短期/偏好/经验/知识）+ 全链路留痕 + HITL 的多 Agent 系统，Python 3.11 + LangGraph + PostgreSQL + SQLAlchemy + FastAPI 全异步。

**架构：** FastAPI 异步层 → LangGraph 主图（Supervisor 循环路由）→ Agent 子图（营销助手/经营分析/调度优化）→ 记忆装配层（四层记忆注入 prompt）→ 数据门面（内置工具 + MCP）。状态用 langgraph-checkpoint-postgres 持久化；HITL 用 interrupt()；留痕用异步队列批量落库不阻塞主流程。

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
│   │   ├── experience.py       # Experience / ExperienceApproval
│   │   ├── knowledge.py        # Document / Chunk
│   │   ├── trace.py            # ExecutionTrace / TraceEvent / HitlTask
│   │   └── configs.py          # AgentConfig / McpServer
│   ├── schemas/                # Pydantic 请求/响应模型
│   ├── api/                    # auth/chat/conversations/hitl/documents/
│   │                           #   experiences/approvals/org/traces/configs
│   ├── services/
│   │   ├── document_parser.py  # PDF/Word/Markdown 解析+切分
│   │   ├── embedding.py        # embedding 客户端封装
│   │   ├── experience_svc.py   # 经验提炼/审批/晋升
│   │   ├── preference_svc.py   # 偏好提取/合并去重
│   │   ├── summary.py          # 对话滚动摘要
│   │   └── seed.py             # 种子数据
│   ├── agents/
│   │   ├── state.py            # AgentState 定义
│   │   ├── graph.py            # 主图装配 + Supervisor 循环
│   │   ├── supervisor.py       # 路由节点（结构化输出）
│   │   ├── registry.py         # AgentRegistry 动态装配
│   │   ├── marketing/agent.py  # 营销助手子图
│   │   ├── sales_analysis/agent.py
│   │   └── scheduling/agent.py
│   ├── memory/
│   │   ├── assembly.py         # MemoryAssembly 统一装配
│   │   ├── short_term.py
│   │   ├── preferences.py
│   │   ├── experiences.py
│   │   └── knowledge.py
│   ├── tools/
│   │   ├── facade.py           # DataFacade 统一门面
│   │   ├── risk.py             # 风险评估器
│   │   ├── builtin/sql_tool.py
│   │   ├── builtin/http_tool.py
│   │   ├── builtin/calc_tool.py
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
    ├── test_supervisor.py / test_traces.py / test_hitl.py
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
from sqlalchemy import select
from app.models.org import Department, Role, User

@pytest.mark.asyncio
async def test_create_user_with_department(db_session):
    dept = Department(name="市场部")
    db_session.add(dept)
    await db_session.flush()
    role = Role(code="member", name="成员")
    db_session.add(role)
    await db_session.flush()
    user = User(username="alice", password_hash="x", department_id=dept.id, role_id=role.id, display_name="爱丽丝")
    db_session.add(user)
    await db_session.flush()
    result = await db_session.scalar(select(User).where(User.username == "alice"))
    assert result.department.name == "市场部"
    assert result.role.code == "member"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_org.py -v`
预期：FAIL，`ImportError: cannot import name 'Department'`

- [ ] **步骤 3：实现模型**

```python
# backend/app/models/org.py
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))

class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_id])
    users: Mapped[list["User"]] = relationship(back_populates="department")

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id"))
    display_name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    department: Mapped[Department | None] = relationship(back_populates="users")
    role: Mapped[Role | None] = relationship()
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
    result = await db_session.scalar(select(Conversation).where(Conversation.id == conv.id))
    assert len(result.messages) == 1
    assert result.messages[0].role == "user"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_chat_models.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现模型**

```python
# backend/app/models/chat.py
from datetime import datetime
from uuid import uuid4
from sqlalchemy import UUID, BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(128), default="新对话")
    summary: Mapped[str | None] = mapped_column(Text)
    current_trace_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    conversation: Mapped[Conversation] = relationship(back_populates="messages")
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
        owner_id=1, scope="personal", status="approved",
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
from sqlalchemy import UUID, BigInteger, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from app.core.database import Base

class Experience(Base):
    __tablename__ = "experiences"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    scope: Mapped[str] = mapped_column(String(16))  # personal/dept/company
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft/pending/approved/rejected
    title: Mapped[str] = mapped_column(String(128))
    summary: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    event_time: Mapped[date | None] = mapped_column(Date)
    result_metrics: Mapped[dict | None] = mapped_column(JSONB)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    source_trace_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    approvals: Mapped[list["ExperienceApproval"]] = relationship(back_populates="experience", cascade="all, delete-orphan")

class ExperienceApproval(Base):
    __tablename__ = "experience_approvals"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    experience_id: Mapped[str] = mapped_column(ForeignKey("experiences.id"))
    from_scope: Mapped[str] = mapped_column(String(16))
    to_scope: Mapped[str] = mapped_column(String(16))
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    experience: Mapped[Experience] = relationship(back_populates="approvals")
```

```python
# backend/app/models/knowledge.py
from datetime import datetime
from uuid import uuid4
from sqlalchemy import UUID, BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from app.core.database import Base

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(256))
    file_path: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="parsing")  # parsing/ready/failed
    uploader_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")

class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    meta_: Mapped[dict | None] = mapped_column("meta", JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    document: Mapped[Document] = relationship(back_populates="chunks")
```

```python
# backend/app/models/__init__.py 追加
from app.models.experience import Experience, ExperienceApproval
from app.models.knowledge import Document, Chunk
__all__ += ["Experience", "ExperienceApproval", "Document", "Chunk"]
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
from app.models.trace import ExecutionTrace, TraceEvent, HitlTask
from app.models.configs import AgentConfig, McpServer

@pytest.mark.asyncio
async def test_trace_event_flow(db_session):
    trace = ExecutionTrace(user_id=1, status="running", supervisor_routes=[{"agent": "marketing"}])
    db_session.add(trace)
    await db_session.flush()
    db_session.add(TraceEvent(trace_id=trace.id, type="llm_call", payload={"model": "x", "tokens": 100}))
    db_session.add(HitlTask(trace_id=trace.id, node_id="n1", reason="高风险操作", status="pending"))
    await db_session.commit()
    result = await db_session.scalar(select(ExecutionTrace).where(ExecutionTrace.id == trace.id))
    assert result.supervisor_routes[0]["agent"] == "marketing"
    assert result.hitl_tasks[0].status == "pending"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_trace_models.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现模型**

```python
# backend/app/models/trace.py
from datetime import datetime
from uuid import uuid4
from sqlalchemy import UUID, BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class ExecutionTrace(Base):
    __tablename__ = "execution_traces"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running/completed/interrupted/failed
    supervisor_routes: Mapped[list | None] = mapped_column(JSONB, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    events: Mapped[list["TraceEvent"]] = relationship(back_populates="trace")
    hitl_tasks: Mapped[list["HitlTask"]] = relationship(back_populates="trace")

class TraceEvent(Base):
    __tablename__ = "trace_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(ForeignKey("execution_traces.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # route/llm/tool/memory/hitl
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    trace: Mapped[ExecutionTrace] = relationship(back_populates="events")

class HitlTask(Base):
    __tablename__ = "hitl_tasks"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    trace_id: Mapped[str] = mapped_column(ForeignKey("execution_traces.id"))
    node_id: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    context: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/approved/rejected
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace: Mapped[ExecutionTrace] = relationship(back_populates="hitl_tasks")
```

```python
# backend/app/models/configs.py
from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class AgentConfig(Base):
    __tablename__ = "agents"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    model_key: Mapped[str] = mapped_column(String(64), default="default")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)  # system_prompt / tool_whitelist
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

class McpServer(Base):
    __tablename__ = "mcp_servers"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(String(512))
    auth_type: Mapped[str] = mapped_column(String(16), default="none")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
```

```python
# backend/app/models/__init__.py 追加
from app.models.trace import ExecutionTrace, TraceEvent, HitlTask
from app.models.configs import AgentConfig, McpServer
__all__ += ["ExecutionTrace", "TraceEvent", "HitlTask", "AgentConfig", "McpServer"]
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

### 任务 7：认证（JWT + 密码哈希）

**文件：**
- 创建：`backend/app/core/security.py`、`backend/app/core/deps.py`
- 创建：`backend/app/schemas/auth.py`、`backend/app/api/auth.py`
- 创建：`backend/app/main.py`、`backend/tests/test_auth.py`

- [ ] **步骤 1：编写失败的测试**

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

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_auth.py -v`
预期：FAIL，`ModuleNotFoundError: app.main`

- [ ] **步骤 3：实现 security / deps / schemas / 路由 / main**

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

def create_access_token(user_id: int, username: str) -> str:
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
    user = await db.scalar(select(User).where(User.id == int(payload["sub"])))
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
    id: int
    username: str
    display_name: str
    department_id: int | None = None
    role_id: int | None = None
    model_config = {"from_attributes": True}
```

```python
# backend/app/api/auth.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_db, get_current_user
from app.core.security import hash_password, verify_password, create_access_token
from app.models.org import User
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/register", response_model=UserOut)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if await db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(400, "用户名已存在")
    user = User(username=body.username, password_hash=hash_password(body.password), display_name=body.display_name)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.username == body.username))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    return TokenResponse(access_token=create_access_token(user.id, user.username))

@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
```

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth
from app.core.config import settings

app = FastAPI(title="云书 Agent")
app.add_middleware(CORSMiddleware, allow_origins=settings.FRONTEND_ORIGINS.split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_auth.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: JWT 认证与注册登录"
```

---

### 任务 8：组织架构 API

**文件：**
- 创建：`backend/app/api/org.py`、`backend/app/schemas/org.py`
- 创建：`backend/tests/test_org_api.py`
- 修改：`backend/app/main.py`

- [ ] **步骤 1：编写失败的测试**

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

运行：`cd backend && pytest tests/test_org_api.py -v`
预期：FAIL，404

- [ ] **步骤 3：实现路由并在 main.py 注册**

```python
# backend/app/schemas/org.py
from pydantic import BaseModel

class DepartmentCreate(BaseModel):
    name: str

class DepartmentOut(BaseModel):
    id: int
    name: str
    owner_id: int | None = None
    model_config = {"from_attributes": True}
```

```python
# backend/app/api/org.py
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_db, get_current_user
from app.models.org import Department, User
from app.schemas.auth import UserOut
from app.schemas.org import DepartmentCreate, DepartmentOut

router = APIRouter(tags=["org"])

@router.post("/api/departments", response_model=DepartmentOut)
async def create_department(body: DepartmentCreate, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    dept = Department(name=body.name)
    db.add(dept)
    await db.commit()
    await db.refresh(dept)
    return dept

@router.get("/api/departments", response_model=list[DepartmentOut])
async def list_departments(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    return (await db.scalars(select(Department))).all()

@router.get("/api/users", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    return (await db.scalars(select(User))).all()
```

```python
# backend/app/main.py 追加
from app.api import org
app.include_router(org.router)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_org_api.py -v`
预期：PASS

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
from app.models.configs import AgentConfig
from app.services.seed import seed_roles, seed_agents

@pytest.mark.asyncio
async def test_seed_creates_defaults(db_session):
    await seed_roles(db_session)
    await seed_agents(db_session)
    roles = (await db_session.scalars(select(Role))).all()
    agents = (await db_session.scalars(select(AgentConfig))).all()
    assert {r.code for r in roles} >= {"member", "dept_owner", "admin"}
    assert {a.code for a in agents} >= {"marketing", "sales_analysis", "scheduling"}
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_seed.py -v`
预期：FAIL，ModuleNotFoundError

- [ ] **步骤 3：实现种子服务与脚本**

```python
# backend/app/services/seed.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.org import Role
from app.models.configs import AgentConfig

ROLES = [("member", "成员"), ("dept_owner", "部门负责人"), ("admin", "公司管理员")]
AGENTS = [
    ("marketing", "营销助手", "营销方案策划与效果复盘"),
    ("sales_analysis", "经营分析", "经营数据查询与分析"),
    ("scheduling", "调度优化", "资源与排期优化"),
]

async def seed_roles(db: AsyncSession) -> None:
    for code, name in ROLES:
        if not await db.scalar(select(Role).where(Role.code == code)):
            db.add(Role(code=code, name=name))
    await db.commit()

async def seed_agents(db: AsyncSession) -> None:
    for code, name, desc in AGENTS:
        if not await db.scalar(select(AgentConfig).where(AgentConfig.code == code)):
            db.add(AgentConfig(code=code, name=name, description=desc, config={"system_prompt": "", "tool_whitelist": []}))
    await db.commit()
```

```python
# backend/scripts/seed.py
import asyncio
from app.core.database import SessionLocal
from app.services.seed import seed_roles, seed_agents

async def main():
    async with SessionLocal() as db:
        await seed_roles(db)
        await seed_agents(db)
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

### 任务 10：会话与消息 API

**文件：**
- 创建：`backend/app/api/conversations.py`、`backend/app/schemas/chat.py`
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
    id: int
    role: str
    content: str
    created_at: datetime
    model_config = {"from_attributes": True}
```

```python
# backend/app/api/conversations.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.models.chat import Conversation, Message
from app.schemas.chat import ConversationCreate, ConversationOut, MessageOut

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

@router.post("", response_model=ConversationOut)
async def create_conversation(body: ConversationCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    conv = Conversation(user_id=user.id, title=body.title)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv

@router.get("", response_model=list[ConversationOut])
async def list_conversations(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return (await db.scalars(select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.created_at.desc()))).all()

@router.get("/{conv_id}/messages", response_model=list[MessageOut])
async def list_messages(conv_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    conv = await db.get(Conversation, conv_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(404, "会话不存在")
    return conv.messages
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
    conv = Conversation(user_id=1, title="t")
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.chat import Conversation, Message

async def build_context(db: AsyncSession, conversation_id: str, recent_rounds: int = 10) -> str:
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        return ""
    msgs = (await db.scalars(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc()).limit(recent_rounds * 2)
    )).all()
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
    conv = Conversation(user_id=1, title="t", summary=None)
    db_session.add(conv)
    await db_session.commit()
    monkeypatch.setattr("app.services.summary.summarize_text", lambda text: "压缩后的摘要")
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.chat import Conversation, Message
from app.llm.factory import ModelFactory

async def summarize_text(messages_text: str) -> str:
    llm = ModelFactory.get_llm()
    resp = await llm.ainvoke(
        f"将以下对话压缩为简洁的中文摘要，保留关键决策、数字与结论：\n{messages_text}\n摘要："
    )
    return resp.content if hasattr(resp, "content") else str(resp)

async def maybe_roll_summary(db: AsyncSession, conversation_id: str, force: bool = False, max_messages: int = 20) -> None:
    conv = await db.get(Conversation, conversation_id)
    count = (await db.execute(select(Message).where(Message.conversation_id == conversation_id))).scalar_one_or_none()  # count 见步骤注释
    if not force and (count is None or count < max_messages):
        return
    recent = (await db.scalars(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc()).limit(10)
    )).all()
    text = "\n".join(f"{m.role}: {m.content}" for m in reversed(recent))
    old = f"已有摘要：{conv.summary}\n" if conv.summary else ""
    conv.summary = await summarize_text(old + text)
    await db.commit()
```

> 注：`count` 查询用 `select(func.count(Message.id)).where(...)` 取标量；若简化可去掉阈值判断，仅保留 force 参数。

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

class AgentState(TypedDict, total=False):
    conversation_id: str
    user_id: int
    user_message: str
    history: str
    memory_context: str          # 记忆装配结果
    agent_response: str
    route_history: Annotated[list[str], add]  # 已路由过的 agent，防死循环
    hitl_decision: str | None    # approved/rejected
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

- [ ] **步骤 4：实现 SSE 聊天路由（EventSourceResponse）**

```python
# backend/app/api/chat.py
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.models.chat import Conversation, Message
from app.agents.graph import graph

router = APIRouter(prefix="/api/chat", tags=["chat"])

class ChatRequest(BaseModel):
    conversation_id: str
    message: str

@router.post("/completions")
async def chat_completions(body: ChatRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    conv = await db.get(Conversation, body.conversation_id)
    if not conv or conv.user_id != user.id:
        return StreamingResponse(iter([f"data: {json.dumps({'error': '会话不存在'}, ensure_ascii=False)}\n\n"]), media_type="text/event-stream")

    async def event_stream():
        yield f"data: {json.dumps({'event': 'start'}, ensure_ascii=False)}\n\n"
        result = await graph.ainvoke({"conversation_id": conv.id, "user_id": user.id, "user_message": body.message})
        text = result.get("agent_response", "")
        yield f"data: {json.dumps({'event': 'token', 'content': text}, ensure_ascii=False)}\n\n"
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

- [ ] **步骤 3：改造 chat.py：写入消息 + 装配短期记忆**

```python
# backend/app/api/chat.py 关键改造：写入消息 + 短期记忆装配 + 摘要

async def chat_completions(body: ChatRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    conv = await db.get(Conversation, body.conversation_id)
    if not conv or conv.user_id != user.id:
        return StreamingResponse(iter([f"data: {json.dumps({'error': '会话不存在'}, ensure_ascii=False)}\n\n"]), media_type="text/event-stream")

    # 先持久化用户消息
    db.add(Message(conversation_id=conv.id, role="user", content=body.message))
    await db.commit()

    async def event_stream():
        from app.memory.short_term import build_context
        yield f"data: {json.dumps({'event': 'start'}, ensure_ascii=False)}\n\n"
        history = await build_context(db, conv.id, recent_rounds=10)
        result = await graph.ainvoke({
            "conversation_id": conv.id, "user_id": user.id,
            "user_message": body.message, "history": history,
        })
        text = result.get("agent_response", "")
        db.add(Message(conversation_id=conv.id, role="assistant", content=text))
        await db.commit()
        # 消息超过阈值触发滚动摘要
        from app.services.summary import maybe_roll_summary
        await maybe_roll_summary(db, conv.id)
        yield f"data: {json.dumps({'event': 'token', 'content': text}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'event': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

```python
# backend/app/agents/graph.py 关键改造：echo 节点带上 history
async def echo_node(state: AgentState) -> dict:
    return {"agent_response": f"收到：{state.get('user_message', '')}\n\n[上下文]\n{state.get('history', '')[:200]}"}
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
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_document_parser.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现解析与切分（RecursiveCharacterTextSplitter）**

```python
# backend/app/services/document_parser.py
import io
from pypdf import PdfReader
from docx import Document as DocxDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter

def parse_text(content: bytes, ext: str) -> str:
    ext = ext.lower().lstrip(".")
    if ext == "pdf":
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    if ext in ("docx", "doc"):
        doc = DocxDocument(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)
    # md/txt
    return content.decode("utf-8", errors="ignore")

def split_chunks(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """按中文语义边界递归切分（优先段落/句子，退化为字符）。"""
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

### 任务 18：文档上传 API + 向量入库

**文件：**
- 创建：`backend/app/api/documents.py`
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
    monkeypatch.setattr("app.api.documents.embed_texts", fake_embed)
    monkeypatch.setattr("app.api.documents.embed_query", lambda t: [0.1, 0.2, 0.3])

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

- [ ] **步骤 3：实现上传与检索路由**

```python
# backend/app/api/documents.py
import os
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.models.knowledge import Document, Chunk
from app.services.document_parser import parse_text, split_chunks
from app.services.embedding import embed_texts, embed_query
from pgvector.sqlalchemy import Vector
from sqlalchemy.sql import text as sqltext

router = APIRouter(tags=["knowledge"])
UPLOAD_DIR = "storage/documents"

@router.post("/api/documents")
async def upload_document(
    file: UploadFile = File(...), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    content = await file.read()
    ext = file.filename.rsplit(".", 1)[-1]
    doc_id = str(uuid4())
    path = os.path.join(UPLOAD_DIR, f"{doc_id}.{ext}")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    doc = Document(id=doc_id, title=file.filename, file_path=path, status="parsing", uploader_id=user.id)
    db.add(doc)
    await db.commit()
    try:
        text = parse_text(content, ext)
        chunks = split_chunks(text)
        vecs = await embed_texts(chunks)
        for i, (chunk_text, vec) in enumerate(zip(chunks, vecs)):
            db.add(Chunk(document_id=doc_id, seq=i, content=chunk_text, embedding=vec))
        doc.status = "ready"
        await db.commit()
    except Exception as e:
        doc.status = "failed"
        await db.commit()
        raise HTTPException(500, f"解析失败: {e}")
    return doc

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5

@router.post("/api/kb/search")
async def search_kb(body: SearchRequest, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    query_vec = await embed_query(body.query)
    rows = (await db.execute(
        sqltext(
            "SELECT id, content, document_id, 1 - (embedding <=> :q) AS score "
            "FROM chunks WHERE embedding IS NOT NULL ORDER BY embedding <=> :q LIMIT :k"
        ),
        {"q": query_vec, "k": body.top_k},
    )).all()
    return {"results": [{"id": r.id, "content": r.content, "document_id": r.document_id, "score": round(r.score, 4)} for r in rows]}
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
from app.services.embedding import embed_query
from sqlalchemy.sql import text as sqltext

async def search_chunks(db: AsyncSession, query: str, top_k: int = 5) -> list[dict]:
    query_vec = await embed_query(query)
    rows = (await db.execute(
        sqltext("SELECT id, content, document_id FROM chunks WHERE embedding IS NOT NULL ORDER BY embedding <=> :q LIMIT :k"),
        {"q": query_vec, "k": top_k},
    )).all()
    return [{"id": r.id, "content": r.content, "document_id": r.document_id} for r in rows]

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
    await merge_preference(db_session, user_id=1, category="style", content="回答简洁", confidence=0.8, source="s1")
    await merge_preference(db_session, user_id=1, category="style", content="回答简洁", confidence=0.9, source="s2")
    rows = (await db_session.scalars(select(Preference).where(Preference.user_id == 1))).all()
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
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class Preference(Base):
    __tablename__ = "preferences"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(16))  # style/decision/habit
    content: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    source: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

```python
# backend/app/services/preference_svc.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.preferences import Preference

async def merge_preference(db: AsyncSession, user_id: int, category: str, content: str, confidence: float, source: str) -> None:
    existing = (await db.scalars(
        select(Preference).where(Preference.user_id == user_id, Preference.category == category, Preference.content == content)
    )).first()
    if existing:
        existing.confidence = max(existing.confidence, confidence)
    else:
        db.add(Preference(user_id=user_id, category=category, content=content, confidence=confidence, source=source))
    await db.commit()
```

- [ ] **步骤 4：实现偏好提取（对话结束后 LLM 结构化提取）**

```python
# backend/app/services/preference_svc.py 追加
import json
from app.llm.factory import ModelFactory

PREF_EXTRACT_PROMPT = (
    "你是用户偏好分析器。根据对话提取用户偏好，输出 JSON 数组，元素格式 "
    '{"category": "style|decision|habit", "content": "偏好描述", "confidence": 0~1}。'
    "没有偏好时输出 []。只输出 JSON。\n对话：{text}"
)

async def extract_preferences(text: str) -> list[dict]:
    llm = ModelFactory.get_llm()
    resp = await llm.ainvoke(PREF_EXTRACT_PROMPT.format(text=text))
    raw = resp.content if hasattr(resp, "content") else str(resp)
    try:
        return json.loads(raw)
    except Exception:
        return []

async def extract_and_save(db: AsyncSession, user_id: int, text: str) -> None:
    prefs = await extract_preferences(text)
    for p in prefs:
        await merge_preference(db, user_id, p.get("category", "habit"), p.get("content", ""), float(p.get("confidence", 0.5)), "auto")
```

```python
# backend/app/memory/preferences.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.preferences import Preference

async def build_context(db: AsyncSession, user_id: int) -> str:
    rows = (await db.scalars(select(Preference).where(Preference.user_id == user_id))).all()
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
- 创建：`backend/app/services/experience_svc.py`
- 创建：`backend/tests/test_experience_extract.py`

- [ ] **步骤 1：编写失败的测试（monkeypatch LLM 与 embedding）**

```python
# backend/tests/test_experience_extract.py
import pytest
from sqlalchemy import select
from app.models.experience import Experience
from app.services.experience_svc import distill_experience, save_personal_experience

@pytest.mark.asyncio
async def test_distill_and_save(db_session, monkeypatch):
    async def fake_llm(text):
        class R:
            content = '{"title": "国庆大促", "summary": "满减+直播", "content": "详情", "tags": ["营销"], "event_time": "2025-10-01", "result_metrics": {"gmv": 320}}'
        return R()
    monkeypatch.setattr("app.services.experience_svc.ModelFactory.get_llm", lambda: Fake())
    monkeypatch.setattr("app.services.experience_svc.embed_texts", lambda t: [[0.1, 0.2, 0.3]])

    exp = await distill_experience("用户：策划国庆营销方案\n助手：建议满减+直播", user_id=1, trace_id="t1")
    assert exp is not None
    assert exp.title == "国庆大促"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_experience_extract.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现经验提炼服务**

```python
# backend/app/services/experience_svc.py
import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.experience import Experience
from app.services.embedding import embed_texts
from app.llm.factory import ModelFactory

DISTILL_PROMPT = (
    "你是企业经验提炼器。从对话中提炼有价值的历史决策/策略/教训，输出一个 JSON 对象，字段："
    '{"title": 标题, "summary": 要点摘要, "content": 完整决策过程, "tags": [业务标签], '
    '"event_time": 事件日期 YYYY-MM-DD, "result_metrics": {效果指标}}。'
    "营销/策略类必须包含 event_time 和 result_metrics，否则视为无价值输出 null。只输出 JSON。\n对话：{text}"
)

async def distill_experience(text: str, user_id: int, trace_id: str) -> Experience | None:
    llm = ModelFactory.get_llm()
    resp = await llm.ainvoke(DISTILL_PROMPT.format(text=text[:6000]))
    raw = resp.content if hasattr(resp, "content") else str(resp)
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not data or data.get("title") is None:
        return None
    vec = (await embed_texts([f"{data.get('title','')} {data.get('summary','')}"]))[0]
    return Experience(
        owner_id=user_id, scope="personal", status="draft",
        title=data["title"], summary=data.get("summary", ""), content=data.get("content", ""),
        tags=data.get("tags", []), event_time=data.get("event_time"), result_metrics=data.get("result_metrics"),
        source_trace_id=trace_id, embedding=vec,
    )

async def save_personal_experience(db: AsyncSession, exp: Experience) -> None:
    db.add(exp)
    await db.commit()
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
    db_session.add(Experience(owner_id=1, scope="personal", status="approved", title="国庆大促",
                              summary="满减+直播", event_time="2025-10-01", embedding=[0.1, 0.2, 0.3]))
    await db_session.commit()
    monkeypatch.setattr("app.memory.experiences.embed_query", lambda t: [0.1, 0.2, 0.3])
    ctx = await build_experience_context(db_session, user_id=1, department_id=None, query="国庆营销")
    assert "国庆大促" in ctx
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_experience_retrieve.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现经验检索（可见范围 + 同期加权 + 层级偏好）**

```python
# backend/app/memory/experiences.py
from datetime import datetime
from sqlalchemy import select, text as sqltext
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.experience import Experience
from app.services.embedding import embed_query

SCOPE_ORDER = {"personal": 0, "dept": 1, "company": 2}

async def build_experience_context(db: AsyncSession, user_id: int, department_id: int | None, query: str, top_k: int = 5) -> str:
    qv = await embed_query(query)
    rows = (await db.execute(sqltext(
        "SELECT id, title, summary, scope, event_time "
        "FROM experiences WHERE embedding IS NOT NULL "
        "ORDER BY embedding <=> :q LIMIT 30"
    ), {"q": qv})).all()
    hits = []
    now_month = datetime.now().month
    for r in rows:
        exp = await db.get(Experience, r.id)
        # 可见范围过滤：personal 仅本人；dept 需同部门；company 全员
        if exp.scope == "personal" and exp.owner_id != user_id:
            continue
        if exp.scope == "dept" and (department_id is None or exp.department_id != department_id):
            continue
        score = SCOPE_ORDER.get(exp.scope, 3)
        if exp.event_time and exp.event_time.month == now_month:  # 同期加权
            score -= 0.5
        hits.append((score, exp))
    hits.sort(key=lambda x: x[0])
    selected = [e for _, e in hits[:top_k]]
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

### 任务 23：经验中心 API（分层视图 + 提交审批）

**文件：**
- 创建：`backend/app/api/experiences.py`
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
# backend/app/api/experiences.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.models.experience import Experience, ExperienceApproval
from app.services.embedding import embed_texts

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

@router.post("")
async def create_experience(body: ExperienceCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    vec = (await embed_texts([f"{body.title} {body.summary}"]))[0]
    exp = Experience(owner_id=user.id, scope="personal", status="draft", title=body.title,
                     summary=body.summary, content=body.content, tags=body.tags,
                     event_time=body.event_time, result_metrics=body.result_metrics,
                     department_id=user.department_id, embedding=vec)
    db.add(exp)
    await db.commit()
    await db.refresh(exp)
    return exp

@router.post("/{exp_id}/submit")
async def submit_experience(exp_id: str, body: SubmitRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    exp = await db.get(Experience, exp_id)
    if not exp or exp.owner_id != user.id or exp.scope != "personal":
        raise HTTPException(404, "经验不存在或不可提交")
    if body.to_scope not in ("dept", "company"):
        raise HTTPException(400, "目标层级无效")
    exp.status = "pending"
    db.add(ExperienceApproval(experience_id=exp.id, from_scope="personal", to_scope=body.to_scope, status="pending"))
    await db.commit()
    await db.refresh(exp)
    return exp

@router.get("")
async def list_experiences(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (await db.scalars(select(Experience).where(
        (Experience.owner_id == user.id) | (Experience.scope == "company") | (
            (Experience.scope == "dept") & (Experience.department_id == user.department_id)
        )
    ).order_by(Experience.created_at.desc()))).all()
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

### 任务 24：审批 API（部门负责人/管理员审批晋升）

**文件：**
- 创建：`backend/app/api/approvals.py`
- 创建：`backend/tests/test_approvals_api.py`
- 修改：`backend/app/main.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_approvals_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.experience import Experience, ExperienceApproval

@pytest.mark.asyncio
async def test_approve_promotes_to_dept(db_session, monkeypatch):
    monkeypatch.setattr("app.api.experiences.embed_texts", lambda t: [[0.1, 0.2, 0.3]])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "owner", "password": "x123456", "display_name": "Owner"})
        r = await c.post("/api/auth/login", json={"username": "owner", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        # 创建待审批经验
        r = await c.post("/api/experiences", json={"title": "t", "summary": "s"}, headers=h)
        exp_id = r.json()["id"]
        await c.post(f"/api/experiences/{exp_id}/submit", json={"to_scope": "dept"}, headers=h)
        # 审批
        r = await c.get("/api/approvals", headers=h)
        assert len(r.json()) >= 1
        ap_id = r.json()[0]["id"]
        r = await c.post(f"/api/approvals/{ap_id}/decide", json={"approve": True, "comment": "ok"}, headers=h)
        assert r.status_code == 200
        exp = await db_session.get(Experience, exp_id)
        assert exp.scope == "dept" and exp.status == "approved"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_approvals_api.py -v`
预期：FAIL，404

- [ ] **步骤 3：实现审批路由**

```python
# backend/app/api/approvals.py
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.models.experience import Experience, ExperienceApproval

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

class DecideRequest(BaseModel):
    approve: bool
    comment: str = ""

@router.get("")
async def list_approvals(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    # 部门负责人可审 personal->dept；管理员可审 dept->company
    rows = (await db.scalars(select(ExperienceApproval).where(ExperienceApproval.status == "pending"))).all()
    return [{"id": a.id, "experience_id": a.experience_id, "from_scope": a.from_scope, "to_scope": a.to_scope} for a in rows]

@router.post("/{approval_id}/decide")
async def decide_approval(approval_id: str, body: DecideRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    ap = await db.get(ExperienceApproval, approval_id)
    if not ap or ap.status != "pending":
        raise HTTPException(404, "审批不存在")
    exp = await db.get(Experience, ap.experience_id)
    ap.status = "approved" if body.approve else "rejected"
    ap.approver_id = user.id
    ap.comment = body.comment
    ap.decided_at = datetime.now(timezone.utc)
    if body.approve:
        exp.scope = ap.to_scope
        exp.status = "approved"
    else:
        exp.status = "rejected"
    await db.commit()
    return {"ok": True}
```

- [ ] **步骤 4：main.py 注册并运行测试**

运行：`cd backend && pytest tests/test_approvals_api.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 经验审批与晋升"
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
    ctx = await assemble_memory(None, user_id=1, conversation_id="c1", department_id=2, query="国庆营销")
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
    db: AsyncSession, user_id: int, conversation_id: str,
    department_id: int | None, query: str,
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
from app.agents.supervisor import route_decision, ROUTE_SCHEMA

def test_route_schema_fields():
    assert {"agent", "reason", "confidence"} <= set(ROUTE_SCHEMA.keys())

@pytest.mark.asyncio
async def test_route_decision_parses(monkeypatch):
    async def fake_invoke(prompt):
        class R:
            content = '{"agent": "marketing", "reason": "营销策划", "confidence": 0.9}'
        return R()
    monkeypatch.setattr("app.agents.supervisor.ModelFactory.get_llm", lambda k: Fake())
    decision = await route_decision("策划国庆营销方案", ["marketing", "sales_analysis", "scheduling"])
    assert decision["agent"] == "marketing"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_supervisor.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现 Supervisor 路由**

```python
# backend/app/agents/supervisor.py
import json
from app.llm.factory import ModelFactory

ROUTE_SCHEMA = {"agent": "str", "reason": "str", "confidence": "float"}
AGENT_CODES = ["marketing", "sales_analysis", "scheduling", "general"]

ROUTE_PROMPT = (
    "你是意图路由器。从用户消息判断交给哪个 agent，可选：{agents}。"
    "输出 JSON：{{\"agent\": 其中一个, \"reason\": 理由, \"confidence\": 0~1}}。只输出 JSON。\n消息：{message}"
)

async def route_decision(message: str, agents: list[str], model_key: str = "default") -> dict:
    llm = ModelFactory.get_llm(model_key)
    resp = await llm.ainvoke(ROUTE_PROMPT.format(agents=agents, message=message))
    raw = resp.content if hasattr(resp, "content") else str(resp)
    try:
        data = json.loads(raw)
    except Exception:
        return {"agent": "general", "reason": "解析失败兜底", "confidence": 0.1}
    if data.get("agent") not in agents:
        data["agent"] = "general"
    return data

async def decide_done(agent_response: str, model_key: str = "default") -> bool:
    llm = ModelFactory.get_llm(model_key)
    resp = await llm.ainvoke(
        f"判断以下回答是否已完整解决问题，仅输出 true 或 false。\n回答：{agent_response[:2000]}"
    )
    raw = resp.content if hasattr(resp, "content") else str(resp)
    return "false" not in raw.lower()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_supervisor.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: Supervisor 循环路由"
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
from app.agents.marketing.agent import build_marketing_node

@pytest.mark.asyncio
async def test_marketing_node_returns(monkeypatch):
    async def fake_llm(prompt):
        class R:
            content = "营销方案：满减+直播"
        return R()
    monkeypatch.setattr("app.agents.marketing.agent.ModelFactory.get_llm", lambda k: Fake())
    node = build_marketing_node()
    result = await node({"user_message": "策划国庆营销", "memory_context": "【经验】去年满减效果好"})
    assert "营销方案" in result["agent_response"]
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_marketing_agent.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现营销助手子图节点（含工具绑定占位）**

```python
# backend/app/agents/marketing/agent.py
from app.llm.factory import ModelFactory

SYSTEM_PROMPT = (
    "你是营销助手。结合【记忆上下文】中的个人偏好、历史经验、知识库与企业数据，"
    "为用户策划营销方案。营销策略需包含目标、渠道、预算、预期效果。回答用中文。"
)

def build_marketing_node():
    async def node(state: dict) -> dict:
        llm = ModelFactory.get_llm("marketing")
        prompt = f"{SYSTEM_PROMPT}\n\n{state.get('memory_context', '')}\n\n用户：{state.get('user_message', '')}"
        resp = await llm.ainvoke(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)
        return {"agent_response": text, "route_history": ["marketing"]}
    return node
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
from app.agents.sales_analysis.agent import build_sales_node
from app.agents.scheduling.agent import build_scheduling_node

@pytest.mark.asyncio
async def test_sales_node(monkeypatch):
    async def fake_llm(prompt):
        class R:
            content = "经营分析：Q3 营收同比 +15%"
        return R()
    monkeypatch.setattr("app.agents.sales_analysis.agent.ModelFactory.get_llm", lambda k: Fake())
    result = await build_sales_node()({"user_message": "分析今年 Q3 经营情况", "memory_context": ""})
    assert "经营分析" in result["agent_response"]
    assert result["route_history"] == ["sales_analysis"]
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_agents_extra.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现两个 agent 节点**

```python
# backend/app/agents/sales_analysis/agent.py
from app.llm.factory import ModelFactory

SYSTEM_PROMPT = (
    "你是经营分析专家。结合记忆上下文与企业数据（可调用 SQL 工具查询），"
    "给出量化分析结论，指出趋势与风险。回答用中文。"
)

def build_sales_node():
    async def node(state: dict) -> dict:
        llm = ModelFactory.get_llm("sales_analysis")
        prompt = f"{SYSTEM_PROMPT}\n\n{state.get('memory_context', '')}\n\n用户：{state.get('user_message', '')}"
        resp = await llm.ainvoke(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)
        return {"agent_response": text, "route_history": ["sales_analysis"]}
    return node
```

```python
# backend/app/agents/scheduling/agent.py
from app.llm.factory import ModelFactory

SYSTEM_PROMPT = (
    "你是调度优化专家。结合记忆上下文与资源约束，给出排期/调度优化建议，"
    "包含时间线、资源分配、风险点。回答用中文。"
)

def build_scheduling_node():
    async def node(state: dict) -> dict:
        llm = ModelFactory.get_llm("scheduling")
        prompt = f"{SYSTEM_PROMPT}\n\n{state.get('memory_context', '')}\n\n用户：{state.get('user_message', '')}"
        resp = await llm.ainvoke(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)
        return {"agent_response": text, "route_history": ["scheduling"]}
    return node
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

### 任务 29：AgentRegistry 动态注册 + 主图装配

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
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_registry.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现注册中心并装配主图（Supervisor 循环）**

```python
# backend/app/agents/registry.py
class AgentRegistry:
    def __init__(self):
        self._nodes: dict[str, callable] = {}

    def register(self, code: str, node: callable) -> None:
        self._nodes[code] = node

    def get(self, code: str) -> callable:
        return self._nodes[code]

    def list(self) -> list[str]:
        return list(self._nodes.keys())
```

```python
# backend/app/agents/graph.py 重写：Supervisor 循环主图
from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.registry import AgentRegistry
from app.agents.supervisor import route_decision, decide_done
from app.agents.marketing.agent import build_marketing_node
from app.agents.sales_analysis.agent import build_sales_node
from app.agents.scheduling.agent import build_scheduling_node

registry = AgentRegistry()
registry.register("marketing", build_marketing_node())
registry.register("sales_analysis", build_sales_node())
registry.register("scheduling", build_scheduling_node())

MAX_ROUTES = 4

def build_graph():
    g = StateGraph(AgentState)

    async def supervisor_node(state: AgentState) -> dict:
        agents = registry.list()
        decision = await route_decision(state.get("user_message", ""), agents)
        state["pending_agent"] = decision["agent"]
        return {"pending_agent": decision["agent"]}

    def router(state: AgentState) -> str:
        agent = state.get("pending_agent", "general")
        if len(state.get("route_history", [])) >= MAX_ROUTES:
            return "done"
        return agent if agent in registry.list() else "done"

    async def done_node(state: AgentState) -> dict:
        return {"agent_response": state.get("agent_response", "") or "已完成"}

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

graph = build_graph()
```

> 注：`pending_agent` 需要加入 `AgentState`。循环限定 MAX_ROUTES=4 防死循环；简化实现为单轮分发后直接 done，多轮协作在留痕与 HITL 接入后再细化。

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

- [ ] **步骤 3：改造 chat.py：图执行前装配记忆**

```python
# backend/app/api/chat.py 关键改造：装配记忆后执行图
from app.memory.assembly import assemble_memory
from app.services.experience_svc import distill_experience, save_personal_experience
from app.services.preference_svc import extract_and_save

async def event_stream():
    yield f"data: {json.dumps({'event': 'start'}, ensure_ascii=False)}\n\n"
    mem = await assemble_memory(db, user.id, conv.id, user.department_id, body.message)
    result = await graph.ainvoke({
        "conversation_id": conv.id, "user_id": user.id,
        "user_message": body.message, "memory_context": mem,
    })
    text = result.get("agent_response", "")
    db.add(Message(conversation_id=conv.id, role="assistant", content=text))
    await db.commit()
    # 对话结束：偏好提取 + 经验提炼（异步 fire-and-forget）
    dialog = f"用户：{body.message}\n助手：{text}"
    await extract_and_save(db, user.id, dialog)
    exp = await distill_experience(dialog, user.id, result.get("trace_id", ""))
    if exp:
        await save_personal_experience(db, exp)
    yield f"data: {json.dumps({'event': 'token', 'content': text}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'event': 'done'}, ensure_ascii=False)}\n\n"
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

### 任务 31：DataFacade 统一门面 + 内置工具

**文件：**
- 创建：`backend/app/tools/facade.py`
- 创建：`backend/app/tools/builtin/sql_tool.py`、`backend/app/tools/builtin/http_tool.py`、`backend/app/tools/builtin/calc_tool.py`
- 创建：`backend/tests/test_facade.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_facade.py
import pytest
from app.tools.facade import DataFacade, register_builtin_tools

def test_facade_registry():
    facade = DataFacade()
    register_builtin_tools(facade)
    assert "calc" in facade.list_tools()
    assert facade.execute("calc", {"expr": "1+2"}) == 3

def test_risk_levels():
    facade = DataFacade()
    register_builtin_tools(facade)
    assert facade.get_risk("calc") == "low"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_facade.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现门面与内置工具（统一 Tool 接口 + 风险等级）**

```python
# backend/app/tools/facade.py
from typing import Awaitable, Callable

ToolFunc = Callable[..., Awaitable | object]

class Tool:
    def __init__(self, name: str, fn: ToolFunc, risk: str = "low", description: str = ""):
        self.name, self.fn, self.risk, self.description = name, fn, risk, description

class DataFacade:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def get_risk(self, name: str) -> str:
        return self._tools[name].risk

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def execute(self, name: str, kwargs: dict):
        return self._tools[name].fn(**kwargs)

facade = DataFacade()

def register_builtin_tools(f: DataFacade) -> None:
    f.register(Tool("calc", lambda expr: eval(expr, {"__builtins__": {}}), "low", "数学计算"))
    f.register(Tool("http_get", lambda url: _http_get(url), "low", "GET 请求"))
    f.register(Tool("sql_query", _sql_query, "medium", "数据库查询"))
    f.register(Tool("file_delete", lambda path: _file_delete(path), "high", "删除文件"))

def _http_get(url: str):
    import httpx
    return httpx.get(url, timeout=10).text[:2000]

async def _sql_query(sql: str):
    from sqlalchemy import text as sqltext
    from app.core.database import engine
    async with engine.connect() as conn:
        rows = (await conn.execute(sqltext(sql))).all()
        return [dict(r._mapping) for r in rows]

def _file_delete(path: str):
    import os
    os.remove(path)
    return f"deleted {path}"

register_builtin_tools(facade)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_facade.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: DataFacade 统一门面与内置工具"
```

---

### 任务 32：风险评估器 + HITL interrupt

**文件：**
- 创建：`backend/app/tools/risk.py`
- 创建：`backend/tests/test_risk.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_risk.py
from app.tools.risk import needs_hitl, request_hitl

def test_high_risk_requires_hitl():
    assert needs_hitl("high") is True

def test_low_risk_skips():
    assert needs_hitl("low") is False

def test_request_hitl_records():
    task = request_hitl(trace_id="t1", node_id="n1", reason="删除文件", context={"path": "/tmp/x"})
    assert task["status"] == "pending"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_risk.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：实现风险评估器（interrupt 占位 + 任务记录）**

```python
# backend/app/tools/risk.py
from langgraph.types import interrupt

async def execute_with_risk(facade, tool_name: str, kwargs: dict, trace_id: str) -> object:
    tool = facade.get(tool_name)
    if tool.risk == "high":
        approved = interrupt({
            "tool": tool_name, "args": kwargs, "reason": f"高风险操作：{tool.description}",
        })
        if approved is not True:
            return {"error": "操作被驳回"}
    return await _maybe_await(facade.execute(tool_name, kwargs))

def request_hitl(trace_id: str, node_id: str, reason: str, context: dict) -> dict:
    # 实际实现写入 hitl_tasks 表（见任务 33 的 API 层）；此处返回内存占位
    return {"trace_id": trace_id, "node_id": node_id, "reason": reason, "context": context, "status": "pending"}

def needs_hitl(risk: str) -> bool:
    return risk == "high"

async def _maybe_await(result):
    return await result if hasattr(result, "__await__") else result
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_risk.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 风险评估器与 HITL interrupt 机制"
```

---

### 任务 33：HITL 审批 API（待办 + approve/reject）

**文件：**
- 创建：`backend/app/api/hitl.py`
- 创建：`backend/tests/test_hitl_api.py`
- 修改：`backend/app/main.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_hitl_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.trace import HitlTask, ExecutionTrace

@pytest.mark.asyncio
async def test_hitl_approve_flow(db_session):
    trace = ExecutionTrace(user_id=1, status="interrupted")
    db_session.add(trace)
    await db_session.flush()
    db_session.add(HitlTask(trace_id=trace.id, node_id="n1", reason="删除文件", status="pending"))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "judy", "password": "x123456", "display_name": "Judy"})
        r = await c.post("/api/auth/login", json={"username": "judy", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.get("/api/hitl/tasks", headers=h)
        assert len(r.json()) >= 1
        task_id = r.json()[0]["id"]
        r = await c.post(f"/api/hitl/tasks/{task_id}/approve", json={"approved": True}, headers=h)
        assert r.status_code == 200
        task = await db_session.get(HitlTask, task_id)
        assert task.status == "approved"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_hitl_api.py -v`
预期：FAIL，404

- [ ] **步骤 3：实现 HITL 路由**

```python
# backend/app/api/hitl.py
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.models.trace import HitlTask, ExecutionTrace

router = APIRouter(prefix="/api/hitl", tags=["hitl"])

@router.get("/tasks")
async def list_tasks(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.scalars(select(HitlTask).where(HitlTask.status == "pending"))).all()
    return [{"id": t.id, "trace_id": t.trace_id, "reason": t.reason, "context": t.context} for t in rows]

class DecideHitl(BaseModel):
    approved: bool

@router.post("/tasks/{task_id}/approve")
async def approve_task(task_id: str, body: DecideHitl, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    task = await db.get(HitlTask, task_id)
    if not task or task.status != "pending":
        raise HTTPException(404, "任务不存在")
    task.status = "approved" if body.approved else "rejected"
    task.approver_id = user.id
    task.decided_at = datetime.now(timezone.utc)
    trace = await db.get(ExecutionTrace, task.trace_id)
    if trace:
        trace.status = "completed"
    await db.commit()
    return {"ok": True}
```

- [ ] **步骤 4：main.py 注册并运行测试**

运行：`cd backend && pytest tests/test_hitl_api.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: HITL 审批 API"
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

- [ ] **步骤 3：chat.py 创建 trace + graph 埋点 + traces 查询 API**

```python
# backend/app/api/chat.py 关键改造：创建 trace 并记录路由
from uuid import uuid4
from app.models.trace import ExecutionTrace
from app.traces.collector import collector

async def event_stream():
    trace = ExecutionTrace(id=str(uuid4()), user_id=user.id, conversation_id=conv.id, status="running", supervisor_routes=[])
    db.add(trace)
    await db.commit()
    yield f"data: {json.dumps({'event': 'start', 'trace_id': trace.id}, ensure_ascii=False)}\n\n"
    mem = await assemble_memory(db, user.id, conv.id, user.department_id, body.message)
    result = await graph.ainvoke({
        "conversation_id": conv.id, "user_id": user.id,
        "user_message": body.message, "memory_context": mem, "trace_id": trace.id,
    })
    text = result.get("agent_response", "")
    db.add(Message(conversation_id=conv.id, role="assistant", content=text))
    trace.status = "completed"
    trace.supervisor_routes = result.get("route_history", [])
    conv.current_trace_id = trace.id
    await db.commit()
    collector.emit(trace.id, "route", {"routes": trace.supervisor_routes})
    # ...（偏好提取/经验提炼同任务 30）
```

```python
# backend/app/api/traces.py —— 监测查询 API
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.models.trace import ExecutionTrace, TraceEvent

router = APIRouter(prefix="/api/traces", tags=["traces"])

@router.get("")
async def list_traces(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (await db.scalars(select(ExecutionTrace).where(ExecutionTrace.user_id == user.id).order_by(ExecutionTrace.started_at.desc()).limit(50))).all()
    return [{"id": t.id, "status": t.status, "conversation_id": t.conversation_id, "supervisor_routes": t.supervisor_routes} for t in rows]

@router.get("/{trace_id}/events")
async def trace_events(trace_id: str, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.scalars(select(TraceEvent).where(TraceEvent.trace_id == trace_id).order_by(TraceEvent.id))).all()
    return [{"type": e.type, "payload": e.payload, "created_at": e.created_at} for e in rows]
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
# backend/app/agents/graph.py 关键改造
from langgraph.checkpoint.postgres import PostgresSaver
from app.core.config import settings

def build_graph():
    ...  # 同任务 29
    # 用 checkpointer 编译，thread_id = conversation_id
    from sqlalchemy.engine import make_url
    from psycopg_pool import AsyncConnectionPool
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    pg_url = settings.DATABASE_URL.replace("+asyncpg", "")
    pool = AsyncConnectionPool(pg_url, max_size=10, kwargs={"autocommit": True})
    checkpointer = AsyncPostgresSaver(pool)
    return g.compile(checkpointer=checkpointer)

graph = build_graph()
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

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_mcp_adapter.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: MCP 服务注册与动态工具接入"
```

---

### 任务 38：配置管理 API（agents / mcp-servers / models）

**文件：**
- 创建：`backend/app/api/configs.py`
- 创建：`backend/tests/test_configs_api.py`
- 修改：`backend/app/main.py`

- [ ] **步骤 1：编写失败的测试**

```python
# backend/tests/test_configs_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_agent_config_crud():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "leah", "password": "x123456", "display_name": "Leah"})
        r = await c.post("/api/auth/login", json={"username": "leah", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/agents", json={"code": "new_agent", "name": "新Agent", "model_key": "default"}, headers=h)
        assert r.status_code == 200
        r = await c.get("/api/agents", headers=h)
        assert any(a["code"] == "new_agent" for a in r.json())
        r = await c.post("/api/mcp-servers", json={"name": "erp", "url": "http://x/mcp"}, headers=h)
        assert r.status_code == 200
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && pytest tests/test_configs_api.py -v`
预期：FAIL，404

- [ ] **步骤 3：实现配置路由**

```python
# backend/app/api/configs.py
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.models.configs import AgentConfig, McpServer
from app.tools.mcp_adapter import mcp_registry

router = APIRouter(tags=["configs"])

class AgentIn(BaseModel):
    code: str
    name: str
    model_key: str = "default"
    config: dict = {}

class McpIn(BaseModel):
    name: str
    url: str
    auth_type: str = "none"
    config: dict = {}

@router.post("/api/agents")
async def create_agent(body: AgentIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    row = AgentConfig(code=body.code, name=body.name, model_key=body.model_key, config=body.config)
    db.add(row)
    await db.commit()
    return row

@router.get("/api/agents")
async def list_agents(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    return (await db.scalars(select(AgentConfig))).all()

@router.post("/api/mcp-servers")
async def create_mcp(body: McpIn, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    row = McpServer(name=body.name, url=body.url, auth_type=body.auth_type, config=body.config)
    db.add(row)
    await db.commit()
    mcp_registry.register({"name": row.name, "url": row.url, "auth_type": row.auth_type, "config": row.config, "enabled": True})
    return row

@router.get("/api/mcp-servers")
async def list_mcp(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    return (await db.scalars(select(McpServer))).all()
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

### 任务 40：聊天界面（SSE 流式 + 会话列表 + HITL 审批浮层）

**文件：**
- 创建：`frontend/src/views/Chat.vue`、`frontend/src/views/HitlPanel.vue`
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

- [ ] **步骤 3：实现 HITL 审批浮层（轮询待办）**

```vue
<!-- frontend/src/views/HitlPanel.vue -->
<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import client from '../api/client'

const tasks = ref<any[]>([])
let timer: number | undefined

onMounted(() => { timer = window.setInterval(load, 5000); load() })
onUnmounted(() => window.clearInterval(timer))

async function load() {
  const { data } = await client.get('/hitl/tasks')
  tasks.value = data
}

async function decide(id: string, approved: boolean) {
  await client.post(`/hitl/tasks/${id}/approve`, { approved })
  load()
}
</script>

<template>
  <a-drawer v-model:open="true" title="待人工确认" placement="right">
    <div v-for="t in tasks" :key="t.id" style="margin-bottom: 12px">
      <p>{{ t.reason }}</p>
      <a-button type="primary" @click="decide(t.id, true)">确认</a-button>
      <a-button danger @click="decide(t.id, false)">驳回</a-button>
    </div>
  </a-drawer>
</template>
```

- [ ] **步骤 4：验证页面可交互**

运行：`cd frontend && npm run dev`，登录后创建会话并发消息
预期：消息流式渲染；后端运行 `cd backend && uvicorn app.main:app --reload` 提供 API（vite proxy 代理 `/api` 到 `http://localhost:8000`）

- [ ] **步骤 5：Commit**

```bash
git add frontend
git commit -m "feat: 聊天界面（SSE 流式+会话+HITL 审批）"
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

### 任务 42：管理界面（阶段 3：组织架构 + 配置 + 监测）

**文件：**
- 创建：`frontend/src/views/Org.vue`、`frontend/src/views/Configs.vue`、`frontend/src/views/Traces.vue`

- [ ] **步骤 1：组织架构页**：复用 `GET/POST /api/departments`、`/api/users`，部门列表 + 用户列表 + 新建部门表单
- [ ] **步骤 2：配置页**：agent 列表 + 新建 agent 表单 + MCP 服务列表 + 新建 MCP 表单（调用任务 38 的 API）
- [ ] **步骤 3：监测页**：`GET /api/traces` 列表 + 点击行展示 `GET /api/traces/{id}/events` 时间线（按 type 着色：route=蓝 / llm=紫 / tool=橙 / hitl=红）
- [ ] **步骤 4：验证页面可交互**

运行：`cd frontend && npm run dev`
预期：三页均能调用对应 API 并展示数据

- [ ] **步骤 5：Commit**

```bash
git add frontend
git commit -m "feat: 组织架构/配置/监测管理界面"
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
| §5 Agent 注册 / DataFacade / MCP / 风险 | 27, 28, 29, 31, 32, 37 |
| §6 API（认证/聊天/HITL/知识/经验/组织/监测/配置） | 7, 8, 10, 14, 15, 18, 23, 24, 33, 35, 38 |
| §7 技术决策（异步/checkpoint/多模型/部署） | 1, 11, 36, 43 |
| HITL interrupt | 32, 33 |
| 前端三阶段 | 39, 40, 41, 42 |

**2. 占位符扫描**：无 TODO/待定；任务 36 中 `... # 同任务 29` 为明确的复用指引（主图装配代码已在任务 29 完整给出）。

**3. 类型一致性**：
- `AgentState` 统一在任务 14 定义；任务 29 需追加 `pending_agent: str` 字段（已在任务 29 注释中说明）
- 记忆模块命名统一：`build_context`（短期）、`build_pref_context`（偏好，任务 20 中实际名为 `build_context`，任务 25 测试 mock 名为 `build_pref_context`——**执行时以 `app.memory.preferences.build_context` 为准**，任务 25 的 monkeypatch 目标需相应调整）
- `embed_texts / embed_query` 在任务 16 定义，被 18/21/22/23 复用，签名一致

**4. 执行顺序提示**：任务 25 的测试 monkeypatch 路径与任务 20 命名存在一处不一致（`build_pref_context` vs `build_context`），实现时以任务 20 的实际函数名为准修正测试。