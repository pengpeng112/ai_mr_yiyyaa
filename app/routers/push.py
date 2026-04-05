"""
数据推送路由 —— /api/push
"""
import time
import uuid
import threading
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas import ManualPushRequest, RetryRequest, PushProgress, MessageResponse
from app.config import load_config
from app.database import get_db, SessionLocal
from app.oracle_client import fetch_records, group_by_patient, build_mr_text_combined
from app.postgresql_client import fetch_pg_records

from app.services import (
    ConfigParser, PushExecutor, PushConfig, PushResult, build_dify_payload,
    get_task_manager
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _log_push_funnel(trigger_type: str, query_date: str, raw_rows: int, filtered_rows: int, grouped_count: int, result: PushResult | None = None):
    skipped = 0
    success = 0
    failed = 0
    skip_reason_counts = {}
    if result:
        for item in result.results:
            status = str(item.get("status", ""))
            if status == "success":
                success += 1
            elif status == "skipped":
                skipped += 1
                reason = str(item.get("skip_reason", "unknown") or "unknown")
                skip_reason_counts[reason] = int(skip_reason_counts.get(reason, 0)) + 1
            else:
                failed += 1
    logger.info(
        "[推送漏斗] trigger=%s query_date=%s raw_rows=%s filtered_rows=%s grouped=%s success=%s failed=%s skipped=%s",
        trigger_type,
        query_date,
        raw_rows,
        filtered_rows,
        grouped_count,
        success,
        failed,
        skipped,
    )
    if skip_reason_counts:
        logger.info("[推送漏斗] trigger=%s query_date=%s skip_reason_counts=%s", trigger_type, query_date, skip_reason_counts)


@router.post("/manual", summary="手动推送")
def manual_push(body: ManualPushRequest, db: Session = Depends(get_db)):
    config = load_config()

    data_source = ConfigParser.get_data_source_type(config)
    db_cfg = ConfigParser.parse_postgresql_config(config) if data_source == "postgresql" else ConfigParser.parse_oracle_config(config)
    dify_cfg = ConfigParser.parse_dify_config(config)
    push_settings = ConfigParser.get_push_settings(config)
    field_mapping = ConfigParser.get_field_mapping(config, data_source)

    dept_list = body.dept_filter
    if dept_list is None:
        dept_list = ConfigParser.get_department_list(config)

    if body.async_mode and not body.dry_run:
        task_id = str(uuid.uuid4())[:8]
        task_manager = get_task_manager()
        task_manager.create_task(task_id)

        t = threading.Thread(
            target=_async_push,
            args=(task_id, body.query_date, dept_list, data_source, db_cfg, dify_cfg,
                  config, push_settings, field_mapping),
            daemon=True,
        )
        t.start()
        return {"task_id": task_id, "message": "异步任务已提交"}

    try:
        records = fetch_pg_records(db_cfg, dept_list, body.query_date) if data_source == "postgresql" else fetch_records(db_cfg, dept_list, body.query_date)
    except Exception as e:
        return MessageResponse(message=f"{data_source} 查询失败: {e}", success=False)

    raw_rows = len(records)

    dept_config = config.get("departments", {})
    dept_field = field_mapping.get("dept", "所在科室名称")
    records = ConfigParser.filter_departments(records, dept_config, dept_field)
    filtered_rows = len(records)

    grouped = group_by_patient(records, field_mapping)

    if body.dry_run:
        name_field = field_mapping.get("patient_name", "患者姓名")
        preview = []
        for pid, precs in grouped.items():
            payload = build_dify_payload(precs, field_mapping, body.query_date)
            preview.append({
                "patient_id": pid,
                "patient_name": precs[0].get(name_field, ""),
                "dept": precs[0].get(dept_field, ""),
                "record_count": len(precs),
                "mr_text_preview": build_mr_text_combined(precs, field_mapping)[:500] + "...",
                "dify_payload": payload,
            })
        return {
            "dry_run": True,
            "total_patients": len(grouped),
            "total_records": len(records),
            "raw_rows": raw_rows,
            "filtered_rows": filtered_rows,
            "preview": preview,
        }

    push_config = PushConfig(
        trigger_type="manual",
        query_date=body.query_date,
        interval_ms=push_settings["interval_ms"],
        max_retry=push_settings["max_retry"],
        notify_enabled=True,
    )

    executor = PushExecutor(dify_cfg, config.get("notify", {}), field_mapping)
    result = executor.execute(db, grouped, push_config)
    _log_push_funnel("manual", body.query_date, raw_rows, filtered_rows, len(grouped), result)

    return {
        "total": result.total,
        "success": result.success,
        "failed": result.failed,
        "skipped": len([r for r in result.results if r.get("status") == "skipped"]),
        "raw_rows": raw_rows,
        "filtered_rows": filtered_rows,
        "grouped": len(grouped),
        "results": result.results,
    }


@router.post("/preview", summary="Dry-run 预览（仅抽数不推送）")
def preview_push(body: ManualPushRequest, db: Session = Depends(get_db)):
    body.dry_run = True
    return manual_push(body, db)


@router.post("/retry", summary="批量重推失败记录")
def retry_push(body: RetryRequest, db: Session = Depends(get_db)):
    config = load_config()

    dify_cfg = ConfigParser.parse_dify_config(config)
    push_settings = ConfigParser.get_push_settings(config)
    data_source = ConfigParser.get_data_source_type(config)
    field_mapping = ConfigParser.get_field_mapping(config, data_source)
    max_retry = push_settings["max_retry"]

    executor = PushExecutor(dify_cfg, config.get("notify", {}), field_mapping)
    results = executor.execute_retry(db, body.log_ids, max_retry)

    return {"results": results}


@router.get("/status/{task_id}", response_model=PushProgress, summary="查询异步任务进度")
def get_push_status(task_id: str):
    task_manager = get_task_manager()
    progress = task_manager.get_task(task_id)

    if not progress:
        return PushProgress(task_id=task_id, status="not_found")

    return PushProgress(
        task_id=progress.task_id,
        status=progress.status,
        total=progress.total,
        processed=progress.processed,
        success=progress.success,
        failed=progress.failed,
        skipped=progress.skipped,
    )


def _async_push(task_id, query_date, dept_list, data_source, db_cfg, dify_cfg,
                config, push_settings, field_mapping):
    db = SessionLocal()
    task_manager = get_task_manager()

    try:
        records = fetch_pg_records(db_cfg, dept_list, query_date) if data_source == "postgresql" else fetch_records(db_cfg, dept_list, query_date)
        raw_rows = len(records)

        dept_config = config.get("departments", {})
        dept_field = field_mapping.get("dept", "所在科室名称")
        records = ConfigParser.filter_departments(records, dept_config, dept_field)
        filtered_rows = len(records)

        grouped = group_by_patient(records, field_mapping)
        task_manager.update_task(task_id, total=len(grouped))

        push_config = PushConfig(
            trigger_type="manual",
            query_date=query_date,
            interval_ms=push_settings["interval_ms"],
            max_retry=push_settings["max_retry"],
            notify_enabled=True,
        )

        class CallbackPushExecutor(PushExecutor):
            def execute(self, db, grouped_records, push_config):
                start_time = time.time()
                result = PushResult(total=len(grouped_records))

                try:
                    for patient_id, patient_records in grouped_records.items():
                        try:
                            with db.begin_nested():
                                single_result = self._push_single_record(db, patient_id, patient_records, push_config)
                            result.results.append(single_result)

                            status = str(single_result.get("status", "failed"))
                            if status == "success":
                                result.success += 1
                                task_manager.increment_processed(task_id, result_status="success")
                            elif status == "skipped":
                                task_manager.increment_processed(task_id, result_status="skipped")
                            else:
                                result.failed += 1
                                task_manager.increment_processed(task_id, result_status="failed")

                            time.sleep(push_config.interval_ms / 1000)

                        except Exception as e:
                            logger.error(f"推送患者 {patient_id} 时发生异常: {e}")
                            result.failed += 1
                            task_manager.increment_processed(task_id, result_status="failed")
                            result.results.append({
                                "patient_id": patient_id,
                                "status": "error",
                                "error": str(e),
                            })

                    db.commit()

                except Exception as e:
                    logger.error(f"批量推送过程中发生严重错误: {e}")
                    db.rollback()
                    raise

                result.duration_seconds = time.time() - start_time
                return result

        executor = CallbackPushExecutor(dify_cfg, config.get("notify", {}), field_mapping)
        result = executor.execute(db, grouped, push_config)
        _log_push_funnel("async", query_date, raw_rows, filtered_rows, len(grouped), result)
        task_manager.update_task(task_id, status="completed")

    except Exception as e:
        logger.error(f"异步推送异常: {e}", exc_info=True)
        task_manager.update_task(task_id, status="failed")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()
