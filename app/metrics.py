"""轻量可观测性指标注册表（023 P1-09 本地部分）。

纯内存实现，不引入第三方依赖；进程重启即清零。
- 请求计数：按 (方法, 路由模板, 状态码类) 聚合，避免高基数；
- Dify 调用延迟：count/sum/min/max + 简单分桶（100ms/500ms/2000ms）；
- 调度漏斗：按 (job 锁名, 结果) 计数（daily_push/discharge_push）。
SLO、磁盘、前端异常、告警联动等运维平台指标不在本骨架范围（丙类）。
"""
from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()

# (method, route_template, status_class) -> count
_request_counts: dict[tuple[str, str, str], int] = defaultdict(int)

# Dify 延迟：count/sum/min/max + 分桶边界
_DIFY_BUCKET_BOUNDS_MS = (100, 500, 2000)
_dify_latency = {"count": 0, "sum_ms": 0, "min_ms": None, "max_ms": 0}
_dify_buckets: dict[str, int] = defaultdict(int)

# (lock_name, outcome) -> count
_scheduler_runs: dict[tuple[str, str], int] = defaultdict(int)


def _status_class(status: int) -> str:
    if status < 400:
        return "2xx/3xx"
    if status < 500:
        return "4xx"
    return "5xx"


def record_request(method: str, route: str, status: int) -> None:
    with _lock:
        _request_counts[(method.upper(), route or "unrouted", _status_class(int(status)))] += 1


def record_dify_latency(elapsed_ms: int) -> None:
    ms = int(elapsed_ms)
    with _lock:
        _dify_latency["count"] += 1
        _dify_latency["sum_ms"] += ms
        if _dify_latency["min_ms"] is None or ms < _dify_latency["min_ms"]:
            _dify_latency["min_ms"] = ms
        if ms > _dify_latency["max_ms"]:
            _dify_latency["max_ms"] = ms
        if ms <= _DIFY_BUCKET_BOUNDS_MS[0]:
            _dify_buckets["<=100ms"] += 1
        elif ms <= _DIFY_BUCKET_BOUNDS_MS[1]:
            _dify_buckets["100-500ms"] += 1
        elif ms <= _DIFY_BUCKET_BOUNDS_MS[2]:
            _dify_buckets["500-2000ms"] += 1
        else:
            _dify_buckets[">2000ms"] += 1


def record_scheduler_run(lock_name: str, outcome: str) -> None:
    with _lock:
        _scheduler_runs[(lock_name, outcome)] += 1


def snapshot() -> dict:
    with _lock:
        requests_view = {
            "total": sum(_request_counts.values()),
            "by_route": [
                {"method": m, "route": r, "status_class": s, "count": c}
                for (m, r, s), c in sorted(_request_counts.items())
            ],
        }
        dify = dict(_dify_latency)
        dify["avg_ms"] = round(dify["sum_ms"] / dify["count"], 2) if dify["count"] else None
        dify["buckets"] = dict(_dify_buckets)
        scheduler_view = [
            {"job": job, "outcome": outcome, "count": count}
            for (job, outcome), count in sorted(_scheduler_runs.items())
        ]
        return {
            "requests": requests_view,
            "dify_latency": dify,
            "scheduler_runs": scheduler_view,
        }


def reset_metrics() -> None:
    """仅测试使用：清空全部指标。"""
    with _lock:
        _request_counts.clear()
        _dify_latency.update({"count": 0, "sum_ms": 0, "min_ms": None, "max_ms": 0})
        _dify_buckets.clear()
        _scheduler_runs.clear()
