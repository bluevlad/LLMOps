"""LLMOps FastAPI entrypoint.

Phase 1a: 헬스체크만. /api/models, /api/batch-runs, /api/auth 는 Phase 1b 에서 추가.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="LLMOps API",
        version="0.1.0",
        description="로컬 LLM 사용 현황·ROI 통합 관제 — 표준: Claude-Opus-bluevlad/standards/ai/",
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

    return app


app = create_app()
