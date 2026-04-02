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
from app.models import PushLog, AuditDimensionResult, AuditConclusion, User
from app.config import load_config
from app.dify_pusher import push_to_dify, parse_dify_structured_output
from app.services import ConfigParser
from app.auth import get_current_user

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
    _user: User = Depends(get_current_user),
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


# 注意：/export/csv 必须在 /{log_id} 之前定义，否则 "export" 会被当作 log_id 解析
@router.get("/export/csv", summary="导出 CSV")
def export_csv(
    status: str = Query(None),
    dept: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
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

    EXPORT_MAX_ROWS = 10000
    logs = q.order_by(desc(PushLog.push_time)).limit(EXPORT_MAX_ROWS).all()

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


@router.get("/{log_id}", response_model=PushLogDetail, summary="日志详情（含完整AI结果）")
def get_log_detail(log_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    log = db.query(PushLog).filter(PushLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")
    return PushLogDetail.model_validate(log)


@router.post("/{log_id}/retry", response_model=MessageResponse, summary="单条重推")
def retry_single(log_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    log = db.query(PushLog).filter(PushLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")

    config = load_config()
    push_settings = ConfigParser.get_push_settings(config)
    max_retry = push_settings["max_retry"]

    if log.retry_count >= max_retry:
        return MessageResponse(message=f"已达最大重试次数({max_retry})", success=False)

    if not log.request_json and not log.mr_text:
        return MessageResponse(message="无原始推送内容，无法重推", success=False)

    dify_cfg = ConfigParser.parse_dify_config(config)
    payload = json.loads(log.request_json) if log.request_json else log.mr_text
    result = push_to_dify(payload, dify_cfg, log.patient_id)

    log.status = result.get("status", "failed")
    log.workflow_run_id = result.get("workflow_run_id", "")
    log.task_id = result.get("task_id", "")
    log.ai_result = json.dumps(result.get("result", {}), ensure_ascii=False)
    log.response_json = json.dumps(result.get("result", {}), ensure_ascii=False)
    log.inconsistency = 1 if result.get("inconsistency") else 0
    log.severity = result.get("severity", "")
    log.risk_score = result.get("risk_score", 0)
    log.error_msg = result.get("error", "")
    log.elapsed_ms = result.get("elapsed_ms", 0)
    log.parse_status = "success" if result.get("parsed_output", {}).get("parse_success") else "failed"
    log.parse_error = result.get("parse_error", "")
    log.ai_version = result.get("parsed_output", {}).get("version", "1.0")
    log.retry_count += 1
    log.push_time = datetime.now()
    log.trigger_type = "retry"

    # 清除旧的审计结果，保存新的
    db.query(AuditDimensionResult).filter(AuditDimensionResult.push_log_id == log_id).delete()
    db.query(AuditConclusion).filter(AuditConclusion.push_log_id == log_id).delete()

    parsed = result.get("parsed_output", {})
    if parsed and parsed.get("parse_success"):
        for dim in parsed.get("dimensions", []):
            db.add(AuditDimensionResult(
                push_log_id=log_id,
                dimension_code=dim.get("dimension_code", ""),
                dimension=dim.get("dimension", ""),
                status=dim.get("status", "❓"),
                severity=dim.get("severity", ""),
                confidence=float(dim.get("confidence", 0) or 0),
                medical_content=dim.get("medical_content", ""),
                nursing_content=dim.get("nursing_content", ""),
                explanation=dim.get("explanation", ""),
                issue_summary=dim.get("issue_summary", ""),
                recommendation=dim.get("recommendation", ""),
                medical_evidence_json=json.dumps(dim.get("medical_evidence", []), ensure_ascii=False),
                nursing_evidence_json=json.dumps(dim.get("nursing_evidence", []), ensure_ascii=False),
            ))
        focus_items = parsed.get("focus_items", [])
        db.add(AuditConclusion(
            push_log_id=log_id,
            has_inconsistency=1 if parsed.get("inconsistency") else 0,
            severity=parsed.get("severity", ""),
            risk_score=parsed.get("risk_score", 0),
            overall_conclusion=parsed.get("overall_conclusion", ""),
            focus_items=json.dumps(focus_items, ensure_ascii=False) if focus_items else "[]",
            audit_date=parsed.get("audit_date", ""),
            reasoning_brief=parsed.get("reasoning_brief", ""),
            ai_version=parsed.get("version", "1.0"),
        ))

    db.commit()
    return MessageResponse(
        message=f"重推完成，状态: {result.get('status')}",
        success=result.get("status") == "success",
    )
