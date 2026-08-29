import json
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AuditDimensionResult, PushLog, QCAlertFeedback, QCFeedback, QCRecordAlertLog
from app.services.retention_service import (
    RetentionConfig,
    RetentionService,
    _sql_not_equal_text,
)


def test_sql_not_equal_text_oracle_uses_dbms_lob_substr():
    """Oracle CLOB 不得写 col != 'x'，须 DBMS_LOB.SUBSTR（修 ORA-00932）。"""
    pred = _sql_not_equal_text("mr_text", "[已清理]", oracle=True)
    assert "DBMS_LOB.SUBSTR(mr_text" in pred
    assert "!=" not in pred
    assert "<>" in pred
    assert "[已清理]" in pred

    sqlite_pred = _sql_not_equal_text("mr_text", "[已清理]", oracle=False)
    assert "DBMS_LOB" not in sqlite_pred
    assert "!=" in sqlite_pred


def test_l3_cleanup_preserves_json_contracts_and_cleans_all_sensitive_fields():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    log = PushLog(
        push_time=datetime.now() - timedelta(days=60), trigger_type="auto", query_date="2026-01-01",
        patient_id="P1", status="success", mr_text="病历", request_json="{}", response_json="{}",
    )
    db.add(log)
    db.flush()
    db.add(AuditDimensionResult(
        push_log_id=log.id, dimension="测试", medical_content="[已清理]", nursing_content="护理正文",
        medical_evidence_json='["证据"]', nursing_evidence_json='["证据"]', extra_json='{"secret": 1}',
    ))
    db.add(QCRecordAlertLog(push_log_id=log.id, payload_json='{"patient": "P1"}', last_error="错误正文"))
    db.commit()

    result = RetentionService(db, RetentionConfig({"l3_sensitive_content_days": 30}))._cleanup_l3()
    db.refresh(log)
    dim = db.query(AuditDimensionResult).one()
    alert = db.query(QCRecordAlertLog).one()
    assert log.mr_text == "[已清理]"
    assert log.request_json == "[已清理]"
    assert log.response_json == "[已清理]"
    assert dim.nursing_content == "[已清理]"
    assert json.loads(dim.medical_evidence_json) == []
    assert json.loads(dim.nursing_evidence_json) == []
    assert json.loads(dim.extra_json) == {}
    assert json.loads(alert.payload_json) == {}
    assert alert.last_error == "[已清理]"
    assert result["masked"] == 1
    assert result["dimension_masked"] == 1
    assert result["alert_masked"] == 1
    db.close()


def test_l3_cleanup_skips_already_masked_push_log():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    log = PushLog(
        push_time=datetime.now() - timedelta(days=60),
        trigger_type="auto",
        query_date="2026-01-01",
        patient_id="P2",
        status="success",
        mr_text="[已清理]",
        request_json="[已清理]",
        response_json="[已清理]",
        parse_error="[已清理]",
    )
    db.add(log)
    db.commit()
    result = RetentionService(db, RetentionConfig({"l3_sensitive_content_days": 30}))._cleanup_l3()
    assert result["masked"] == 0
    db.close()



def test_l3_cleanup_masks_alert_feedback_and_qc_feedback():
    """L3 反馈两表（QCAlertFeedback/QCFeedback）脱敏覆盖（001 §2.2.3 缺口核对补测）。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    log = PushLog(
        push_time=datetime.now() - timedelta(days=60), trigger_type="auto", query_date="2026-01-01",
        patient_id="P3", status="success", mr_text="[已清理]", request_json="[已清理]", response_json="[已清理]",
    )
    db.add(log)
    db.flush()
    alert = QCRecordAlertLog(
        push_log_id=log.id, payload_json="{}", last_error="[已清理]",
    )
    db.add(alert)
    db.flush()
    db.add(QCAlertFeedback(
        alert_log_id=alert.id, push_log_id=log.id, dimension_code="dim-1",
        action="rectified", reason="医生理由正文", rectification_text="整改正文",
    ))
    db.add(QCFeedback(
        push_log_id=log.id, dept_id=1, severity="low", status="pending", created_by=1,
        feedback_text="反馈正文", rectification_text="整改说明正文",
    ))
    db.commit()

    result = RetentionService(db, RetentionConfig({"l3_sensitive_content_days": 30}))._cleanup_l3()
    fb = db.query(QCAlertFeedback).one()
    qf = db.query(QCFeedback).one()
    assert fb.reason == "[已清理]"
    assert fb.rectification_text == "[已清理]"
    assert qf.feedback_text == "[已清理]"
    assert qf.rectification_text == "[已清理]"
    assert result["feedback_masked"] == 1
    assert result["qc_feedback_masked"] == 1
    db.close()
