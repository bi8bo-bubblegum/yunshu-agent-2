# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api import auth


app = FastAPI(title="云枢 Agent")
app.add_middleware(CORSMiddleware, allow_origins=settings.FRONTEND_ORIGINS.split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)