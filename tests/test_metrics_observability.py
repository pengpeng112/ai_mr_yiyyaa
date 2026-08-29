"""可观测性指标骨架测试（023 P1-09 本地部分 / 031 T1-8）。

覆盖：三类指标计数正确性（mock 断言）、/api/metrics 鉴权正反、
请求计数中间件按路由模板聚合。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.metrics as metrics
from app.auth import get_current_user
from app.main import metrics_request_counter
from app.routers.metrics import router as metrics_router


@pytest.fixture(autouse=True)
def _clean_metrics():
    metrics.reset_metrics()
    yield
    metrics.reset_metrics()


def test_record_request_counts_by_status_class():
    metrics.record_request("GET", "/api/logs", 200)
    metrics.record_request("get", "/api/logs", 200)
    metrics.record_request("GET", "/api/logs", 404)
    metrics.record_request("POST", "/api/push/manual", 500)
    snap = metrics.snapshot()
    by = {(r["method"], r["route"], r["status_class"]): r["count"] for r in snap["requests"]["by_route"]}
    assert by[("GET", "/api/logs", "2xx/3xx")] == 2
    assert by[("GET", "/api/logs", "4xx")] == 1
    assert by[("POST", "/api/push/manual", "5xx")] == 1
    assert snap["requests"]["total"] == 4


def test_record_dify_latency_buckets_and_agg():
    for ms in (50, 150, 800, 5000):
        metrics.record_dify_latency(ms)
    d = metrics.snapshot()["dify_latency"]
    assert d["count"] == 4
    assert d["sum_ms"] == 6000
    assert d["min_ms"] == 50
    assert d["max_ms"] == 5000
    assert d["avg_ms"] == 1500.0
    assert d["buckets"] == {"<=100ms": 1, "100-500ms": 1, "500-2000ms": 1, ">2000ms": 1}


def test_record_scheduler_run_outcomes():
    metrics.record_scheduler_run("daily_push", "completed")
    metrics.record_scheduler_run("daily_push", "completed")
    metrics.record_scheduler_run("discharge_push", "skipped_lock")
    snap = metrics.snapshot()["scheduler_runs"]
    by = {(s["job"], s["outcome"]): s["count"] for s in snap}
    assert by[("daily_push", "completed")] == 2
    assert by[("discharge_push", "skipped_lock")] == 1


@pytest.fixture()
def app_with_metrics():
    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    @app.get("/api/boom")
    def boom():
        # 与生产等价：异常经异常处理器转为 500 响应（中间件能看到状态码）
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="boom")

    app.include_router(metrics_router, prefix="/api/metrics")
    app.middleware("http")(metrics_request_counter)
    return app


def test_metrics_endpoint_requires_auth(app_with_metrics):
    client = TestClient(app_with_metrics, raise_server_exceptions=False)
    r = client.get("/api/metrics")
    assert r.status_code in (401, 403)


def test_metrics_endpoint_with_user_and_middleware_counts(app_with_metrics):
    app_with_metrics.dependency_overrides[get_current_user] = lambda: object()
    client = TestClient(app_with_metrics, raise_server_exceptions=False)
    assert client.get("/api/ping").status_code == 200
    client.get("/api/boom")  # 500
    r = client.get("/api/metrics")
    assert r.status_code == 200
    data = r.json()
    by = {(x["method"], x["route"], x["status_class"]): x["count"] for x in data["requests"]["by_route"]}
    assert by[("GET", "/api/ping", "2xx/3xx")] >= 1
    assert by[("GET", "/api/boom", "5xx")] == 1
    # 路由模板聚合：metrics 自身请求也按模板（非含具体值）计数
    assert all("{" not in route for _, route, _ in by)
