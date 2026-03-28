"""
推送日志路由 —— /api/logs
"""
import csv
import io
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.schemas import PushLogItem, PushLogDetail, PaginatedLogs, MessageResponse
from app.database import get_db
from app.models import PushLog, AuditDimensionResult, AuditConclusion
from app.config import load_config, decrypt_value
from app.dify_pusher import push_to_dify

router = APIRouter()
logger = logging.getLogger(__name__)


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
        "科室", "住院号", "状态", "不一致", "严重程度", "耗时(ms)", "重试次数", "错误信息",
    ])
    for log in logs:
        writer.writerow([
            log.id, log.push_time, log.trigger_type, log.query_date,
            log.patient_id, log.patient_name, log.dept,
            getattr(log, "admission_no", ""),
            log.status,
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

    logger.info(f"单条重推 | log_id={log_id} | patient_id={log.patient_id}")
    result = push_to_dify(log.mr_text, dify_cfg, log.patient_id)
    parsed_output = result.get("parsed_output", {})

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

    # 重建结构化审计数据
    if result.get("status") == "success" and parsed_output:
        try:
            db.query(AuditDimensionResult).filter(AuditDimensionResult.push_log_id == log_id).delete()
            db.query(AuditConclusion).filter(AuditConclusion.push_log_id == log_id).delete()

            for dim in parsed_output.get("dimensions", []):
                db.add(AuditDimensionResult(
                    push_log_id=log_id,
                    dimension=dim.get("dimension", ""),
                    status=dim.get("status", ""),
                    medical_content=dim.get("medical_content", ""),
                    nursing_content=dim.get("nursing_content", ""),
                    explanation=dim.get("explanation", ""),
                ))
            db.add(AuditConclusion(
                push_log_id=log_id,
                overall_conclusion=parsed_output.get("overall_conclusion", ""),
                focus_items=json.dumps(parsed_output.get("focus_items", []), ensure_ascii=False),
                audit_date=log.query_date,
            ))
            logger.info(f"单条重推: 结构化审计数据已重建 | log_id={log_id}")
        except Exception as e:
            logger.error(f"单条重推: 结构化审计数据重建失败 | log_id={log_id} | error={e}")

    db.commit()
    return MessageResponse(
        message=f"重推完成，状态: {result.get('status')}",
        success=result.get("status") == "success",
    )
