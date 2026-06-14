"""
调度单审计类型执行器 —— 从 scheduler.py 拆分，负责单个 audit_type 的数据加载、推送执行和结果统计。
"""
import copy
import logging
import time
from datetime import datetime

from app.database import SessionLocal
from app.models import SchedulerHistory
from app.oracle_client import fetch_records, group_by_patient
from app.postgresql_client import fetch_pg_records
from app.services.config_parser import ConfigParser
from app.services.data_source_loader import load_patient_bundles
from app.services.push_executor import PushExecutor, PushConfig
from app.services.bulk_push_executor import BulkPushExecutor
from app.services.scheduler_run_modes import audit_type_for_run_mode

logger = logging.getLogger(__name__)

_INPATIENT_FILTER = "\n    AND a.出院日期 IS NULL"


def _inject_inpatient_filter(query_sql: str) -> str:
    """在 SQL 的 {dept_filter} 后注入在院患者过滤条件。"""
    if not query_sql:
        return query_sql
    if "{dept_filter}" in query_sql:
        return query_sql.replace("{dept_filter}", "{dept_filter}" + _INPATIENT_FILTER)
    logger.warning("在院模式注入失败：query_sql 中未找到 {dept_filter}，保持原 SQL")
    return query_sql


def run_daily_push_for_audit_type(
    config: dict,
    data_source: str,
    db_cfg: dict,
    audit_type,
    query_date: str,
    dept_list: list,
    push_settings: dict,
    field_mapping: dict,
    audit_run_mode: str = "daily_increment",
) -> dict:
    start_time = time.time()
    db = SessionLocal()
    grouped = {}
    success = 0
    failed = 0
    skipped = 0
    status = "completed"
    raw_rows = 0
    filtered_rows = 0
    pending_error = None
    history_persist_error = ""

    try:
        audit_type = audit_type_for_run_mode(audit_type, audit_run_mode)
        payload_cfg = audit_type.payload or {}
        builder = str(payload_cfg.get("builder") or "")
        is_legacy_pn = builder == "legacy_progress_nursing"
        use_multi_source = not is_legacy_pn or audit_run_mode == "discharge_final"

        if is_legacy_pn and not use_multi_source:
            effective_db_cfg = db_cfg
            if audit_run_mode == "daily_increment":
                effective_db_cfg = copy.deepcopy(db_cfg)
                effective_db_cfg["query_sql"] = _inject_inpatient_filter(effective_db_cfg.get("query_sql", ""))
            records = fetch_pg_records(effective_db_cfg, dept_list, query_date) if data_source == "postgresql" else fetch_records(effective_db_cfg, dept_list, query_date)
            raw_rows = len(records)
            dept_config = config.get("departments", {})
            dept_field = field_mapping.get("dept", "所在科室名称")
            records = ConfigParser.filter_departments(records, dept_config, dept_field)
            filtered_rows = len(records)
            grouped = group_by_patient(records, field_mapping)
            dify_legacy = ConfigParser.parse_dify_config(config)
            persisted = ConfigParser.parse_persisted_dify_targets(config)
            if persisted:
                executor = BulkPushExecutor(
                    dify_config=dify_legacy,
                    notify_config=config.get("notify", {}),
                    field_mapping=field_mapping,
                    dify_targets=persisted,
                )
            else:
                executor = PushExecutor(dify_legacy, config.get("notify", {}), field_mapping)
        else:
            if audit_run_mode == "discharge_final":
                date_dimension = "discharge_date"
            elif audit_run_mode == "daily_increment":
                date_dimension = "inpatient_date"
            else:
                date_dimension = "query_date"
            bundles = load_patient_bundles(
                audit_type=audit_type,
                root_config=config,
                query_date=query_date,
                date_dimension=date_dimension,
                dept_filter=dept_list,
            )
            raw_rows = len(bundles)
            filtered_rows = len(bundles)
            grouped = {bundle.bundle_id: bundle for bundle in bundles}
            override_dify = audit_type.dify.model_dump()
            if override_dify.get("api_key_enc") and not override_dify.get("api_key"):
                override_dify["api_key"] = ConfigParser.parse_dify_config({"dify": override_dify}).get("api_key", "")

            persisted = ConfigParser.parse_persisted_dify_targets(config)
            if persisted:
                executor = BulkPushExecutor(
                    dify_config=override_dify,
                    notify_config=config.get("notify", {}),
                    field_mapping=field_mapping,
                    dify_targets=persisted,
                )
            else:
                executor = PushExecutor(override_dify, config.get("notify", {}), field_mapping)

        push_config = PushConfig(
            trigger_type="auto",
            query_date=query_date,
            audit_type_code=audit_type.code,
            audit_type=audit_type,
            audit_run_mode=audit_run_mode,
            interval_ms=push_settings["interval_ms"],
            max_retry=push_settings["max_retry"],
            notify_enabled=True,
        )
        if isinstance(executor, BulkPushExecutor):
            result = executor.execute(grouped, push_config)
        else:
            result = executor.execute(db, grouped, push_config)
        success = int(result.success)
        failed = int(result.failed)
        skipped = int(getattr(result, "skipped", 0) or len([item for item in result.results if str(item.get("status", "")) == "skipped"]))

        skip_reason_counts = {}
        for item in result.results:
            if str(item.get("status", "")) == "skipped":
                reason = str(item.get("skip_reason", "unknown") or "unknown")
                skip_reason_counts[reason] = int(skip_reason_counts.get(reason, 0)) + 1
        logger.info(
            "[推送漏斗] trigger=auto audit_type=%s audit_run_mode=%s query_date=%s raw_rows=%s filtered_rows=%s grouped=%s success=%s failed=%s skipped=%s",
            audit_type.code,
            audit_run_mode,
            query_date,
            raw_rows,
            filtered_rows,
            len(grouped),
            success,
            failed,
            skipped,
        )
        if skip_reason_counts:
            logger.info(
                "[推送漏斗] trigger=auto audit_type=%s query_date=%s skip_reason_counts=%s",
                audit_type.code,
                query_date,
                skip_reason_counts,
            )
    except Exception as exc:
        db.rollback()
        status = "failed"
        pending_error = exc
        logger.error("定时推送类型执行异常: audit_type=%s err=%s", getattr(audit_type, "code", ""), exc, exc_info=True)
    finally:
        duration = int(time.time() - start_time)
        history = SchedulerHistory(
            run_time=datetime.now(),
            trigger_type="auto",
            query_date=query_date,
            audit_type_code=audit_type.code,
            total_records=len(grouped),
            success_count=success,
            failed_count=failed,
            duration_seconds=duration,
            status=status,
        )
        try:
            db.add(history)
            db.commit()
        except Exception as persist_error:
            db.rollback()
            history_persist_error = f"history_persist_failed: {persist_error}"
            logger.error("定时任务历史写入失败: audit_type=%s err=%s", audit_type.code, persist_error, exc_info=True)
        db.close()

    if pending_error:
        raise pending_error
    return {
        "total": len(grouped),
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "history_persist_error": history_persist_error,
    }
