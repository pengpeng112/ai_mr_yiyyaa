from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import PushLog, QCFeedback
from app.routers import push as push_router
from app.schemas import ManualPushRequest
from app.services.data_source_loader import PatientBundle


def _audit_type(code="lab_exam_vs_progress_nursing", builder="lab_exam_progress_nursing"):
    return SimpleNamespace(
        code=code,
        name=code,
        payload={"builder": builder},
        group_key=["patient_id", "visit_number"],
    )


def _bundle(bundle_id="P001::1", sources=None, primary_source="lab"):
    return PatientBundle(
        bundle_id=bundle_id,
        group_values={"patient_id": "P001", "visit_number": "1"},
        sources=sources or {},
        source_field_mappings={},
        primary_source=primary_source,
        query_date="2026-05-01",
    )


def _sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _patch_precheck_dependencies(monkeypatch, audit_type, bundles, latest_map=None):
    monkeypatch.setattr(push_router, "load_config", lambda: {"data_source": {"type": "oracle"}})
    monkeypatch.setattr(push_router, "_resolve_manual_audit_types", lambda _config, _body: (None, [audit_type]))
    monkeypatch.setattr(
        push_router,
        "load_patient_bundles",
        lambda **_kwargs: (bundles, {"source_row_counts": {"lab": len(bundles)}}),
    )
    monkeypatch.setattr(push_router, "_load_latest_push_map", lambda _db, _keys: latest_map or {})


def test_push_precheck_does_not_double_count_empty_and_history(monkeypatch):
    audit_type = _audit_type()
    bundle = _bundle(sources={"progress": [{"content": "only progress"}]})
    latest = SimpleNamespace(status="success", reviewed_flag=1, manual_override=0)
    _patch_precheck_dependencies(monkeypatch, audit_type, [bundle], {"lab_exam_vs_progress_nursing::P001::1": latest})

    db = _sqlite_session()
    try:
        result = push_router.push_precheck(
            ManualPushRequest(query_date="2026-05-01", audit_type_codes=[audit_type.code]),
            db=db,
            _admin=object(),
        )
    finally:
        db.close()

    precheck = result["results"][0]["precheck"]
    assert precheck["bundle_count"] == 1
    assert precheck["skip_count"] == 1
    assert precheck["pushable_count"] == 0
    assert precheck["skip_reason_counts"] == {"empty_lab_exam": 1}
    assert sum(precheck["skip_reason_counts"].values()) == precheck["skip_count"]


def test_push_precheck_legacy_empty_audit_type_code_matches_rectified_suppressed(monkeypatch):
    audit_type = _audit_type("progress_vs_nursing", "legacy_progress_nursing")
    bundle = _bundle(sources={"primary": [{"患者ID": "P001", "次数": "1"}]}, primary_source="primary")
    _patch_precheck_dependencies(monkeypatch, audit_type, [bundle])

    db = _sqlite_session()
    try:
        log = PushLog(
            push_time=datetime.now(),
            trigger_type="manual",
            query_date="2026-05-01",
            patient_id="P001",
            visit_number="1",
            audit_type_code="",
            status="success",
            pushed_flag=1,
        )
        db.add(log)
        db.flush()
        db.add(
            QCFeedback(
                push_log_id=log.id,
                dept_id=1,
                created_by=1,
                status="rectified",
                suppress_ai_push=True,
            )
        )
        db.commit()

        result = push_router.push_precheck(
            ManualPushRequest(query_date="2026-05-01", audit_type_codes=[audit_type.code]),
            db=db,
            _admin=object(),
        )
    finally:
        db.close()

    precheck = result["results"][0]["precheck"]
    assert precheck["skip_reason_counts"].get("rectified_suppressed") == 1
    assert precheck["skip_count"] == 1
    assert precheck["pushable_count"] == 0


def test_push_precheck_rectified_suppressed_is_scoped_by_audit_type(monkeypatch):
    audit_type = _audit_type("lab_exam_vs_progress_nursing", "lab_exam_progress_nursing")
    bundle = _bundle(sources={"lab": [{"x": 1}], "progress": [{"x": 2}]})
    _patch_precheck_dependencies(monkeypatch, audit_type, [bundle])

    db = _sqlite_session()
    try:
        log = PushLog(
            push_time=datetime.now(),
            trigger_type="manual",
            query_date="2026-05-01",
            patient_id="P001",
            visit_number="1",
            audit_type_code="other_audit_type",
            status="success",
            pushed_flag=1,
        )
        db.add(log)
        db.flush()
        db.add(
            QCFeedback(
                push_log_id=log.id,
                dept_id=1,
                created_by=1,
                status="rectified",
                suppress_ai_push=True,
            )
        )
        db.commit()

        result = push_router.push_precheck(
            ManualPushRequest(query_date="2026-05-01", audit_type_codes=[audit_type.code]),
            db=db,
            _admin=object(),
        )
    finally:
        db.close()

    precheck = result["results"][0]["precheck"]
    assert "rectified_suppressed" not in precheck["skip_reason_counts"]
    assert precheck["skip_count"] == 0
    assert precheck["pushable_count"] == 1


def test_push_match_diagnostics_returns_context_inclusion_reasons(monkeypatch):
    audit_type = _audit_type()
    bundle = _bundle(
        sources={
            "lab": [
                {
                    "patient_id": "P001",
                    "visit_number": "1",
                    "test_no": "LAB1",
                    "test_name": "血常规",
                    "item_name": "白细胞",
                    "result": "12",
                    "abnormal_indicator": "H",
                    "result_time": "2026-05-01 10:00:00",
                }
            ],
            "progress": [
                {
                    "patient_id": "P001",
                    "visit_number": "1",
                    "record_id": "PR-BEFORE",
                    "record_name": "报告前病程",
                    "content": "before",
                    "event_time": "2026-05-01 09:00:00",
                },
                {
                    "patient_id": "P001",
                    "visit_number": "1",
                    "record_id": "PR-AFTER",
                    "record_name": "报告后病程",
                    "content": "after",
                    "event_time": "2026-05-01 11:00:00",
                },
            ],
            "nursing": [],
        }
    )
    _patch_precheck_dependencies(monkeypatch, audit_type, [bundle])
    db = _sqlite_session()
    try:
        result = push_router.push_match_diagnostics(
            ManualPushRequest(query_date="2026-05-01", audit_type_codes=[audit_type.code]),
            db=db,
            _admin=object(),
        )
    finally:
        db.close()

    detail = result["bundle_details"][0]
    rows = {row["record_id"]: row for row in detail["progress_candidates"]}
    assert result["source_row_counts"] == {"lab": 1}
    assert rows["PR-AFTER"]["status"] == "included"
    assert rows["PR-AFTER"]["matched_event_time"] == "2026-05-01 10:00:00"
    assert rows["PR-BEFORE"]["status"] == "excluded"
    assert "不晚于" in rows["PR-BEFORE"]["reason"]
