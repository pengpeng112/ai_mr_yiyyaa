# -*- coding: utf-8 -*-
"""048 T2 核查列表分页/有界聚合验收：真实 total、稳定排序、参数校验、
科室范围强制（详情/动作）、SQL 证明不全量加载 Issue、100/1000/10000 行耗时记录。

数据全部合成（SQLite 内存）；Oracle 只做方言编译检查，不代表真实库验收。
"""

import json
import time
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.dialects import oracle as oracle_dialect

from prearchive.closed_loop_api import create_closed_loop_router
from prearchive.closed_loop_models import IssueRow, RunRow
from prearchive.issue_service import browse_check_runs
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.rule_repository import RuleRepository
from prearchive.rule_service import RuleService

from test_pa_closed_loop_api import ADMIN_TOKEN, SIGNING_SECRET

FULL_PERMS = ("prearchive_rule_view,prearchive_check_view,"
              "prearchive_issue_review,prearchive_issue_feedback")


@pytest.fixture()
def stack():
    engine = build_sqlite_engine(":memory:")
    session_factory = build_session_factory(engine)
    repo = RuleRepository(session_factory)
    service = RuleService(repo)
    config = {"admin_api": {"enabled": True, "admin_token": ADMIN_TOKEN,
                            "signing_secret": SIGNING_SECRET},
              "rule_registry": {"mode": "file", "governance": {}}}
    app = FastAPI()
    app.include_router(create_closed_loop_router(config, session_factory, repo,
                                                 service))
    return TestClient(app), session_factory, engine


def _headers(perms=FULL_PERMS, actor_id="admin-1", request_id="req-1"):
    from urllib.parse import quote
    from prearchive.admin_api import (
        ACTOR_ID_HEADER, ACTOR_NAME_HEADER, ACTOR_PERMS_HEADER,
        ACTOR_SIGNATURE_HEADER, ADMIN_TOKEN_HEADER, REQUEST_ID_HEADER,
        actor_signature,
    )
    name = quote("管理员", safe="")
    return {
        ADMIN_TOKEN_HEADER: ADMIN_TOKEN,
        ACTOR_ID_HEADER: actor_id,
        ACTOR_NAME_HEADER: name,
        ACTOR_PERMS_HEADER: perms,
        REQUEST_ID_HEADER: request_id,
        ACTOR_SIGNATURE_HEADER: actor_signature(
            SIGNING_SECRET, actor_id, name, perms, request_id),
    }


def _seed_runs(session_factory, count, *, created_at=None, dept="D001",
               prefix="PERF", start=1, visit="1", is_trial=0):
    created_at = created_at or datetime(2026, 9, 15, 12, 0, 0)
    with session_factory() as session:
        for i in range(start, start + count):
            session.add(RunRow(
                id=f"run-{prefix}-{i:06d}", run_revision=1,
                patient_id=f"P{prefix}{i:06d}", visit_number=visit,
                dept_code=dept, dept_name=f"科室{dept}",
                trigger_type="paperless_rpa", is_trial=is_trial,
                status="completed", created_at=created_at,
                summary_json=json.dumps({"fail_count": 1, "status": "fail"})))
        session.commit()


def _seed_issues(session_factory, count, *, dept="D001", prefix="PERF",
                 status="open"):
    """给 run-{prefix}-{i} 各造 2 条正式 issue（不同规则）。"""
    with session_factory() as session:
        for i in range(1, count + 1):
            pid = f"P{prefix}{i:06d}"
            for rule in ("R-A", "R-B"):
                session.add(IssueRow(
                    id=f"iss-{prefix}-{i:06d}-{rule}", issue_key=f"{pid}|1|{rule}",
                    patient_id=pid, visit_number="1", dept_code=dept,
                    rule_id=rule, status=status, is_trial=0))
        session.commit()


# ---------------------------------------------------------------- 分页核心


def test_pagination_same_timestamp_no_dup_no_missing(stack):
    client, sf, _ = stack
    total_runs = 305
    _seed_runs(sf, total_runs, prefix="PAGE")   # 全部同一 created_at

    seen = []
    page = 1
    while True:
        r = client.get("/api/admin/checks", headers=_headers(),
                       params={"page": page, "page_size": 100})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == total_runs
        assert data["page"] == page and data["page_size"] == 100
        if not data["items"]:
            break
        seen.extend(item["run_id"] for item in data["items"])
        page += 1
        assert page <= 10, "异常翻页死循环"
    assert len(seen) == total_runs, "翻页总数不守恒"
    assert len(set(seen)) == total_runs, "翻页出现重复行"

    # 空页：越过末页
    r = client.get("/api/admin/checks", headers=_headers(),
                   params={"page": 99, "page_size": 100})
    assert r.json()["items"] == [] and r.json()["total"] == total_runs

    # 筛选后不足一页
    r = client.get("/api/admin/checks", headers=_headers(),
                   params={"page": 1, "page_size": 100, "dept_code": "D001",
                           "patient_id": "PPAGE000001"})
    assert r.json()["total"] == 1 and len(r.json()["items"]) == 1

    # 排序稳定性：同 created_at 下按 id desc（确定性顺序）
    first = client.get("/api/admin/checks", headers=_headers(),
                       params={"page": 1, "page_size": 3}).json()["items"]
    ids = [item["run_id"] for item in first]
    assert ids == sorted(ids, reverse=True)


def test_invalid_params_return_422_not_500(stack):
    client, sf, _ = stack
    _seed_runs(sf, 1, prefix="V")
    cases = [
        {"page": 0},
        {"page": -1},
        {"page_size": 0},
        {"page_size": -5},
        {"page_size": 301},
        {"limit": 0},
        {"limit": 301},
        {"is_trial": 2},
        {"is_trial": -1},
    ]
    for params in cases:
        r = client.get("/api/admin/checks", headers=_headers(), params=params)
        assert r.status_code == 422, f"{params} → {r.status_code}"

    # 旧 limit 兼容：只传 limit → 单页大小
    r = client.get("/api/admin/checks", headers=_headers(),
                   params={"limit": 1})
    assert r.status_code == 200 and len(r.json()["items"]) == 1
    # 同时显式传 page_size + limit → page_size 优先
    _seed_runs(sf, 3, prefix="V2", start=2)
    r = client.get("/api/admin/checks", headers=_headers(),
                   params={"limit": 1, "page_size": 2})
    assert r.status_code == 200 and len(r.json()["items"]) == 2


def test_cross_dept_same_patient_multi_visit_isolation(stack):
    client, sf, _ = stack
    # 同一患者两次就诊分属两科；第三位患者另一科
    with sf() as session:
        rows = [
            RunRow(id="run-A1", run_revision=1, patient_id="PX", visit_number="1",
                   dept_code="D001", dept_name="普外科", status="completed",
                   created_at=datetime(2026, 9, 15, 8, 0, 0)),
            RunRow(id="run-A2", run_revision=1, patient_id="PX", visit_number="2",
                   dept_code="D002", dept_name="骨科", status="completed",
                   created_at=datetime(2026, 9, 15, 9, 0, 0)),
            RunRow(id="run-B1", run_revision=1, patient_id="PY", visit_number="1",
                   dept_code="D002", dept_name="骨科", status="completed",
                   created_at=datetime(2026, 9, 15, 10, 0, 0)),
        ]
        session.add_all(rows)
        # 各就诊各 1 条 open issue（跨科室计数不得互串）
        for rid, pid, visit, dept in (("i1", "PX", "1", "D001"),
                                      ("i2", "PX", "2", "D002"),
                                      ("i3", "PY", "1", "D002")):
            session.add(IssueRow(id=rid, issue_key=f"{pid}|{visit}|R", patient_id=pid,
                                 visit_number=visit, dept_code=dept,
                                 rule_id="R", status="open", is_trial=0))
        session.commit()

    # D001 只见 PX/1（患者+次数联合键精确隔离）
    r = client.get("/api/admin/checks", headers=_headers(),
                   params={"dept_code": "D001"}).json()
    assert r["total"] == 1
    assert r["items"][0]["visit_number"] == "1"
    assert r["items"][0]["open_issues"] == 1

    # D002：PX/2 与 PY/1 两条，各 1 open，不携带 D001 计数
    r = client.get("/api/admin/checks", headers=_headers(),
                   params={"dept_code": "D002"}).json()
    assert r["total"] == 2
    by_visit = {item["visit_number"] + item["patient_id"]: item
                for item in r["items"]}
    assert by_visit["2PX"]["open_issues"] == 1
    assert by_visit["1PY"]["open_issues"] == 1


# ---------------------------------------------------------------- 详情/动作科室强制


def test_detail_and_action_dept_enforcement(stack):
    client, sf, _ = stack
    with sf() as session:
        session.add(RunRow(id="run-D1", run_revision=1, patient_id="PD",
                           visit_number="1", dept_code="D001", dept_name="普外科",
                           status="completed",
                           created_at=datetime(2026, 9, 15, 8, 0, 0)))
        session.add(IssueRow(id="iss-D1", issue_key="PD|1|R", patient_id="PD",
                             visit_number="1", dept_code="D001", rule_id="R",
                             status="open", is_trial=0, version=1))
        session.commit()

    # 详情：范围匹配 200；不匹配 403；未传不限制（BFF 决定）
    assert client.get("/api/admin/checks/run-D1", headers=_headers(),
                      params={"enforce_dept_code": "D001"}).status_code == 200
    r = client.get("/api/admin/checks/run-D1", headers=_headers(),
                   params={"enforce_dept_code": "D999"})
    assert r.status_code == 403
    assert client.get("/api/admin/checks/run-D1", headers=_headers()).status_code == 200

    assert client.get("/api/admin/issues/iss-D1", headers=_headers(),
                      params={"enforce_dept_code": "D001"}).status_code == 200
    assert client.get("/api/admin/issues/iss-D1", headers=_headers(),
                      params={"enforce_dept_code": "D999"}).status_code == 403

    # 动作：越科室 403 且不落任何状态变更/动作历史
    r = client.post("/api/admin/issues/iss-D1/actions", headers=_headers(),
                    json={"action": "viewed", "enforce_dept_code": "D999"})
    assert r.status_code == 403
    with sf() as session:
        assert session.get(IssueRow, "iss-D1").status == "open"
    r = client.post("/api/admin/issues/iss-D1/actions", headers=_headers(),
                    json={"action": "viewed", "enforce_dept_code": "D001"})
    assert r.status_code == 200 and r.json()["status"] == "viewed"


# ---------------------------------------------------------------- 有界聚合 SQL 证明 + 耗时


def _capture_issue_sql(engine):
    statements: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        if "MED_PREARCHIVE_ISSUE" in statement.upper():
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _before)
    return statements, lambda: event.remove(engine, "before_cursor_execute", _before)


def test_issue_aggregation_is_bounded_by_sql(stack):
    """SQL 事件证明：issue 查询带 (patient_id, visit_number) IN 元组过滤 +
    GROUP BY 聚合，不整表加载 IssueRow。"""
    client, sf, engine = stack
    _seed_runs(sf, 5, prefix="BND")
    _seed_issues(sf, 5, prefix="BND")

    statements, detach = _capture_issue_sql(engine)
    try:
        r = client.get("/api/admin/checks", headers=_headers(),
                       params={"page": 1, "page_size": 3})
        assert r.status_code == 200 and len(r.json()["items"]) == 3
    finally:
        detach()
    assert statements, "未捕获 issue 聚合查询"
    for sql in statements:
        upper = sql.upper()
        assert "GROUP BY" in upper, sql
        assert ("IN" in upper), sql
        # 不允许无过滤整表扫（WHERE 必须先于聚合存在）
        assert "WHERE" in upper, sql

    # 零本页 run：不触发任何 issue 查询
    statements2, detach2 = _capture_issue_sql(engine)
    try:
        r = client.get("/api/admin/checks", headers=_headers(),
                       params={"page": 50, "page_size": 100})
        assert r.status_code == 200 and r.json()["items"] == []
    finally:
        detach2()
    assert statements2 == [], "空页不应扫 issue 表"


def test_browse_scaling_records_duration(stack):
    """100/1000/10000 run+issue 下记录耗时与环境（不做无依据毫秒断言，只记录）。"""
    client, sf, _ = stack
    durations: dict[int, float] = {}
    for count in (100, 1000, 10000):
        engine2 = build_sqlite_engine(":memory:")
        sf2 = build_session_factory(engine2)
        _seed_runs(sf2, count, prefix=f"S{count}")
        _seed_issues(sf2, count, prefix=f"S{count}")
        t0 = time.perf_counter()
        runs, total, counts = browse_check_runs(
            sf2, page=1, page_size=100)
        durations[count] = time.perf_counter() - t0
        assert total == count and len(runs) == 100
        assert len(counts) == 100
        engine2.dispose()
    print(f"\n[perf] browse_check_runs page_size=100 耗时(s)={durations}")
    # 仅宽松健全性（数量级），非验收阈值
    assert durations[10000] < 30


def test_queries_compile_on_oracle_dialect(stack):
    """方言检查：分页/计数/元组 IN 聚合可在 Oracle 方言编译（非真实库执行）。"""
    from sqlalchemy import func, select, tuple_
    stmt = (select(RunRow.patient_id, RunRow.visit_number, RunRow.status,
                   func.count())
            .where(IssueRow.is_trial == 0,
                   tuple_(IssueRow.patient_id,
                          IssueRow.visit_number).in_([("p1", "1"), ("p2", "2")]))
            .group_by(RunRow.patient_id, RunRow.visit_number, RunRow.status))
    compiled = str(stmt.compile(dialect=oracle_dialect.dialect()))
    assert "GROUP BY" in compiled.upper()

    run_stmt = (select(RunRow)
                .where(RunRow.is_trial == 0)
                .order_by(RunRow.created_at.desc(), RunRow.id.desc())
                .offset(100).limit(100))
    str(run_stmt.compile(dialect=oracle_dialect.dialect()))
    count_stmt = select(func.count()).select_from(
        select(RunRow).where(RunRow.is_trial == 0).subquery())
    str(count_stmt.compile(dialect=oracle_dialect.dialect()))


def test_list_checks_counts_semantics_documented(stack):
    """计数语义=就诊当前缺陷状态（按 (patient,visit) 聚合的当前 issue 表），
    非历史 run 时点快照：新 run 后 issue 状态变化立即反映在旧 run 行计数上。"""
    client, sf, _ = stack
    _seed_runs(sf, 1, prefix="SEM", created_at=datetime(2026, 9, 1, 8, 0, 0))
    _seed_issues(sf, 1, prefix="SEM", status="open")   # 2 条 open（R-A/R-B）
    item = client.get("/api/admin/checks", headers=_headers()).json()["items"][0]
    assert item["open_issues"] == 2 and item["resolved_issues"] == 0
    with sf() as session:
        rows = session.execute(select(IssueRow)).scalars().all()
        for row in rows:
            row.status = "resolved"
        session.commit()
    item = client.get("/api/admin/checks", headers=_headers()).json()["items"][0]
    assert item["open_issues"] == 0 and item["resolved_issues"] == 2
