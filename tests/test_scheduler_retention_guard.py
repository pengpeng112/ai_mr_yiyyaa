from app import scheduler


def test_multi_worker_always_disables_in_process_scheduler(monkeypatch):
    monkeypatch.setenv("ENABLE_SCHEDULER", "true")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    assert scheduler.is_scheduler_env_enabled() is False
    monkeypatch.setenv("SCHEDULER_LEADER", "true")
    assert scheduler.is_scheduler_env_enabled() is False


def test_invalid_worker_count_disables_scheduler(monkeypatch):
    monkeypatch.setenv("ENABLE_SCHEDULER", "true")
    monkeypatch.setenv("WEB_CONCURRENCY", "not-a-number")
    assert scheduler.is_scheduler_env_enabled() is False
