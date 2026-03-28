"""
数据推送路由 —— /api/push
"""
import json
import time
import uuid
import threading
import logging
from datetime import datetime
from typing import Dict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas import ManualPushRequest, RetryRequest, PushProgress, MessageResponse
from app.config import load_config, decrypt_value
from app.database import get_db, SessionLocal
from app.models import PushLog, AuditDimensionResult, AuditConclusion
from app.oracle_client import fetch_records, group_by_patient, build_mr_text_combined
from app.dify_pusher import push_to_dify
from app.notifier import send_notification

router = APIRouter()
logger = logging.getLogger(__name__)

# 异步任务进度存储
_task_progress: Dict[str, PushProgress] = {}


def _save_structured_audit(db: Session, log_id: int, parsed_output: dict, query_date: str):
    """保存结构化审计数据（AuditDimensionResult + AuditConclusion）"""
    try:
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
            audit_date=query_date,
        ))
        logger.info(f"结构化审计数据已保存 | log_id={log_id} | dimensions={len(parsed_output.get('dimensions',[]))}")
    except Exception as e:
        logger.error(f"结构化审计数据保存失败 | log_id={log_id} | error={e}", exc_info=True)


def _delete_structured_audit(db: Session, log_id: int):
    """删除旧的结构化审计数据（用于重推时重建）"""
    try:
        db.query(AuditDimensionResult).filter(AuditDimensionResult.push_log_id == log_id).delete()
        db.query(AuditConclusion).filter(AuditConclusion.push_log_id == log_id).delete()
    except Exception as e:
        logger.error(f"删除旧结构化审计数据失败 | log_id={log_id} | error={e}")


@router.post("/manual", summary="手动推送")
def manual_push(body: ManualPushRequest, db: Session = Depends(get_db)):
    config = load_config()

    oracle_cfg = config.get("oracle", {})
    try:
        oracle_cfg["password"] = decrypt_value(oracle_cfg.get("password_enc", ""))
    except Exception:
        oracle_cfg["password"] = ""

    dify_cfg = config.get("dify", {})
    try:
        dify_cfg["api_key"] = decrypt_value(dify_cfg.get("api_key_enc", ""))
    except Exception:
        dify_cfg["api_key"] = ""

    sql_config = config.get("sql", {})

    dept_list = body.dept_filter
    if dept_list is None:
        dept_cfg = config.get("departments", {})
        dept_list = dept_cfg.get("list", []) if dept_cfg.get("mode") == "include" else []

    push_cfg = config.get("push", {})
    interval_ms = push_cfg.get("interval_ms", 500)

    if body.async_mode and not body.dry_run:
        task_id = str(uuid.uuid4())[:8]
        _task_progress[task_id] = PushProgress(task_id=task_id, status="running")
        t = threading.Thread(
            target=_async_push,
            args=(task_id, body.query_date, dept_list, oracle_cfg, dify_cfg, config, interval_ms, sql_config),
            daemon=True,
        )
        t.start()
        return {"task_id": task_id, "message": "异步任务已提交"}

    try:
        records = fetch_records(oracle_cfg, dept_list, body.query_date, sql_config)
    except Exception as e:
        return MessageResponse(message=f"Oracle 查询失败: {e}", success=False)

    dept_cfg = config.get("departments", {})
    sql_dept_col = sql_config.get("dept_column", "所在科室名称") if sql_config else "所在科室名称"
    if dept_cfg.get("mode") == "exclude" and dept_cfg.get("list"):
        exclude_set = set(dept_cfg["list"])
        records = [r for r in records if r.get(sql_dept_col) not in exclude_set]

    grouped = group_by_patient(records)

    if body.dry_run:
        preview = []
        for pid, precs in grouped.items():
            preview.append({
                "patient_id": pid,
                "patient_name": precs[0].get("患者姓名", ""),
                "dept": precs[0].get(sql_dept_col, ""),
                "record_count": len(precs),
                "mr_text_preview": build_mr_text_combined(precs)[:500] + "...",
            })
        return {"dry_run": True, "total_patients": len(grouped), "total_records": len(records), "preview": preview}

    logger.info(f"手动推送开始 | date={body.query_date} | patients={len(grouped)}")
    results = []
    for pid, precs in grouped.items():
        mr_text = build_mr_text_combined(precs)
        first = precs[0]
        result = push_to_dify(mr_text, dify_cfg, pid)
        parsed_output = result.get("parsed_output", {})

        log = PushLog(
            push_time=datetime.now(),
            trigger_type="manual",
            query_date=body.query_date,
            patient_id=pid,
            patient_name=first.get("患者姓名", ""),
            dept=first.get(sql_dept_col, ""),
            admission_no=first.get("住院号", ""),
            visit_number=str(first.get("次数", "")),
            workflow_run_id=result.get("workflow_run_id", ""),
            task_id=result.get("task_id", ""),
            status=result.get("status", "failed"),
            ai_result=json.dumps(result.get("result", {}), ensure_ascii=False),
            inconsistency=1 if result.get("inconsistency") else 0,
            severity=result.get("severity", ""),
            error_msg=result.get("error", ""),
            elapsed_ms=result.get("elapsed_ms", 0),
            mr_text=mr_text,
        )
        db.add(log)
        db.flush()

        if parsed_output and result.get("status") == "success":
            _save_structured_audit(db, log.id, parsed_output, body.query_date)

        logger.info(
            f"患者推送完成 | pid={pid} | status={result.get('status')} "
            f"| inconsistency={result.get('inconsistency')} | elapsed_ms={result.get('elapsed_ms', 0)}"
        )

        results.append({"patient_id": pid, "status": result.get("status"), "inconsistency": result.get("inconsistency", False)})

        if result.get("inconsistency"):
            try:
                send_notification(pid, result, config.get("notify", {}))
            except Exception as e:
                logger.warning(f"通知发送失败 | pid={pid} | error={e}")

        time.sleep(interval_ms / 1000)

    db.commit()
    success_count = sum(1 for r in results if r["status"] == "success")
    logger.info(f"手动推送完成 | total={len(results)} | success={success_count} | failed={len(results)-success_count}")
    return {"total": len(results), "success": success_count, "failed": len(results) - success_count, "results": results}


@router.post("/preview", summary="Dry-run 预览（仅抽数不推送）")
def preview_push(body: ManualPushRequest, db: Session = Depends(get_db)):
    body.dry_run = True
    return manual_push(body, db)


@router.post("/retry", summary="批量重推失败记录")
def retry_push(body: RetryRequest, db: Session = Depends(get_db)):
    config = load_config()
    dify_cfg = config.get("dify", {})
    try:
        dify_cfg["api_key"] = decrypt_value(dify_cfg.get("api_key_enc", ""))
    except Exception:
        dify_cfg["api_key"] = ""

    push_cfg = config.get("push", {})
    interval_ms = push_cfg.get("interval_ms", 500)
    max_retry = push_cfg.get("max_retry", 3)

    results = []
    for log_id in body.log_ids:
        log = db.query(PushLog).filter(PushLog.id == log_id).first()
        if not log:
            results.append({"log_id": log_id, "status": "not_found"})
            continue
        if log.retry_count >= max_retry:
            results.append({"log_id": log_id, "status": "max_retry_exceeded"})
            continue
        if not log.mr_text:
            results.append({"log_id": log_id, "status": "no_mr_text"})
            continue

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

        if result.get("status") == "success" and parsed_output:
            _delete_structured_audit(db, log_id)
            _save_structured_audit(db, log_id, parsed_output, log.query_date)

        results.append({"log_id": log_id, "status": result.get("status")})
        time.sleep(interval_ms / 1000)

    db.commit()
    return {"results": results}


@router.get("/status/{task_id}", response_model=PushProgress, summary="查询异步任务进度")
def get_push_status(task_id: str):
    progress = _task_progress.get(task_id)
    if not progress:
        return PushProgress(task_id=task_id, status="not_found")
    return progress


def _async_push(task_id, query_date, dept_list, oracle_cfg, dify_cfg, config, interval_ms, sql_config):
    db = SessionLocal()
    progress = _task_progress[task_id]
    try:
        records = fetch_records(oracle_cfg, dept_list, query_date, sql_config)

        dept_cfg = config.get("departments", {})
        sql_dept_col = sql_config.get("dept_column", "所在科室名称") if sql_config else "所在科室名称"
        if dept_cfg.get("mode") == "exclude" and dept_cfg.get("list"):
            exclude_set = set(dept_cfg["list"])
            records = [r for r in records if r.get(sql_dept_col) not in exclude_set]

        grouped = group_by_patient(records)
        progress.total = len(grouped)
        logger.info(f"异步推送开始 | task_id={task_id} | date={query_date} | patients={len(grouped)}")

        for pid, precs in grouped.items():
            mr_text = build_mr_text_combined(precs)
            first = precs[0]
            result = push_to_dify(mr_text, dify_cfg, pid)
            parsed_output = result.get("parsed_output", {})

            log = PushLog(
                push_time=datetime.now(),
                trigger_type="manual",
                query_date=query_date,
                patient_id=pid,
                patient_name=first.get("患者姓名", ""),
                dept=first.get(sql_dept_col, ""),
                admission_no=first.get("住院号", ""),
                visit_number=str(first.get("次数", "")),
                workflow_run_id=result.get("workflow_run_id", ""),
                task_id=result.get("task_id", ""),
                status=result.get("status", "failed"),
                ai_result=json.dumps(result.get("result", {}), ensure_ascii=False),
                inconsistency=1 if result.get("inconsistency") else 0,
                severity=result.get("severity", ""),
                error_msg=result.get("error", ""),
                elapsed_ms=result.get("elapsed_ms", 0),
                mr_text=mr_text,
            )
            db.add(log)
            db.flush()

            if parsed_output and result.get("status") == "success":
                _save_structured_audit(db, log.id, parsed_output, query_date)

            progress.processed += 1
            if result.get("status") == "success":
                progress.success += 1
            else:
                progress.failed += 1

            if result.get("inconsistency"):
                try:
                    send_notification(pid, result, config.get("notify", {}))
                except Exception as e:
                    logger.warning(f"通知发送失败 | pid={pid} | error={e}")

            time.sleep(interval_ms / 1000)

        db.commit()
        progress.status = "completed"
        logger.info(f"异步推送完成 | task_id={task_id} | success={progress.success} | failed={progress.failed}")
    except Exception as e:
        logger.error(f"异步推送异常 | task_id={task_id} | error={e}", exc_info=True)
        progress.status = "failed"
    finally:
        db.close()
