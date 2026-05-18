"""APScheduler 잡 등록 — Ollama 폴링(10분) + MLX 스캔(1시간)."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.pollers import mlx as mlx_poller
from app.pollers import ollama as ollama_poller

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    sched = AsyncIOScheduler(timezone=settings.app_tz)
    sched.add_job(
        ollama_poller.run_once,
        "interval",
        seconds=settings.poller_ollama_interval_seconds,
        id="ollama_poller",
        next_run_time=None,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        mlx_poller.run_once,
        "interval",
        seconds=settings.poller_mlx_interval_seconds,
        id="mlx_poller",
        next_run_time=None,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    logger.info("Scheduler started (ollama %ds, mlx %ds)",
                settings.poller_ollama_interval_seconds,
                settings.poller_mlx_interval_seconds)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
