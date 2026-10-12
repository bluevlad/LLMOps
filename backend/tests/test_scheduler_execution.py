"""실제 스케줄러 실행을 검증하며 폴러·네트워크·DB 부작용은 대체한다."""
import asyncio
from datetime import datetime, timezone

import pytest

from app.jobs import scheduler


@pytest.mark.asyncio
async def test_pollers_repeat_and_alert_start_is_aware(monkeypatch):
    counts = {"ollama": 0, "mlx": 0}
    events = {key: asyncio.Event() for key in counts}

    def job(key):
        async def run():
            counts[key] += 1
            if counts[key] >= 2:
                events[key].set()
        return run

    monkeypatch.setattr(scheduler.ollama_poller, "run_once", job("ollama"))
    monkeypatch.setattr(scheduler.mlx_poller, "run_once", job("mlx"))
    monkeypatch.setattr(scheduler.settings, "poller_ollama_interval_seconds", 0.02)
    monkeypatch.setattr(scheduler.settings, "poller_mlx_interval_seconds", 0.02)
    monkeypatch.setattr(scheduler.settings, "alert_eval_interval_seconds", 600)
    scheduler.start_scheduler()
    running = scheduler._scheduler
    try:
        scheduler.start_scheduler()
        assert scheduler._scheduler is running
        for item in running.get_jobs():
            assert item.next_run_time is not None
            assert item.next_run_time.tzinfo is not None
        assert running.get_job("alert_evaluator").next_run_time > datetime.now(timezone.utc)
        await asyncio.wait_for(asyncio.gather(*(e.wait() for e in events.values())), timeout=2)
    finally:
        scheduler.stop_scheduler()
        await asyncio.sleep(0)
    assert scheduler._scheduler is None
    assert not running.running
