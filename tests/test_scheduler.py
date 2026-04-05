import time

from app import scheduler


def test_validate_cron_expression_valid():
    ok, msg = scheduler.validate_cron_expression("*/10 * * * *")
    assert ok is True
    assert msg == "ok"


def test_validate_cron_expression_invalid_parts():
    ok, msg = scheduler.validate_cron_expression("* * *")
    assert ok is False
    assert "5个部分" in msg


def test_get_last_run_info_returns_copy():
    scheduler._last_run_info = {"k": "v"}
    value = scheduler.get_last_run_info()
    value["k"] = "x"
    assert scheduler._last_run_info["k"] == "v"


def test_trigger_now_sets_last_error_on_thread_crash(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "_daily_push_job", _raise)
    scheduler._last_run_info = {}
    scheduler.trigger_now(_query_date="2026-01-01", _dept_override=[])
    time.sleep(0.1)
    info = scheduler.get_last_run_info()
    assert "trigger_thread_crash" in info.get("last_error", "")
