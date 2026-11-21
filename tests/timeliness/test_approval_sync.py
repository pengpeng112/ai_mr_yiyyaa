"""T9：审批同步与扣罚台账测试（app/timeliness/approval_sync.py + /api/timeliness/approvals*）。

覆盖（主设计文档 §15 T9 验收口径）：
- 同步幂等：重复执行 created=0、skipped_existing 计数；唯一键五列去重
  （同患者+监控码+apply_date_time 不重复建行，微秒差异归一）；
- 事件驱动：flag=1→APPLYING、flag=2→APPROVED（写 tl_event_history）；
  APPROVED 粘滞（不回退 APPLYING）、终态事件跳过（非法转换计数）、
  monitor_code 无对应规则不驱动；
- 扣罚金额按规则当前版本 penalty_amount 回填（FIRST_COURSE 种子未配置→None）；
- 端点：GET /approvals 分页过滤；exempt 需 timeliness_admin+原因必填+留痕+幂等；
  approve 写开关关闭 409（不连库：monkeypatch 必炸哨兵 writer 证明未触达）、
  默认演练 DRY_RUN 不改台账、显式 dry_run=false 成功路径对齐本地 flag 与事件、
  writer rowcount 异常 409；/dicts 含 jhemr_write_enabled；sync 端点只读源
  不可用 503（不伪造数据）。

全部测试不连接任何真实数据库；writer 以 mock/必炸哨兵注入。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth as auth_module
from app.database import Base, get_db
from app.models import Department, Permission, Role, RolePermission, User
from app.routers import timeliness as timeliness_router
from app.timeliness.approval_sync import sync_approvals
from app.timeliness.models import (
    TLActionLog,
    TLApproval,
    TLEvent,
    TLEventHistory,
    TLRule,
    TLRuleVersion,
)

NOW = datetime(2026, 11, 12, 9, 0, 0)
APPLY_DT = datetime(2026, 11, 12, 8, 30, 0)


def _row(**overrides):
    base = {
        "patient_id": "P001",
        "visit_id": "1",
        "monitor_code": "JH04.02.002",  # FIRST_COURSE 种子的监控码
        "apply_date_time": APPLY_DT,
        "type": "1",
        "flag": "1",
        "apply_user_id": "doc001",
        "apply_reason": "患者手术中",
        "approve_user_id": None,
        "approve_date_time": None,
        "hospital_no": "49557032X",  # 2026-11-12 裁定：真实 14 列含 hospital_no（NOT NULL）
        "dept_code": "0201",
    }
    base.update(overrides)
    return base


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    from app.timeliness.rules_seed import seed_rules

    seed_rules(db)

    perm = Permission(name="timeliness_admin", description="admin", module="timeliness")
    view_perm = Permission(name="timeliness_view", description="view", module="timeliness")
    db.add_all([perm, view_perm])
    admin_role = Role(name="admin", description="管理员")
    viewer_role = Role(name="tl_viewer", description="viewer")
    db.add_all([admin_role, viewer_role])
    db.flush()
    db.add(RolePermission(role_id=admin_role.id, permission_id=perm.id))
    db.add(RolePermission(role_id=viewer_role.id, permission_id=view_perm.id))
    db.flush()
    admin = User(username="tl_admin", password_hash="x", full_name="admin", role_id=admin_role.id)
    viewer = User(username="tl_viewer", password_hash="x", full_name="viewer", role_id=viewer_role.id)
    db.add_all([admin, viewer])

    version = (
        db.query(TLRuleVersion)
        .join(TLRule, TLRule.id == TLRuleVersion.rule_id)
        .filter(TLRule.rule_code == "FIRST_COURSE", TLRuleVersion.version_no == 1)
        .one()
    )
    # 三个事件：PENDING（flag=1 驱动）、OVERDUE（flag=2 驱动）、COMPLETED_ON_TIME（终态跳过）
    for pid, status in (("P001", "PENDING"), ("P002", "OVERDUE"), ("P003", "COMPLETED_ON_TIME")):
        db.add(TLEvent(
            event_uid=f"FIRST_COURSE:{pid}:1:1", rule_code="FIRST_COURSE",
            rule_version_id=version.id, patient_id=pid, visit_id="1",
            dept_code="0201", t0=NOW, status=status,
            last_scan_at=NOW, created_at=NOW, updated_at=NOW,
        ))
    db.commit()

    app = FastAPI()
    app.include_router(timeliness_router.router, prefix="/api/timeliness")
    app.dependency_overrides[get_db] = lambda: db
    yield db, {"admin": admin, "viewer": viewer}, app
    db.close()


def client_as(app, user) -> TestClient:
    app.dependency_overrides[auth_module.get_current_user] = lambda: user
    return TestClient(app)


# ---- sync_approvals 纯函数 ----


def test_sync_creates_rows_and_drives_applying(env):
    db, _users, _app = env
    stats = sync_approvals(db, {}, rows=[_row()])
    assert stats["created"] == 1 and stats["skipped_invalid"] == 0
    row = db.query(TLApproval).one()
    assert row.patient_id == "P001" and row.monitor_code == "JH04.02.002"
    assert row.flag == "1" and row.apply_reason == "患者手术中"
    # hospital_no/dept_code 随源行映射（approve 真实回写与科室白名单依赖这两列）
    assert row.hospital_no == "49557032X" and row.dept_code == "0201"
    # 2026-11-13 返工：FIRST_COURSE 种子 penalty_amount=200（12 条可锁定规则口径）
    assert row.penalty_amount == 200
    # flag=1 驱动 PENDING 事件 → APPLYING + 历史
    event = db.query(TLEvent).filter(TLEvent.patient_id == "P001").one()
    assert event.status == "APPLYING"
    hist = db.query(TLEventHistory).filter(TLEventHistory.event_id == event.id).one()
    assert hist.from_status == "PENDING" and hist.to_status == "APPLYING"
    assert "approval sync" in hist.reason


def test_sync_backfills_default_penalty_when_rule_unconfigured(env):
    """监控码无对应规则（或规则 penalty 为空）→ 按 DEFAULT_PENALTY_AMOUNT=200 回填。"""
    db, _users, _app = env
    stats = sync_approvals(db, {}, rows=[_row(monitor_code="JH99.99.999")])
    assert stats["created"] == 1
    row = db.query(TLApproval).one()
    assert row.penalty_amount == 200


def test_sync_updates_existing_row_flag_1_to_2_preserving_local_fields(env):
    """2026-11-13 返工核心：JHEMR 原生审批通过原地 UPDATE → 本地跟随升级 flag 1→2。

    本地人工 penalty_exempt/exempt_reason 与已有 PC_WEB 渠道标记不被覆盖；
    approve_channel 为空时补 JHEMR_NATIVE；计入 updated 而非 skipped_existing。
    """
    db, _users, _app = env
    first = sync_approvals(db, {}, rows=[_row(flag="1")])
    assert first["created"] == 1 and first["updated"] == 0
    approval = db.query(TLApproval).one()
    # 本地人工操作痕迹（豁免 + PC_WEB 渠道标记）
    approval.penalty_exempt = True
    approval.exempt_reason = "医疗部核定免罚"
    approval.approve_channel = "PC_WEB"
    db.commit()

    stats = sync_approvals(db, {}, rows=[_row(flag="2", approve_user_id="chief9",
                                              approve_date_time=datetime(2026, 11, 12, 9, 30))])
    assert stats["updated"] == 1 and stats["created"] == 0 and stats["skipped_existing"] == 0
    db.refresh(approval)
    assert approval.flag == "2"
    assert approval.approve_user_id == "chief9"
    assert approval.approve_date_time == datetime(2026, 11, 12, 9, 30)
    # 本地人工字段与既有渠道标记保留
    assert approval.penalty_exempt is True
    assert approval.exempt_reason == "医疗部核定免罚"
    assert approval.approve_channel == "PC_WEB"   # 已有渠道标记不被覆盖
    # 事件被 flag=2 驱动到 APPROVED
    event = db.query(TLEvent).filter(TLEvent.patient_id == "P001").one()
    assert event.status == "APPROVED"


def test_sync_existing_row_backfills_channel_jhemr_native_when_empty(env):
    """approve_channel 为空且源行已审批通过 → 补 JHEMR_NATIVE（原生画布审批溯源）。"""
    db, _users, _app = env
    sync_approvals(db, {}, rows=[_row(flag="1")])
    approval = db.query(TLApproval).one()
    assert approval.approve_channel is None
    stats = sync_approvals(db, {}, rows=[_row(flag="2", approve_user_id="chief9",
                                              approve_date_time=datetime(2026, 11, 12, 9, 30))])
    assert stats["updated"] == 1
    db.refresh(approval)
    assert approval.approve_channel == "JHEMR_NATIVE"


def test_sync_existing_row_backfills_empty_penalty_on_update(env):
    """更新既有行时 penalty_amount 为空 → 按规则（缺省 200）回填。"""
    db, _users, _app = env
    sync_approvals(db, {}, rows=[_row(flag="1")])
    approval = db.query(TLApproval).one()
    approval.penalty_amount = None   # 模拟历史同步（旧口径未回填）
    db.commit()
    sync_approvals(db, {}, rows=[_row(flag="2", approve_user_id="chief9",
                                      approve_date_time=datetime(2026, 11, 12, 9, 30))])
    db.refresh(approval)
    assert approval.penalty_amount == 200


def test_sync_unchanged_existing_row_still_skips(env):
    """源行与本地行完全一致 → skipped_existing（不重复更新 synced_at）。"""
    db, _users, _app = env
    sync_approvals(db, {}, rows=[_row(flag="1")])
    before = db.query(TLApproval).one().synced_at
    stats = sync_approvals(db, {}, rows=[_row(flag="1")], now=lambda: before + timedelta(hours=1))
    assert stats["skipped_existing"] == 1 and stats["updated"] == 0
    assert db.query(TLApproval).one().synced_at == before


def test_sync_is_idempotent(env):
    db, _users, _app = env
    first = sync_approvals(db, {}, rows=[_row(), _row(patient_id="P002", flag="2")])
    assert first["created"] == 2
    second = sync_approvals(db, {}, rows=[_row(), _row(patient_id="P002", flag="2")])
    assert second["created"] == 0 and second["skipped_existing"] == 2
    assert db.query(TLApproval).count() == 2
    assert db.query(TLEventHistory).count() == 2  # 重跑不重复写历史（APPLYING unchanged / APPROVED unchanged）


def test_sync_dedupes_same_key_ignoring_microseconds(env):
    db, _users, _app = env
    sync_approvals(db, {}, rows=[_row(apply_date_time=APPLY_DT)])
    again = sync_approvals(db, {}, rows=[_row(apply_date_time=APPLY_DT.replace(microsecond=123456))])
    assert again["created"] == 0 and again["skipped_existing"] == 1
    assert db.query(TLApproval).count() == 1


def test_sync_skips_rows_missing_key_fields(env):
    db, _users, _app = env
    stats = sync_approvals(db, {}, rows=[
        _row(monitor_code=""), _row(type=""), _row(patient_id=None),
        _row(hospital_no=""),  # hospital_no 为 NOT NULL 且模板 B 必需 → 缺失按无效跳过
    ])
    assert stats["created"] == 0 and stats["skipped_invalid"] == 4
    assert db.query(TLApproval).count() == 0


def test_sync_flag2_drives_approved_and_sticky(env):
    db, _users, _app = env
    stats = sync_approvals(db, {}, rows=[_row(patient_id="P002", flag="2",
                                              approve_user_id="chief",
                                              approve_date_time=datetime(2026, 11, 12, 9, 0))])
    assert stats["events_updated"] == 1
    event = db.query(TLEvent).filter(TLEvent.patient_id == "P002").one()
    assert event.status == "APPROVED"
    # 重跑 flag=1（申请行仍在）不得把 APPROVED 拉回 APPLYING（粘滞）
    again = sync_approvals(db, {}, rows=[_row(patient_id="P002", flag="2")])
    assert again["events_unchanged"] == 1
    later = sync_approvals(db, {}, rows=[_row(patient_id="P002", flag="1",
                                              apply_date_time=datetime(2026, 11, 12, 10, 0))])
    assert later["events_skipped"] == 1
    db.refresh(event)
    assert event.status == "APPROVED"


def test_sync_terminal_event_is_skipped(env):
    db, _users, _app = env
    stats = sync_approvals(db, {}, rows=[_row(patient_id="P003", flag="2")])  # COMPLETED_ON_TIME 终态
    assert stats["events_skipped"] == 1 and stats["events_updated"] == 0
    event = db.query(TLEvent).filter(TLEvent.patient_id == "P003").one()
    assert event.status == "COMPLETED_ON_TIME"


def test_sync_unknown_monitor_code_does_not_drive_events(env):
    db, _users, _app = env
    stats = sync_approvals(db, {}, rows=[_row(monitor_code="JH99.99.999")])
    assert stats["created"] == 1 and stats["events_updated"] == 0
    assert db.query(TLEvent).filter(TLEvent.patient_id == "P001").one().status == "PENDING"


def test_sync_accepts_fetch_rows_callable(env):
    db, _users, _app = env
    calls = []

    def fake_fetch(since):
        calls.append(since)
        return [_row()]

    stats = sync_approvals(db, {}, fetch_rows=fake_fetch, since="2026-11-01")
    assert calls == ["2026-11-01"]
    assert stats["created"] == 1


# ---- 端点 ----


def test_approvals_list_filters(env):
    db, users, app = env
    db.add(TLApproval(patient_id="P001", visit_id="1", monitor_code="JH04.02.002",
                      apply_date_time=APPLY_DT, type="1", flag="1",
                      hospital_no="49557032X", dept_code="0201",
                      penalty_amount=None, synced_at=NOW))
    db.add(TLApproval(patient_id="P009", visit_id="1", monitor_code="JH04.02.003",
                      apply_date_time=APPLY_DT, type="1", flag="2",
                      hospital_no="49557032X", dept_code="040112",
                      penalty_amount=None, synced_at=NOW))
    # 科室筛选按 Department 表解析（编码或名称）。
    db.add(Department(name="肝胆外科", code="040112"))
    db.commit()
    client = client_as(app, users["admin"])
    resp = client.get("/api/timeliness/approvals")
    assert resp.status_code == 200 and resp.json()["total"] == 2
    resp = client.get("/api/timeliness/approvals", params={"patient_id": "P009"})
    assert resp.json()["total"] == 1 and resp.json()["items"][0]["flag"] == "2"
    resp = client.get("/api/timeliness/approvals", params={"monitor_code": "JH04.02.002"})
    assert resp.json()["total"] == 1
    # 2026-11-13 返工：科室筛选（编码）+ 行带出 dept_code（台账展示用）。
    resp = client.get("/api/timeliness/approvals", params={"dept": "040112"})
    assert resp.json()["total"] == 1 and resp.json()["items"][0]["patient_id"] == "P009"
    assert resp.json()["items"][0]["dept_code"] == "040112"
    resp = client.get("/api/timeliness/approvals", params={"dept": "不存在科室"})
    assert resp.json()["total"] == 0


def test_exempt_requires_admin_and_reason_and_logs(env):
    db, users, app = env
    approval = TLApproval(patient_id="P001", visit_id="1", monitor_code="JH04.02.002",
                          apply_date_time=APPLY_DT, type="1", flag="1",
                          hospital_no="49557032X",
                          penalty_amount=200, synced_at=NOW)
    db.add(approval)
    db.commit()
    client = client_as(app, users["viewer"])
    assert client.post(f"/api/timeliness/approvals/{approval.id}/exempt",
                       json={"exempt_reason": "误报"}).status_code == 403  # 无 timeliness_admin

    admin_client = client_as(app, users["admin"])
    resp = admin_client.post(f"/api/timeliness/approvals/{approval.id}/exempt", json={})
    assert resp.status_code == 422  # 原因缺失（pydantic min_length）
    resp = admin_client.post(f"/api/timeliness/approvals/{approval.id}/exempt",
                             json={"exempt_reason": "系统误报，医疗部核实免罚"})
    assert resp.status_code == 200
    db.refresh(approval)
    assert approval.penalty_exempt is True
    assert approval.exempt_reason == "系统误报，医疗部核实免罚"
    log = db.query(TLActionLog).filter(TLActionLog.action_type == "APPROVAL_EXEMPT").one()
    assert log.mode == "EXECUTED" and "误报" in log.result and log.target == f"tl_approval:{approval.id}"
    # 幂等：重复豁免不覆盖既有原因
    resp = admin_client.post(f"/api/timeliness/approvals/{approval.id}/exempt",
                             json={"exempt_reason": "再次提交"})
    assert resp.status_code == 200 and resp.json()["message"] == "approval already exempted"
    db.refresh(approval)
    assert approval.exempt_reason == "系统误报，医疗部核实免罚"
    assert db.query(TLActionLog).filter(TLActionLog.action_type == "APPROVAL_EXEMPT").count() == 1


def test_exempt_cancel_roundtrip_and_audit(env):
    """2026-11-13 返工：cancel=true 取消豁免——清除豁免与原因、留 APPROVAL_EXEMPT_CANCEL
    审计；未豁免时幂等返回。"""
    db, users, app = env
    approval = TLApproval(patient_id="P005", visit_id="1", monitor_code="JH04.02.002",
                          apply_date_time=APPLY_DT, type="1", flag="1",
                          hospital_no="49557032X", penalty_amount=200, synced_at=NOW)
    db.add(approval)
    db.commit()
    admin_client = client_as(app, users["admin"])

    # 未豁免 → 幂等返回，不留审计
    resp = admin_client.post(f"/api/timeliness/approvals/{approval.id}/exempt",
                             json={"exempt_reason": "取消原因", "cancel": True})
    assert resp.status_code == 200 and resp.json()["message"] == "approval not exempted"
    assert db.query(TLActionLog).filter(
        TLActionLog.action_type == "APPROVAL_EXEMPT_CANCEL").count() == 0

    admin_client.post(f"/api/timeliness/approvals/{approval.id}/exempt",
                      json={"exempt_reason": "首罚豁免"})
    resp = admin_client.post(f"/api/timeliness/approvals/{approval.id}/exempt",
                             json={"exempt_reason": "复核后不豁免", "cancel": True})
    assert resp.status_code == 200 and resp.json()["message"] == "penalty exemption cancelled"
    db.refresh(approval)
    assert approval.penalty_exempt is False and approval.exempt_reason is None
    cancel_log = db.query(TLActionLog).filter(
        TLActionLog.action_type == "APPROVAL_EXEMPT_CANCEL").one()
    assert cancel_log.mode == "EXECUTED" and "复核后不豁免" in cancel_log.result


class _ExplodingWriter:
    """必炸哨兵：任何实例化即失败——证明 409 路径零连库。"""

    def __init__(self, *args, **kwargs):
        raise AssertionError("JhemrWriter must not be constructed when write switch is off")


class _FakeWriter:
    """可控 writer 替身：记录调用参数，返回预设 outcome。"""

    instances: list["_FakeWriter"] = []
    outcome: dict = {}
    error: Exception | None = None

    def __init__(self, db, config):
        self.calls: list[dict] = []
        _FakeWriter.instances.append(self)

    def approve_limit_log(self, **kwargs):
        self.calls.append(kwargs)
        if _FakeWriter.error is not None:
            raise _FakeWriter.error
        return dict(_FakeWriter.outcome)


@pytest.fixture()
def fake_writer(monkeypatch):
    _FakeWriter.instances = []
    _FakeWriter.outcome = {}
    _FakeWriter.error = None
    monkeypatch.setattr(timeliness_router, "JhemrWriter", _FakeWriter)
    return _FakeWriter


def _enable_write(monkeypatch, enabled: bool):
    monkeypatch.setattr(
        timeliness_router, "load_config",
        lambda: {"timeliness": {"enabled": True, "jhemr_write": {"enabled": enabled}}},
    )


def _make_approval(db) -> TLApproval:
    approval = TLApproval(patient_id="P002", visit_id="1", monitor_code="JH04.02.002",
                          apply_date_time=APPLY_DT, type="1", flag="1",
                          hospital_no="49557032X", dept_code="0201",
                          penalty_amount=200, synced_at=NOW)
    db.add(approval)
    db.commit()
    return approval


def test_approve_write_switch_off_returns_409_without_touching_writer(env, monkeypatch, fake_writer):
    db, users, app = env
    _enable_write(monkeypatch, enabled=False)
    approval = _make_approval(db)
    resp = client_as(app, users["admin"]).post(
        f"/api/timeliness/approvals/{approval.id}/approve", json={})
    assert resp.status_code == 409
    assert "超时审批" in resp.json()["detail"]
    assert fake_writer.instances == []  # writer 从未被构造 → 零连库
    blocked = db.query(TLActionLog).filter(TLActionLog.action_type == "JHEMR_APPROVE").one()
    assert blocked.mode == "BLOCKED"
    db.refresh(approval)
    assert approval.flag == "1"  # 台账未变


def test_approve_default_is_dry_run_and_keeps_ledger(env, monkeypatch, fake_writer):
    db, users, app = env
    _enable_write(monkeypatch, enabled=True)
    fake_writer.outcome = {"handled": True, "executed": False, "mode": "DRY_RUN",
                           "rowcount": None, "action_log_id": 77, "reason": ""}
    approval = _make_approval(db)
    resp = client_as(app, users["admin"]).post(
        f"/api/timeliness/approvals/{approval.id}/approve", json={})
    assert resp.status_code == 200
    assert resp.json()["message"] == "dry-run recorded (nothing written)"
    call = fake_writer.instances[0].calls[0]
    assert call["dry_run"] is True and call["monitor_code"] == "JH04.02.002"
    # 台账两列必须随请求传给 writer（科室白名单 + 模板 B WHERE 条件）
    assert call["hospital_no"] == "49557032X" and call["dept_code"] == "0201"
    db.refresh(approval)
    assert approval.flag == "1"  # 演练不改台账


def test_approve_real_execution_aligns_local_ledger_and_events(env, monkeypatch, fake_writer):
    db, users, app = env
    _enable_write(monkeypatch, enabled=True)
    fake_writer.outcome = {"handled": True, "executed": True, "mode": "EXECUTED",
                           "rowcount": 1, "action_log_id": 88, "reason": ""}
    approval = _make_approval(db)  # P002 的 OVERDUE 事件
    resp = client_as(app, users["admin"]).post(
        f"/api/timeliness/approvals/{approval.id}/approve", json={"dry_run": False})
    assert resp.status_code == 200 and resp.json()["message"].startswith("approved")
    assert fake_writer.instances[0].calls[0]["dry_run"] is False
    call = fake_writer.instances[0].calls[0]
    assert call["hospital_no"] == "49557032X" and call["dept_code"] == "0201"
    db.refresh(approval)
    assert approval.flag == "2" and approval.approve_user_id == "tl_admin"
    event = db.query(TLEvent).filter(TLEvent.patient_id == "P002").one()
    assert event.status == "APPROVED"
    assert db.query(TLEventHistory).filter(TLEventHistory.event_id == event.id).count() == 1


def test_approve_idempotent_when_already_flag2(env, monkeypatch, fake_writer):
    db, users, app = env
    _enable_write(monkeypatch, enabled=True)
    approval = _make_approval(db)
    approval.flag = "2"
    db.commit()
    resp = client_as(app, users["admin"]).post(
        f"/api/timeliness/approvals/{approval.id}/approve", json={"dry_run": False})
    assert resp.status_code == 200
    assert "already approved" in resp.json()["message"]
    assert fake_writer.instances == []


def test_approve_rowcount_error_maps_to_409(env, monkeypatch, fake_writer):
    from app.timeliness.jhemr_writer import JhemrWriteRowCountError

    db, users, app = env
    _enable_write(monkeypatch, enabled=True)
    fake_writer.error = JhemrWriteRowCountError("模板 B 受影响行数为 0（要求 1）")
    approval = _make_approval(db)
    resp = client_as(app, users["admin"]).post(
        f"/api/timeliness/approvals/{approval.id}/approve", json={"dry_run": False})
    assert resp.status_code == 409
    assert "受影响行数" in resp.json()["detail"]


def test_approve_writer_blocked_surfaces_reason(env, monkeypatch, fake_writer):
    db, users, app = env
    _enable_write(monkeypatch, enabled=True)
    fake_writer.outcome = {"handled": False, "executed": False, "mode": "BLOCKED",
                           "rowcount": None, "action_log_id": 9,
                           "reason": "blocked: dept not in pilot whitelist"}
    approval = _make_approval(db)
    resp = client_as(app, users["admin"]).post(
        f"/api/timeliness/approvals/{approval.id}/approve", json={"dry_run": False})
    assert resp.status_code == 200
    assert resp.json()["data"]["mode"] == "BLOCKED"
    db.refresh(approval)
    assert approval.flag == "1"


def test_dicts_includes_write_switch(env):
    _db, users, app = env
    resp = client_as(app, users["viewer"]).get("/api/timeliness/dicts")
    assert resp.status_code == 200
    assert resp.json()["jhemr_write_enabled"] is False  # 模板默认关


def test_sync_endpoint_unavailable_source_returns_503(env, monkeypatch):
    db, users, app = env
    from app.timeliness.config import TimelinessNotConfigured

    def broken(*args, **kwargs):
        raise TimelinessNotConfigured("timeliness 未启用")

    monkeypatch.setattr(timeliness_router, "sync_approvals", broken)
    resp = client_as(app, users["admin"]).post("/api/timeliness/approvals/sync")
    assert resp.status_code == 503
    assert "readonly source unavailable" in resp.json()["detail"]


def test_sync_endpoint_runs_and_reports_stats(env, monkeypatch):
    db, users, app = env
    monkeypatch.setattr(
        timeliness_router, "sync_approvals",
        lambda db_, cfg, since=None: {"created": 3, "skipped_existing": 0, "skipped_invalid": 1,
                                      "events_updated": 2, "events_unchanged": 0, "events_skipped": 1},
    )
    resp = client_as(app, users["admin"]).post("/api/timeliness/approvals/sync")
    assert resp.status_code == 200
    assert resp.json()["data"]["created"] == 3
