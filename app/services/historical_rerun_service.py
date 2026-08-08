"""历史质控手工重跑：预检、批次与执行（ACTIVE/007）。

preview 只读；执行路径默认 suppress 外部告警。
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import load_config
from app.database import SessionLocal
from app.models import HistoricalRerunBatch, HistoricalRerunItem, PushExecution, PushLog, QCFeedback
from app.services.audit_type_registry import AuditTypeRegistry
from app.services.config_parser import ConfigParser
from app.services.current_result_filter import apply_current_result_filter
from app.services.data_source_loader import load_patient_bundles
from app.services.historical_rerun_identity import (
    is_identity_ambiguous,
    make_business_identity_hash,
    make_candidate_hash,
    make_config_snapshot_hash,
)
from app.services.payload_composer import compose
from app.services.push_date_utils import resolve_query_dates
from app.services.push_idempotency import claim_execution, finish_execution
from app.services.push_log_supersede import mark_historical_reaudit_superseded
from app.services.push_log_writer import create_push_log, create_skipped_push_log
from app.services.push_skip_policy import get_empty_lab_exam_skip_reason, get_surgery_chain_skip_reason
from app.services.push_types import PushConfig
from app.services.qc_status_semantics import is_qc_usable
from app.services.record_identity import get_bundle_source_key
from app.services.audit_result_writer import save_audit_results
from app.dify_pusher import push_to_dify
from app.services.push_executor import with_audit_type_mr_type

logger = logging.getLogger(__name__)

class _LeaseHeartbeat:
    """后台线程定期续约 consumer lease 和 execution lease，防止长 Dify 调用期间过期。"""

    def __init__(self, batch_id: int, owner_token: str, execution_id: int | None = None, interval: float = 30.0):
        self._batch_id = batch_id
        self._owner_token = owner_token
        self._execution_id = execution_id
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"lease-hb-{self._batch_id}")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                hb_db = SessionLocal()
                try:
                    _renew_consumer_lease(hb_db, self._batch_id, self._owner_token)
                    if self._execution_id:
                        from app.services.push_idempotency import heartbeat_execution
                        execution = hb_db.query(PushExecution).filter(PushExecution.id == self._execution_id).first()
                        if execution:
                            heartbeat_execution(hb_db, execution, execution.owner_token or "")
                    hb_db.commit()
                finally:
                    hb_db.close()
            except Exception:
                logger.debug("lease heartbeat failed batch=%s", self._batch_id, exc_info=True)


BATCH_STATUSES = {
    "draft",
    "confirmed",
    "running",
    "paused",
    "completed",
    "completed_with_errors",
    "cancelled",
    "failed",
}

ITEM_TERMINAL = {
    "success",
    "failed",
    "skipped",
    "identity_ambiguous",
    "rectified_suppressed",
    "concurrent_changed",
    "cancelled",
}

DEFAULT_SHARD_LIMIT = 100
_MAX_REASON_LEN = 500


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _json_loads(text: str) -> Any:
    try:
        return json.loads(text or "[]")
    except Exception:
        return []


def _find_current_push_log(
    db: Session,
    *,
    source_record_key: str,
    audit_type_code: str,
    audit_run_mode: str,
    patient_id: str,
    visit_number: str,
) -> Optional[PushLog]:
    q = apply_current_result_filter(
        db.query(PushLog)
        .filter(
            PushLog.status == "success",
            PushLog.pushed_flag == 1,
            PushLog.audit_type_code == audit_type_code,
            PushLog.audit_run_mode == audit_run_mode,
        )
    )
    if source_record_key:
        q = q.filter(PushLog.source_record_key == source_record_key)
    else:
        q = q.filter(
            PushLog.patient_id == patient_id,
            PushLog.visit_number == visit_number,
        )
    return q.order_by(PushLog.push_time.desc()).first()


def _find_legacy_empty_key_current(
    db: Session,
    *,
    audit_type_code: str,
    audit_run_mode: str,
    patient_id: str,
    visit_number: str,
) -> Optional[PushLog]:
    """查找同身份下 source_record_key 为空的旧当前 success 记录（Oracle 空字符串=NULL）。"""
    from sqlalchemy import or_
    q = apply_current_result_filter(
        db.query(PushLog)
        .filter(
            PushLog.status == "success",
            PushLog.pushed_flag == 1,
            PushLog.audit_type_code == audit_type_code,
            PushLog.audit_run_mode == audit_run_mode,
            PushLog.patient_id == patient_id,
            PushLog.visit_number == visit_number,
        )
    )
    q = q.filter(
        or_(
            PushLog.source_record_key.is_(None),
            PushLog.source_record_key == "",
        )
    )
    return q.order_by(PushLog.push_time.desc()).first()


def _is_rectified_suppressed(
    db: Session,
    *,
    patient_id: str,
    visit_number: str,
    audit_type_code: str,
) -> bool:
    q = (
        db.query(QCFeedback)
        .join(PushLog, QCFeedback.push_log_id == PushLog.id)
        .filter(QCFeedback.suppress_ai_push == True)  # noqa: E712
        .filter(QCFeedback.status == "rectified")
        .filter(PushLog.patient_id == patient_id)
        .filter(PushLog.audit_type_code == audit_type_code)
    )
    if visit_number:
        q = q.filter(PushLog.visit_number == visit_number)
    return q.with_entities(QCFeedback.id).first() is not None


def preview_historical_rerun(
    db: Session,
    *,
    date_from: str,
    date_to: str,
    date_dimension: str = "query_date",
    audit_type_codes: Optional[List[str]] = None,
    dept_filter: Optional[List[str]] = None,
    audit_run_mode: str = "daily_increment",
    shard_limit: int = DEFAULT_SHARD_LIMIT,
) -> Dict[str, Any]:
    """只读预检：不调用 Dify、不写 PushLog。"""
    config = load_config()
    registry = AuditTypeRegistry()
    if audit_type_codes:
        audit_types = [registry.get_or_default(code) for code in audit_type_codes]
        audit_types = [a for a in audit_types if a and getattr(a, "enabled", True)]
    else:
        audit_types = registry.list_enabled()

    query_dates = resolve_query_dates(date_from, date_to, None)
    depts = [str(d).strip() for d in (dept_filter or []) if str(d).strip()]
    run_mode = str(audit_run_mode or "daily_increment").strip() or "daily_increment"

    candidates: List[Dict[str, Any]] = []
    daily_stats: Dict[str, Dict[str, int]] = {}
    type_stats: Dict[str, Dict[str, int]] = {}

    def _bump(bucket: Dict[str, Dict[str, int]], key: str, field: str, n: int = 1) -> None:
        row = bucket.setdefault(
            key,
            {
                "candidate_count": 0,
                "pushable": 0,
                "has_current": 0,
                "identity_ambiguous": 0,
                "legacy_empty_key_current": 0,
                "rectified_suppressed": 0,
                "already_running": 0,
                "load_failed": 0,
            },
        )
        row[field] = int(row.get(field, 0) or 0) + n
        if field != "candidate_count":
            row["candidate_count"] = int(row.get("candidate_count", 0) or 0) + n

    for qdate in query_dates:
        for audit_type in audit_types:
            code = str(getattr(audit_type, "code", "") or "")
            try:
                bundles = load_patient_bundles(
                    audit_type,
                    config,
                    query_date=qdate,
                    date_dimension=date_dimension or "query_date",
                    dept_filter=depts or None,
                )
            except Exception as exc:
                logger.warning("historical preview load failed date=%s type=%s err=%s", qdate, code, exc)
                _bump(daily_stats, qdate, "load_failed")
                _bump(type_stats, code, "load_failed")
                continue

            for bundle in bundles or []:
                source_key = get_bundle_source_key(bundle, audit_type, run_mode)
                patient_id = str(bundle.group_values.get("patient_id") or "")
                visit_number = str(
                    bundle.group_values.get("visit_number")
                    or bundle.group_values.get("次数")
                    or ""
                )
                identity_hash = make_business_identity_hash(
                    source_key, code, run_mode, patient_id, visit_number
                )
                current = _find_current_push_log(
                    db,
                    source_record_key=source_key,
                    audit_type_code=code,
                    audit_run_mode=run_mode,
                    patient_id=patient_id,
                    visit_number=visit_number,
                )

                legacy_empty_current = None
                if source_key:
                    legacy_empty_current = _find_legacy_empty_key_current(
                        db,
                        audit_type_code=code,
                        audit_run_mode=run_mode,
                        patient_id=patient_id,
                        visit_number=visit_number,
                    )

                if is_identity_ambiguous(source_key):
                    category = "identity_ambiguous"
                elif legacy_empty_current is not None:
                    category = "legacy_empty_key_current"
                elif _is_rectified_suppressed(
                    db, patient_id=patient_id, visit_number=visit_number, audit_type_code=code
                ):
                    category = "rectified_suppressed"
                else:
                    category = "pushable"

                item = {
                    "business_identity_hash": identity_hash,
                    "source_record_key": source_key,
                    "audit_type_code": code,
                    "audit_run_mode": run_mode,
                    "patient_id": patient_id,
                    "visit_number": visit_number,
                    "query_date": qdate,
                    "dept": "",
                    "previous_current_push_log_id": getattr(current, "id", None),
                    "has_current_result": current is not None,
                    "category": category,
                }
                # 尽量补科室（不读病历正文）
                try:
                    primary = (bundle.sources or {}).get(bundle.primary_source) or []
                    if primary:
                        fm = (bundle.source_field_mappings or {}).get(bundle.primary_source) or {}
                        item["dept"] = str(primary[0].get(fm.get("dept", "所在科室名称"), "") or "")
                except Exception:
                    pass

                candidates.append(item)
                _bump(daily_stats, qdate, category)
                _bump(type_stats, code, category)
                if current is not None:
                    daily_stats[qdate]["has_current"] = int(daily_stats[qdate].get("has_current", 0)) + 1
                    type_stats[code]["has_current"] = int(type_stats[code].get("has_current", 0)) + 1

    # 去重：同身份只保留一条（按日期+类型稳定排序后首次）
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in sorted(
        candidates,
        key=lambda x: (x["query_date"], x["audit_type_code"], x["business_identity_hash"]),
    ):
        key = item["business_identity_hash"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    pushable = [c for c in deduped if c["category"] == "pushable"]
    identity_ambiguous = [c for c in deduped if c["category"] == "identity_ambiguous"]
    legacy_empty = [c for c in deduped if c["category"] == "legacy_empty_key_current"]
    rectified = [c for c in deduped if c["category"] == "rectified_suppressed"]

    candidate_hash = make_candidate_hash(deduped)
    config_snapshot_hash = make_config_snapshot_hash(
        date_from=date_from,
        date_to=date_to,
        date_dimension=date_dimension,
        audit_type_codes=[str(getattr(a, "code", "") or "") for a in audit_types],
        dept_filter=depts,
        alert_policy="suppress",
        existing_result_policy="replace_current",
    )

    estimated_dify_calls = len(pushable)
    requires_async = estimated_dify_calls > int(shard_limit or DEFAULT_SHARD_LIMIT)

    return {
        "date_from": date_from,
        "date_to": date_to,
        "date_dimension": date_dimension,
        "audit_run_mode": run_mode,
        "audit_type_codes": [str(getattr(a, "code", "") or "") for a in audit_types],
        "dept_filter": depts,
        "candidate_hash": candidate_hash,
        "config_snapshot_hash": config_snapshot_hash,
        "candidate_count": len(deduped),
        "pushable_count": len(pushable),
        "identity_ambiguous_count": len(identity_ambiguous),
        "legacy_empty_key_current_count": len(legacy_empty),
        "rectified_suppressed_count": len(rectified),
        "has_current_count": sum(1 for c in deduped if c.get("has_current_result")),
        "manifest_complete": all(
            int(v.get("load_failed", 0)) == 0 for v in daily_stats.values()
        ),
        "load_failed_count": sum(
            int(v.get("load_failed", 0)) for v in daily_stats.values()
        ),
        "estimated_dify_calls": estimated_dify_calls,
        "requires_async": requires_async,
        "shard_limit": int(shard_limit or DEFAULT_SHARD_LIMIT),
        "daily_stats": daily_stats,
        "type_stats": type_stats,
        "candidates": deduped,
        # 不返回 mr_text / 姓名列表中的敏感大字段
    }


def create_batch_from_preview(
    db: Session,
    preview: Dict[str, Any],
    *,
    actor: str,
    actor_ip: str = "",
    reason: str,
    confirm_candidate_hash: str,
    alert_policy: str = "suppress",
    include_rectified: bool = False,
) -> HistoricalRerunBatch:
    """根据 preview 创建持久批次；候选哈希必须一致。"""
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("reaudit_reason is required")
    if len(reason) > _MAX_REASON_LEN:
        raise ValueError(f"reaudit_reason too long (max {_MAX_REASON_LEN})")
    # 禁止把疑似密钥写进理由
    lowered = reason.lower()
    for banned in ("password", "api_key", "secret", "token="):
        if banned in lowered:
            raise ValueError("reaudit_reason must not contain secrets")

    expected = str(preview.get("candidate_hash") or "")
    if not confirm_candidate_hash or confirm_candidate_hash != expected:
        raise LookupError("candidate_hash mismatch; re-run preview")

    # P0-3: load_failed > 0 时禁止创建批次（fail-closed）
    load_failed_count = int(preview.get("load_failed_count") or 0)
    if load_failed_count > 0:
        raise ValueError(
            f"preview incomplete: {load_failed_count} shard(s) failed to load; "
            "cannot create batch from incomplete manifest"
        )
    if not preview.get("manifest_complete", True):
        raise ValueError("preview manifest_complete=False; cannot create batch")

    alert_policy = str(alert_policy or "suppress").strip() or "suppress"
    if alert_policy not in {"suppress", "new_high_only"}:
        raise ValueError("invalid alert_policy")

    candidates = list(preview.get("candidates") or [])
    items_to_create = []
    for c in candidates:
        cat = str(c.get("category") or "")
        if cat == "pushable":
            items_to_create.append(c)
        elif cat == "identity_ambiguous":
            items_to_create.append(c)
        elif cat == "rectified_suppressed" and include_rectified:
            items_to_create.append(c)

    batch = HistoricalRerunBatch(
        status="confirmed",
        actor=str(actor or "")[:50],
        actor_ip=str(actor_ip or "")[:64],
        reason=reason[:_MAX_REASON_LEN],
        date_from=str(preview.get("date_from") or ""),
        date_to=str(preview.get("date_to") or ""),
        date_dimension=str(preview.get("date_dimension") or "query_date"),
        audit_type_codes_json=_json_dumps(preview.get("audit_type_codes") or []),
        dept_filter_json=_json_dumps(preview.get("dept_filter") or []),
        existing_result_policy="replace_current",
        alert_policy=alert_policy,
        candidate_hash=expected,
        config_snapshot_hash=str(preview.get("config_snapshot_hash") or ""),
        candidate_count=len(items_to_create),
        processed=0,
        success_count=0,
        failed_count=0,
        skipped_count=0,
        superseded_count=0,
    )
    db.add(batch)
    db.flush()

    for c in items_to_create:
        cat = str(c.get("category") or "pushable")
        status = "pending" if cat == "pushable" else cat
        item = HistoricalRerunItem(
            batch_id=batch.id,
            business_identity_hash=str(c.get("business_identity_hash") or ""),
            source_record_key=str(c.get("source_record_key") or ""),
            audit_type_code=str(c.get("audit_type_code") or ""),
            audit_run_mode=str(c.get("audit_run_mode") or "daily_increment"),
            patient_id=str(c.get("patient_id") or ""),
            visit_number=str(c.get("visit_number") or ""),
            query_date=str(c.get("query_date") or ""),
            dept=str(c.get("dept") or ""),
            previous_current_push_log_id=c.get("previous_current_push_log_id"),
            status=status,
            reason_code=cat if cat != "pushable" else "",
        )
        db.add(item)

    db.flush()
    return batch


def get_batch_dict(batch: HistoricalRerunBatch) -> Dict[str, Any]:
    return {
        "id": batch.id,
        "status": batch.status,
        "actor": batch.actor,
        "reason": batch.reason,
        "date_from": batch.date_from,
        "date_to": batch.date_to,
        "date_dimension": batch.date_dimension,
        "audit_type_codes": _json_loads(batch.audit_type_codes_json),
        "dept_filter": _json_loads(batch.dept_filter_json),
        "existing_result_policy": batch.existing_result_policy,
        "alert_policy": batch.alert_policy,
        "candidate_hash": batch.candidate_hash,
        "config_snapshot_hash": batch.config_snapshot_hash,
        "candidate_count": batch.candidate_count,
        "processed": batch.processed,
        "success": batch.success_count,
        "failed": batch.failed_count,
        "skipped": batch.skipped_count,
        "superseded": batch.superseded_count,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "finished_at": batch.finished_at.isoformat() if batch.finished_at else None,
        "cancelled_at": batch.cancelled_at.isoformat() if batch.cancelled_at else None,
        "last_error": batch.last_error or "",
    }


def get_item_dict(item: HistoricalRerunItem) -> Dict[str, Any]:
    return {
        "id": item.id,
        "batch_id": item.batch_id,
        "business_identity_hash": item.business_identity_hash,
        "source_record_key": item.source_record_key,
        "audit_type_code": item.audit_type_code,
        "audit_run_mode": item.audit_run_mode,
        "patient_id": item.patient_id,
        "visit_number": item.visit_number,
        "query_date": item.query_date,
        "dept": item.dept,
        "execution_id": item.execution_id,
        "previous_current_push_log_id": item.previous_current_push_log_id,
        "new_push_log_id": item.new_push_log_id,
        "status": item.status,
        "reason_code": item.reason_code,
        "reason_message": item.reason_message,
        "attempt_count": item.attempt_count,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def set_batch_control(db: Session, batch_id: int, action: str) -> HistoricalRerunBatch:
    batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
    if not batch:
        raise LookupError("batch not found")
    action = str(action or "").strip().lower()
    if action == "pause":
        if batch.status not in {"running", "confirmed"}:
            raise ValueError(f"cannot pause batch in status={batch.status}")
        batch.status = "paused"
    elif action == "resume":
        if batch.status not in {"paused", "confirmed", "running"}:
            raise ValueError(f"cannot resume batch in status={batch.status}")
        if batch.status == "running":
            now = datetime.now()
            has_active = batch.consumer_owner and batch.consumer_lease_until and batch.consumer_lease_until > now
            if has_active:
                return batch
            recover_stale_running_items(db, batch_id, actor="resume_api")
        batch.status = "running"
        if not batch.started_at:
            batch.started_at = datetime.now()
    elif action == "cancel":
        if batch.status in {"completed", "completed_with_errors", "cancelled"}:
            raise ValueError(f"cannot cancel batch in status={batch.status}")
        batch.status = "cancelled"
        batch.cancelled_at = datetime.now()
        batch.finished_at = datetime.now()
        # 未开始 item 标记取消
        pending = (
            db.query(HistoricalRerunItem)
            .filter(
                HistoricalRerunItem.batch_id == batch_id,
                HistoricalRerunItem.status == "pending",
            )
            .all()
        )
        for item in pending:
            item.status = "cancelled"
            item.reason_code = "cancelled"
            item.updated_at = datetime.now()
    else:
        raise ValueError(f"unknown action: {action}")
    db.flush()
    return batch


def build_reconciliation(db: Session, batch_id: int) -> Dict[str, Any]:
    """对账诊断：使用正式业务身份，qc_usable 包含 parse+contract，总数不受 limit 影响。"""
    batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
    if not batch:
        raise LookupError("batch not found")
    items = (
        db.query(HistoricalRerunItem)
        .filter(HistoricalRerunItem.batch_id == batch_id)
        .all()
    )
    by_status: Dict[str, int] = {}
    superseded_pairs = []
    empty_key_count = 0
    qc_usable_count = 0
    dual_current_count = 0

    for item in items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        if not (item.source_record_key or "").strip():
            empty_key_count += 1
        if item.new_push_log_id and item.previous_current_push_log_id:
            superseded_pairs.append(
                {
                    "item_id": item.id,
                    "source_record_key": item.source_record_key or "",
                    "audit_type_code": item.audit_type_code or "",
                    "audit_run_mode": item.audit_run_mode or "",
                    "previous_current_push_log_id": item.previous_current_push_log_id,
                    "new_push_log_id": item.new_push_log_id,
                    "status": item.status,
                }
            )
        if item.status == "success" and item.new_push_log_id:
            new_log = db.query(PushLog).filter(PushLog.id == item.new_push_log_id).first()
            if new_log and is_qc_usable(new_log.status, new_log.parse_status, getattr(new_log, "contract_valid", None)):
                qc_usable_count += 1
            if new_log and new_log.superseded_by is None and new_log.status not in ("discarded",):
                prev_log = db.query(PushLog).filter(PushLog.id == item.previous_current_push_log_id).first() if item.previous_current_push_log_id else None
                if prev_log and prev_log.superseded_by is None and prev_log.status not in ("discarded",):
                    dual_current_count += 1

    total_items = len(items)
    return {
        "batch": get_batch_dict(batch),
        "item_status_counts": by_status,
        "superseded_pairs": superseded_pairs,
        "total_items": total_items,
        "empty_key_count": empty_key_count,
        "qc_usable_count": qc_usable_count,
        "dual_current_count": dual_current_count,
        "before_current_estimate": batch.candidate_count,
        "after_success": batch.success_count,
        "after_superseded": batch.superseded_count,
        "failed": batch.failed_count,
        "skipped": batch.skipped_count,
    }


def _claim_next_item(db: Session, batch_id: int) -> Optional[HistoricalRerunItem]:
    batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
    if not batch or batch.status not in {"running", "confirmed"}:
        return None
    if batch.status == "confirmed":
        batch.status = "running"
        batch.started_at = batch.started_at or datetime.now()

    # Oracle 会把 order_by + first + FOR UPDATE 编译成带 ROWNUM 的内联视图，
    # 进而触发 ORA-02014。先稳定选择主键，再对基表主键行加锁并复核状态。
    item_id_row = (
        db.query(HistoricalRerunItem.id)
        .filter(
            HistoricalRerunItem.batch_id == batch_id,
            HistoricalRerunItem.status == "pending",
        )
        .order_by(HistoricalRerunItem.id.asc())
        .first()
    )
    if not item_id_row:
        return None
    item = (
        db.query(HistoricalRerunItem)
        .filter(HistoricalRerunItem.id == int(item_id_row[0]))
        .with_for_update()
        .one_or_none()
    )
    if not item or item.batch_id != batch_id or item.status != "pending":
        return None
    item.status = "running"
    item.attempt_count = int(item.attempt_count or 0) + 1
    item.updated_at = datetime.now()
    db.flush()
    return item


def _finalize_batch_if_done(db: Session, batch_id: int) -> None:
    batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
    if not batch or batch.status in {"cancelled", "paused", "failed"}:
        return
    remaining = (
        db.query(HistoricalRerunItem)
        .filter(
            HistoricalRerunItem.batch_id == batch_id,
            HistoricalRerunItem.status.in_(["pending", "running"]),
        )
        .count()
    )
    if remaining:
        return
    failed = int(batch.failed_count or 0)
    concurrent = (
        db.query(HistoricalRerunItem)
        .filter(
            HistoricalRerunItem.batch_id == batch_id,
            HistoricalRerunItem.status == "concurrent_changed",
        )
        .count()
    )
    if failed or concurrent:
        batch.status = "completed_with_errors"
    else:
        batch.status = "completed"
    batch.finished_at = datetime.now()
    db.flush()


def _process_one_item(batch_id: int, item_id: int) -> None:
    """单条 item：claim execution → Dify → 落库替代 → finish。默认 suppress 告警。"""
    db = SessionLocal()
    try:
        batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
        item = db.query(HistoricalRerunItem).filter(HistoricalRerunItem.id == item_id).first()
        if not batch or not item:
            return
        if batch.status in {"paused", "cancelled"}:
            if item.status == "running":
                item.status = "pending" if batch.status == "paused" else "cancelled"
                item.updated_at = datetime.now()
                db.commit()
            return

        if item.status in {"identity_ambiguous", "rectified_suppressed"}:
            batch.processed = int(batch.processed or 0) + 1
            batch.skipped_count = int(batch.skipped_count or 0) + 1
            db.commit()
            return

        config = load_config()
        registry = AuditTypeRegistry()
        audit_type = registry.get_or_default(item.audit_type_code)
        if not audit_type:
            item.status = "failed"
            item.reason_code = "audit_type_missing"
            item.reason_message = "audit type not found"
            batch.processed = int(batch.processed or 0) + 1
            batch.failed_count = int(batch.failed_count or 0) + 1
            db.commit()
            return

        source_version = f"hist_rerun:{batch_id}"
        execution, claimed, reason = claim_execution(
            db,
            source_record_key=item.source_record_key,
            audit_type_code=item.audit_type_code,
            audit_run_mode=item.audit_run_mode,
            source_version=source_version,
            force=True,
        )
        if execution:
            item.execution_id = execution.id
        if not claimed:
            # P1-3: in_flight/exception 是可重试技术状态，不得伪装为业务 skipped
            if reason in ("in_flight", "claim_exception"):
                item.status = "pending"
                item.reason_code = reason
                item.reason_message = f"retryable: {reason}"
                item.attempt_count = max(0, int(item.attempt_count or 1) - 1)
                db.commit()
                return
            item.status = "skipped"
            item.reason_code = reason
            item.reason_message = reason
            batch.processed = int(batch.processed or 0) + 1
            batch.skipped_count = int(batch.skipped_count or 0) + 1
            db.commit()
            return

        execution_id = execution.id if execution else None
        source_record_key = item.source_record_key
        patient_id = item.patient_id
        visit_number = item.visit_number
        query_date = item.query_date
        run_mode = item.audit_run_mode
        depts = _json_loads(batch.dept_filter_json) or None
        date_dimension = str(batch.date_dimension or "query_date")
        previous_current_id = item.previous_current_push_log_id
        alert_policy = batch.alert_policy
        db.commit()  # 提交 claim，释放写锁后再加载/调 Dify
        db.close()

        # 加载 bundle（无 DB 会话）
        try:
            bundles = load_patient_bundles(
                audit_type,
                config,
                query_date=query_date,
                date_dimension=date_dimension,
                dept_filter=depts,
            )
        except Exception as load_exc:
            db = SessionLocal()
            try:
                item = db.query(HistoricalRerunItem).filter(HistoricalRerunItem.id == item_id).first()
                batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
                execution = (
                    db.query(PushExecution).filter(PushExecution.id == execution_id).first()
                    if execution_id
                    else None
                )
                if item:
                    item.status = "failed"
                    item.reason_code = "load_failed"
                    item.reason_message = str(load_exc)[:500]
                if execution:
                    finish_execution(db, execution, "failed", error_message=str(load_exc)[:500])
                if batch:
                    batch.processed = int(batch.processed or 0) + 1
                    batch.failed_count = int(batch.failed_count or 0) + 1
                db.commit()
            finally:
                db.close()
            return

        matched = None
        for bundle in bundles or []:
            key = get_bundle_source_key(bundle, audit_type, run_mode)
            if key == source_record_key:
                matched = bundle
                break
            pid = str(bundle.group_values.get("patient_id") or "")
            vn = str(bundle.group_values.get("visit_number") or bundle.group_values.get("次数") or "")
            if pid == patient_id and vn == visit_number:
                matched = bundle
                break

        db = SessionLocal()
        item = db.query(HistoricalRerunItem).filter(HistoricalRerunItem.id == item_id).first()
        batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
        execution = (
            db.query(PushExecution).filter(PushExecution.id == execution_id).first()
            if execution_id
            else None
        )
        if not item or not batch:
            db.close()
            return

        if not matched:
            item.status = "failed"
            item.reason_code = "bundle_not_found"
            item.reason_message = "source bundle not found at execute time"
            if execution:
                finish_execution(db, execution, "failed", error_message=item.reason_message)
            batch.processed = int(batch.processed or 0) + 1
            batch.failed_count = int(batch.failed_count or 0) + 1
            db.commit()
            return

        push_config = PushConfig(
            trigger_type="manual",
            query_date=query_date,
            audit_type_code=item.audit_type_code,
            audit_type=audit_type,
            audit_run_mode=run_mode,
            notify_enabled=False,
        )
        field_mapping = ConfigParser.get_field_mapping(
            config, ConfigParser.get_data_source_type(config)
        )
        payload, mr_text = compose(
            audit_type, matched, query_date, audit_run_mode=run_mode
        )
        surgery_reason, surgery_msg = get_surgery_chain_skip_reason(audit_type, matched)
        if surgery_reason:
            log = create_skipped_push_log(
                matched,
                matched.sources.get(matched.primary_source) or [{}],
                field_mapping,
                push_config,
                surgery_reason,
                surgery_msg,
                patient_id,
            )
            db.add(log)
            db.flush()
            item.status = "skipped"
            item.reason_code = surgery_reason
            item.reason_message = surgery_msg
            item.new_push_log_id = log.id
            if execution:
                finish_execution(db, execution, "skipped", push_log_id=log.id, error_message=surgery_msg)
            batch.processed = int(batch.processed or 0) + 1
            batch.skipped_count = int(batch.skipped_count or 0) + 1
            db.commit()
            return

        lab_skip = get_empty_lab_exam_skip_reason(payload)
        if lab_skip:
            log = create_skipped_push_log(
                matched,
                matched.sources.get(matched.primary_source) or [{}],
                field_mapping,
                push_config,
                "empty_lab_exam",
                lab_skip,
                patient_id,
            )
            db.add(log)
            db.flush()
            item.status = "skipped"
            item.reason_code = "empty_lab_exam"
            item.reason_message = lab_skip
            item.new_push_log_id = log.id
            if execution:
                finish_execution(db, execution, "skipped", push_log_id=log.id, error_message=lab_skip)
            batch.processed = int(batch.processed or 0) + 1
            batch.skipped_count = int(batch.skipped_count or 0) + 1
            db.commit()
            return

        # Dify 调用：使用与手动/调度相同的节点池 resolver
        pool = ConfigParser.resolve_dify_target_pool(config, audit_type)
        dify_cfg = dict(pool.get("base_config") or ConfigParser.parse_dify_config(config) or {})
        targets = list(pool.get("targets") or [])
        if targets:
            first = targets[0] if isinstance(targets[0], dict) else {}
            for k in ("base_url", "api_key", "timeout_seconds"):
                if first.get(k):
                    dify_cfg[k] = first[k]
            dify_result_target_name = str(first.get("name") or "")
        else:
            dify_result_target_name = ""

        response_cfg = (audit_type.response or {}) if audit_type else {}
        parse_strategy = str(response_cfg.get("parse_strategy") or "hybrid")
        dify_override = with_audit_type_mr_type({}, audit_type)
        dify_override.pop("api_key", None)
        dify_override.pop("api_key_enc", None)

        dify_input = mr_text or json.dumps(payload, ensure_ascii=False, default=str)
        audit_type_code = item.audit_type_code
        db.close()  # 网络调用前释放会话

        # P1-2: 长 Dify 调用期间持续心跳续约
        _hb = _LeaseHeartbeat(batch_id, "", execution_id=execution_id, interval=30.0)
        _hb._owner_token = ""  # consumer lease 由 run_batch 持有；此处仅续约 execution
        _hb.start()
        try:
            dify_result = push_to_dify(
            dify_input,
            dify_cfg,
            patient_id,
            dify_config_override=dify_override or None,
            response_paths=response_cfg,
            parse_strategy=parse_strategy,
            audit_type_code=audit_type_code,
            expected_dimensions_override=list(getattr(audit_type, "dimension_codes", None) or []) or None,
        )
        finally:
            _hb.stop()

        if dify_result_target_name and isinstance(dify_result, dict):
            dify_result.setdefault("_target_name", dify_result_target_name)

        # 新会话写入结果
        db = SessionLocal()
        item = db.query(HistoricalRerunItem).filter(HistoricalRerunItem.id == item_id).first()
        batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
        execution = (
            db.query(PushExecution).filter(PushExecution.id == execution_id).first()
            if execution_id
            else None
        )
        if not item or not batch:
            return

        log = create_push_log(
            matched,
            matched.sources.get(matched.primary_source) or [{}],
            field_mapping,
            dify_result,
            payload,
            mr_text,
            push_config,
            patient_id,
        )
        # 标记手工重跑入口
        log.manual_override = 1
        log.trigger_type = "manual"
        db.add(log)
        db.flush()

        parsed = dify_result.get("parsed_output") or {}
        parse_ok = bool(parsed.get("parse_success"))
        if parse_ok and parse_strategy in {"hybrid", "dimensions_only"}:
            save_audit_results(db, log.id, dify_result, audit_type_code)

        superseded = 0
        if is_qc_usable(log.status, log.parse_status, getattr(log, "contract_valid", None)):
            # P0-1 write-before guard: 再次检查空 key 旧当前，防止 preview 后并发变化
            if source_record_key:
                _legacy_guard = _find_legacy_empty_key_current(
                    db,
                    audit_type_code=item.audit_type_code,
                    audit_run_mode=run_mode,
                    patient_id=patient_id,
                    visit_number=visit_number,
                )
                if _legacy_guard is not None:
                    log.status = "discarded"
                    log.superseded_at = datetime.now()
                    item.status = "identity_ambiguous"
                    item.reason_code = "legacy_empty_key_guard"
                    item.reason_message = "legacy empty-key current detected at write time"
                    item.new_push_log_id = log.id
                    if execution:
                        finish_execution(db, execution, "failed", push_log_id=log.id, error_message=item.reason_message)
                    batch.processed = int(batch.processed or 0) + 1
                    batch.skipped_count = int(batch.skipped_count or 0) + 1
                    db.commit()
                    return
            superseded = mark_historical_reaudit_superseded(
                db,
                log,
                expected_previous_id=previous_current_id,
            )
            if superseded == -1:
                # P0-4: 并发变化 — 新结果不得留在当前视图；标记 discarded 退出当前查询
                log.status = "discarded"
                log.superseded_at = datetime.now()
                item.status = "concurrent_changed"
                item.reason_code = "concurrent_changed"
                item.reason_message = "previous current result changed before supersede; new result invalidated"
                item.new_push_log_id = log.id
                if execution:
                    finish_execution(
                        db,
                        execution,
                        "failed",
                        push_log_id=log.id,
                        error_message=item.reason_message,
                        elapsed_ms=int(dify_result.get("elapsed_ms") or 0),
                    )
                batch.processed = int(batch.processed or 0) + 1
                batch.failed_count = int(batch.failed_count or 0) + 1
                db.commit()
                return

            # 默认 suppress 告警；仅 new_high_only 且合格 high 才入队
            if alert_policy == "new_high_only" and str(log.severity or "").lower() == "high":
                try:
                    from app.services.relay_alert_service import RelayAlertService

                    RelayAlertService(db, config).enqueue_high_severity_alerts(log.id)
                except Exception as exc:
                    logger.error("historical rerun alert enqueue failed: %s", exc, exc_info=True)

            item.status = "success"
            item.new_push_log_id = log.id
            item.reason_code = "replaced" if superseded else "success_no_previous"
            if execution:
                finish_execution(
                    db,
                    execution,
                    "success",
                    push_log_id=log.id,
                    elapsed_ms=int(dify_result.get("elapsed_ms") or 0),
                    target_name=str(dify_result.get("_target_name") or ""),
                )
            batch.processed = int(batch.processed or 0) + 1
            batch.success_count = int(batch.success_count or 0) + 1
            batch.superseded_count = int(batch.superseded_count or 0) + max(0, int(superseded or 0))
        else:
            item.status = "failed"
            item.reason_code = "not_qc_usable"
            item.reason_message = f"status={log.status} parse_status={log.parse_status}"
            item.new_push_log_id = log.id
            if execution:
                finish_execution(
                    db,
                    execution,
                    "failed",
                    push_log_id=log.id,
                    error_message=item.reason_message,
                    elapsed_ms=int(dify_result.get("elapsed_ms") or 0),
                )
            batch.processed = int(batch.processed or 0) + 1
            batch.failed_count = int(batch.failed_count or 0) + 1

        db.commit()

        if alert_policy == "new_high_only" and item.status == "success":
            try:
                from app.services.relay_alert_service import RelayAlertService

                RelayAlertService(db, config).dispatch_pending(push_log_ids=[log.id])
            except Exception:
                logger.exception("historical rerun alert dispatch failed")
    except Exception as exc:
        logger.exception("historical rerun item failed batch=%s item=%s", batch_id, item_id)
        try:
            try:
                db.rollback()
            except Exception:
                pass
            try:
                db.close()
            except Exception:
                pass
            db = SessionLocal()
            item = db.query(HistoricalRerunItem).filter(HistoricalRerunItem.id == item_id).first()
            batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
            if item and item.status == "running":
                item.status = "failed"
                item.reason_code = "exception"
                item.reason_message = str(exc)[:500]
                item.updated_at = datetime.now()
            if batch:
                batch.processed = int(batch.processed or 0) + 1
                batch.failed_count = int(batch.failed_count or 0) + 1
                batch.last_error = str(exc)[:500]
            db.commit()
        except Exception:
            logger.exception("historical rerun failure bookkeeping failed")
    finally:
        try:
            db.close()
        except Exception:
            pass


CONSUMER_LEASE_SECONDS = 120
STALE_ITEM_THRESHOLD_SECONDS = 300

_active_consumers: Dict[int, str] = {}
_consumer_lock = threading.Lock()


def _try_acquire_consumer_lease(db: Session, batch_id: int, owner_token: str) -> bool:
    """数据库级 consumer claim；同一 batch 任意时刻最多一个有效消费者。"""
    batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).with_for_update().first()
    if not batch:
        return False
    now = datetime.now()
    if batch.consumer_owner and batch.consumer_lease_until and batch.consumer_lease_until > now:
        if batch.consumer_owner != owner_token:
            return False
    batch.consumer_owner = owner_token
    batch.consumer_lease_until = now + timedelta(seconds=CONSUMER_LEASE_SECONDS)
    batch.consumer_heartbeat_at = now
    db.flush()
    return True


def _renew_consumer_lease(db: Session, batch_id: int, owner_token: str) -> bool:
    """续约 consumer lease。"""
    batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
    if not batch or batch.consumer_owner != owner_token:
        return False
    now = datetime.now()
    batch.consumer_lease_until = now + timedelta(seconds=CONSUMER_LEASE_SECONDS)
    batch.consumer_heartbeat_at = now
    db.flush()
    return True


def _release_consumer_lease(db: Session, batch_id: int, owner_token: str) -> None:
    """释放 consumer lease。"""
    batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
    if batch and batch.consumer_owner == owner_token:
        batch.consumer_owner = ""
        batch.consumer_lease_until = None
        db.flush()


def recover_stale_running_items(db: Session, batch_id: int, actor: str = "system") -> int:
    """恢复 stale running items：lease 过期 + updated_at 超阈值 + batch 无有效 consumer。"""
    now = datetime.now()
    batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
    if not batch:
        return 0
    has_active_consumer = (
        batch.consumer_owner
        and batch.consumer_lease_until
        and batch.consumer_lease_until > now
    )
    if has_active_consumer:
        return 0
    threshold = now - timedelta(seconds=STALE_ITEM_THRESHOLD_SECONDS)
    stale_items = (
        db.query(HistoricalRerunItem)
        .filter(
            HistoricalRerunItem.batch_id == batch_id,
            HistoricalRerunItem.status == "running",
            HistoricalRerunItem.updated_at < threshold,
        )
        .all()
    )
    recovered = 0
    for item in stale_items:
        exec_lease_valid = False
        if item.execution_id:
            from app.models import PushExecution
            execution = db.query(PushExecution).filter(PushExecution.id == item.execution_id).first()
            if execution and execution.lease_until and execution.lease_until > now:
                exec_lease_valid = True
        if exec_lease_valid:
            continue
        item.status = "pending"
        item.reason_code = "stale_recovery"
        item.reason_message = f"recovered by {actor} at {now.isoformat()}; original_status=running"
        item.updated_at = now
        recovered += 1
    if recovered:
        logger.info("recover_stale_running_items batch=%s recovered=%s actor=%s", batch_id, recovered, actor)
    db.flush()
    return recovered


def run_batch(batch_id: int, max_items: Optional[int] = None) -> None:
    """串行消费批次 pending items；支持 pause/cancel 检查。消费者单例通过 DB lease 保证。"""
    owner_token = secrets.token_hex(16)
    with _consumer_lock:
        if batch_id in _active_consumers:
            logger.info("run_batch: consumer already active for batch=%s, skipping", batch_id)
            return
        _active_consumers[batch_id] = owner_token
    try:
        _run_batch_inner(batch_id, owner_token, max_items)
    finally:
        with _consumer_lock:
            _active_consumers.pop(batch_id, None)
        try:
            db = SessionLocal()
            _release_consumer_lease(db, batch_id, owner_token)
            db.commit()
            db.close()
        except Exception as release_exc:
            logger.error(
                "consumer lease release failed batch=%s owner=%s err=%s; relying on expiry recovery",
                batch_id, owner_token[:8], release_exc,
            )


def _run_batch_inner(batch_id: int, owner_token: str, max_items: Optional[int] = None) -> None:
    processed = 0
    while True:
        if max_items is not None and processed >= max_items:
            break
        db = SessionLocal()
        try:
            if not _try_acquire_consumer_lease(db, batch_id, owner_token):
                db.rollback()
                logger.info("run_batch: could not acquire consumer lease batch=%s, exiting", batch_id)
                return
            batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
            if not batch:
                db.commit()
                return
            if batch.status == "paused":
                db.commit()
                return
            if batch.status == "cancelled":
                db.commit()
                return
            if batch.status not in {"running", "confirmed"}:
                if batch.status == "confirmed":
                    batch.status = "running"
                    batch.started_at = batch.started_at or datetime.now()
                    db.commit()
                else:
                    db.commit()
                    return
            recover_stale_running_items(db, batch_id, actor=owner_token)
            item = _claim_next_item(db, batch_id)
            if item is None:
                _finalize_batch_if_done(db, batch_id)
                db.commit()
                return
            item_id = item.id
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("claim next item failed batch=%s", batch_id)
            return
        finally:
            db.close()

        _process_one_item(batch_id, item_id)
        processed += 1

        db = SessionLocal()
        try:
            _finalize_batch_if_done(db, batch_id)
            db.commit()
        finally:
            db.close()


def start_batch_async(batch_id: int) -> None:
    """幂等启动批次消费者；重复调用不会启动多个线程。"""
    owner_token = secrets.token_hex(16)
    with _consumer_lock:
        if batch_id in _active_consumers:
            logger.info("start_batch_async: consumer already active for batch=%s", batch_id)
            return
        _active_consumers[batch_id] = owner_token
    thread = threading.Thread(target=run_batch, args=(batch_id,), daemon=True, name=f"hist-rerun-{batch_id}")
    thread.start()
