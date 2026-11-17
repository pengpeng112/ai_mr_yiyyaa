"""W6：批量路径只对 Dify 超时原地重试一次。

其他失败不重试。串行 push_to_dify 仍由批量包装层承接，本文件只打批量入口。
"""

import requests

from app.services.bulk_push_executor import BulkPushExecutor

PATIENT = "SYN-W6"


def _executor() -> BulkPushExecutor:
    return BulkPushExecutor(
        {"base_url": "http://dify.invalid/v1", "api_key": "test", "name": "t1"},
        empty_retry_max=0,
    )


def _patch_push(monkeypatch, func, sleeps: list[float]):
    monkeypatch.setattr("app.services.bulk_push_executor.push_to_dify", func)
    monkeypatch.setattr("app.services.bulk_push_executor.time.sleep", lambda seconds: sleeps.append(float(seconds)))


def test_timeout_then_success_retries_once(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    def fake_push(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.exceptions.Timeout("synthetic")
        return {"status": "success", "result": {"aa": "{\"ok\":true}"}, "inconsistency": False, "severity": "low"}

    _patch_push(monkeypatch, fake_push, sleeps)
    result = _executor()._push_with_empty_retry("synthetic-mr", PATIENT)
    assert result["status"] == "success"
    assert result["attempt"] == 1
    assert calls["n"] == 2
    assert sleeps and max(sleeps) <= 5


def test_two_timeouts_return_failed(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    def fake_push(*_args, **_kwargs):
        calls["n"] += 1
        raise requests.exceptions.Timeout("synthetic")

    _patch_push(monkeypatch, fake_push, sleeps)
    result = _executor()._push_with_empty_retry("synthetic-mr", PATIENT)
    assert result["status"] == "failed"
    assert result["attempt"] == 1
    assert calls["n"] == 2
    assert sleeps and max(sleeps) <= 5


def test_timeout_result_dict_retries_once_then_succeeds(monkeypatch):
    """push_to_dify 把 Timeout 收成失败字典时，批量层仍只重试这一类。"""
    calls = {"n": 0}
    sleeps: list[float] = []

    def fake_push(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"status": "failed", "error": "请求超时（180s）"}
        return {"status": "success", "result": {"aa": "{\"ok\":true}"}, "inconsistency": False, "severity": "low"}

    _patch_push(monkeypatch, fake_push, sleeps)
    result = _executor()._push_with_empty_retry("synthetic-mr", PATIENT)
    assert result["status"] == "success"
    assert result["attempt"] == 1
    assert calls["n"] == 2


def test_http_error_and_connection_error_are_not_retried(monkeypatch):
    sleeps: list[float] = []
    calls = {"n": 0}

    def fake_http(*_args, **_kwargs):
        calls["n"] += 1
        return {"status": "failed", "error": "HTTP 503"}

    _patch_push(monkeypatch, fake_http, sleeps)
    result = _executor()._push_with_empty_retry("synthetic-mr", PATIENT)
    assert result["status"] == "failed"
    assert calls["n"] == 1
    assert sleeps == []

    calls["n"] = 0

    def fake_conn(*_args, **_kwargs):
        calls["n"] += 1
        raise requests.exceptions.ConnectionError("synthetic refused")

    monkeypatch.setattr("app.services.bulk_push_executor.push_to_dify", fake_conn)
    try:
        _executor()._push_with_empty_retry("synthetic-mr", PATIENT)
        raised = False
    except requests.exceptions.ConnectionError:
        raised = True
    assert raised is True
    assert calls["n"] == 1
