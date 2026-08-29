"""前置机告警列表与 CSV 导出契约测试（023 P1-04 / 031 T1-3）。

覆盖：列表/导出筛选单源复用（R15）、导出内容与审计、患者标识脱敏、
admin 权限契约、后台告警列表逐字段筛选自动化（001 §4.2.4 尾注遗留，D14）。
"""
import csv
import inspect
import io
import json
from datetime import datetime
from types import SimpleNamespace

from fastapi.params import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.database import Base
from app.models import ExportAuditLog, PushLog, QCAlertFeedback, QCRecordAlertLog
from app.routers import patient_qc


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(db, n=3):
    alerts = []
    for i in range(n):
        pl = PushLog(
            patient_id=f"P{i}", visit_number="1", dept="内科", patient_name=f"患者{i}",
            admission_no=f"A{i}", status="success", severity="high", trigger_type="manual",
            query_date="2026-08-01", push_time=datetime(2026, 8, 5, 10, 0, 0),
            inconsistency=0, risk_score=0, elapsed_ms=0, retry_count=0, request_json="",
        )
        db.add(pl)
        db.flush()
        alert = QCRecordAlertLog(
            push_log_id=pl.id, dimension_code=f"dim{i}", patient_id=f"P{i}", visit_number="1",
            dept="内科" if i % 2 == 0 else "外科",
            severity="high" if i == 0 else "medium",
            alert_level="red", status="success" if i < 2 else "failed",
            viewed_flag=i % 2, view_count=i, viewer_name=f"医生{i}",
            payload_json='{"patient_info": {"patient_name": "敏感姓名"}}',
            created_at=datetime(2026, 8, 10, 9, 0, i),
        )
        db.add(alert)
        db.flush()
        alerts.append(alert)
    db.commit()
    return alerts


def _request():
    return Request({
        "type": "http", "method": "GET",
        "path": "/api/patient-qc/relay-alert/logs/export",
        "headers": [(b"user-agent", b"relay-export-test")],
        "client": ("127.0.0.1", 1), "query_string": b"",
        "scheme": "http", "server": ("test", 80), "asgi": {"version": "3.0"},
    })


def _admin():
    return SimpleNamespace(id=1, username="admin")


_FILTER_KWARGS = dict(
    patient_id=None, status=None, viewed_flag=None, dept=None,
    severity=None, date_from=None, date_to=None,
)


def test_list_and_export_share_single_filter_helper(monkeypatch):
    """R15：列表与导出必须走同一个筛选构造函数（禁止复制粘贴筛选逻辑）。"""
    db = _make_db()
    _seed(db)
    calls = []
    original = patient_qc._apply_relay_alert_filters

    def spy(q, **kwargs):
        calls.append(kwargs)
        return original(q, **kwargs)

    monkeypatch.setattr(patient_qc, "_apply_relay_alert_filters", spy)

    patient_qc.list_relay_alert_logs(db=db, _admin=_admin(), page=1, limit=20, **_FILTER_KWARGS)
    patient_qc.export_relay_alert_logs_csv(
        request=_request(), db=db, current_user=_admin(), **_FILTER_KWARGS
    )
    assert len(calls) == 2
    assert calls[0] == calls[1] == _FILTER_KWARGS
    db.close()


def test_export_csv_content_and_audit_record():
    db = _make_db()
    _seed(db)
    resp = patient_qc.export_relay_alert_logs_csv(
        request=_request(), db=db, current_user=_admin(),
        severity="high", status="success", **{k: v for k, v in _FILTER_KWARGS.items() if k not in ("severity", "status")},
    )
    body = resp.body.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(body)))
    assert resp.media_type.startswith("text/csv")
    assert rows[0][0] == "ID"
    data_rows = [r for r in rows[1:] if r]
    assert len(data_rows) == 1
    assert data_rows[0][3] == "P0"
    # 脱敏：患者正文（payload_json 内容）不得出现在 CSV
    assert "敏感姓名" not in body
    audit = db.query(ExportAuditLog).one()
    assert audit.export_type == "relay_alert"
    assert audit.export_format == "csv"
    assert audit.record_count == 1
    assert audit.status == "success"
    criteria = json.loads(audit.filter_criteria)
    assert criteria["severity"] == "high"
    db.close()


def test_export_audit_masks_patient_id_filter():
    db = _make_db()
    _seed(db)
    patient_qc.export_relay_alert_logs_csv(
        request=_request(), db=db, current_user=_admin(),
        patient_id="P", **{k: v for k, v in _FILTER_KWARGS.items() if k != "patient_id"},
    )
    audit = db.query(ExportAuditLog).one()
    assert json.loads(audit.filter_criteria)["patient_id"] == "已提供"
    db.close()


def test_list_and_export_require_admin_role():
    """权限契约：告警列表与导出都必须挂 admin 角色门。"""
    for fn in (patient_qc.list_relay_alert_logs, patient_qc.export_relay_alert_logs_csv):
        deps = [
            p.default for p in inspect.signature(fn).parameters.values()
            if isinstance(p.default, Depends) and getattr(p.default.dependency, "__closure__", None)
        ]
        roles = [
            cell.cell_contents
            for d in deps
            for cell in d.dependency.__closure__
            if isinstance(cell.cell_contents, str)
        ]
        assert "admin" in roles, fn.__name__


def test_relay_alert_list_filters_cover_every_field():
    """D14：后台告警列表逐字段筛选自动化。"""
    db = _make_db()
    _seed(db)

    def call(**overrides):
        kwargs = {**_FILTER_KWARGS, **overrides}
        return patient_qc.list_relay_alert_logs(db=db, _admin=_admin(), page=1, limit=50, **kwargs)

    assert call()["total"] == 3
    assert call(status="failed")["total"] == 1
    assert call(severity="high")["total"] == 1
    assert call(dept="外科")["total"] == 1
    assert call(viewed_flag=1)["total"] == 1
    assert call(patient_id="P1")["total"] == 1
    assert call(date_from="2026-08-10", date_to="2026-08-10")["total"] == 3
    assert call(date_from="2026-08-11")["total"] == 0
    # 无效日期不报错、不过滤
    assert call(date_from="bad-date")["total"] == 3
    db.close()


def test_relay_alert_list_pagination_and_feedback_join():
    db = _make_db()
    alerts = _seed(db)
    # 反馈挂在最新一条（created_at 最大 → 第 1 页首行）
    db.add(QCAlertFeedback(
        alert_log_id=alerts[2].id, push_log_id=alerts[2].push_log_id,
        dimension_code="dim2", action="rectified", reason="理由正文",
    ))
    db.commit()

    result = patient_qc.list_relay_alert_logs(
        db=db, _admin=_admin(), page=2, limit=2, **_FILTER_KWARGS
    )
    assert result["total"] == 3
    assert len(result["items"]) == 1  # 第 2 页仅剩 1 条

    first_page = patient_qc.list_relay_alert_logs(
        db=db, _admin=_admin(), page=1, limit=2, **_FILTER_KWARGS
    )
    with_fb = [i for i in first_page["items"] if i["feedback_action"]]
    assert len(with_fb) == 1
    assert with_fb[0]["feedback_action"] == "rectified"
    db.close()
