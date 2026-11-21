"""064-WP04：时效台账审批与月度考核全面升级（后端验收用例）。

覆盖任务书 §六：
1. stats/monthly 任意日期区间只计区间内事件与审批；
2. 旧调用 stats/monthly?month=YYYY-MM 返回结构与改造前一致（month/totals/rows 逐项相等）；
3. 新旧聚合实现（SQL 聚合 vs 旧循环）对同一数据逐行一致；
4. page/limit 分页：当页 rows + total_rows + 全量 totals；
5. export/monthly format=xlsx：openpyxl 真 Excel（标题/表头/freeze E3/数据行/合计）+
   ExportAuditLog(export_format='xlsx')；旧 month 调用仍返回 CSV；
6. home 范围用户导出只含本科室；
7. events 新增字段（remaining_minutes/latest_approval/临床字段，visit_meta 走 mock）+
   approvals 新筛选与 status_counts + 非法日期 400。

零真实 Oracle/HIS 连接：visit_meta 与 staff_name 全部 monkeypatch。
"""
from __future__ import annotations

import io
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth as auth_module
from app.database import Base, get_db
from app.models import Department, ExportAuditLog, Permission, Role, RolePermission, User
from app.routers import timeliness as timeliness_router
from app.timeliness.models import TLApproval, TLEvent, TLRule, TLRuleVersion
from app.timeliness.rules_seed import seed_rules

D0 = datetime(2026, 11, 5, 8, 0, 0)

VISIT_META = {
    ("T0001", "1"): {
        "patient_name": "患者甲", "dept_code": "0201", "doctor_in_charge_id": "D001",
        "inp_no": "0510001", "sex": "男", "age": "45",
        "admission_date": "2026-11-04T08:00:00", "discharge_date": None,
        "admission_diagnosis": "急性阑尾炎", "nursing_level": "二级护理",
        "discharge_diagnosis": "慢性阑尾炎",
    },
    ("T0003", "1"): {
        "patient_name": "患者丙", "dept_code": "0201", "doctor_in_charge_id": "D002",
        "inp_no": "0510003", "sex": "女", "age": "52",
        "admission_date": "2026-11-06T09:00:00", "discharge_date": None,
        "admission_diagnosis": "慢性鼻窦炎", "nursing_level": "三级护理",
        "discharge_diagnosis": "",
    },
}


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    seed_rules(db)

    permissions = {}
    for name in ("timeliness_view", "timeliness_export", "timeliness_admin"):
        perm = Permission(name=name, description=name, module="timeliness")
        db.add(perm)
        permissions[name] = perm

    admin_role = Role(name="admin", description="管理员")
    db.add(admin_role)
    db.flush()
    for perm_name in permissions:
        db.add(RolePermission(role_id=admin_role.id, permission_id=permissions[perm_name].id))
    admin = User(username="wp04_admin", password_hash="x", full_name="管理员", role_id=admin_role.id)
    db.add(admin)

    dept_ear = Department(name="耳科", code="0201")
    dept_nose = Department(name="鼻科", code="0202")
    db.add_all([dept_ear, dept_nose])
    db.flush()

    # home 范围用户（本科室可见 + 导出权限）
    home_role = Role(name="wp04_home", description="耳科 home")
    db.add(home_role)
    db.flush()
    for name in ("timeliness_view", "timeliness_export"):
        db.add(RolePermission(role_id=home_role.id, permission_id=permissions[name].id))
    home = User(username="wp04_home_user", password_hash="x", full_name="耳科医生",
                role_id=home_role.id, dept_id=dept_ear.id)
    db.add(home)

    version = (
        db.query(TLRuleVersion)
        .join(TLRule, TLRule.id == TLRuleVersion.rule_id)
        .filter(TLRule.rule_code == "FIRST_COURSE", TLRuleVersion.version_no == 1)
        .one()
    )

    def add_event(pid, vid, dept_code, doctor_id, status, t0, overdue_minutes=None):
        db.add(TLEvent(
            event_uid=f"FIRST_COURSE:{pid}:{vid}:{t0:%d%H%M}", rule_code="FIRST_COURSE",
            rule_version_id=version.id, patient_id=pid, visit_id=vid,
            dept_code=dept_code, responsible_doctor_id=doctor_id, t0=t0,
            deadline=t0.replace(hour=20, minute=0, second=0) if t0.hour < 20 else None,
            status=status, overdue_minutes=overdue_minutes,
            last_scan_at=t0, created_at=t0, updated_at=t0,
        ))

    # 区间内（2026-11-01 ~ 2026-11-10）
    add_event("T0001", "1", "0201", "D001", "COMPLETED_ON_TIME", datetime(2026, 11, 5, 8, 0))
    add_event("T0001", "1", "0201", "D001", "OVERDUE", datetime(2026, 11, 6, 8, 0), 90)
    add_event("T0003", "1", "0201", "D002", "WARNING", datetime(2026, 11, 7, 8, 0))
    add_event("T0004", "1", "0202", "D003", "COMPLETED_LATE", datetime(2026, 11, 8, 8, 0), 45)
    # 区间外（11-25，只在 month=2026-11 全月口径出现）
    add_event("T0001", "1", "0201", "D001", "PENDING", datetime(2026, 11, 25, 8, 0))

    def add_approval(pid, monitor_code, flag, apply_dt, dept_code, apply_user,
                     penalty_amount=None, penalty_exempt=False):
        db.add(TLApproval(
            patient_id=pid, visit_id="1", monitor_code=monitor_code,
            apply_date_time=apply_dt, type="LIMIT", flag=flag, apply_user_id=apply_user,
            hospital_no="0510000", dept_code=dept_code, penalty_amount=penalty_amount,
            penalty_exempt=penalty_exempt, apply_reason="临床超时申请",
        ))

    add_approval("T0001", "JH04.02.002", "2", datetime(2026, 11, 5, 10, 0), "0201", "D001", 300)
    add_approval("T0001", "JH04.02.002", "2", datetime(2026, 11, 6, 9, 0), "0201", "D001", None)
    add_approval("T0003", "JH04.02.002", "1", datetime(2026, 11, 7, 8, 30), "0201", "D002")
    add_approval("T0003", "JH04.02.002", "2", datetime(2026, 11, 25, 8, 0), "0201", "D002",
                 100, True)
    add_approval("T0004", "JH04.02.002", "2", datetime(2026, 11, 8, 9, 0), "0202", "D003",
                 200, True)
    db.commit()

    app = FastAPI()
    app.include_router(timeliness_router.router, prefix="/api/timeliness")
    app.dependency_overrides[get_db] = lambda: db
    yield db, {"admin": admin, "home": home}, app
    db.close()


def client_as(app, user) -> TestClient:
    app.dependency_overrides[auth_module.get_current_user] = lambda: user
    return TestClient(app)


@pytest.fixture()
def patched_his(monkeypatch):
    """visit_meta 与 staff 姓名映射全 mock（零真实 HIS 连接）。"""
    from app.timeliness import his_oracle_reader

    monkeypatch.setattr(his_oracle_reader, "fetch_patient_visit_meta",
                        lambda pairs: dict(VISIT_META))
    monkeypatch.setattr(his_oracle_reader, "get_staff_name_map",
                        lambda **kwargs: {"D001": "张医生", "D002": "李医生", "D003": "王医生"})
    return monkeypatch


# ---- 验收 1：任意日期区间只计区间内数据 ----

def test_stats_monthly_range_only_counts_range(env):
    db, users, app = env
    body = client_as(app, users["admin"]).get(
        "/api/timeliness/stats/monthly",
        params={"date_from": "2026-11-01", "date_to": "2026-11-10"},
    ).json()
    assert body["date_from"] == "2026-11-01"
    assert body["date_to"] == "2026-11-10"
    totals = body["totals"]
    # 区间内 4 事件（T0001×2 + T0003 + T0004）；11-25 的 PENDING 不计
    assert totals["total"] == 4
    assert totals["completed_on_time"] == 1
    assert totals["completed_late"] == 1
    assert totals["overdue"] == 1
    assert totals["warning"] == 1
    assert totals["pending"] == 0
    # 审批：A1/A2/A3/A5 落区间（A4 11-25 不计）；扣罚 300+200（A2 None 兜底）=500
    assert totals["approval_count"] == 4
    assert totals["approved_unlock_count"] == 3
    assert totals["exempt_count"] == 1
    assert totals["penalty_amount_total"] == 500
    keys = {(r["dept_code"], r["responsible_doctor_id"]) for r in body["rows"]}
    assert ("0201", "D001") in keys and ("0202", "D003") in keys


# ---- 验收 2：旧调用 month 返回结构兼容 ----

def test_stats_monthly_legacy_month_shape_unchanged(env):
    db, users, app = env
    body = client_as(app, users["admin"]).get(
        "/api/timeliness/stats/monthly", params={"month": "2026-11"}).json()
    # 旧三键齐全且语义不变；month 仍为 YYYY-MM
    assert body["month"] == "2026-11"
    assert set(("month", "totals", "rows")) <= set(body)
    # 11-25 事件/审批计入全月口径
    assert body["totals"]["total"] == 5
    assert body["totals"]["pending"] == 1
    assert body["totals"]["approval_count"] == 5
    assert body["totals"]["approved_unlock_count"] == 4
    assert body["totals"]["exempt_count"] == 2
    assert body["totals"]["penalty_amount_total"] == 500
    row = next(r for r in body["rows"]
               if r["dept_code"] == "0201" and r["responsible_doctor_id"] == "D001")
    for legacy_key in ("dept_code", "responsible_doctor_id", "total", "completed_on_time",
                       "completed_late", "overdue", "pending", "warning", "other",
                       "approval_count", "approved_unlock_count", "exempt_count",
                       "penalty_amount_total"):
        assert legacy_key in row
    assert row["total"] == 3            # E1+E2+E5
    assert row["completed_on_time"] == 1
    assert row["pending"] == 1
    assert row["approval_count"] == 2   # A1+A2
    assert row["penalty_amount_total"] == 500


# ---- 验收 3：新旧聚合实现逐行一致 ----

def _legacy_monthly_rows(db, current_user, month, dept=None):
    """改造前循环实现（旧代码原样复刻，作对照基准）。"""
    from datetime import timedelta

    from app.services.timeliness_access import timeliness_visibility

    month_start = datetime.strptime(month, "%Y-%m")
    month_end = (month_start + timedelta(days=32)).replace(day=1)

    def blank(dept_code, doctor_id):
        row = {"dept_code": dept_code, "responsible_doctor_id": doctor_id}
        for name in ("total", "completed_on_time", "completed_late", "overdue",
                     "pending", "warning", "other"):
            row[name] = 0
        for name in ("approval_count", "approved_unlock_count", "exempt_count",
                     "penalty_amount_total"):
            row[name] = 0
        return row

    query = db.query(TLEvent).filter(TLEvent.t0 >= month_start, TLEvent.t0 < month_end)
    visibility = timeliness_visibility(db, current_user)
    query = visibility.apply(query, TLEvent.dept_code)
    grouped: dict[tuple[str, str], dict] = {}
    for event in query.all():
        key = (event.dept_code or "", event.responsible_doctor_id or "")
        row = grouped.setdefault(key, blank(*key))
        row["total"] += 1
        if event.status == "COMPLETED_ON_TIME":
            row["completed_on_time"] += 1
        elif event.status == "COMPLETED_LATE":
            row["completed_late"] += 1
        elif event.status == "OVERDUE":
            row["overdue"] += 1
        elif event.status == "PENDING":
            row["pending"] += 1
        elif event.status == "WARNING":
            row["warning"] += 1
        else:
            row["other"] += 1
    approval_query = db.query(TLApproval).filter(
        TLApproval.apply_date_time >= month_start, TLApproval.apply_date_time < month_end)
    approval_query = visibility.apply(approval_query, TLApproval.dept_code)
    for approval in approval_query.all():
        key = (approval.dept_code or "", approval.apply_user_id or "")
        row = grouped.setdefault(key, blank(*key))
        row["approval_count"] += 1
        if str(approval.flag or "").strip() == "2":
            row["approved_unlock_count"] += 1
            if not bool(approval.penalty_exempt):
                amount = approval.penalty_amount
                row["penalty_amount_total"] += int(amount if amount is not None else 200)
        if bool(approval.penalty_exempt):
            row["exempt_count"] += 1
    return sorted(grouped.values(), key=lambda r: (r["dept_code"], r["responsible_doctor_id"]))


def test_monthly_rows_new_impl_matches_legacy(env):
    db, users, app = env
    legacy = _legacy_monthly_rows(db, users["admin"], "2026-11")
    fresh = timeliness_router._monthly_rows(db, users["admin"], "2026-11")
    assert len(legacy) == len(fresh)
    for old_row, new_row in zip(legacy, fresh):
        for key, value in old_row.items():
            assert new_row[key] == value, f"{key}: legacy={value} new={new_row[key]}"
        # 新增计算字段：on_time_rate = 按时/(按时+超时完成)×100
        denom = new_row["completed_on_time"] + new_row["completed_late"]
        expected = round(new_row["completed_on_time"] / denom * 100, 1) if denom else 0.0
        assert new_row["on_time_rate"] == expected


# ---- 验收 4：分页 ----

def test_stats_monthly_paged_rows_with_full_totals(env):
    db, users, app = env
    body = client_as(app, users["admin"]).get(
        "/api/timeliness/stats/monthly",
        params={"month": "2026-11", "page": 1, "limit": 2}).json()
    assert body["total_rows"] == 3
    assert body["page"] == 1 and body["limit"] == 2
    assert len(body["rows"]) == 2
    # totals 全量合计（换页不变）：全月 5 事件
    assert body["totals"]["total"] == 5
    body2 = client_as(app, users["admin"]).get(
        "/api/timeliness/stats/monthly",
        params={"month": "2026-11", "page": 2, "limit": 2}).json()
    assert len(body2["rows"]) == 1
    assert body2["totals"]["total"] == body["totals"]["total"]


# ---- 验收 5：xlsx 导出（真二进制）与 CSV 兼容 ----

def test_export_monthly_xlsx_and_csv(env):
    db, users, app = env
    client = client_as(app, users["admin"])
    resp = client.get("/api/timeliness/export/monthly", params={
        "format": "xlsx", "date_from": "2026-11-01", "date_to": "2026-11-10"})
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb.active
    assert ws.title == "时效考核统计"
    assert ws.cell(row=1, column=1).value == "病历时效考核统计表（2026-11-01 至 2026-11-10）"
    assert ws.cell(row=2, column=1).value == "科室名称"
    assert ws.cell(row=2, column=11).value == "按时率"
    assert ws.cell(row=2, column=15).value == "应扣金额(元)"
    assert ws.freeze_panes == "E3"
    # 区间口径 3 行数据 + 合计行（第 6 行）
    assert ws.max_row == 6
    assert ws.cell(row=6, column=1).value == "合计"
    assert ws.cell(row=6, column=5).value == 4
    assert ws.cell(row=6, column=15).value == 500
    # 按时率单元格为小数 + 百分比格式（含合计行校验：1/(1+1)=0.5 → 50.0%，防再次 /100 变 0.5%）
    rate_cell = ws.cell(row=3, column=11)
    assert rate_cell.number_format == "0.0%"
    sum_rate_cell = ws.cell(row=6, column=11)
    assert sum_rate_cell.number_format == "0.0%"
    assert sum_rate_cell.value == pytest.approx(0.5, abs=1e-4)
    # 审计记录 xlsx
    audit = db.query(ExportAuditLog).filter(
        ExportAuditLog.export_format == "xlsx").order_by(ExportAuditLog.id.desc()).first()
    assert audit is not None
    assert audit.export_type == "timeliness_monthly"
    import json as _json

    criteria = _json.loads(audit.filter_criteria) if isinstance(audit.filter_criteria, str) \
        else audit.filter_criteria
    assert criteria["date_from"] == "2026-11-01"
    assert criteria["date_to"] == "2026-11-10"

    # 旧调用：month 仍返回 CSV（结构不变）
    resp_csv = client.get("/api/timeliness/export/monthly", params={"month": "2026-11"})
    assert resp_csv.status_code == 200
    assert "text/csv" in resp_csv.headers["content-type"]
    lines = resp_csv.text.strip().splitlines()
    assert lines[0].startswith("月份")
    assert len(lines) == 1 + 3            # 表头 + 3 数据行
    audit_csv = db.query(ExportAuditLog).filter(
        ExportAuditLog.export_format == "csv").order_by(ExportAuditLog.id.desc()).first()
    assert audit_csv is not None


# ---- 验收 6：home 范围用户导出只含本科室 ----

def test_export_monthly_home_scope_only_own_dept(env):
    db, users, app = env
    resp = client_as(app, users["home"]).get(
        "/api/timeliness/export/monthly", params={"month": "2026-11"})
    assert resp.status_code == 200
    lines = resp.text.strip().splitlines()
    data_rows = [line.split(",") for line in lines[1:]]
    assert len(data_rows) >= 1
    assert all(row[1] == "0201" for row in data_rows)   # 科室编码列只有本科
    assert not any(row[1] == "0202" for row in data_rows)


# ---- 验收 7：events 新字段 / approvals 新筛选与状态汇总 / 非法日期 400 ----

def test_events_new_fields_with_mocked_visit_meta(env, patched_his):
    db, users, app = env
    body = client_as(app, users["admin"]).get("/api/timeliness/events").json()
    by_pid = {(i["patient_id"], i["visit_id"], i["status"]): i for i in body["items"]}
    on_time = by_pid[("T0001", "1", "COMPLETED_ON_TIME")]
    assert on_time["remaining_minutes"] is None          # 终态 → None
    assert on_time["inp_no"] == "0510001"
    assert on_time["sex"] == "男" and on_time["age"] == "45"
    assert on_time["admission_date"] == "2026-11-04T08:00:00"
    assert on_time["admission_diagnosis"] == "急性阑尾炎"
    assert on_time["nursing_level"] == "二级护理"
    # latest_approval：同患者同 visit 同监控码 → rule 匹配最新一条（A2 flag=2）
    assert on_time["latest_approval"]["flag"] == "2"
    assert on_time["latest_approval"]["match"] == "rule"
    assert on_time["latest_approval"]["penalty_exempt"] is False
    overdue = by_pid[("T0001", "1", "OVERDUE")]
    assert overdue["remaining_minutes"] is not None and overdue["remaining_minutes"] < 0
    warning = by_pid[("T0003", "1", "WARNING")]
    # T0003 最新申请 A4（11-25，flag=2 豁免）→ 同患者最新一条
    assert warning["latest_approval"]["flag"] == "2"
    assert warning["latest_approval"]["penalty_exempt"] is True


def test_events_doctor_filter(env, patched_his):
    db, users, app = env
    client = client_as(app, users["admin"])
    body = client.get("/api/timeliness/events", params={"doctor": "D001"}).json()
    assert body["total"] == 3
    assert {i["responsible_doctor_id"] for i in body["items"]} == {"D001"}
    # 姓名模糊 → 工号集合（staff map mock：张医生→D001）
    body_name = client.get("/api/timeliness/events", params={"doctor": "张医生"}).json()
    assert body_name["total"] == 3
    # 无匹配 → 空列表而非报错
    body_none = client.get("/api/timeliness/events", params={"doctor": "不存在"}).json()
    assert body_none["total"] == 0 and body_none["items"] == []


def test_approvals_new_filters_and_status_counts(env, patched_his):
    db, users, app = env
    client = client_as(app, users["admin"])
    body = client.get("/api/timeliness/approvals").json()
    assert body["status_counts"] == {"total": 5, "pending": 1, "approved": 4, "exempted": 2}
    assert body["total"] == 5
    row = next(i for i in body["items"] if i["patient_id"] == "T0001")
    assert row["approve_user_name"] == ""
    assert row["inp_no"] == "0510001"
    assert row["admission_diagnosis"] == "急性阑尾炎"
    assert row["apply_reason"] == "临床超时申请"          # 全文不截断
    # flag 筛选不影响 status_counts（同筛选不含 flag）
    body_flag = client.get("/api/timeliness/approvals", params={"flag": "1"}).json()
    assert body_flag["total"] == 1
    assert body_flag["status_counts"]["total"] == 5
    # 申请日期区间筛选：11-01~11-10 → A1/A2/A3/A5 共 4 条
    body_range = client.get("/api/timeliness/approvals", params={
        "apply_date_from": "2026-11-01", "apply_date_to": "2026-11-10"}).json()
    assert body_range["total"] == 4
    assert body_range["status_counts"]["total"] == 4
    # 申请人筛选（工号精确）
    body_applicant = client.get("/api/timeliness/approvals",
                                params={"applicant": "D001"}).json()
    assert body_applicant["total"] == 2
    # event_overdue_minutes：T0001 的事件（同患者同规则）存在
    linked = [i for i in body["items"] if i["patient_id"] == "T0001"]
    assert all(i["event_deadline"] is not None for i in linked)
    assert linked[0]["event_overdue_minutes"] is not None


def test_invalid_period_returns_400(env):
    db, users, app = env
    client = client_as(app, users["admin"])
    assert client.get("/api/timeliness/stats/monthly",
                      params={"date_from": "not-a-date", "date_to": "2026-11-10"}).status_code == 400
    assert client.get("/api/timeliness/stats/monthly",
                      params={"date_from": "2026-11-10", "date_to": "2026-11-01"}).status_code == 400
    assert client.get("/api/timeliness/stats/monthly",
                      params={"date_from": "2025-01-01", "date_to": "2026-01-03"}).status_code == 400
    assert client.get("/api/timeliness/stats/monthly",
                      params={"date_from": "2026-11-01"}).status_code == 400
    assert client.get("/api/timeliness/export/monthly",
                      params={"format": "pdf", "month": "2026-11"}).status_code == 422
    assert client.get("/api/timeliness/approvals",
                      params={"apply_date_from": "not-a-date"}).status_code == 400
