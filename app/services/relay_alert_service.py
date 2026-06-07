"""
前置机高危问题推送服务
当质控结果 severity == "high" 时，将每个高危维度作为一条消息推送到前置机接口，
由前置机转发企业微信告知医护人员。
"""
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import datetime
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.models import QCRecordAlertLog, QCFeedback, PushLog, AuditDimensionResult, AuditConclusion
from app.services.patient_snapshot import extract_patient_snapshot
from app.services.alert_token import generate_alert_token
from app.services.alert_evidence_service import extract_evidence_titles, build_evidence_summary

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit.relay_alert")


from app.utils.json_utils import safe_json_dumps as _safe_json_dumps


def _parse_json(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return {}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = _as_text(value)
        if text:
            return text
    return ""


_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*[^\s&]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+", re.I),
]


def _safe_error_text(text: str, limit: int = 200) -> str:
    value = str(text or "")
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("***", value)
    return value[:limit]


def _is_oracle_data_source() -> bool:
    from app.config import load_config
    cfg = load_config()
    return ((cfg.get("data_source") or {}).get("type") or "oracle") == "oracle"


def _get_oracle_connection_from_config():
    from app.config import load_config
    from app.services.config_parser import ConfigParser
    from app.oracle_client import get_oracle_connection
    cfg = ConfigParser.parse_oracle_config(load_config())
    return get_oracle_connection(cfg)


def _query_patient_dept_code(patient_id: str, visit_number: str = "") -> str:
    """从 JHEMR.V_QYBR 视图获取患者的出院/住院科室编码。"""
    if not patient_id or not _is_oracle_data_source():
        return ""
    if visit_number:
        visit_num = visit_number.strip()
    else:
        visit_num = ""
    conn = None
    cur = None
    try:
        conn = _get_oracle_connection_from_config()
        cur = conn.cursor()
        if visit_num:
            cur.execute(
                "SELECT \"出院科室编码\" FROM JHEMR.V_QYBR WHERE \"患者ID\" = :1 AND \"次数\" = :2 AND ROWNUM = 1",
                [patient_id, visit_num],
            )
        else:
            cur.execute(
                "SELECT \"出院科室编码\" FROM JHEMR.V_QYBR WHERE \"患者ID\" = :1 AND ROWNUM = 1",
                [patient_id],
            )
        row = cur.fetchone()
        if row:
            return _as_text(row[0])
    except Exception:
        pass
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return ""


def _query_patient_dept_info(patient_id: str, visit_number: str = "") -> dict:
    """从 JHEMR.V_QYBR 查询患者科室信息。仅使用已确认存在的字段。"""
    if not patient_id or not _is_oracle_data_source():
        return {}
    visit_num = str(visit_number or "").strip()
    conn = None
    cur = None
    try:
        conn = _get_oracle_connection_from_config()
        cur = conn.cursor()
        if visit_num:
            cur.execute(
                'SELECT * FROM (SELECT "出院科室编码", "所在科室名称", "入院科室名称", "出院日期", "入院日期" FROM JHEMR.V_QYBR WHERE "患者ID" = :pid AND "次数" = :vn ORDER BY "出院日期" DESC NULLS LAST, "入院日期" DESC NULLS LAST) WHERE ROWNUM = 1',
                {"pid": patient_id, "vn": visit_num},
            )
        else:
            cur.execute(
                'SELECT * FROM (SELECT "出院科室编码", "所在科室名称", "入院科室名称", "出院日期", "入院日期" FROM JHEMR.V_QYBR WHERE "患者ID" = :pid ORDER BY "出院日期" DESC NULLS LAST, "入院日期" DESC NULLS LAST) WHERE ROWNUM = 1',
                {"pid": patient_id},
            )
        row = cur.fetchone()
        if row:
            return {
                "dept_code": _as_text(row[0]),
                "dept_name": _as_text(row[1]),
                "admission_dept_name": _as_text(row[2]),
                "discharge_dept_name": "",
            }
    except Exception:
        pass
    finally:
        if cur is not None:
            try: cur.close()
            except Exception: pass
        if conn is not None:
            try: conn.close()
            except Exception: pass
    return {}


def _query_personnel_by_dept(dept_code: str = "", dept_name: str = "", role_keywords: list[str] | None = None) -> dict:
    """从 ODS.V_AI_ZKUSER 视图按科室编码或科室名称查询人员，默认查护理负责人/护士长。"""
    if (not dept_code and not dept_name) or not _is_oracle_data_source():
        return {}
    if role_keywords is None:
        role_keywords = ["护士长", "护理"]
    conn = None
    cur = None
    try:
        conn = _get_oracle_connection_from_config()
        cur = conn.cursor()
        role_values = [f"%{_as_text(kw)}%" for kw in role_keywords if _as_text(kw)]
        if not role_values:
            return {}
        like_clause = " OR ".join([f"remark LIKE :role{i}" for i in range(len(role_values))])
        role_params = {f"role{i}": value for i, value in enumerate(role_values)}
        # 按科室编码优先
        if dept_code:
            cur.execute(
                f"SELECT userid, user_name, remark FROM ODS.V_AI_ZKUSER WHERE \"科室编码\" = :dept_code AND ({like_clause}) AND ROWNUM = 1",
                {"dept_code": dept_code, **role_params},
            )
            row = cur.fetchone()
            if row:
                return {"userid": _as_text(row[0]), "user_name": _as_text(row[1]), "remark": _as_text(row[2])}
        # 按科室名称回退
        if dept_name:
            cur.execute(
                f"SELECT userid, user_name, remark FROM ODS.V_AI_ZKUSER WHERE \"所在科室\" = :dept_name AND ({like_clause}) AND ROWNUM = 1",
                {"dept_name": dept_name, **role_params},
            )
            row = cur.fetchone()
            if row:
                return {"userid": _as_text(row[0]), "user_name": _as_text(row[1]), "remark": _as_text(row[2])}
    except Exception:
        pass
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return {}


def _query_userid_by_name(user_name: str) -> dict:
    """从 ODS.V_AI_ZKUSER 按姓名反查 userid。用于管床医生/病历创建医师 userid 缺失时的回退。"""
    name = _as_text(user_name)
    if not name or not _is_oracle_data_source():
        return {}
    conn = None
    cur = None
    try:
        conn = _get_oracle_connection_from_config()
        cur = conn.cursor()
        cur.execute(
            "SELECT userid, user_name FROM ODS.V_AI_ZKUSER WHERE user_name = :name AND ROWNUM = 1",
            {"name": name},
        )
        row = cur.fetchone()
        if row:
            return {"userid": _as_text(row[0]), "user_name": _as_text(row[1])}
    except Exception:
        pass
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return {}


def _query_attending_doctor(patient_id: str, visit_number: str = "") -> dict:
    """从 JHEMR.V_QYBR 直接查询患者管床医生姓名和编号，用于 userid 缺失时的回退。"""
    if not patient_id or not _is_oracle_data_source():
        return {}
    if visit_number:
        visit_num = str(visit_number or "").strip()
    else:
        visit_num = ""
    conn = None
    cur = None
    try:
        conn = _get_oracle_connection_from_config()
        cur = conn.cursor()
        if visit_num:
            cur.execute(
                'SELECT * FROM (SELECT "管床医生编号", "管床医生", "出院日期", "入院日期" FROM JHEMR.V_QYBR WHERE "患者ID" = :pid AND "次数" = :vn ORDER BY "出院日期" DESC NULLS LAST, "入院日期" DESC NULLS LAST) WHERE ROWNUM = 1',
                {"pid": patient_id, "vn": visit_num},
            )
        else:
            cur.execute(
                'SELECT * FROM (SELECT "管床医生编号", "管床医生", "出院日期", "入院日期" FROM JHEMR.V_QYBR WHERE "患者ID" = :pid ORDER BY "出院日期" DESC NULLS LAST, "入院日期" DESC NULLS LAST) WHERE ROWNUM = 1',
                {"pid": patient_id},
            )
        row = cur.fetchone()
        if row:
            return {"doctor_id": _as_text(row[0]), "doctor_name": _as_text(row[1])}
    except Exception:
        pass
    finally:
        if cur is not None:
            try: cur.close()
            except Exception: pass
        if conn is not None:
            try: conn.close()
            except Exception: pass
    return {}


def _format_push_time(push_time: Any) -> str:
    if isinstance(push_time, datetime):
        return push_time.strftime("%Y-%m-%d %H:%M:%S")
    return str(push_time or "")


def _hydrate_patient_context(patient_info: dict, push_log: PushLog | None) -> dict:
    """统一补全前置机消息、H5详情页和后台列表需要的患者上下文。只补缺失字段。"""
    result = dict(patient_info)

    pid = result.get("patient_id") or ""
    vn = result.get("visit_number") or ""

    # 科室名称补全
    dept = _first_non_empty(
        result.get("dept"),
        result.get("dept_name"),
        result.get("department"),
        result.get("所在科室名称"),
        result.get("科室"),
    )
    if push_log and push_log.dept and not dept:
        dept = push_log.dept
    if not dept:
        dept_info = _query_patient_dept_info(pid, vn)
        result["dept_code"] = result.get("dept_code") or dept_info.get("dept_code") or ""
        dept = dept_info.get("dept_name") or ""
        result["admission_dept_name"] = result.get("admission_dept_name") or dept_info.get("admission_dept_name") or ""
    result["dept"] = dept
    result["dept_name"] = dept

    # 科室编码补全
    dept_code = _first_non_empty(
        result.get("dept_code"),
        result.get("科室编码"),
        result.get("department_code"),
    )
    if not dept_code:
        dept_info = _query_patient_dept_info(pid, vn)
        dept_code = dept_info.get("dept_code") or ""
    result["dept_code"] = dept_code

    # 管床医师补全
    doctor_id = _first_non_empty(
        result.get("doctor_id"),
        result.get("attending_doctor_userid"),
        result.get("attending_doctor_id"),
        result.get("管床医生编号"),
        result.get("管床医师编号"),
    )
    doctor_name = _first_non_empty(
        result.get("doctor_name"),
        result.get("attending_doctor_name"),
        result.get("attending_doctor"),
        result.get("管床医生"),
        result.get("管床医师"),
    )
    if (not doctor_id or not doctor_name) and pid:
        doc = _query_attending_doctor(pid, vn)
        if not doctor_id:
            doctor_id = doc.get("doctor_id") or ""
        if not doctor_name:
            doctor_name = doc.get("doctor_name") or ""
    if doctor_name and not doctor_id:
        lookup = _query_userid_by_name(doctor_name)
        doctor_id = lookup.get("userid") or doctor_id
    result["doctor_id"] = doctor_id
    result["doctor_name"] = doctor_name

    return result


def _get_patient_info(log: PushLog) -> dict:
    """从 push_log 中提取患者信息，复用 patient_snapshot。"""
    snapshot = extract_patient_snapshot(log)
    request_json = _parse_json(getattr(log, "request_json", "") or "")
    patient_info = request_json.get("patient_info", {}) if isinstance(request_json.get("patient_info"), dict) else {}

    doctor_id = _first_non_empty(
        patient_info.get("管床医师编号"),
        patient_info.get("管床医生编号"),
        patient_info.get("管床医生ID"),
        patient_info.get("管床医师ID"),
        patient_info.get("attending_doctor_id"),
        patient_info.get("attending_doctor_userid"),
        patient_info.get("doctor_id"),
        patient_info.get("userid"),
    )
    doctor_name = _first_non_empty(
        patient_info.get("管床医师"),
        patient_info.get("管床医生"),
        patient_info.get("attending_doctor_name"),
        patient_info.get("attending_doctor"),
        patient_info.get("doctor_name"),
    )
    nurse_head_id = _first_non_empty(patient_info.get("nurse_head_userid"), patient_info.get("nurse_head_id"), patient_info.get("护士长ID"))
    nurse_head_name = _first_non_empty(patient_info.get("nurse_head_name"), patient_info.get("护士长"))

    dept_code = _first_non_empty(
        patient_info.get("科室编码"),
        patient_info.get("dept_code"),
        patient_info.get("department_code"),
        snapshot.get("dept_code"),
    )
    if not dept_code:
        dept_code = _query_patient_dept_code(log.patient_id or "", str(log.visit_number or ""))

    result = {
        "patient_id": snapshot.get("patient_id") or log.patient_id or "",
        "patient_name": snapshot.get("patient_name") or log.patient_name or "",
        "admission_no": snapshot.get("admission_no") or log.admission_no or "",
        "visit_number": str(log.visit_number or ""),
        "dept": snapshot.get("dept_name") or log.dept or "",
        "doctor_id": doctor_id,
        "doctor_name": doctor_name,
        "nurse_head_userid": nurse_head_id,
        "nurse_head_name": nurse_head_name,
        "dept_code": dept_code,
        "admission_dept_name": snapshot.get("admission_dept_name") or "",
        "discharge_dept_name": snapshot.get("discharge_dept_name") or "",
    }

    return _hydrate_patient_context(result, log)


def _get_rule(cfg: dict, severity: str) -> tuple[str, dict]:
    rules = cfg.get("receiver_rules") or {}
    if not isinstance(rules, dict):
        rules = {}
    rule = rules.get(severity) or {}
    if not isinstance(rule, dict):
        rule = {}
    defaults = {
        "high": {"attending_doctor": True, "record_creator": True, "nurse_head": True, "fixed_users": [], "dedupe": True, "max_receivers": 5},
        "medium": {"attending_doctor": True, "record_creator": True, "nurse_head": False, "fixed_users": [], "dedupe": True, "max_receivers": 3},
        "low": {"attending_doctor": False, "record_creator": False, "nurse_head": False, "fixed_users": [], "dedupe": True, "max_receivers": 0},
    }.get(severity, {})
    merged = dict(defaults)
    merged.update(rule)
    return severity or "unknown", merged


def _extract_record_creator(payload: dict) -> dict:
    records: list[dict] = []
    documents = payload.get("medical_documents")
    if isinstance(documents, list):
        records.extend([item for item in documents if isinstance(item, dict)])
    sources = payload.get("sources")
    if isinstance(sources, dict):
        for source in sources.values():
            if not isinstance(source, dict):
                continue
            source_records = source.get("records")
            if isinstance(source_records, list):
                records.extend([item for item in source_records if isinstance(item, dict)])

    for item in records:
        if not isinstance(item, dict):
            continue
        userid = _first_non_empty(
            item.get("record_creator_userid"),
            item.get("record_creator_id"),
            item.get("creator_userid"),
            item.get("creator_id"),
            item.get("signed_doctor_id"),
            item.get("doctor_guid"),
            item.get("病历创建人编码"),
            item.get("病历创建人ID"),
            item.get("创建人ID"),
            item.get("病历文书_签名医师ID"),
        )
        name = _first_non_empty(
            item.get("record_creator_name"),
            item.get("creator_name"),
            item.get("signed_doctor_name"),
            item.get("signed_doctor"),
            item.get("creator"),
            item.get("病历创建人"),
            item.get("创建人"),
        )
        if userid or name:
            return {"userid": userid, "user_name": name}
    return {"userid": "", "user_name": ""}


# ---------- 默认 payload 字段配置 ----------

_DEFAULT_PAYLOAD_FIELDS = [
    {"key": "event", "source": "__static__", "static_value": "record_qc_issue", "enabled": True, "label": "事件类型", "group": "meta"},
    {"key": "doctor_id", "source": "patient_info.doctor_id", "enabled": True, "label": "管床医师编号", "group": "patient"},
    {"key": "doctor_name", "source": "patient_info.doctor_name", "enabled": True, "label": "管床医师", "group": "patient"},
    {"key": "dept", "source": "patient_info.dept", "enabled": True, "label": "科室", "group": "patient"},
    {"key": "patient_name", "source": "patient_info.patient_name", "enabled": True, "label": "患者姓名", "group": "patient"},
    {"key": "admission_no", "source": "patient_info.admission_no", "enabled": True, "label": "住院号", "group": "patient"},
    {"key": "document_type", "source": "dimension.dimension_name", "enabled": True, "label": "维度名称", "group": "dimension"},
    {"key": "problem", "source": "dimension.problem", "enabled": True, "label": "问题描述", "group": "dimension"},
    {"key": "problem_code", "source": "dimension.problem_code", "enabled": True, "label": "问题编码", "group": "dimension"},
    {"key": "alert_level", "source": "dimension.alert_level", "enabled": True, "label": "警示级别", "group": "dimension"},
    {"key": "severity", "source": "dimension.severity", "enabled": True, "label": "严重度", "group": "dimension"},
    {"key": "occurred_at", "source": "meta.occurred_at", "enabled": True, "label": "发生时间", "group": "meta"},
    {"key": "source", "source": "__static__", "static_value": "病历质控系统", "enabled": True, "label": "来源标识", "group": "meta"},
]


def _resolve_path(ctx: dict, path: str) -> str:
    """从 ctx 中按点分路径取值，返回字符串。"""
    parts = path.split(".")
    cur = ctx
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            cur = getattr(cur, p, None) if cur is not None else None
        if cur is None:
            return ""
    return str(cur)


def build_signed_request(payload: dict, secret: str) -> tuple[bytes, dict[str, str]]:
    """构建 HMAC_SHA256 签名的请求体和 headers。"""
    raw_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    message = timestamp.encode("utf-8") + b"." + raw_body
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Relay-Timestamp": timestamp,
        "X-Relay-Signature": signature,
    }
    return raw_body, headers


class RelayAlertService:
    """前置机高危问题推送服务。"""

    def __init__(self, db: Session, config: dict):
        self.db = db
        self.config = config or {}
        self.relay_cfg = self.config.get("relay_alert") or {}
        self.enabled = bool(self.relay_cfg.get("enabled"))
        self.base_url = str(self.relay_cfg.get("base_url") or "").rstrip("/")
        self.endpoint = str(self.relay_cfg.get("endpoint") or "/qc-record-alert")
        self.timeout = int(self.relay_cfg.get("timeout_seconds") or 10)
        self.max_retry = int(self.relay_cfg.get("max_retry") or 3)
        self.source = str(self.relay_cfg.get("source") or "病历质控系统")
        self.severity_levels = set(self.relay_cfg.get("severity_levels") or ["high"])
        self.secret = self._resolve_secret()
        detail_cfg = self.relay_cfg.get("detail_page") or {}
        self.detail_enabled = True if detail_cfg.get("enabled") is None else bool(detail_cfg.get("enabled"))
        self.token_ttl = int(detail_cfg.get("token_ttl_hours") or 72)
        self.external_base_url = str(detail_cfg.get("external_base_url") or "http://ydbi.sdent.com.cn:29080").rstrip("/")

    def _resolve_secret(self) -> str:
        plain = str(self.relay_cfg.get("secret_key") or "").strip()
        if plain:
            return plain
        enc = str(self.relay_cfg.get("secret_key_enc") or "").strip()
        if not enc:
            return ""
        try:
            from app.config import decrypt_value
            return decrypt_value(enc)
        except Exception:
            logger.warning("[relay_alert] secret_key_enc 解密失败，跳过推送")
            return ""

    def _build_receivers(self, patient_info: dict, push_log: PushLog | None, severity: str) -> tuple[list[dict], dict]:
        """按配置生成前置机接收人列表。userid 是唯一匹配键。"""
        request_payload = _parse_json(getattr(push_log, "request_json", "") or "") if push_log else {}
        rule_name, rule = _get_rule(self.relay_cfg, severity)
        receivers: list[dict] = []
        skipped: list[dict] = []

        def add_receiver(source: str, userid: str, user_name: str = "") -> None:
            userid = _as_text(userid)
            user_name = _as_text(user_name)
            if not userid and user_name:
                lookup = _query_userid_by_name(user_name)
                if lookup.get("userid"):
                    userid = _as_text(lookup.get("userid"))
            if not userid:
                skipped.append({"source": source, "reason": "empty_userid", "user_name": user_name})
                return
            receivers.append({"source": source, "userid": userid, "user_name": user_name})

        if rule.get("attending_doctor"):
            doc_id = patient_info.get("doctor_id") or patient_info.get("attending_doctor_userid") or ""
            doc_name = patient_info.get("doctor_name") or patient_info.get("attending_doctor_name") or ""
            # fallback: try snapshot/raw source for doctor info when empty
            if (not doc_id or not doc_name) and push_log:
                snapshot = _parse_json(getattr(push_log, "request_json", "") or "")
                if not doc_id:
                    doc_id = _first_non_empty(
                        snapshot.get("patient_info", {}).get("管床医生编号"),
                        snapshot.get("patient_info", {}).get("管床医生ID"),
                        snapshot.get("patient_info", {}).get("管床医师编号"),
                    )
                if not doc_name:
                    doc_name = _first_non_empty(
                        snapshot.get("patient_info", {}).get("管床医生"),
                        snapshot.get("patient_info", {}).get("管床医师"),
                    )
            # final fallback: query Oracle V_QYBR directly for doctor info
            if (not doc_id or not doc_name) and push_log:
                qdoc = _query_attending_doctor(
                    patient_info.get("patient_id") or "",
                    patient_info.get("visit_number") or "",
                )
                if qdoc.get("doctor_id") and not doc_id:
                    doc_id = qdoc["doctor_id"]
                if qdoc.get("doctor_name") and not doc_name:
                    doc_name = qdoc["doctor_name"]
            add_receiver("attending_doctor", doc_id, doc_name)

        if rule.get("record_creator"):
            creator = _extract_record_creator(request_payload)
            add_receiver("record_creator", creator.get("userid"), creator.get("user_name"))

        if rule.get("nurse_head"):
            if patient_info.get("nurse_head_userid"):
                add_receiver("nurse_head", patient_info.get("nurse_head_userid"), patient_info.get("nurse_head_name"))
            else:
                # 级别2：静态配置 nurse_heads
                nurse_heads = self.relay_cfg.get("nurse_heads") or []
                dept = patient_info.get("dept") or ""
                dept_code = patient_info.get("dept_code") or ""
                matched = False
                if isinstance(nurse_heads, list):
                    for item in nurse_heads:
                        if not isinstance(item, dict) or not item.get("enabled", True):
                            continue
                        if _as_text(item.get("dept")) and _as_text(item.get("dept")) != dept:
                            continue
                        add_receiver("nurse_head", item.get("userid"), item.get("user_name"))
                        matched = True
                        break
                # 级别3：查询 ODS.V_AI_ZKUSER 视图
                if not matched and (dept_code or dept):
                    nh = _query_personnel_by_dept(dept_code=dept_code, dept_name=dept)
                    if nh:
                        add_receiver("nurse_head", nh.get("userid"), nh.get("user_name"))
                        matched = True
                if not matched:
                    skipped.append({"source": "nurse_head", "reason": "not_configured", "dept": dept or dept_code})

        fixed_users = rule.get("fixed_users") or []
        if isinstance(fixed_users, list):
            for item in fixed_users:
                if isinstance(item, dict):
                    add_receiver("fixed_user", item.get("userid"), item.get("user_name"))
                else:
                    add_receiver("fixed_user", item, "")

        deduped = bool(rule.get("dedupe", True))
        if deduped:
            seen = set()
            unique = []
            for item in receivers:
                userid = item.get("userid") or ""
                if userid in seen:
                    skipped.append({"source": item.get("source"), "reason": "duplicate_userid", "userid": userid})
                    continue
                seen.add(userid)
                unique.append(item)
            receivers = unique

        max_receivers = int(rule.get("max_receivers") or 0)
        if max_receivers > 0 and len(receivers) > max_receivers:
            for item in receivers[max_receivers:]:
                skipped.append({"source": item.get("source"), "reason": "max_receivers_exceeded", "userid": item.get("userid")})
            receivers = receivers[:max_receivers]

        debug = {
            "rule": rule_name,
            "deduped": deduped,
            "skipped": skipped,
            "source_fields": {
                "attending_doctor": "patient_info.attending_doctor_userid/doctor_id",
                "record_creator": "medical_documents/sources.records creator_userid/creator_id",
                "nurse_head": "patient_info.nurse_head_userid / relay_alert.nurse_heads / ODS.V_AI_ZKUSER视图",
            },
        }
        return receivers, debug

    def _is_suppressed_for_push_log(self, push_log_id: int) -> bool:
        """检查对应 PushLog 的整改抑制状态。"""
        log = self.db.query(PushLog).filter(PushLog.id == push_log_id).first()
        if not log:
            return False
        return (
            self.db.query(QCFeedback.id)
            .join(PushLog, QCFeedback.push_log_id == PushLog.id)
            .filter(QCFeedback.suppress_ai_push == True)
            .filter(QCFeedback.status.in_(["rectified", "closed"]))
            .filter(PushLog.patient_id == log.patient_id)
            .filter(PushLog.visit_number == str(log.visit_number or ""))
            .filter(PushLog.audit_type_code == str(log.audit_type_code or ""))
            .first()
            is not None
        )

    def enqueue_high_severity_alerts(self, push_log_id: int) -> int:
        """根据 push_log_id 读取结论和维度，生成待发送 alert log。返回新增数量。"""
        if not self.enabled:
            return 0

        if self._is_suppressed_for_push_log(push_log_id):
            audit_logger.info("[relay_alert] push_log_id=%s suppressed by QCFeedback", push_log_id)
            return 0

        log = self.db.query(PushLog).filter(PushLog.id == push_log_id).first()
        if not log:
            return 0

        conclusion = self.db.query(AuditConclusion).filter(
            AuditConclusion.push_log_id == push_log_id
        ).first()

        dimensions = self.db.query(AuditDimensionResult).filter(
            AuditDimensionResult.push_log_id == push_log_id
        ).all()

        patient_info = _get_patient_info(log)
        visit_number = str(log.visit_number or "")
        push_time = _format_push_time(log.push_time)
        added = 0

        # 维度级推送（只按 severity 过滤，不额外要求 status/issue_summary）
        seen_codes: set[str] = set()
        for idx, dim in enumerate(dimensions):
            if dim.severity not in self.severity_levels:
                continue

            # 生成唯一的 dimension_code：空值或重复时用 fallback
            raw_code = (dim.dimension_code or "").strip()
            if not raw_code:
                raw_code = f"__dim_{idx}__"
            code = raw_code
            suffix = 1
            while code in seen_codes or self._exists_alert(push_log_id, code):
                suffix += 1
                code = f"{raw_code}__{suffix}"
            seen_codes.add(code)

            payload = self._build_payload(
                patient_info=patient_info,
                dimension_name=dim.dimension or dim.dimension_code or "",
                problem=dim.issue_summary or dim.explanation or "",
                problem_code=code,
                alert_level=dim.alert_level or "",
                severity=dim.severity or "",
                occurred_at=push_time,
                dimension_obj=dim,
                push_log=log,
            )
            alert = self._create_alert_log(push_log_id, code, patient_info, visit_number, dim.severity, dim.alert_level, payload)
            self.db.flush()
            self._append_detail_fields(alert, dim.closure_hours)
            added += 1

        # 结论级兜底：没有任何维度被创建时，若结论严重度命中则创建 __conclusion__
        if added == 0 and conclusion and conclusion.severity in self.severity_levels:
            if not self._exists_alert(push_log_id, "__conclusion__"):
                conclusion_text = (conclusion.overall_conclusion or conclusion.overall_qc_summary or "").strip()
                payload = self._build_payload(
                    patient_info=patient_info,
                    dimension_name="总体结论",
                    problem=conclusion_text or "高危质控问题",
                    problem_code="conclusion",
                    alert_level=conclusion.alert_level or "",
                    severity=conclusion.severity or "",
                    occurred_at=push_time,
                    conclusion_obj=conclusion,
                    push_log=log,
                )
                alert = self._create_alert_log(push_log_id, "__conclusion__", patient_info, visit_number, conclusion.severity, conclusion.alert_level, payload)
                self.db.flush()
                self._append_detail_fields(alert, conclusion.closure_hours)
                added += 1

        if added:
            self.db.flush()
            audit_logger.info("[relay_alert] enqueue push_log_id=%s count=%s", push_log_id, added)
        return added

    def _exists_alert(self, push_log_id: int, dimension_code: str) -> bool:
        return self.db.query(QCRecordAlertLog.id).filter(
            QCRecordAlertLog.push_log_id == push_log_id,
            QCRecordAlertLog.dimension_code == dimension_code,
        ).first() is not None

    def _build_payload(
        self,
        patient_info: dict,
        dimension_name: str,
        problem: str,
        problem_code: str,
        alert_level: str,
        severity: str,
        occurred_at: str,
        *,
        dimension_obj: AuditDimensionResult | None = None,
        conclusion_obj: AuditConclusion | None = None,
        push_log: PushLog | None = None,
    ) -> dict:
        fields = self.relay_cfg.get("payload_fields")
        if not fields:
            fields = _DEFAULT_PAYLOAD_FIELDS
        source = self.source

        ctx = {
            "patient_info": patient_info,
            "dimension": {
                "dimension_name": dimension_name or "",
                "problem": problem or "",
                "problem_code": problem_code or "",
                "alert_level": alert_level or "",
                "severity": severity or "",
                "confidence": str(getattr(dimension_obj, "confidence", "") or ""),
                "closure_hours": str(getattr(dimension_obj, "closure_hours", "") or ""),
                "recommendation": getattr(dimension_obj, "recommendation", "") or "",
                "status": getattr(dimension_obj, "status", "") or "",
                "medical_content": getattr(dimension_obj, "medical_content", "") or "",
                "nursing_content": getattr(dimension_obj, "nursing_content", "") or "",
                "explanation": getattr(dimension_obj, "explanation", "") or "",
                "issue_summary": getattr(dimension_obj, "issue_summary", "") or "",
            },
            "conclusion": {
                "risk_score": str(getattr(conclusion_obj, "risk_score", "") or ""),
                "overall_conclusion": getattr(conclusion_obj, "overall_conclusion", "") or "",
                "focus_items": getattr(conclusion_obj, "focus_items", "") or "",
                "reasoning_brief": getattr(conclusion_obj, "reasoning_brief", "") or "",
                "overall_qc_summary": getattr(conclusion_obj, "overall_qc_summary", "") or "",
                "closure_hours": str(getattr(conclusion_obj, "closure_hours", "") or ""),
                "severity": getattr(conclusion_obj, "severity", "") or "",
                "alert_level": getattr(conclusion_obj, "alert_level", "") or "",
            },
            "meta": {
                "event": "record_qc_issue",
                "occurred_at": occurred_at or "",
                "source": source,
                "visit_number": patient_info.get("visit_number") or "",
                "patient_id": patient_info.get("patient_id") or "",
                "audit_type_code": getattr(push_log, "audit_type_code", "") or "",
                "push_log_id": str(getattr(push_log, "id", "") or ""),
                "query_date": getattr(push_log, "query_date", "") or "",
            },
        }

        payload: dict = {}
        for f in fields:
            if not f.get("enabled", True):
                continue
            key = f.get("key", "")
            if not key:
                continue
            src = f.get("source", "")
            if src == "__static__":
                val = f.get("static_value", "")
            else:
                val = _resolve_path(ctx, src)
            if key == "source" and not val:
                val = source
            payload[key] = val
        receivers, receiver_debug = self._build_receivers(patient_info, push_log, severity)
        payload["receivers"] = receivers
        payload["receiver_rule"] = receiver_debug.get("rule", severity or "")
        payload["receiver_debug"] = receiver_debug
        payload["dept_name"] = patient_info.get("dept") or payload.get("dept") or ""
        payload["dept"] = patient_info.get("dept") or payload.get("dept") or ""
        payload["dept_code"] = patient_info.get("dept_code") or ""
        payload["admission_dept_name"] = patient_info.get("admission_dept_name") or ""
        payload["discharge_dept_name"] = patient_info.get("discharge_dept_name") or ""
        payload["doctor_id"] = patient_info.get("doctor_id") or payload.get("doctor_id") or ""
        payload["doctor_name"] = patient_info.get("doctor_name") or payload.get("doctor_name") or ""
        evidence_titles = extract_evidence_titles(push_log, dimension_obj, conclusion_obj)
        evidence_summary = build_evidence_summary(evidence_titles)
        payload["evidence_summary"] = evidence_summary
        payload["evidence_title"] = evidence_summary
        payload["evidence_titles"] = evidence_titles
        return payload

    def _create_alert_log(
        self,
        push_log_id: int,
        dimension_code: str,
        patient_info: dict,
        visit_number: str,
        severity: str,
        alert_level: str,
        payload: dict,
    ) -> QCRecordAlertLog:
        alert = QCRecordAlertLog(
            push_log_id=push_log_id,
            dimension_code=dimension_code,
            patient_id=patient_info.get("patient_id") or "",
            visit_number=visit_number or "",
            dept=patient_info.get("dept") or "",
            severity=severity or "",
            alert_level=alert_level or "",
            payload_json=_safe_json_dumps(payload),
            status="pending",
            retry_count=0,
        )
        self.db.add(alert)
        return alert

    def _append_detail_fields(self, alert: QCRecordAlertLog, closure_hours: int | None = None) -> None:
        """两阶段：alert log 已有 id 后，追加 detail_url 等系统保留字段并回写 payload_json。"""
        payload = json.loads(alert.payload_json or "{}")
        payload["alert_id"] = alert.id
        if self.secret:
            token = generate_alert_token(alert.id, self.secret, self.token_ttl)
            payload["detail_url"] = f"{self.external_base_url}/qc-detail/{alert.id}?token={token}"
            payload["action_required"] = True
        else:
            payload["detail_url"] = ""
            payload["action_required"] = False
            payload["config_error"] = "relay_alert.secret is required for detail_url"
        if closure_hours and "closure_hours" not in payload:
            payload["closure_hours"] = closure_hours
        alert.payload_json = _safe_json_dumps(payload)

    def dispatch_pending(self, limit: int = 100, push_log_ids: list[int] | None = None) -> dict:
        """发送 pending/failed 且 retry_count < max_retry 的 alert。
        
        Args:
            limit: 最多发送条数。
            push_log_ids: 若指定，只发送这些 push_log_id 关联的 alert（用于并发场景防重复）。
        """
        if not self.enabled:
            return {"sent": 0, "failed": 0, "skipped": 0, "reason": "disabled"}
        if not self.secret:
            return {"sent": 0, "failed": 0, "skipped": 0, "reason": "no_secret"}
        if not self.base_url:
            return {"sent": 0, "failed": 0, "skipped": 0, "reason": "no_base_url"}

        url = f"{self.base_url}{self.endpoint}"
        q = self.db.query(QCRecordAlertLog).filter(
            QCRecordAlertLog.status.in_(["pending", "failed"]),
            QCRecordAlertLog.retry_count < self.max_retry,
        )
        if push_log_ids:
            q = q.filter(QCRecordAlertLog.push_log_id.in_(push_log_ids))
        rows = q.order_by(QCRecordAlertLog.created_at.asc()).limit(limit).all()

        sent = 0
        failed = 0
        suppressed = 0
        for row in rows:
            try:
                if self._is_suppressed_for_push_log(row.push_log_id):
                    row.status = "suppressed"
                    row.last_error = "suppressed by rectified feedback"
                    row.updated_at = datetime.now()
                    suppressed += 1
                    continue

                payload = _parse_json(row.payload_json)
                if not payload:
                    row.status = "failed"
                    row.last_error = "empty payload"
                    row.retry_count += 1
                    failed += 1
                    continue

                payload_to_send = dict(payload)
                if not self.relay_cfg.get("send_structured_evidence", False):
                    payload_to_send.pop("evidence_titles", None)

                raw_body, headers = build_signed_request(payload_to_send, self.secret)
                resp = requests.post(url, data=raw_body, headers=headers, timeout=self.timeout)

                if resp.status_code < 300:
                    row.status = "success"
                    row.sent_at = datetime.now()
                    row.last_error = ""
                    sent += 1
                    audit_logger.info(
                        "[relay_alert] sent push_log_id=%s dim=%s status=%s",
                        row.push_log_id, row.dimension_code, resp.status_code,
                    )
                else:
                    row.status = "failed"
                    row.last_error = _safe_error_text(f"HTTP {resp.status_code}: {resp.text}", 200)
                    row.retry_count += 1
                    failed += 1
                    audit_logger.warning(
                        "[relay_alert] failed push_log_id=%s dim=%s http_status=%s body=%s",
                        row.push_log_id, row.dimension_code, resp.status_code, resp.text[:200],
                    )
            except Exception as exc:
                row.status = "failed"
                row.last_error = _safe_error_text(str(exc), 500)
                row.retry_count += 1
                failed += 1
                audit_logger.error(
                    "[relay_alert] error push_log_id=%s dim=%s err=%s",
                    row.push_log_id, row.dimension_code, exc,
                )

        if sent or failed or suppressed:
            self.db.commit()
        return {"sent": sent, "failed": failed, "suppressed": suppressed, "skipped": len(rows) - sent - failed - suppressed, "reason": ""}

    def send_one(self, alert_log: QCRecordAlertLog) -> bool:
        """签名并 POST 到前置机。"""
        if not self.enabled or not self.secret or not self.base_url:
            return False

        url = f"{self.base_url}{self.endpoint}"
        try:
            payload = _parse_json(alert_log.payload_json)
            raw_body, headers = build_signed_request(payload, self.secret)
            resp = requests.post(url, data=raw_body, headers=headers, timeout=self.timeout)

            if resp.status_code < 300:
                alert_log.status = "success"
                alert_log.sent_at = datetime.now()
                alert_log.last_error = ""
                return True
            else:
                alert_log.status = "failed"
                alert_log.last_error = _safe_error_text(f"HTTP {resp.status_code}: {resp.text}", 200)
                alert_log.retry_count += 1
                return False
        except Exception as exc:
            alert_log.status = "failed"
            alert_log.last_error = _safe_error_text(str(exc), 500)
            alert_log.retry_count += 1
            return False
