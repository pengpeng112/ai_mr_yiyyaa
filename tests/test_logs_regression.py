"""回归测试：日志删除、失败原因展示、跳过记录修复。"""
from types import SimpleNamespace
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    AuditConclusion,
    AuditDimensionResult,
    PushLog,
    QCFeedback,
    QCFeedbackHistory,
)
from app.schemas import PushLogItem
from app.routers.logs import (
    _failure_reason,
    _skip_reason_label,
    _delete_push_logs,
)


# ---- _skip_reason_label ----

def test_skip_reason_label_known():
    assert _skip_reason_label("unreviewed_pending") == "已推送未复核"
    assert _skip_reason_label("rectified_suppressed") == "已整改抑制推送"
    assert _skip_reason_label("empty_lab_exam") == "检验检查数据为空"
    assert _skip_reason_label("empty_progress_nursing") == "病程护理记录为空"
    assert _skip_reason_label("empty_both_sides") == "检验检查和病程护理均为空"
    assert _skip_reason_label("cancelled") == "用户取消"


def test_skip_reason_label_unknown_passthrough():
    assert _skip_reason_label("some_new_reason") == "some_new_reason"


def test_skip_reason_label_none_and_empty():
    assert _skip_reason_label("") == ""
    assert _skip_reason_label(None) == ""


# ---- _failure_reason ----

def test_failure_reason_skipped_shows_label():
    log = SimpleNamespace(status="skipped", skip_reason="unreviewed_pending", error_msg="已推送但未复核", parse_error="")
    assert _failure_reason(log) == "已推送未复核：已推送但未复核"


def test_failure_reason_skipped_shows_label_and_detail():
    log = SimpleNamespace(status="skipped", skip_reason="empty_lab_exam", error_msg="病程和护理记录均为空，跳过 Dify 推送", parse_error="")
    assert _failure_reason(log) == "检验检查数据为空：病程和护理记录均为空，跳过 Dify 推送"


def test_failure_reason_skipped_fallback_to_error_msg():
    log = SimpleNamespace(status="skipped", skip_reason="", error_msg="跳过详情", parse_error="")
    assert _failure_reason(log) == "跳过详情"


def test_failure_reason_failed_shows_error_msg():
    log = SimpleNamespace(status="failed", skip_reason="", error_msg="Dify 超时", parse_error="")
    assert _failure_reason(log) == "Dify 超时"


def test_failure_reason_failed_fallback_to_parse_error():
    log = SimpleNamespace(status="failed", skip_reason="", error_msg="", parse_error="JSON 解析失败")
    assert _failure_reason(log) == "JSON 解析失败"


def test_failure_reason_success_returns_empty():
    log = SimpleNamespace(status="success", skip_reason="", error_msg="", parse_error="")
    assert _failure_reason(log) == ""


def test_failure_reason_error_status():
    log = SimpleNamespace(status="error", skip_reason="", error_msg="网络错误", parse_error="")
    assert _failure_reason(log) == "网络错误"


# ---- PushLogItem schema 新字段 ----

def test_push_log_item_includes_new_fields():
    payload = {
        "id": 1,
        "push_time": "2026-05-24T10:00:00",
        "trigger_type": "manual",
        "query_date": "2026-05-24",
        "patient_id": "p001",
        "patient_name": "张三",
        "dept": "心内科",
        "audit_type_code": "progress_vs_nursing",
        "audit_type_name": "病程护理核查",
        "status": "skipped",
        "inconsistency": 0,
        "severity": "",
        "risk_score": 0,
        "elapsed_ms": 0,
        "retry_count": 0,
        "pushed_flag": 0,
        "reviewed_flag": 0,
        "manual_override": 0,
        "skip_reason": "unreviewed_pending",
        "skip_reason_label": "已推送未复核",
        "error_msg": "已推送但未复核",
        "failure_reason": "已推送未复核",
        "alert_level": "",
    }
    item = PushLogItem.model_validate(payload)
    assert item.skip_reason == "unreviewed_pending"
    assert item.skip_reason_label == "已推送未复核"
    assert item.failure_reason == "已推送未复核"
    assert item.pushed_flag == 0


def test_push_log_item_new_fields_default_empty():
    payload = {
        "id": 2,
        "push_time": "2026-05-24T10:00:00",
        "trigger_type": "manual",
        "query_date": "2026-05-24",
        "patient_id": "p002",
        "status": "success",
        "inconsistency": 0,
        "elapsed_ms": 100,
        "retry_count": 0,
    }
    item = PushLogItem.model_validate(payload)
    assert item.skip_reason_label == ""
    assert item.failure_reason == ""


def test_push_log_item_null_fields_normalize():
    payload = {
        "id": 3,
        "push_time": "2026-05-24T10:00:00",
        "trigger_type": "manual",
        "query_date": "2026-05-24",
        "patient_id": "p003",
        "status": "skipped",
        "inconsistency": 0,
        "elapsed_ms": 0,
        "retry_count": 0,
        "skip_reason": None,
        "skip_reason_label": None,
        "error_msg": None,
        "failure_reason": None,
    }
    item = PushLogItem.model_validate(payload)
    assert item.skip_reason == ""
    assert item.skip_reason_label == ""
    assert item.error_msg == ""
    assert item.failure_reason == ""


# ---- skipped 日志 pushed_flag=0 ----

def test_create_skipped_push_log_has_pushed_flag_0():
    from app.services.push_executor import PushExecutor, PushConfig
    executor = PushExecutor(
        dify_config={},
        field_mapping={
            "patient_name": "patient_name",
            "admission_no": "admission_no",
            "visit_number": "visit_number",
            "dept": "dept",
        },
    )
    config = PushConfig(trigger_type="auto", query_date="2026-05-24")
    records = [{"mrid": "mr-100", "patient_name": "李四", "admission_no": "a100", "visit_number": "1", "dept": "骨科"}]
    log = executor._create_skipped_push_log(
        patient_id="p100_1",
        patient_records=records,
        push_config=config,
        skip_reason="unreviewed_pending",
        skip_message="已推送但未复核",
    )
    assert log.status == "skipped"
    assert log.pushed_flag == 0, "skipped 日志 pushed_flag 应为 0，避免阻断后续推送"


# ---- _delete_push_logs 数据库测试 ----

def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_delete_push_log_cascades_related_data():
    db = _make_db()
    # 创建 PushLog
    log = PushLog(
        push_time=datetime.now(), trigger_type="manual", query_date="2026-05-24",
        patient_id="p001", status="success", pushed_flag=1,
    )
    db.add(log)
    db.flush()
    log_id = log.id

    # 创建关联数据
    db.add(AuditDimensionResult(push_log_id=log_id, dimension="测试维度", status="pass"))
    db.add(AuditConclusion(push_log_id=log_id, has_inconsistency=0, risk_score=10))
    db.add(QCFeedback(push_log_id=log_id, dept_id=1, severity="low", status="pending", created_by=1))
    db.commit()

    feedback = db.query(QCFeedback).filter(QCFeedback.push_log_id == log_id).first()
    feedback_id = feedback.id
    db.add(QCFeedbackHistory(feedback_id=feedback_id, new_status="pending", changed_by=1))
    db.commit()

    # 执行删除
    deleted = _delete_push_logs(db, [log_id])
    assert deleted == 1

    # 验证所有关联数据已清理
    assert db.query(PushLog).filter(PushLog.id == log_id).count() == 0
    assert db.query(AuditDimensionResult).filter(AuditDimensionResult.push_log_id == log_id).count() == 0
    assert db.query(AuditConclusion).filter(AuditConclusion.push_log_id == log_id).count() == 0
    assert db.query(QCFeedback).filter(QCFeedback.push_log_id == log_id).count() == 0
    assert db.query(QCFeedbackHistory).filter(QCFeedbackHistory.feedback_id == feedback_id).count() == 0


def test_delete_push_logs_bulk():
    db = _make_db()
    for i in range(5):
        db.add(PushLog(
            push_time=datetime.now(), trigger_type="manual", query_date="2026-05-24",
            patient_id=f"p{i}", status="success", pushed_flag=1,
        ))
    db.commit()

    ids = [log.id for log in db.query(PushLog).all()]
    deleted = _delete_push_logs(db, ids[:3])
    assert deleted == 3
    assert db.query(PushLog).count() == 2


def test_delete_push_logs_empty_ids():
    db = _make_db()
    assert _delete_push_logs(db, []) == 0
    assert _delete_push_logs(db, [0, -1]) == 0


# ---- 路由顺序验证 ----

def test_bulk_delete_route_defined_before_single_delete():
    """验证 DELETE /bulk/delete 路由在 DELETE /{log_id} 之前注册，避免 FastAPI 路由冲突。"""
    from app.routers.logs import router
    # 只检查 DELETE 方法的路由
    delete_routes = [
        (i, r.path)
        for i, r in enumerate(router.routes)
        if hasattr(r, 'path') and 'DELETE' in (getattr(r, 'methods', None) or set())
    ]
    bulk_idx = next((i for i, (idx, p) in enumerate(delete_routes) if p == "/bulk/delete"), None)
    single_idx = next((i for i, (idx, p) in enumerate(delete_routes) if p == "/{log_id}"), None)
    assert bulk_idx is not None, "/bulk/delete DELETE 路由不存在"
    assert single_idx is not None, "/{log_id} DELETE 路由不存在"
    assert bulk_idx < single_idx, "/bulk/delete DELETE 路由必须在 /{log_id} DELETE 之前定义"
