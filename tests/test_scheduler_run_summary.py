"""003 工作包 A：调度完整性汇总与质控可用语义。"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import AuditDimensionResult, Base, PushLog, QCRecordAlertLog, SchedulerHistory
from app.services.qc_status_semantics import (
    derive_qc_display_status,
    enrich_log_status_fields,
    is_qc_usable,
)
from app.services.scheduler_run_summary import (
    attach_history_item_flags,
    build_scheduler_run_summary,
    derive_overall_run_status,
    sanitize_error_summary,
)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_qc_usable_excludes_parse_failed_and_fallback():
    assert is_qc_usable("success", "success") is True
    assert is_qc_usable("success", "failed") is False
    assert is_qc_usable("success", "fallback") is False
    assert is_qc_usable("failed", "success") is False
    assert derive_qc_display_status("success", "failed") == "parse_failed"
    fields = enrich_log_status_fields("success", "failed")
    assert fields["transport_success"] is True
    assert fields["qc_usable"] is False
    assert "解析失败" in fields["qc_display_label"]


def test_derive_overall_partial_when_one_type_failed_before_pushlog():
    status = derive_overall_run_status(
        configured_codes=[
            "admission_vs_first_progress",
            "jyjc_vs_bcnursing",
            "progress_vs_nursing",
        ],
        type_statuses={
            "admission_vs_first_progress": "completed",
            "jyjc_vs_bcnursing": "failed",
            "progress_vs_nursing": "completed",
        },
    )
    assert status == "partial"


def test_derive_overall_failed_when_all_failed():
    status = derive_overall_run_status(
        configured_codes=["a", "b"],
        type_statuses={"a": "failed", "b": "failed"},
    )
    assert status == "failed"


def test_derive_overall_completed():
    status = derive_overall_run_status(
        configured_codes=["a", "b"],
        type_statuses={"a": "completed", "b": "completed"},
    )
    assert status == "completed"


def test_derive_overall_partial_when_missing_terminal():
    status = derive_overall_run_status(
        configured_codes=["a", "b", "c"],
        type_statuses={"a": "completed", "b": "completed"},
    )
    assert status == "partial"


def test_build_summary_type_level_failure_and_parse_failed_not_qc_usable(db_session):
    qdate = "2026-07-14"
    mode = "discharge_final"
    codes = [
        "admission_vs_first_progress",
        "jyjc_vs_bcnursing",
        "progress_vs_nursing",
    ]

    db_session.add_all(
        [
            SchedulerHistory(
                run_time=datetime(2026, 7, 14, 11, 0, 0),
                trigger_type="auto",
                query_date=qdate,
            audit_type_code="admission_vs_first_progress",
            audit_run_mode=mode,
                total_records=2,
                success_count=2,
                failed_count=0,
                duration_seconds=10,
                status="completed",
            ),
            SchedulerHistory(
                run_time=datetime(2026, 7, 14, 11, 1, 0),
                trigger_type="auto",
                query_date=qdate,
            audit_type_code="jyjc_vs_bcnursing",
            audit_run_mode=mode,
            error_code="ORA_TNS_RECEIVE_TIMEOUT",
            error_msg="ORA-12609: TNS receive timeout",
                total_records=0,
                success_count=0,
                failed_count=0,
                duration_seconds=5,
                status="failed",
            ),
            SchedulerHistory(
                run_time=datetime(2026, 7, 14, 11, 2, 0),
                trigger_type="auto",
                query_date=qdate,
            audit_type_code="progress_vs_nursing",
            audit_run_mode=mode,
                total_records=1,
                success_count=1,
                failed_count=0,
                duration_seconds=8,
                status="completed",
            ),
            PushLog(
                push_time=datetime(2026, 7, 14, 11, 0, 5),
                trigger_type="auto",
                query_date=qdate,
                patient_id="p1",
                audit_type_code="admission_vs_first_progress",
                audit_run_mode=mode,
                status="success",
                parse_status="failed",
                severity="",
            ),
            PushLog(
                push_time=datetime(2026, 7, 14, 11, 0, 6),
                trigger_type="auto",
                query_date=qdate,
                patient_id="p2",
                audit_type_code="admission_vs_first_progress",
                audit_run_mode=mode,
                status="success",
                parse_status="success",
                severity="high",
            ),
            PushLog(
                push_time=datetime(2026, 7, 14, 11, 2, 1),
                trigger_type="auto",
                query_date=qdate,
                patient_id="p3",
                audit_type_code="progress_vs_nursing",
                audit_run_mode=mode,
                status="success",
                parse_status="success",
                severity="low",
            ),
        ]
    )
    db_session.commit()

    # high dim + dept_filtered alert on usable admission log
    usable = (
        db_session.query(PushLog)
        .filter(PushLog.patient_id == "p2")
        .one()
    )
    db_session.add(
        AuditDimensionResult(
            push_log_id=usable.id,
            dimension_code="physical_examination",
            dimension="体格检查",
            status="fail",
            severity="high",
            confidence=0.9,
        )
    )
    db_session.add(
        QCRecordAlertLog(
            push_log_id=usable.id,
            dimension_code="physical_examination",
            patient_id="p2",
            severity="high",
            status="dept_filtered",
        )
    )
    db_session.commit()

    summary = build_scheduler_run_summary(
        db_session,
        query_date=qdate,
        audit_run_mode=mode,
        configured_codes=codes,
        lock_running=False,
    )

    assert summary["overall_status"] == "partial"
    assert summary["history_attribution"] == "scheduler_history_run_mode"
    assert summary["incomplete"] is True
    assert summary["banner"] is not None
    assert "jyjc_vs_bcnursing" in summary["type_level_failures"]

    by_code = {t["audit_type_code"]: t for t in summary["types"]}
    assert by_code["jyjc_vs_bcnursing"]["type_level_failure_before_pushlog"] is True
    assert by_code["jyjc_vs_bcnursing"]["history_error_code"] == "ORA_TNS_RECEIVE_TIMEOUT"
    assert by_code["jyjc_vs_bcnursing"]["push_log_count"] == 0
    assert by_code["admission_vs_first_progress"]["transport_success"] == 2
    assert by_code["admission_vs_first_progress"]["parse_failed"] == 1
    assert by_code["admission_vs_first_progress"]["qc_usable"] == 1  # parse_failed 不计可用
    assert by_code["admission_vs_first_progress"]["high"] == 1
    assert by_code["admission_vs_first_progress"]["alerts"]["dept_filtered"] == 1
    assert summary["totals"]["qc_usable"] == 2  # admission usable + progress


def test_sanitize_error_summary_redacts_sql_and_secrets():
    raw = "password=secret123 SELECT * FROM patients WHERE id=1 api_key=abcd"
    cleaned = sanitize_error_summary(raw)
    assert "secret123" not in cleaned
    assert "abcd" not in cleaned
    assert "SELECT" not in cleaned or "[redacted]" in cleaned


def test_attach_history_flags_for_pre_pushlog_failure():
    flags = attach_history_item_flags(
        {
            "status": "failed",
            "total_records": 0,
            "failed_count": 0,
            "audit_type_code": "jyjc_vs_bcnursing",
        }
    )
    assert flags["type_level_failure_before_pushlog"] is True
    assert flags["cannot_infer_from_pushlog_failed_zero"] is True


def test_null_history_fields_tolerant():
    flags = attach_history_item_flags(
        {
            "status": None,
            "total_records": None,
            "failed_count": None,
        }
    )
    assert flags["type_level_failure_before_pushlog"] is False


def test_summary_does_not_mix_daily_and_discharge_histories(db_session):
    qdate = "2026-07-14"
    code = "admission_vs_first_progress"
    db_session.add_all([
        SchedulerHistory(
            run_time=datetime(2026, 7, 14, 9, 5), trigger_type="auto", query_date=qdate,
            audit_type_code=code, total_records=1, success_count=1, failed_count=0,
            duration_seconds=10, status="completed",
            audit_run_mode="daily_increment",
        ),
        SchedulerHistory(
            run_time=datetime(2026, 7, 14, 12, 5), trigger_type="auto", query_date=qdate,
            audit_type_code=code, total_records=0, success_count=0, failed_count=0,
            duration_seconds=10, status="failed",
            audit_run_mode="discharge_final",
        ),
        PushLog(
            push_time=datetime(2026, 7, 14, 9, 4), trigger_type="auto", query_date=qdate,
            patient_id="daily", audit_type_code=code, audit_run_mode="daily_increment",
            status="success", parse_status="success",
        ),
        PushLog(
            push_time=datetime(2026, 7, 14, 12, 4), trigger_type="auto", query_date=qdate,
            patient_id="discharge", audit_type_code=code, audit_run_mode="discharge_final",
            status="success", parse_status="success",
        ),
    ])
    db_session.commit()

    daily = build_scheduler_run_summary(
        db_session, query_date=qdate, audit_run_mode="daily_increment", configured_codes=[code]
    )
    discharge = build_scheduler_run_summary(
        db_session, query_date=qdate, audit_run_mode="discharge_final", configured_codes=[code]
    )
    assert daily["history_attribution"] == "scheduler_history_run_mode"
    assert daily["types"][0]["history_status"] == "completed"
    assert discharge["types"][0]["history_status"] == "failed"


def test_summary_without_mode_anchor_is_unknown(db_session):
    db_session.add(SchedulerHistory(
        run_time=datetime(2026, 7, 14, 9, 5), trigger_type="auto", query_date="2026-07-14",
        audit_type_code="a", total_records=0, success_count=0, failed_count=0,
        duration_seconds=1, status="failed", audit_run_mode="",
    ))
    db_session.commit()
    summary = build_scheduler_run_summary(
        db_session, query_date="2026-07-14", audit_run_mode="daily_increment", configured_codes=["a"]
    )
    assert summary["overall_status"] == "unknown"
    assert summary["history_attribution"] == "unavailable_no_mode_push_anchor"


def test_run_summary_uses_mode_specific_lock(monkeypatch, db_session):
    from app.routers import scheduler as scheduler_router

    seen = []
    monkeypatch.setattr(scheduler_router, "load_config", lambda: {
        "scheduler_daily": {"audit_type_codes": ["a"]},
        "scheduler_discharge": {"audit_type_codes": ["a"]},
    })
    monkeypatch.setattr(
        "app.services.scheduler_lock_service.get_scheduler_lock_info",
        lambda lock_name: seen.append(lock_name) or {"status": "idle"},
    )
    monkeypatch.setattr(
        scheduler_router,
        "build_scheduler_run_summary",
        lambda *_args, **kwargs: {"lock_running": kwargs["lock_running"]},
    )

    scheduler_router.scheduler_run_summary(
        query_date="2026-07-14",
        audit_run_mode="discharge_final",
        db=db_session,
        _user=object(),
    )
    assert seen == ["discharge_push"]


def test_scheduler_history_api_exposes_mode_and_sanitized_error(db_session):
    from app.routers import scheduler as scheduler_router

    db_session.add(SchedulerHistory(
        run_time=datetime(2026, 8, 3, 11, 45),
        trigger_type="auto",
        query_date="2026-08-02",
        audit_type_code="progress_vs_nursing",
        audit_run_mode="discharge_final",
        total_records=0,
        success_count=0,
        failed_count=1,
        duration_seconds=60,
        status="failed",
        error_code="ORA_TNS_RECEIVE_TIMEOUT",
        error_msg="ORA-12609 SELECT * FROM patient_table WHERE patient_id='P001'",
    ))
    db_session.commit()

    result = scheduler_router.scheduler_history(
        page=1,
        limit=20,
        db=db_session,
        _user=object(),
    )
    item = result["items"][0]
    assert item["audit_run_mode"] == "discharge_final"
    assert item["error_code"] == "ORA_TNS_RECEIVE_TIMEOUT"
    assert "SELECT" not in item["error_msg"]
    assert "P001" not in item["error_msg"]
