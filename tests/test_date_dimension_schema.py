"""date_dimension 公开 schema 契约测试（001 §3.2-4 悬空收口）。

背景：调度器 daily_increment 对 EMR 海量源派发 inpatient_date（在院日增量），
loader `_fetch_inpatient_emr_records` 有显式分支，但公开 schema 枚举此前未覆盖，
导致手动推送/历史重跑无法复现同一加载语义。本测试固化修补后的契约。
"""
import pytest
from pydantic import ValidationError

from app.schemas import (
    AuditTypeTestSourceRequest,
    HistoricalRerunBatchCreateRequest,
    HistoricalRerunPreviewRequest,
    ManualPushRequest,
)

SCHEMA_CASES = [
    ("AuditTypeTestSourceRequest", AuditTypeTestSourceRequest, {"query_date": "2026-08-01"}),
    ("ManualPushRequest", ManualPushRequest, {}),
    (
        "HistoricalRerunPreviewRequest",
        HistoricalRerunPreviewRequest,
        {"query_date": "2026-08-01", "audit_run_mode": "daily_increment"},
    ),
    (
        "HistoricalRerunBatchCreateRequest",
        HistoricalRerunBatchCreateRequest,
        {"confirm_candidate_hash": "a" * 16, "query_date": "2026-08-01", "reaudit_reason": "复现口径"},
    ),
]


@pytest.mark.parametrize("name,schema,base", SCHEMA_CASES)
def test_date_dimension_accepts_inpatient_date(name, schema, base):
    """inpatient_date（在院日增量，EMR 源内部口径）必须与 loader/调度器一致可透传。"""
    payload = {**base, "date_dimension": "inpatient_date"}
    assert schema(**payload).date_dimension == "inpatient_date"


@pytest.mark.parametrize("name,schema,base", SCHEMA_CASES)
def test_date_dimension_rejects_unknown_value(name, schema, base):
    payload = {**base, "date_dimension": "not_a_dimension"}
    with pytest.raises(ValidationError):
        schema(**payload)


@pytest.mark.parametrize(
    "dimension",
    ["query_date", "record_create_date", "admission_date", "inpatient_date", "discharge_date"],
)
def test_date_dimension_full_enum_still_accepted(dimension):
    """既有枚举值全部保持可用（兼容性不回退）。"""
    req = ManualPushRequest(date_dimension=dimension)
    assert req.date_dimension == dimension
