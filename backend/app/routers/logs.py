"""
推送日志路由 —— /api/logs
"""
import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.schemas import PushLogItem, PushLogDetail, PaginatedLogs, MessageResponse
from app.database import get_db
from app.models import PushLog
from app.config import load_config, decrypt_value
from app.dify_pusher import push_to_dify

router = APIRouter()


@router.get("", response_model=PaginatedLogs, summary="分页查询推送日志")
def query_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    status: str = Query(None, description="success|failed|skipped|pending"),
    dept: str = Query(None),
    date_from: str = Query(None, description="yyyy-mm-dd"),
    date_to: str = Query(None, description="yyyy-mm-dd"),
    patient_id: str = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(PushLog)
    if status:
        q = q.filter(PushLog.status == status)
    if dept:
        q = q.filter(PushLog.dept == dept)
    if date_from:
        q = q.filter(PushLog.query_date >= date_from)
    if date_to:
        q = q.filter(PushLog.query_date <= date_to)
    if patient_id:
        q = q.filter(PushLog.patient_id.contains(patient_id))

    total = q.count()
    items = (
        q.order_by(desc(PushLog.push_time))
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return PaginatedLogs(
        total=total,
        page=page,
        limit=limit,
        items=[PushLogItem.model_validate(i) for i in items],
    )


@router.get("/{log_id}", response_model=PushLogDetail, summary="日志详情（含完整AI结果）")
def get_log_detail(log_id: int, db: Session = Depends(get_db)):
    log = db.query(PushLog).filter(PushLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")
    return PushLogDetail.model_validate(log)


@router.get("/export/csv", summary="导出 CSV")
def export_csv(
    status: str = Query(None),
    dept: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(PushLog)
    if status:
        q = q.filter(PushLog.status == status)
    if dept:
        q = q.filter(PushLog.dept == dept)
    if date_from:
        q = q.filter(PushLog.query_date >= date_from)
    if date_to:
        q = q.filter(PushLog.query_date <= date_to)

    logs = q.order_by(desc(PushLog.push_time)).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "推送时间", "触发类型", "查询日期", "患者ID", "姓名",
        "科室", "状态", "不一致", "严重程度", "耗时(ms)", "重试次数", "错误信息",
    ])
    for log in logs:
        writer.writerow([
            log.id, log.push_time, log.trigger_type, log.query_date,
            log.patient_id, log.patient_name, log.dept, log.status,
            "是" if log.inconsistency else "否", log.severity,
            log.elapsed_ms, log.retry_count, log.error_msg,
        ])

    output.seek(0)
    filename = f"push_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/{log_id}/retry", response_model=MessageResponse, summary="单条重推")
def retry_single(log_id: int, db: Session = Depends(get_db)):
    log = db.query(PushLog).filter(PushLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")

    config = load_config()
    push_cfg = config.get("push", {})
    max_retry = push_cfg.get("max_retry", 3)

    if log.retry_count >= max_retry:
        return MessageResponse(message=f"已达最大重试次数({max_retry})", success=False)

    if not log.mr_text:
        return MessageResponse(message="无原始推送文本，无法重推", success=False)

    dify_cfg = config.get("dify", {})
    try:
        dify_cfg["api_key"] = decrypt_value(dify_cfg.get("api_key_enc", ""))
    except Exception:
        dify_cfg["api_key"] = ""

    result = push_to_dify(log.mr_text, dify_cfg, log.patient_id)

    log.status = result.get("status", "failed")
    log.workflow_run_id = result.get("workflow_run_id", "")
    log.task_id = result.get("task_id", "")
    log.ai_result = json.dumps(result.get("result", {}), ensure_ascii=False)
    log.inconsistency = 1 if result.get("inconsistency") else 0
    log.severity = result.get("severity", "")
    log.error_msg = result.get("error", "")
    log.elapsed_ms = result.get("elapsed_ms", 0)
    log.retry_count += 1
    log.push_time = datetime.now()
    log.trigger_type = "retry"

    db.commit()
    return MessageResponse(
        message=f"重推完成，状态: {result.get('status')}",
        success=result.get("status") == "success",
    )
