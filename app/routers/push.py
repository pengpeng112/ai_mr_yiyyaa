"""
Push routes: /api/push
Supports manual push by single date or date range with multiple date dimensions.
"""

import logging
import threading
import time
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import load_config
from app.database import SessionLocal, get_app_db_type, get_db
from app.oracle_client import build_mr_text_combined, fetch_records, group_by_patient
from app.postgresql_client import fetch_pg_records
from app.schemas import ManualPushRequest, PushProgress, RetryRequest
from app.services.bulk_push_executor import BulkPushExecutor
from app.services import (
    ConfigParser,
    PushConfig,
    PushExecutor,
    PushResult,
    build_dify_payload,
    get_task_manager,
)

router = APIRouter()
logger = logging.getLogger(__name__)


KEY_PATIENT_ID = "\u60a3\u8005ID"
KEY_VISIT_NO = "\u6b21\u6570"
KEY_PATIENT_NAME = "\u60a3\u8005\u59d3\u540d"
KEY_DEPT = "\u6240\u5728\u79d1\u5ba4\u540d\u79f0"
KEY_MR_FINISH_TIME = "\u75c5\u5386\u6587\u4e66_\u5b8c\u6210\u65f6\u95f4"
KEY_MR_TITLE_TIME = "\u75c5\u5386\u6807\u9898\u65f6\u95f4"
KEY_NURSE_CREATE_TIME = "\u62a4\u7406\u8bb0\u5f55_\u521b\u5efa\u65f6\u95f4"
KEY_NURSE_TIME = "\u62a4\u7406\u8bb0\u5f55\u65f6\u95f4"
KEY_NURSE_FORM_TIME = "\u62a4\u7406\u8bb0\u5f55\u8868\u5355\u5355\u521b\u5efa\u65f6\u95f4"
KEY_ADMISSION_DATE = "\u5165\u9662\u65e5\u671f"
KEY_DISCHARGE_DATE = "\u51fa\u9662\u65e5\u671f"
KEY_DISCHARGE_TIME = "\u51fa\u9662\u65f6\u95f4"
KEY_DISCHARGE_DATETIME = "\u51fa\u9662\u65e5\u671f\u65f6\u95f4"

DATE_DIMENSION_FIELDS = {
    "query_date": [],
    "record_create_date": [
        KEY_MR_FINISH_TIME,
        KEY_MR_TITLE_TIME,
        KEY_NURSE_CREATE_TIME,
        KEY_NURSE_TIME,
        KEY_NURSE_FORM_TIME,
    ],
    "admission_date": [KEY_ADMISSION_DATE],
    "discharge_date": [KEY_DISCHARGE_DATE, KEY_DISCHARGE_TIME, KEY_DISCHARGE_DATETIME],
}


def _log_push_funnel(
    trigger_type: str,
    query_date_label: str,
    raw_rows: int,
    filtered_rows: int,
    grouped_count: int,
    result: PushResult | None = None,
) -> None:
    skipped = 0
    success = 0
    failed = 0
    skip_reason_counts: dict[str, int] = {}
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
        "[push_funnel] trigger=%s query_date=%s raw_rows=%s filtered_rows=%s grouped=%s success=%s failed=%s skipped=%s",
        trigger_type,
        query_date_label,
        raw_rows,
        filtered_rows,
        grouped_count,
        success,
        failed,
        skipped,
    )
    if skip_reason_counts:
        logger.info(
            "[push_funnel] trigger=%s query_date=%s skip_reason_counts=%s",
            trigger_type,
            query_date_label,
            skip_reason_counts,
        )


def _parse_date(date_text: str):
    return datetime.strptime(date_text, "%Y-%m-%d").date()


def _resolve_query_dates(body: ManualPushRequest) -> list[str]:
    if body.date_from and body.date_to:
        start_date = _parse_date(body.date_from)
        end_date = _parse_date(body.date_to)
    elif body.query_date:
        start_date = _parse_date(body.query_date)
        end_date = start_date
    else:
        raise HTTPException(status_code=422, detail="query_date or date_from/date_to is required")

    span_days = (end_date - start_date).days + 1
    if span_days <= 0:
        raise HTTPException(status_code=422, detail="date_to must be >= date_from")
    if span_days > 120:
        raise HTTPException(status_code=422, detail="date range cannot exceed 120 days")

    return [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(span_days)]


def _date_label(query_dates: list[str]) -> str:
    if not query_dates:
        return ""
    if len(query_dates) == 1:
        return query_dates[0]
    return f"{query_dates[0]}~{query_dates[-1]}"


def _record_date_in_range(record: dict, field_candidates: list[str], date_from: str, date_to: str) -> bool:
    if not field_candidates:
        return True
    start = _parse_date(date_from)
    end = _parse_date(date_to)
    for field_name in field_candidates:
        raw = record.get(field_name)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        try:
            parsed = _parse_date(text[:10])
        except Exception:
            continue
        if start <= parsed <= end:
            return True
    return False


def _collect_records(
    data_source: str,
    db_cfg: dict,
    dept_list: list[str],
    query_dates: list[str],
    date_dimension: str,
) -> tuple[list[dict], int]:
    all_records: list[dict] = []
    raw_rows = 0
    custom_query_sql = str((db_cfg or {}).get("query_sql") or "").strip().lower()
    sql_uses_query_date = (":query_date" in custom_query_sql) if custom_query_sql else True
    fetch_dates = query_dates if (date_dimension == "query_date" or sql_uses_query_date) else [query_dates[-1]]

    for query_date in fetch_dates:
        day_records = (
            fetch_pg_records(db_cfg, dept_list, query_date)
            if data_source == "postgresql"
            else fetch_records(db_cfg, dept_list, query_date)
        )
        raw_rows += len(day_records)
        all_records.extend(day_records)

    deduped: list[dict] = []
    seen: set[str] = set()
    for item in all_records:
        # 优先使用上游唯一键 MRID（例如 b.mrid||c.form_id）去重。
        # 若旧 SQL 未返回 MRID，则回退历史组合键，兼容存量配置。
        mrid = str(item.get("MRID") or item.get("mrid") or "").strip()
        if mrid:
            dedupe_key = f"mrid::{mrid}"
        else:
            dedupe_key = "legacy::" + "|".join(
                [
                    str(item.get(KEY_PATIENT_ID) or ""),
                    str(item.get(KEY_VISIT_NO) or ""),
                    str(item.get(KEY_DEPT) or ""),
                    str(item.get(KEY_MR_FINISH_TIME) or item.get(KEY_MR_TITLE_TIME) or ""),
                    str(item.get(KEY_NURSE_CREATE_TIME) or item.get(KEY_NURSE_TIME) or item.get(KEY_NURSE_FORM_TIME) or ""),
                ]
            )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(item)

    if date_dimension != "query_date" and query_dates:
        fields = DATE_DIMENSION_FIELDS.get(date_dimension, [])
        date_from = query_dates[0]
        date_to = query_dates[-1]
        deduped = [r for r in deduped if _record_date_in_range(r, fields, date_from, date_to)]

    return deduped, raw_rows


def _build_query_diagnostics(body: ManualPushRequest, db_cfg: dict, raw_rows: int, filtered_rows: int) -> list[str]:
    diagnostics: list[str] = []
    query_sql = str((db_cfg or {}).get("query_sql") or "").strip()
    normalized_sql = query_sql.lower()

    if raw_rows > 0 or filtered_rows > 0:
        return diagnostics

    if not query_sql:
        diagnostics.append("当前使用默认查询 SQL，若按入院/出院日期推送，建议确认默认 SQL 是否满足该维度筛选。")
        return diagnostics

    if "，" in query_sql or "；" in query_sql:
        diagnostics.append("自定义 SQL 中包含中文逗号或分号，请改为英文符号，避免 Oracle 解析异常或结果不符合预期。")
    if " from jhemr.v_cybr" in normalized_sql:
        diagnostics.append("当前 SQL 使用 jhemr.v_cybr，只会返回已出院患者；若要查在院患者，请改回 jhemr.v_zybr 或对应视图。")
    if "inner join" in normalized_sql and ("ydhl" in normalized_sql or "v_hljl" in normalized_sql):
        diagnostics.append("当前 SQL 对护理表使用 INNER JOIN；只要护理记录未匹配上，当天病历就会被整体过滤。若希望保留病历侧数据，请改为 LEFT JOIN。")
    if body.date_dimension != "query_date" and ":query_date" in normalized_sql:
        diagnostics.append("当前选择的不是“查询日期”维度，但 SQL 仍依赖 :query_date 过滤，可能导致入院/出院日期范围内的数据被提前截断。")
    if body.date_dimension != "query_date" and ":query_date" not in normalized_sql:
        diagnostics.append("当前 SQL 未使用 :query_date，系统会按所选维度在查询结果上二次过滤；请确认 SQL 本身返回的数据范围足够覆盖目标时间段。")
    if "ydhl_202501" in normalized_sql:
        diagnostics.append("当前 SQL 指向 ydhl_202501 分表，请确认 2026-04-01 对应数据确实落在该表中，否则会直接返回 0 条。")

    if not diagnostics:
        diagnostics.append("未查询到数据，请重点核对源视图、JOIN 方式、科室名称是否完全匹配，以及所选日期维度与 SQL 过滤条件是否一致。")
    return diagnostics


def _flatten_to_single_records(grouped: dict) -> dict:
    """将按患者分组的字典拆解为每条记录一个独立推送单元。

    原始 grouped: {patient_key: [record1, record2, ...]}
    返回 flattened: {unique_key: [single_record]}
    每条 SQL 查询结果行单独发送一次 Dify 请求。
    """
    flattened: dict = {}
    for patient_key, records in grouped.items():
        for idx, record in enumerate(records):
            mrid = str(record.get("MRID") or record.get("mrid") or "").strip()
            if mrid:
                unique_key = f"{patient_key}::{mrid}"
            else:
                unique_key = f"{patient_key}::{idx}"
            # 避免 key 碰撞（极少数情况）
            if unique_key in flattened:
                unique_key = f"{unique_key}::{id(record)}"
            flattened[unique_key] = [record]
    return flattened


def _prepare_push_data(body: ManualPushRequest, config: dict, data_source: str, db_cfg: dict, field_mapping: dict):
    query_dates = _resolve_query_dates(body)
    query_date_label = _date_label(query_dates)
    dept_list = body.dept_filter if body.dept_filter is not None else ConfigParser.get_department_list(config)

    records, raw_rows = _collect_records(
        data_source=data_source,
        db_cfg=db_cfg,
        dept_list=dept_list,
        query_dates=query_dates,
        date_dimension=body.date_dimension,
    )

    dept_config = config.get("departments", {})
    dept_field = field_mapping.get("dept", KEY_DEPT)
    records = ConfigParser.filter_departments(records, dept_config, dept_field)
    filtered_rows = len(records)
    grouped = group_by_patient(records, field_mapping)
    # 逐条推送：将每条 SQL 记录拆解为独立的推送单元
    grouped = _flatten_to_single_records(grouped)
    return query_dates, query_date_label, dept_list, records, raw_rows, filtered_rows, grouped, dept_field


def _build_manual_dify_targets(body: ManualPushRequest, dify_cfg: dict) -> list[dict] | None:
    targets = []
    if body.dify_targets:
        for item in body.dify_targets:
            if hasattr(item, "model_dump"):
                targets.append(item.model_dump())
            else:
                targets.append(dict(item))
    if not targets:
        return None
    # Fill missing keys from default config for compatibility
    merged = []
    for t in targets:
        cfg = dict(dify_cfg)
        cfg.update(t)
        merged.append(cfg)
    return merged


def _should_use_bulk_executor(body: ManualPushRequest) -> bool:
    if int(body.parallel_workers or 1) > 1:
        return True
    if int(body.empty_retry_max or 0) > 0:
        return True
    if body.dify_targets:
        return True
    return False


def _effective_parallel_workers(requested_workers: int) -> tuple[int, str]:
    workers = max(1, int(requested_workers or 1))
    db_type = str(get_app_db_type() or "").lower()
    if db_type == "sqlite":
        capped = min(workers, 4)
        if capped != workers:
            return capped, "sqlite mode: workers capped to 4 to reduce database lock contention"
    return workers, ""


@router.post("/manual", summary="Manual push")
def manual_push(body: ManualPushRequest, db: Session = Depends(get_db)):
    config = load_config()

    data_source = ConfigParser.get_data_source_type(config)
    db_cfg = (
        ConfigParser.parse_postgresql_config(config)
        if data_source == "postgresql"
        else ConfigParser.parse_oracle_config(config)
    )
    dify_cfg = ConfigParser.parse_dify_config(config)
    push_settings = ConfigParser.get_push_settings(config)
    field_mapping = ConfigParser.get_field_mapping(config, data_source)

    query_dates, query_date_label, dept_list, records, raw_rows, filtered_rows, grouped, dept_field = _prepare_push_data(
        body, config, data_source, db_cfg, field_mapping
    )
    diagnostics = _build_query_diagnostics(body, db_cfg, raw_rows, filtered_rows)
    use_bulk_executor = _should_use_bulk_executor(body)

    if not grouped:
        empty_result = {
            "date_dimension": body.date_dimension,
            "query_dates": query_dates,
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "raw_rows": raw_rows,
            "filtered_rows": filtered_rows,
            "grouped": 0,
            "used_bulk_executor": use_bulk_executor,
            "parallel_workers_effective": 0,
            "worker_note": "",
            "target_metrics": {},
            "empty_retry_total": 0,
            "results": [],
            "diagnostics": diagnostics,
        }
        if body.dry_run:
            empty_result.update(
                {
                    "dry_run": True,
                    "total_patients": 0,
                    "total_records": 0,
                    "preview": [],
                }
            )
        return empty_result

    if body.async_mode and not body.dry_run:
        task_id = str(uuid.uuid4())[:8]
        task_manager = get_task_manager()
        task_manager.create_task(task_id)
        thread_target = _async_push_bulk if use_bulk_executor else _async_push
        thread = threading.Thread(
            target=thread_target,
            args=(
                task_id,
                body.model_dump(),
                dept_list,
                data_source,
                db_cfg,
                dify_cfg,
                config,
                push_settings,
                field_mapping,
            ),
            daemon=True,
        )
        thread.start()
        return {"task_id": task_id, "message": "async task submitted"}

    if body.dry_run:
        name_field = field_mapping.get("patient_name", KEY_PATIENT_NAME)
        preview = []
        for pid, patient_records in grouped.items():
            payload = build_dify_payload(patient_records, field_mapping, query_date_label)
            preview.append(
                {
                    "patient_id": pid,
                    "patient_name": patient_records[0].get(name_field, ""),
                    "dept": patient_records[0].get(dept_field, ""),
                    "record_count": len(patient_records),
                    "mr_text_preview": build_mr_text_combined(patient_records, field_mapping)[:500] + "...",
                    "dify_payload": payload,
                }
            )
        return {
            "dry_run": True,
            "date_dimension": body.date_dimension,
            "query_dates": query_dates,
            "total_patients": len(grouped),
            "total_records": len(records),
            "raw_rows": raw_rows,
            "filtered_rows": filtered_rows,
            "diagnostics": diagnostics,
            "preview": preview,
        }

    push_config = PushConfig(
        trigger_type="manual",
        query_date=query_date_label,
        interval_ms=push_settings["interval_ms"],
        max_retry=push_settings["max_retry"],
        notify_enabled=True,
    )
    effective_workers = 1
    worker_note = ""
    target_metrics: dict = {}
    empty_retry_total = 0
    if use_bulk_executor:
        effective_workers, worker_note = _effective_parallel_workers(body.parallel_workers)
        executor = BulkPushExecutor(
            dify_config=dify_cfg,
            notify_config=config.get("notify", {}),
            field_mapping=field_mapping,
            dify_targets=_build_manual_dify_targets(body, dify_cfg),
            max_workers=effective_workers,
            empty_retry_max=body.empty_retry_max,
            empty_retry_backoff_ms=body.empty_retry_backoff_ms,
            target_strategy=body.target_strategy,
        )
        result = executor.execute(grouped, push_config)
        target_metrics = executor.get_target_metrics()
        empty_retry_total = sum(int((r.get("empty_retry_count") or 0)) for r in result.results)
    else:
        executor = PushExecutor(dify_cfg, config.get("notify", {}), field_mapping)
        result = executor.execute(db, grouped, push_config)
    _log_push_funnel("manual", query_date_label, raw_rows, filtered_rows, len(grouped), result)

    return {
        "date_dimension": body.date_dimension,
        "query_dates": query_dates,
        "total": result.total,
        "success": result.success,
        "failed": result.failed,
        "skipped": len([r for r in result.results if r.get("status") == "skipped"]),
        "raw_rows": raw_rows,
        "filtered_rows": filtered_rows,
        "grouped": len(grouped),
        "used_bulk_executor": use_bulk_executor,
        "parallel_workers_effective": effective_workers,
        "worker_note": worker_note,
        "target_metrics": target_metrics,
        "empty_retry_total": empty_retry_total,
        "diagnostics": diagnostics,
        "results": result.results,
    }


@router.post("/preview", summary="Manual dry-run preview")
def preview_push(body: ManualPushRequest, db: Session = Depends(get_db)):
    body.dry_run = True
    return manual_push(body, db)


@router.post("/retry", summary="Retry failed pushes")
def retry_push(body: RetryRequest, db: Session = Depends(get_db)):
    config = load_config()
    dify_cfg = ConfigParser.parse_dify_config(config)
    push_settings = ConfigParser.get_push_settings(config)
    data_source = ConfigParser.get_data_source_type(config)
    field_mapping = ConfigParser.get_field_mapping(config, data_source)
    executor = PushExecutor(dify_cfg, config.get("notify", {}), field_mapping)
    results = executor.execute_retry(db, body.log_ids, push_settings["max_retry"])
    return {"results": results}


@router.get("/status/{task_id}", response_model=PushProgress, summary="Get async task progress")
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
        cancelled=progress.cancelled,
    )


@router.post("/cancel/{task_id}", summary="Cancel running async task")
def cancel_push_task(task_id: str):
    task_manager = get_task_manager()
    progress = task_manager.get_task(task_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Task not found")
    if progress.status != "running":
        raise HTTPException(status_code=409, detail=f"Task is not running (status={progress.status})")
    ok = task_manager.cancel_task(task_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Failed to cancel task")
    return {"message": "cancel requested", "task_id": task_id}


def _async_push(task_id, body_data, dept_list, data_source, db_cfg, dify_cfg, config, push_settings, field_mapping):
    db = SessionLocal()
    task_manager = get_task_manager()
    try:
        body = ManualPushRequest(**body_data)
        query_dates, query_date_label, _, records, raw_rows, filtered_rows, grouped, _ = _prepare_push_data(
            body, config, data_source, db_cfg, field_mapping
        )
        task_manager.update_task(task_id, total=len(grouped))

        push_config = PushConfig(
            trigger_type="manual",
            query_date=query_date_label,
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
                        # 检查取消标志
                        if task_manager.is_cancelled(task_id):
                            logger.info("async push cancelled by user: task_id=%s processed=%s/%s", task_id, result.success + result.failed, result.total)
                            break
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
                        except Exception as exc:
                            logger.error("push single patient failed: patient_id=%s err=%s", patient_id, exc, exc_info=True)
                            result.failed += 1
                            task_manager.increment_processed(task_id, result_status="failed")
                            result.results.append({"patient_id": patient_id, "status": "error", "error": str(exc)})
                    db.commit()
                except Exception:
                    db.rollback()
                    raise
                result.duration_seconds = time.time() - start_time
                return result

        executor = CallbackPushExecutor(dify_cfg, config.get("notify", {}), field_mapping)
        result = executor.execute(db, grouped, push_config)
        _log_push_funnel("async", query_date_label, raw_rows, filtered_rows, len(grouped), result)
        # 若任务被取消，status 已由 cancel_task 设为 cancelled，不再覆盖
        if not task_manager.is_cancelled(task_id):
            task_manager.update_task(task_id, status="completed")
    except Exception as exc:
        logger.error("async push failed: %s", exc, exc_info=True)
        if not task_manager.is_cancelled(task_id):
            task_manager.update_task(task_id, status="failed")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _async_push_bulk(task_id, body_data, dept_list, data_source, db_cfg, dify_cfg, config, push_settings, field_mapping):
    task_manager = get_task_manager()
    final_status = "failed"
    try:
        body = ManualPushRequest(**body_data)
        _, query_date_label, _, records, raw_rows, filtered_rows, grouped, _ = _prepare_push_data(
            body, config, data_source, db_cfg, field_mapping
        )
        task_manager.update_task(task_id, total=len(grouped))
        push_config = PushConfig(
            trigger_type="manual",
            query_date=query_date_label,
            interval_ms=push_settings["interval_ms"],
            max_retry=push_settings["max_retry"],
            notify_enabled=True,
        )
        effective_workers, worker_note = _effective_parallel_workers(body.parallel_workers)
        if worker_note:
            logger.warning("[async bulk] %s task_id=%s requested=%s effective=%s", worker_note, task_id, body.parallel_workers, effective_workers)
        executor = BulkPushExecutor(
            dify_config=dify_cfg,
            notify_config=config.get("notify", {}),
            field_mapping=field_mapping,
            dify_targets=_build_manual_dify_targets(body, dify_cfg),
            max_workers=effective_workers,
            empty_retry_max=body.empty_retry_max,
            empty_retry_backoff_ms=body.empty_retry_backoff_ms,
            target_strategy=body.target_strategy,
        )
        result = executor.execute(
            grouped,
            push_config,
            on_item_done=lambda status: task_manager.increment_processed(
                task_id,
                result_status="success" if status == "success" else ("skipped" if status == "skipped" else "failed"),
            ),
            stop_check=lambda: task_manager.is_cancelled(task_id),
        )
        target_metrics = executor.get_target_metrics()
        empty_retry_total = sum(int((r.get("empty_retry_count") or 0)) for r in result.results)
        logger.info(
            "[async bulk] task_id=%s target_metrics=%s empty_retry_total=%s",
            task_id,
            target_metrics,
            empty_retry_total,
        )
        _log_push_funnel("async", query_date_label, raw_rows, filtered_rows, len(grouped), result)
        final_status = "completed"
    except Exception as exc:
        logger.error("async bulk push failed: %s", exc, exc_info=True)
        final_status = "failed"
    finally:
        try:
            # 若任务已被取消，status 已由 cancel_task 设为 cancelled，不再覆盖
            if not task_manager.is_cancelled(task_id):
                task_manager.update_task(task_id, status=final_status)
        except Exception as exc:
            logger.error("async bulk push: failed to update task status: %s", exc, exc_info=True)
