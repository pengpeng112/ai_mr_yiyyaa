"""历史质控手工重跑 API（ACTIVE/007）。

独立于 /api/push/manual，避免误触覆盖语义。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import HistoricalRerunBatch, HistoricalRerunItem, User
from app.permissions import require_permission
from app.schemas import HistoricalRerunBatchCreateRequest, HistoricalRerunPreviewRequest
from app.security_utils import public_error_message
from app.services import historical_rerun_service as hrs

router = APIRouter()
logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client:
        return str(request.client.host or "")[:64]
    return ""


@router.post("/preview", summary="历史重新核查预检（只读）")
def preview_historical_rerun(
    body: HistoricalRerunPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_historical_rerun")),
):
    try:
        date_from, date_to = body.resolved_range()
    except ValueError as exc:
        # 来源为 schema 业务校验（日期范围），非内部异常；经 public_error_message 过滤后透传
        raise HTTPException(
            status_code=422,
            detail=public_error_message(exc, "invalid date range"),
        ) from exc

    logger.info(
        "historical_rerun preview actor=%s date=%s~%s dim=%s types=%s",
        getattr(current_user, "username", ""),
        date_from,
        date_to,
        body.date_dimension,
        body.audit_type_codes,
    )
    result = hrs.preview_historical_rerun(
        db,
        date_from=date_from,
        date_to=date_to,
        date_dimension=body.date_dimension,
        audit_type_codes=body.audit_type_codes,
        dept_filter=body.dept_filter,
        audit_run_mode=body.audit_run_mode,
        shard_limit=body.shard_limit,
    )
    # 响应默认不带完整候选明细时可裁剪；首版返回摘要 + 有限条数
    candidates = result.get("candidates") or []
    result["candidates_preview"] = candidates[:50]
    # 完整 candidates 保留给 create 二次预检使用时由服务端再算；对外可不传全文
    result.pop("candidates", None)
    return result


@router.post("/batches", summary="确认并创建历史重跑批次")
def create_historical_rerun_batch(
    body: HistoricalRerunBatchCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_historical_rerun")),
):
    try:
        date_from, date_to = body.resolved_range()
    except ValueError as exc:
        # 来源为 schema 业务校验（日期范围），非内部异常；经 public_error_message 过滤后透传
        raise HTTPException(
            status_code=422,
            detail=public_error_message(exc, "invalid date range"),
        ) from exc

    # 创建前重新预检并校验哈希
    preview = hrs.preview_historical_rerun(
        db,
        date_from=date_from,
        date_to=date_to,
        date_dimension=body.date_dimension,
        audit_type_codes=body.audit_type_codes,
        dept_filter=body.dept_filter,
        audit_run_mode=body.audit_run_mode,
    )
    try:
        batch = hrs.create_batch_from_preview(
            db,
            preview,
            actor=str(getattr(current_user, "username", "") or ""),
            actor_ip=_client_ip(request),
            reason=body.reaudit_reason,
            confirm_candidate_hash=body.confirm_candidate_hash,
            alert_policy=body.alert_policy,
            include_rectified=body.include_rectified,
        )
        db.commit()
    except LookupError as exc:
        db.rollback()
        # LookupError 为业务冲突（如 candidate_hash mismatch），非堆栈/SQL 泄露
        raise HTTPException(
            status_code=409,
            detail=public_error_message(exc, "batch conflict"),
        ) from exc
    except ValueError as exc:
        db.rollback()
        # ValueError 为业务校验失败（reason/policy/preview incomplete 等）
        raise HTTPException(
            status_code=422,
            detail=public_error_message(exc, "invalid batch request"),
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("create historical rerun batch failed")
        raise HTTPException(status_code=500, detail="failed to create batch") from exc

    logger.info(
        "historical_rerun batch created id=%s actor=%s candidates=%s alert_policy=%s",
        batch.id,
        batch.actor,
        batch.candidate_count,
        batch.alert_policy,
    )

    if body.auto_start:
        batch.status = "running"
        batch.started_at = batch.started_at or __import__("datetime").datetime.now()
        db.commit()
        hrs.start_batch_async(batch.id)

    db.refresh(batch)
    return hrs.get_batch_dict(batch)


@router.get("/batches/{batch_id}", summary="查询历史重跑批次")
def get_historical_rerun_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_historical_rerun")),
):
    batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="batch not found")
    return hrs.get_batch_dict(batch)


@router.get("/batches/{batch_id}/items", summary="查询批次明细（不含病历正文）")
def list_historical_rerun_items(
    batch_id: int,
    status: str = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_historical_rerun")),
):
    batch = db.query(HistoricalRerunBatch).filter(HistoricalRerunBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="batch not found")
    q = db.query(HistoricalRerunItem).filter(HistoricalRerunItem.batch_id == batch_id)
    if status:
        q = q.filter(HistoricalRerunItem.status == status)
    total = q.count()
    rows = (
        q.order_by(HistoricalRerunItem.id.asc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [hrs.get_item_dict(r) for r in rows],
    }


@router.post("/batches/{batch_id}/pause", summary="暂停批次（未开始分片）")
def pause_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_historical_rerun")),
):
    try:
        batch = hrs.set_batch_control(db, batch_id, "pause")
        db.commit()
    except LookupError as exc:
        # 业务层固定文案 "batch not found"
        raise HTTPException(
            status_code=404,
            detail=public_error_message(exc, "batch not found"),
        ) from exc
    except ValueError as exc:
        # 业务层状态机冲突，如 cannot pause batch in status=...
        raise HTTPException(
            status_code=409,
            detail=public_error_message(exc, "cannot pause batch"),
        ) from exc
    return hrs.get_batch_dict(batch)


@router.post("/batches/{batch_id}/resume", summary="恢复批次")
def resume_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_historical_rerun")),
):
    try:
        batch = hrs.set_batch_control(db, batch_id, "resume")
        db.commit()
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=public_error_message(exc, "batch not found"),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=public_error_message(exc, "cannot resume batch"),
        ) from exc
    hrs.start_batch_async(batch_id)
    return hrs.get_batch_dict(batch)


@router.post("/batches/{batch_id}/cancel", summary="取消批次")
def cancel_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_historical_rerun")),
):
    try:
        batch = hrs.set_batch_control(db, batch_id, "cancel")
        db.commit()
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=public_error_message(exc, "batch not found"),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=public_error_message(exc, "cannot cancel batch"),
        ) from exc
    return hrs.get_batch_dict(batch)


@router.get("/batches/{batch_id}/reconciliation", summary="批次 before/after 对账")
def reconcile_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_historical_rerun")),
):
    try:
        return hrs.build_reconciliation(db, batch_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=public_error_message(exc, "batch not found"),
        ) from exc
