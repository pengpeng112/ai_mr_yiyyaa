"""
前置机高危问题推送服务
当质控结果 severity == "high" 时，将每个高危维度作为一条消息推送到前置机接口，
由前置机转发企业微信告知医护人员。
"""
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.models import QCRecordAlertLog, PushLog, AuditDimensionResult, AuditConclusion
from app.services.patient_snapshot import extract_patient_snapshot
from app.services.alert_token import generate_alert_token

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


def _format_push_time(push_time: Any) -> str:
    if isinstance(push_time, datetime):
        return push_time.strftime("%Y-%m-%d %H:%M:%S")
    return str(push_time or "")


def _get_patient_info(log: PushLog) -> dict:
    """从 push_log 中提取患者信息，复用 patient_snapshot。"""
    snapshot = extract_patient_snapshot(log)
    request_json = _parse_json(getattr(log, "request_json", "") or "")
    patient_info = request_json.get("patient_info", {}) if isinstance(request_json.get("patient_info"), dict) else {}

    return {
        "patient_id": snapshot.get("patient_id") or log.patient_id or "",
        "patient_name": snapshot.get("patient_name") or log.patient_name or "",
        "admission_no": snapshot.get("admission_no") or log.admission_no or "",
        "visit_number": str(log.visit_number or ""),
        "dept": snapshot.get("dept_name") or log.dept or "",
        "doctor_id": patient_info.get("管床医师编号") or patient_info.get("doctor_id") or "",
        "doctor_name": patient_info.get("管床医师") or patient_info.get("doctor_name") or "",
        "admission_dept_name": snapshot.get("admission_dept_name") or "",
        "discharge_dept_name": snapshot.get("discharge_dept_name") or "",
    }


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

    def enqueue_high_severity_alerts(self, push_log_id: int) -> int:
        """根据 push_log_id 读取结论和维度，生成待发送 alert log。返回新增数量。"""
        if not self.enabled:
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

        # 结论级兜底
        if not dimensions and conclusion and conclusion.severity in self.severity_levels:
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
        token_secret = self.secret or self.source
        token = generate_alert_token(alert.id, token_secret, self.token_ttl)
        detail_url = f"{self.external_base_url}/qc-detail/{alert.id}?token={token}"
        payload = _safe_json_dumps({})  # dummy
        try:
            payload = json.loads(alert.payload_json or "{}")
        except Exception:
            payload = {}
        payload["alert_id"] = alert.id
        payload["detail_url"] = detail_url
        payload["action_required"] = True
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
        for row in rows:
            try:
                payload = _parse_json(row.payload_json)
                if not payload:
                    row.status = "failed"
                    row.last_error = "empty payload"
                    row.retry_count += 1
                    failed += 1
                    continue

                raw_body, headers = build_signed_request(payload, self.secret)
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
                    row.last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    row.retry_count += 1
                    failed += 1
                    audit_logger.warning(
                        "[relay_alert] failed push_log_id=%s dim=%s http_status=%s body=%s",
                        row.push_log_id, row.dimension_code, resp.status_code, resp.text[:200],
                    )
            except Exception as exc:
                row.status = "failed"
                row.last_error = str(exc)[:500]
                row.retry_count += 1
                failed += 1
                audit_logger.error(
                    "[relay_alert] error push_log_id=%s dim=%s err=%s",
                    row.push_log_id, row.dimension_code, exc,
                )

        if sent or failed:
            self.db.commit()
        return {"sent": sent, "failed": failed, "skipped": len(rows) - sent - failed}

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
                alert_log.last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                alert_log.retry_count += 1
                return False
        except Exception as exc:
            alert_log.status = "failed"
            alert_log.last_error = str(exc)[:500]
            alert_log.retry_count += 1
            return False
