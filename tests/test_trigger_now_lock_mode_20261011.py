"""W4：手动触发按运行模式取调度锁。

daily_increment 取 daily_push，discharge_final 取 discharge_push。
两把 DB 锁保持分开，手动终末与定时终末因此互斥。
"""

import time

from app import scheduler


def test_trigger_now_takes_mode_specific_lock(monkeypatch):
    seen: list[str] = []

    def fake_acquire(lock_name):
        seen.append(str(lock_name))
        return False, "test-owner", "held-by-test"

    monkeypatch.setattr(scheduler, "_acquire_scheduler_run_lock_impl", fake_acquire)
    monkeypatch.setattr(
        "app.services.scheduler_history_service.write_scheduler_history_safe",
        lambda **_kwargs: "",
    )

    def run(mode: str) -> str:
        before = len(seen)
        scheduler.trigger_now(_query_date="2026-10-11", _audit_run_mode=mode)
        deadline = time.time() + 2
        while len(seen) == before and time.time() < deadline:
            time.sleep(0.02)
        assert len(seen) == before + 1
        return seen[-1]

    assert run("daily_increment") == "daily_push"
    assert run("discharge_final") == "discharge_push"
    assert seen[0] != seen[1]
