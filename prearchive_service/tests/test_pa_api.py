# -*- coding: utf-8 -*-
"""只读 API 单测：/healthz 心跳 + /api/precheck 鉴权与归属校验（A19 最小实现）。"""

import pytest
from fastapi.testclient import TestClient

from prearchive.api import create_app
from prearchive.heartbeat import Heartbeat
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.store import ResultRepository

from helpers import dt


TOKEN = "test-shared-token"


@pytest.fixture()
def stack(tmp_path):
    repo = ResultRepository(build_session_factory(build_sqlite_engine(":memory:")))
    heartbeat = Heartbeat(tmp_path / "heartbeat.json")
    config = {"api": {"shared_token": TOKEN, "require_dept_binding": True},
              "service": {"heartbeat_max_age_seconds": 900}}
    repo.upsert_result(
        patient_id="P1", visit_id="1", finished_date_time=dt("2026-08-26 10:00:00"),
        problems=[{"rule_id": "R1", "name": "n", "severity": "medium",
                   "message": "m", "mark_item_fid": None}],
        rule_version="v1", dept_code="D1", dept_name="普外科")
    client = TestClient(create_app(config, repo, heartbeat))
    return client, repo, heartbeat, tmp_path


def test_healthz_reports_alive_after_heartbeat(stack):
    client, repo, heartbeat, tmp_path = stack
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"     # 尚无心跳

    heartbeat.write({"watermark": "2026-08-27T11:00:00"})
    resp2 = client.get("/healthz")
    body = resp2.json()
    assert body["status"] == "ok"
    assert body["heartbeat_alive"] is True
    assert body["heartbeat"]["watermark"] == "2026-08-27T11:00:00"


def test_precheck_requires_token(stack):
    client, *_ = stack
    assert client.get("/api/precheck/P1/1",
                      params={"doctor_id": "D01", "dept_code": "D1"}
                      ).status_code == 401
    assert client.get("/api/precheck/P1/1",
                      headers={"X-Precheck-Token": "wrong"},
                      params={"doctor_id": "D01", "dept_code": "D1"}
                      ).status_code == 401


def test_precheck_requires_doctor_and_dept(stack):
    client, *_ = stack
    headers = {"X-Precheck-Token": TOKEN}
    assert client.get("/api/precheck/P1/1", headers=headers
                      ).status_code == 400
    assert client.get("/api/precheck/P1/1", headers=headers,
                      params={"doctor_id": "D01"}).status_code == 400
    assert client.get("/api/precheck/P1/1", headers=headers,
                      params={"dept_code": "D1"}).status_code == 400


def test_precheck_not_found(stack):
    client, *_ = stack
    resp = client.get("/api/precheck/NOPE/9", headers={"X-Precheck-Token": TOKEN},
                      params={"doctor_id": "D01", "dept_code": "D1"})
    assert resp.status_code == 404


def test_precheck_dept_binding_forbids_other_dept(stack):
    """患者归属科室校验（A19 防冒用）：跨科室查询 403。"""
    client, *_ = stack
    resp = client.get("/api/precheck/P1/1", headers={"X-Precheck-Token": TOKEN},
                      params={"doctor_id": "D01", "dept_code": "D2"})
    assert resp.status_code == 403


def test_precheck_ok_returns_problems(stack):
    client, *_ = stack
    resp = client.get("/api/precheck/P1/1", headers={"X-Precheck-Token": TOKEN},
                      params={"doctor_id": "D01", "dept_code": "D1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["problem_count"] == 1
    assert body["problems"][0]["rule_id"] == "R1"
    assert body["queried_by_doctor_id"] == "D01"
    assert body["current"] is True


def test_precheck_placeholder_token_is_503(tmp_path):
    repo = ResultRepository(build_session_factory(build_sqlite_engine(":memory:")))
    heartbeat = Heartbeat(tmp_path / "hb.json")
    config = {"api": {"shared_token": "<SHARED_TOKEN_PLACEHOLDER>"},
              "service": {}}
    client = TestClient(create_app(config, repo, heartbeat))
    resp = client.get("/api/precheck/P1/1", headers={"X-Precheck-Token": "x"},
                      params={"doctor_id": "D", "dept_code": "D1"})
    assert resp.status_code == 503


def test_openapi_available(stack):
    client, *_ = stack
    resp = client.get("/docs")
    assert resp.status_code == 200
