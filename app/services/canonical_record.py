"""
012 P2 草案：统一标准数据契约（CanonicalRecordEnvelope）与源级诊断。

冻结口径（012 §5，不得在本层改写）：
- 病程 event_time 固定为 caption_date_time；
- 护理同时保留 form_time 与 created_date，不得互相覆盖；
- record_id + source_system 必须稳定可追溯；
- query_failed / mapping_failed / 真实 0 行必须严格区分，失败 fail-closed；
- 内部患者键不得进入普通日志/指标/外部消息，统一使用不可逆 bundle_hash。

注意：本模块为独立契约层，尚未接入 load_patient_bundles / payload_composer
调度（切换码需另行书面批准，见 012 §9 P2 与 016 §3.2）。
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION_V1 = "canonical-envelope-v1-20260808"

#: 合法 source_status 取值（012 §5.2）
SOURCE_STATUS_OK = "ok"
SOURCE_STATUS_MISSING = "missing"
SOURCE_STATUS_MAPPING_FAILED = "mapping_failed"
SOURCE_STATUS_QUERY_FAILED = "query_failed"
SOURCE_STATUS_MISSING_CONTENT = "missing_content"
VALID_SOURCE_STATUS = frozenset({
    SOURCE_STATUS_OK,
    SOURCE_STATUS_MISSING,
    SOURCE_STATUS_MAPPING_FAILED,
    SOURCE_STATUS_QUERY_FAILED,
    SOURCE_STATUS_MISSING_CONTENT,
})

_NON_IDENTIFIER_RE = re.compile(r"[^0-9A-Za-z_一-鿿]+")


@dataclass
class CanonicalRecordEnvelope:
    """统一记录信封（012 §5.2）。时间字段保持原生日期类型，仅展示层格式化。"""

    source_system: str            # oracle_jhemr / oracle_ydhl / vastbase_jhemr
    source_name: str              # progress / nursing / admission / ...
    record_kind: str              # progress / nursing / lab / exam / ...
    record_subtype: str           # first_progress / daily_progress / ward_round / ...
    record_id: str                # 来源稳定主键
    patient_key_internal: str
    visit_number_internal: str
    event_time: datetime | None = None
    created_at: datetime | None = None
    signed_at: datetime | None = None
    source_updated_at: datetime | None = None
    template_code: str = ""
    record_name: str = ""
    content: str | None = None
    structured_fields: dict[str, Any] = field(default_factory=dict)
    dept_code: str = ""
    author_code: str = ""
    source_status: str = SOURCE_STATUS_OK
    schema_version: str = SCHEMA_VERSION_V1
    mapping_version: str = ""

    def validate(self) -> list[str]:
        """返回契约违规列表；空列表表示通过。调用方据此 fail-closed。"""
        errors: list[str] = []
        if not self.record_id:
            errors.append("record_id 为空")
        if not self.source_system:
            errors.append("source_system 为空")
        if not self.patient_key_internal:
            errors.append("patient_key_internal 为空")
        if not self.visit_number_internal:
            errors.append("visit_number_internal 为空")
        if self.source_status not in VALID_SOURCE_STATUS:
            errors.append(f"非法 source_status: {self.source_status}")
        for field_name, value in (
            ("event_time", self.event_time),
            ("created_at", self.created_at),
            ("signed_at", self.signed_at),
            ("source_updated_at", self.source_updated_at),
        ):
            if value is not None and not isinstance(value, (datetime, date)):
                errors.append(f"{field_name} 必须为原生日期类型，实际 {type(value).__name__}")
        return errors


@dataclass
class SourceDiagnostics:
    """源级诊断（012 §8.2.4 / §11）。禁止把患者键写入本结构。"""

    source_name: str
    row_count: int = 0
    valid_count: int = 0
    skipped_count: int = 0
    error_code: str | None = None
    elapsed_ms: int = 0
    retry_count: int = 0
    query_failed: bool = False

    def mark_query_failed(self, error_code: str) -> None:
        """查询失败：与真实 0 行严格区分（fail-closed 语义）。"""
        self.query_failed = True
        self.error_code = error_code


def normalize_column_name(name: Any) -> str:
    """列名规范化：Oracle 大写/中文列名与 Vastbase 小写列名统一为小写标识。"""
    text = str(name or "").strip()
    return text.lower()


def normalize_record_keys(record: dict[Any, Any]) -> dict[str, Any]:
    """将数据库行字典的列名统一规范化为小写键，值原样保留。"""
    return {normalize_column_name(key): value for key, value in (record or {}).items()}


def coerce_visit_number(value: Any) -> str:
    """numeric visit_id 与 Oracle 次数规范化为同一字符串身份。

    5 / 5.0 / "5" / "5.0" 均规范化为 "5"，保证不改变既有 bundle 身份。
    空值返回空字符串，由信封校验 fail-closed。
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    text = str(value).strip()
    if not text:
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer() and re.fullmatch(r"[+-]?\d+(\.0+)?", text):
        return str(int(number))
    return text


def ensure_native_datetime(value: Any) -> datetime | date | None:
    """时间字段只接受原生日期类型；字符串一律拒绝（012 §5.2 约束）。"""
    if value is None or isinstance(value, (datetime, date)):
        return value
    raise TypeError(f"时间字段必须为原生日期类型，实际 {type(value).__name__}")


def bundle_hash(patient_key_internal: str, visit_number_internal: str) -> str:
    """不可逆 bundle 哈希：日志/指标中替代明文患者键（012 §5.1/§12.3）。"""
    raw = f"{patient_key_internal}::{visit_number_internal}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def sanitize_log_text(text: str, *internal_keys: str) -> str:
    """防御性脱敏：将日志文本中出现的内部键替换为哈希片段。"""
    sanitized = str(text)
    for key in internal_keys:
        key_text = str(key or "")
        if key_text:
            sanitized = sanitized.replace(key_text, "[internal-key]")
    return sanitized


def assert_no_internal_key_in_labels(labels: dict[str, str]) -> None:
    """指标标签防御：标签值不得形似内部键（仅允许哈希/枚举值）。"""
    for name, value in (labels or {}).items():
        if _NON_IDENTIFIER_RE.sub("", str(value)) and "::" in str(value):
            raise ValueError(f"指标标签 {name} 疑似包含内部键，禁止上报")
