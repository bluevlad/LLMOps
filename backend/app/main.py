"""LLMOps FastAPI entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.batch_runs import router as batch_runs_router
from app.api.comparisons import router as comparisons_router
from app.api.golden_set import router as golden_set_router
from app.api.model_monitor import router as model_monitor_router
from app.api.models import router as models_router
from app.api.public import router as public_router
from app.api.usage import router as usage_router
from app.core.config import settings
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.pollers import mlx as mlx_poller
from app.pollers import ollama as ollama_poller

logging.basicConfig(level=logging.INFO if settings.app_debug else logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시 1회 폴링 (대시보드 즉시 표시) — 실패해도 무시
    try:
        await ollama_poller.run_once()
    except Exception:
        pass
    try:
        await mlx_poller.run_once()
    except Exception:
        pass

    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(
        title="LLMOps API",
        version="0.1.0",
        description="로컬 LLM 사용 현황·ROI 통합 관제 — 표준: Ai-Legacy-bluevlad/standards/ai/",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "llmops", "version": "0.1.0"}

    app.include_router(auth_router, prefix="/api")
    app.include_router(models_router, prefix="/api")
    app.include_router(model_monitor_router, prefix="/api")
    app.include_router(batch_runs_router, prefix="/api")
    app.include_router(comparisons_router, prefix="/api")
    app.include_router(usage_router, prefix="/api")
    app.include_router(golden_set_router, prefix="/api")
    app.include_router(public_router, prefix="/api")

    return app


app = create_app()
