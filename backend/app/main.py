# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api import auth, org, chat, conversations, document

app = FastAPI(title="云枢 Agent")
app.add_middleware(CORSMiddleware, allow_origins=settings.FRONTEND_ORIGINS.split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)
app.include_router(org.router)
app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(document.router)


