# backend/app/main.py
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api import auth, org, chat, conversations, document, experiences, approval, traces, configs
from app.traces.writer import trace_writer_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    """挂载留痕批量落库后台任务：启动时创建，关闭时取消。"""
    task = asyncio.create_task(trace_writer_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="云枢 Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.FRONTEND_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(org.router)
app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(document.router)
app.include_router(experiences.router)
app.include_router(approval.router)
app.include_router(traces.router)
app.include_router(configs.router)