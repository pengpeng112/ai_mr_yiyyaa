"""F-1/F-7 修复回归（round-8 复核轮，2026-10-04）。

背景：/logs 列表与 /logs/export/csv 此前均不接受 severity（UI 记录页严重度筛选
下拉发送该参数但被后端静默忽略→筛选无效，F-7）；导出端点不接受 patient_id
（记录页按患者筛选后导出范围实为全部行，列表与导出范围不一致，F-1）。

验证（内存 SQLite 直调路由函数，admin 直通可见性）：
- 列表 severity 过滤生效；
- 导出 patient_id/severity 过滤生效，CSV 内容与列表同分母；
- 导出审计 filter_criteria 记录 patient_id 与 severity，record_count=实际导出行数。
"""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import ExportAuditLog, PushLog, Role, User
from app.routers import logs as logs_router


@pytest.fixture()
def session_and_admin():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    role = Role(name="admin", description="")
    db.add(role)
    db.flush()
    user = User(username="admin", password_hash="x", full_name="admin", role_id=role.id)
    db.add(user)
    # 三行当前结果：SYNTH-A 2 行（high/low）、SYNTH-B 1 行（high）
    db.add_all([
        PushLog(trigger_type="manual", query_date="2026-08-12", patient_id="SYNTH-A",
                patient_name="甲", status="success", severity="high", dept="听觉植入科"),
        PushLog(trigger_type="manual", query_date="2026-08-12", patient_id="SYNTH-A",
                patient_name="甲", status="success", severity="low", dept="听觉植入科"),
        PushLog(trigger_type="manual", query_date="2026-08-12", patient_id="SYNTH-B",
                patient_name="乙", status="success", severity="high", dept="听觉植入科"),
    ])
    db.commit()
    yield db, SimpleNamespace(id=user.id, username="admin", role_id=role.id)
    db.close()


def _query_logs(db, user, **overrides):
    # 直调路由函数必须显式传全部参数：函数默认值是 Query(...) 标记对象（真值），
    # 缺省会误入过滤分支
    kwargs = dict(
        page=1, limit=50, status=None, dept=None, date_from=None, date_to=None,
        push_time_from=None, push_time_to=None, patient_id=None, patient_name=None,
        audit_type_code=None, reviewed_flag=None, manual_override=None, skip_reason=None,
        discharge_dept_name=None, severity=None, hide_superseded=True,
        include_superseded=False, alert_level=None, db=db, current_user=user,
    )
    kwargs.update(overrides)
    return logs_router.query_logs(**kwargs)


def _export_csv(db, user, **overrides):
    kwargs = dict(
        status=None, dept=None, date_from=None, date_to=None, reviewed_flag=None,
        manual_override=None, skip_reason=None, patient_id=None, severity=None,
        audit_type_code=None, patient_name=None, discharge_dept_name=None,
        hide_superseded=True, include_superseded=False, alert_level=None,
        request=None, db=db, current_user=user,
    )
    kwargs.update(overrides)
    return logs_router.export_csv(**kwargs)


def _csv_text(response) -> str:
    import asyncio

    async def _collect():
        chunks = [chunk async for chunk in response.body_iterator]
        return "".join(c.decode("utf-8") if isinstance(c, bytes) else c for c in chunks)

    return asyncio.run(_collect())


def _latest_audit(db) -> ExportAuditLog:
    return db.query(ExportAuditLog).order_by(ExportAuditLog.id.desc()).first()


def test_list_severity_filter_applies(session_and_admin):
    db, user = session_and_admin
    high = _query_logs(db, user, severity="high")
    assert high.total == 2
    assert {i.patient_id for i in high.items} == {"SYNTH-A", "SYNTH-B"}
    low = _query_logs(db, user, severity="low")
    assert low.total == 1 and low.items[0].patient_id == "SYNTH-A"
    # 不传 severity 时不受影响（含空 severity 历史行口径由 DB 决定，此处 3 行全量）
    assert _query_logs(db, user).total == 3


def test_export_patient_id_scope_matches_list(session_and_admin):
    db, user = session_and_admin
    listed = _query_logs(db, user, patient_id="SYNTH-A")
    response = _export_csv(db, user, patient_id="SYNTH-A")
    text = _csv_text(response)
    assert text.count("SYNTH-A,") == listed.total == 2
    assert "SYNTH-B" not in text
    audit = _latest_audit(db)
    assert audit.record_count == listed.total
    criteria = json.loads(audit.filter_criteria)
    assert criteria["patient_id"] == "SYNTH-A"


def test_export_severity_filter_and_combined(session_and_admin):
    db, user = session_and_admin
    text = _csv_text(_export_csv(db, user, severity="high"))
    assert text.count(",high,") >= 2  # 表头后的数据行含 high 两行（A/B）
    assert _latest_audit(db).record_count == 2
    criteria = json.loads(_latest_audit(db).filter_criteria)
    assert criteria["severity"] == "high"

    combined = _csv_text(_export_csv(db, user, patient_id="SYNTH-A", severity="high"))
    assert combined.count("SYNTH-A,") == 1
    assert _latest_audit(db).record_count == 1


def test_export_unfiltered_keeps_current_semantics(session_and_admin):
    db, user = session_and_admin
    text = _csv_text(_export_csv(db, user))
    assert text.count("SYNTH-A,") == 2 and "SYNTH-B," in text
    criteria = json.loads(_latest_audit(db).filter_criteria)
    assert criteria["patient_id"] is None and criteria["severity"] is None
    assert criteria["meta"]["semantics"] == "current-only"
