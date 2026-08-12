# backend/app/main.py
import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import settings
from app.core.response import convert_datetimes_to_beijing
from app.api import auth, org, chat, conversations, document, experiences, approval, traces, configs
from app.traces.writer import trace_writer_loop
from app.services.dingtalk.stream import start_stream_subscriber
from app.agents import graph as graph_module


@asynccontextmanager
async def lifespan(app: FastAPI):
    """挂载常驻后台任务：留痕批量落库 + 钉钉 Stream 事件订阅（可开关）。"""
    task = asyncio.create_task(trace_writer_loop())
    # 钉钉 Stream 常驻：仅当凭证已配置且显式启用时启动，避免本地无钉钉环境报错
    stream_task = None
    if settings.dingtalk_enabled and settings.DINGTALK_STREAM_ENABLED:
        stream_task = asyncio.create_task(start_stream_subscriber())
    # 在应用事件循环中初始化主图（连接池绑定当前 loop，
    # 避免模块导入时用临时事件循环创建连接导致跨 loop 冲突）
    graph_module.graph = await graph_module.get_graph()
    try:
        yield
    finally:
        task.cancel()
        if stream_task:
            stream_task.cancel()


app = FastAPI(title="云枢 Agent", lifespan=lifespan)


@app.middleware("http")
async def beijing_timezone_middleware(request, call_next):
    """API 响应中的时间字段统一输出为北京时间(+08:00)。"""
    response = await call_next(request)
    ctype = response.headers.get("content-type", "")
    if "json" in ctype and request.url.path.startswith("/api"):
        body = b"".join([chunk async for chunk in response.body_iterator])
        try:
            data = json.loads(body)
        except Exception:
            return StreamingResponse(iter([body]), status_code=response.status_code,
                                     media_type=ctype, headers=dict(response.headers))
        data = convert_datetimes_to_beijing(data)
        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers.pop("content-encoding", None)
        return JSONResponse(content=data, status_code=response.status_code,
                            headers=headers)
    return response


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
