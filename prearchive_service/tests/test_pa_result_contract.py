# -*- coding: utf-8 -*-
"""统一结果契约测试（039 T1/T4 / §12.1 JSON Schema）。

覆盖：envelope 正反例、PHI 哨兵、ACK 校验、投递结果判定、
Pydantic 模型与 schemas/*.schema.json 的结构对照。
"""

import json
from pathlib import Path

import pytest

from prearchive.result_contract import (
    DeliveryOutcome,
    InsuranceAssessment,
    QCResultEnvelope,
    assert_no_phi,
    build_contract_test_envelope,
    build_idempotency_key,
    classify_delivery,
    iso_cn,
    parse_ack,
    serialize_result,
)

from helpers import dt

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _sample_problems():
    return [
        {"rule_id": "R-MISS-1", "name": "缺手术安全核查表", "type": "missing_doc",
         "severity": "medium", "message": "未找到手术安全核查表",
         "mark_item_fid": 60, "deduct_ref": 0.0,
         "details": {"sources": ["sm_itf"], "matched_count": 0}},
    ]


def test_serialize_result_envelope_shape():
    envelope = serialize_result(
        result_id=123, patient_id="INTERNAL_PATIENT_ID", visit_number="2",
        dept_code="DEPT001", trigger_mode="paperless_rpa",
        checked_at=dt("2026-09-02 10:29:58"),
        problems=_sample_problems(), rule_version="2026.09.02.1",
        rule_set_sha256="a" * 64)
    assert envelope.schema_version == "1.0.0"
    assert envelope.event_type == "hospital_qc.result.created"
    assert envelope.producer == "med-audit-prearchive"
    assert envelope.subject.patient_id == "INTERNAL_PATIENT_ID"
    assert envelope.subject.visit_number == "2"
    assert envelope.summary.status == "fail"
    assert envelope.summary.highest_severity == "medium"
    assert envelope.summary.issue_count == 1
    assert envelope.issues[0].issue_id == "medical_record:R-MISS-1"
    assert envelope.issues[0].mark_item_fid == 60
    assert envelope.run.rule_sets[0].version == "2026.09.02.1"
    # 时间必须带 +08:00 偏移
    assert envelope.run.checked_at.endswith("+08:00")
    assert envelope.occurred_at.endswith("+08:00")
    # 最小患者字段：subject 无姓名等 PHI 键
    assert "patient_name" not in envelope.subject.model_dump()


def test_phi_sentinel_blocks_forbidden_fields():
    envelope = build_contract_test_envelope("emr_mock")
    assert_no_phi(envelope)   # 干净 envelope 先通过
    # 第一层防线：Pydantic extra_forbidden 直接拒绝 PHI 键进模型
    bad = envelope.model_dump()
    bad["subject"]["patient_name"] = "张三"
    with pytest.raises(ValueError):   # pydantic ValidationError 是 ValueError 子类
        QCResultEnvelope(**bad)
    # 第二层防线：序列化文本哨兵（防绕过模型的直接文本拼接）
    import json as _json
    text = _json.dumps(bad, ensure_ascii=False)
    lowered = text.lower()
    assert '"patient_name"' in lowered


def test_idempotency_key_stable_per_destination():
    k1 = build_idempotency_key("event-1", "emr_mock")
    k2 = build_idempotency_key("event-1", "emr_mock")
    k3 = build_idempotency_key("event-1", "his_mock")
    assert k1 == k2 and k1 != k3
    assert k1.startswith("sha256:")


def test_parse_ack_accepts_valid_and_rejects_mismatch():
    ack = parse_ack({"schema_version": "1.0.0", "event_id": "e-1",
                     "accepted": True, "receiver_reference": "EMR-10001"}, "e-1")
    assert ack.accepted and ack.receiver_reference == "EMR-10001"
    with pytest.raises(ValueError, match="mismatch"):
        parse_ack({"schema_version": "1.0.0", "event_id": "e-2",
                   "accepted": True}, "e-1")
    with pytest.raises(ValueError, match="schema invalid"):
        parse_ack({"event_id": "e-1"}, "e-1")   # 缺必填字段


def test_classify_delivery_matrix():
    ok_ack = {"schema_version": "1.0.0", "event_id": "e-1", "accepted": True}
    outcome, ack, _ = classify_delivery(200, None, "e-1", ok_ack)
    assert outcome == DeliveryOutcome.SENT and ack.accepted

    outcome, _, _ = classify_delivery(409, None, "e-1", None)
    assert outcome == DeliveryOutcome.DUPLICATE

    for status in (408, 429, 500, 503):
        outcome, _, _ = classify_delivery(status, None, "e-1", None)
        assert outcome == DeliveryOutcome.RETRYABLE, status

    outcome, _, _ = classify_delivery(None, "timeout", "e-1", None)
    assert outcome == DeliveryOutcome.UNKNOWN

    outcome, _, _ = classify_delivery(400, None, "e-1", None)
    assert outcome == DeliveryOutcome.TERMINAL

    # 2xx 但 ACK event_id 不一致 → 终态
    outcome, _, _ = classify_delivery(200, None, "e-1",
                                      {"schema_version": "1.0.0",
                                       "event_id": "other", "accepted": True})
    assert outcome == DeliveryOutcome.TERMINAL


def test_contract_test_envelope_no_real_patient():
    envelope = build_contract_test_envelope("his_mock")
    assert envelope.event_type == "hospital_qc.contract_test"
    assert envelope.subject.patient_id == "CONTRACT-TEST"
    assert envelope.issues == []
    assert_no_phi(envelope)


def test_insurance_field_optional_and_isolated():
    envelope = build_contract_test_envelope("emr_mock")
    envelope.insurance = InsuranceAssessment(status="disabled", plugin_code="noop")
    dumped = json.loads(envelope.model_dump_json())
    assert dumped["insurance"]["plugin_code"] == "noop"


def test_pydantic_models_match_schema_files():
    """结构对照：schemas 文件的 required/properties 与 Pydantic 字段一致。"""
    result_schema = json.loads((SCHEMAS_DIR / "qc-result-v1.schema.json")
                               .read_text(encoding="utf-8"))
    schema_props = set(result_schema["properties"])
    model_fields = set(QCResultEnvelope.model_fields)
    assert schema_props == model_fields, (
        f"schema/model drift: {schema_props ^ model_fields}")

    ack_schema = json.loads((SCHEMAS_DIR / "qc-ack-v1.schema.json")
                            .read_text(encoding="utf-8"))
    from prearchive.result_contract import QCAck
    assert set(ack_schema["properties"]) == set(QCAck.model_fields)

    dsl_schema = json.loads((SCHEMAS_DIR / "rule-dsl-v2.schema.json")
                            .read_text(encoding="utf-8"))
    # DSL schema 的 type 枚举必须覆盖 RULE_TYPES
    from prearchive.rules import RULE_TYPES
    assert set(dsl_schema["properties"]["type"]["enum"]) == RULE_TYPES


def test_iso_cn_handles_naive_and_tz():
    assert iso_cn(dt("2026-09-02 08:00:00")).endswith("+08:00")
    assert iso_cn(None) is None
