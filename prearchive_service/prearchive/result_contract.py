# -*- coding: utf-8 -*-
"""统一结果契约（039 §6）：QC Result JSON v1 序列化器 + ACK 校验。

- 机器可读 JSON Schema 落在 ../schemas/*.schema.json（本模块的 Pydantic 模型
  与其保持字段级一致，测试里有结构对照断言）；
- 出站 envelope 只允许最小患者字段（patient_id/visit_number/encounter_type/
  dept_code），姓名、身份证、电话、地址、医保号、病历正文一律禁止——
  serialize 后有 PHI 哨兵自检；
- 时间统一 Asia/Shanghai (+08:00) 偏移 ISO 串；
- ACK 判定语义（039 §6.3）：2xx+合法 ACK=成功；409 且标识同一 event=幂等成功；
  408/429/5xx/超时=可重试；其他 4xx / ACK event_id 不一致 / schema 不合法=终态。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

CN_TZ = timezone(timedelta(hours=8))
PRODUCER = "med-audit-prearchive"
SCHEMA_VERSION = "1.0.0"
EVENT_RESULT_CREATED = "hospital_qc.result.created"
EVENT_CONTRACT_TEST = "hospital_qc.contract_test"

SUMMARY_STATUS_ORDER = {"pass": 0, "unknown": 1, "warn": 2, "fail": 3}
SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3}

# PHI 哨兵：envelope 序列化文本中出现即抛错（防字段扩展时意外带出）
_PHI_KEYS = ("patient_name", "id_card", "identity_card", "phone", "mobile",
             "address", "insurance_no", "medical_record_text", "mr_text")


def now_cn() -> datetime:
    return datetime.now(CN_TZ)


def iso_cn(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=CN_TZ)
    return value.astimezone(CN_TZ).isoformat(timespec="seconds")


def new_event_id() -> str:
    return str(uuid.uuid4())


class Subject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(min_length=1, max_length=64)
    visit_number: str = Field(min_length=1, max_length=32)
    encounter_type: str = "inpatient"
    dept_code: str = ""


class RuleSetRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    version: str
    sha256: str = ""


class RunInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: object = ""
    trigger_mode: str = ""
    checked_at: str
    data_snapshot_at: Optional[str] = None
    rule_sets: List[RuleSetRef] = Field(default_factory=list)


class SummaryInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str  # pass|warn|fail|unknown
    highest_severity: str = ""  # ""|low|medium|high
    issue_count: int = 0
    unknown_count: int = 0


class QCIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str
    domain: str
    rule_id: str
    rule_version: str
    mark_item_fid: Optional[int] = None
    name: str
    status: str = "fail"           # fail|warn|unknown
    severity: str = "medium"
    message: str
    recommendation: str = ""
    source_systems: List[str] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)
    requires_manual_review: bool = False


class InsuranceAssessment(BaseModel):
    """医保插件评估结果（envelope 可选 insurance 字段）。"""

    model_config = ConfigDict(extra="forbid")

    status: str                     # pass|warn|fail|unknown|disabled
    plugin_code: str
    ruleset_region: str = ""
    ruleset_year: str = ""
    ruleset_version: str = ""
    ruleset_sha256: str = ""
    grouper_code: str = ""
    mdc: str = ""
    adrg: str = ""
    drg: str = ""
    diagnostics: List[dict] = Field(default_factory=list)


class QCResultEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    event_id: str
    event_type: str = EVENT_RESULT_CREATED
    occurred_at: str
    producer: str = PRODUCER
    idempotency_key: str
    subject: Subject
    run: RunInfo
    summary: SummaryInfo
    issues: List[QCIssue] = Field(default_factory=list)
    insurance: Optional[InsuranceAssessment] = None


class QCAck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    event_id: str
    accepted: bool
    received_at: Optional[str] = None
    receiver_reference: str = ""
    message: str = ""


def build_idempotency_key(event_id: str, destination_code: str) -> str:
    """同一接收方重试保持不变：sha256(event_id + destination_code)。"""
    digest = hashlib.sha256(
        f"{event_id}:{destination_code}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def summarize_status(problem_count: int, unknown_count: int) -> str:
    if unknown_count and not problem_count:
        return "unknown"
    if problem_count:
        return "fail"
    return "pass"


def serialize_result(
    *,
    result_id: object,
    patient_id: str,
    visit_number: str,
    dept_code: str,
    trigger_mode: str,
    checked_at: Optional[datetime],
    problems: list,
    rule_version: str = "",
    rule_set_sha256: str = "",
    domain: str = "medical_record",
    data_snapshot_at: Optional[datetime] = None,
    event_id: Optional[str] = None,
    insurance: Optional[InsuranceAssessment] = None,
) -> QCResultEnvelope:
    """PrearchiveResult（problems 列表）→ QC Result Envelope v1。

    只取最小患者字段；problem dict 只拷贝白名单键到 evidence。
    """
    eid = event_id or new_event_id()
    issues: List[QCIssue] = []
    unknown_count = 0
    highest = ""
    for problem in problems or []:
        severity = str(problem.get("severity") or "medium")
        status = "fail" if problem.get("type") != "unknown" else "unknown"
        if problem.get("status") == "unknown":
            status = "unknown"
        if status == "unknown":
            unknown_count += 1
        if SEVERITY_ORDER.get(severity, 0) > SEVERITY_ORDER.get(highest, 0):
            highest = severity
        details = problem.get("details") if isinstance(problem.get("details"), dict) else {}
        # evidence 白名单：只保留标量/列表型最小证据，防整段文书带出
        evidence = {
            k: v for k, v in details.items()
            if isinstance(v, (str, int, float, bool, list)) and len(str(v)) <= 200
        }
        issues.append(QCIssue(
            issue_id=f"{domain}:{problem.get('rule_id', '')}",
            domain=domain,
            rule_id=str(problem.get("rule_id") or ""),
            rule_version=str(problem.get("rule_version") or rule_version or ""),
            mark_item_fid=problem.get("mark_item_fid"),
            name=str(problem.get("name") or ""),
            status=status,
            severity=severity,
            message=str(problem.get("message") or ""),
            source_systems=list(evidence.get("sources") or []) if isinstance(evidence.get("sources"), list) else [],
            evidence=evidence,
        ))
    envelope = QCResultEnvelope(
        event_id=eid,
        occurred_at=iso_cn(now_cn()),
        idempotency_key=build_idempotency_key(eid, "*"),   # 目标无关基键；发送时按目标重算
        subject=Subject(
            patient_id=str(patient_id or ""),
            visit_number=str(visit_number or ""),
            dept_code=str(dept_code or ""),
        ),
        run=RunInfo(
            result_id=result_id,
            trigger_mode=str(trigger_mode or ""),
            checked_at=iso_cn(checked_at or now_cn()),
            data_snapshot_at=iso_cn(data_snapshot_at) if data_snapshot_at else None,
            rule_sets=[RuleSetRef(domain=domain, version=rule_version, sha256=rule_set_sha256)]
            if rule_version else [],
        ),
        summary=SummaryInfo(
            status=summarize_status(len(issues), unknown_count),
            highest_severity=highest,
            issue_count=len(issues),
            unknown_count=unknown_count,
        ),
        issues=issues,
        insurance=insurance,
    )
    return envelope


def build_contract_test_envelope(destination_code: str) -> QCResultEnvelope:
    """「测试连接」专用合成事件：禁止选真实患者（039 §7.1）。"""
    eid = new_event_id()
    return QCResultEnvelope(
        event_id=eid,
        occurred_at=iso_cn(now_cn()),
        event_type=EVENT_CONTRACT_TEST,
        idempotency_key=build_idempotency_key(eid, destination_code),
        subject=Subject(patient_id="CONTRACT-TEST", visit_number="0"),
        run=RunInfo(result_id=0, trigger_mode="contract_test", checked_at=iso_cn(now_cn())),
        summary=SummaryInfo(status="pass", highest_severity="", issue_count=0, unknown_count=0),
        issues=[],
    )


def assert_no_phi(envelope: QCResultEnvelope) -> None:
    """PHI 哨兵：序列化文本出现禁携字段名即抛 ValueError。"""
    text = envelope.model_dump_json()
    lowered = text.lower()
    for key in _PHI_KEYS:
        if f'"{key}"' in lowered:
            raise ValueError(f"PHI sentinel violated: field {key!r} must not appear in envelope")
    # 常见身份证/手机号形态粗筛（虚构数据也可能撞上，仅对超长数字串报警）
    import re
    if re.search(r"\b\d{17}[\dXx]\b", text) or re.search(r"\b1[3-9]\d{9}\b", text):
        raise ValueError("PHI sentinel violated: id-card/phone-like digit sequence found")


def parse_ack(payload: dict, expected_event_id: str) -> QCAck:
    """校验回执：结构合法 + event_id 一致；不一致视为终态错误。"""
    if not isinstance(payload, dict):
        raise ValueError("ack payload must be a JSON object")
    try:
        ack = QCAck(**payload)
    except Exception as exc:
        raise ValueError(f"ack schema invalid: {exc}") from exc
    if ack.event_id != expected_event_id:
        raise ValueError(
            f"ack event_id mismatch: expected {expected_event_id}, got {ack.event_id}")
    return ack


# ---- 投递结果判定 ----

class DeliveryOutcome:
    SENT = "sent"
    DUPLICATE = "duplicate"       # 409 幂等成功
    RETRYABLE = "retryable"       # 408/429/5xx/超时/网络错误
    TERMINAL = "terminal"         # 其他 4xx / 坏 ACK / event_id 不一致
    UNKNOWN = "unknown"           # 超时后状态未知（仍按同 key 重试）


def classify_delivery(http_status: Optional[int], ack_error: Optional[str],
                     event_id: str, ack_payload=None) -> tuple:
    """返回 (outcome, ack_or_none, detail)。"""
    if http_status is None:
        # 网络层失败：状态未知，按同一 idempotency key 重试
        return DeliveryOutcome.UNKNOWN, None, str(ack_error or "network failure")

    if 200 <= http_status < 300:
        try:
            ack = parse_ack(ack_payload or {}, event_id)
        except ValueError as exc:
            return DeliveryOutcome.TERMINAL, None, f"bad ack: {exc}"
        if not ack.accepted:
            return DeliveryOutcome.TERMINAL, ack, "ack.accepted=false"
        return DeliveryOutcome.SENT, ack, "accepted"

    if http_status == 409:
        return DeliveryOutcome.DUPLICATE, None, "409 conflict: already received"

    if http_status in (408, 429) or http_status >= 500:
        return DeliveryOutcome.RETRYABLE, None, f"http {http_status}"

    return DeliveryOutcome.TERMINAL, None, f"http {http_status}"
