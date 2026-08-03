"""
调度单审计类型执行器 —— 从 scheduler.py 拆分，负责单个 audit_type 的数据加载、推送执行和结果统计。
"""
import copy
import logging
import time
from datetime import datetime

from app.database import SessionLocal, get_app_db_type
from app.models import SchedulerHistory
from app.oracle_client import fetch_records, group_by_patient
from app.postgresql_client import fetch_pg_records
from app.services.config_parser import ConfigParser
from app.services.data_source_loader import load_patient_bundles
from app.services.push_executor import PushExecutor, PushConfig
from app.services.bulk_push_executor import BulkPushExecutor
from app.services.push_parallelism import effective_parallel_workers
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


def _build_executor_from_pool(pool: dict, notify_config: dict, field_mapping: dict, parallel_workers: int):
    """按 resolve_dify_target_pool 结果构造 PushExecutor 或 BulkPushExecutor。"""
    base_config = pool.get("base_config") or {}
    if pool.get("pool_unavailable"):
        raise RuntimeError(pool.get("error_code") or "dify_target_pool_unavailable")
    targets = pool.get("targets") or []
    if targets:
        return BulkPushExecutor(
            dify_config=base_config,
            notify_config=notify_config,
            field_mapping=field_mapping,
            dify_targets=targets,
            max_workers=parallel_workers,
            target_strategy=str(pool.get("strategy") or pool.get("target_strategy") or "round_robin"),
            circuit_breaker_failures=int(pool.get("circuit_breaker_failures") or 3),
            circuit_breaker_seconds=int(pool.get("circuit_breaker_seconds") or 60),
        )
    return PushExecutor(base_config, notify_config, field_mapping)


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
    pending_error_code = ""
    history_persist_error = ""
    target_metrics = {}
    executor_mode = "serial"
    pool_summary = {}

    try:
        audit_type = audit_type_for_run_mode(audit_type, audit_run_mode)
        parallel_workers, _ = effective_parallel_workers(
            (push_settings or {}).get("parallel_workers", 4),
            get_app_db_type(),
        )
        payload_cfg = audit_type.payload or {}
        builder = str(payload_cfg.get("builder") or "")
        is_legacy_pn = builder == "legacy_progress_nursing"
        use_multi_source = not is_legacy_pn or audit_run_mode == "discharge_final"

        pool = ConfigParser.resolve_dify_target_pool(config, audit_type)
        pool_summary = {
            "strategy": pool.get("strategy"),
            "enabled_target_count": pool.get("enabled_target_count"),
            "configured_enabled_count": pool.get("configured_enabled_count"),
            "use_bulk": pool.get("use_bulk"),
            "pool_unavailable": pool.get("pool_unavailable"),
            "circuit_breaker_failures": pool.get("circuit_breaker_failures"),
            "circuit_breaker_seconds": pool.get("circuit_breaker_seconds"),
        }
        logger.info(
            "[audit.dify] scheduler_pool audit_type=%s mode=%s strategy=%s targets=%s configured=%s use_bulk=%s",
            getattr(audit_type, "code", ""),
            audit_run_mode,
            pool_summary.get("strategy"),
            pool_summary.get("enabled_target_count"),
            pool_summary.get("configured_enabled_count"),
            pool_summary.get("use_bulk"),
        )

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
            # legacy 路径：基配置使用全局 Dify（与历史行为一致：parse_dify_config(config)）
            # 但仍统一走 resolver 的 targets/策略；base 用全局而非 audit_type 覆盖端点时与旧逻辑对齐
            legacy_pool = ConfigParser.resolve_dify_target_pool(config, audit_type=None)
            # 若 audit_type 也带 extra_inputs.mr_type，仍通过 PushConfig.audit_type 注入
            if legacy_pool.get("pool_unavailable"):
                raise RuntimeError(legacy_pool.get("error_code") or "dify_target_pool_unavailable")
            executor = _build_executor_from_pool(
                legacy_pool,
                config.get("notify", {}),
                field_mapping,
                parallel_workers,
            )
            pool_summary = {
                "strategy": legacy_pool.get("strategy"),
                "enabled_target_count": legacy_pool.get("enabled_target_count"),
                "configured_enabled_count": legacy_pool.get("configured_enabled_count"),
                "use_bulk": legacy_pool.get("use_bulk"),
                "pool_unavailable": legacy_pool.get("pool_unavailable"),
                "circuit_breaker_failures": legacy_pool.get("circuit_breaker_failures"),
                "circuit_breaker_seconds": legacy_pool.get("circuit_breaker_seconds"),
            }
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
            executor = _build_executor_from_pool(
                pool,
                config.get("notify", {}),
                field_mapping,
                parallel_workers,
            )

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
            executor_mode = "bulk"
            result = executor.execute(grouped, push_config)
            try:
                target_metrics = executor.get_target_metrics()
            except Exception:
                target_metrics = {}
        else:
            executor_mode = "serial"
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
            "[推送漏斗] trigger=auto audit_type=%s audit_run_mode=%s query_date=%s raw_rows=%s filtered_rows=%s grouped=%s success=%s failed=%s skipped=%s executor=%s",
            audit_type.code,
            audit_run_mode,
            query_date,
            raw_rows,
            filtered_rows,
            len(grouped),
            success,
            failed,
            skipped,
            executor_mode,
        )
        if skip_reason_counts:
            logger.info(
                "[推送漏斗] trigger=auto audit_type=%s query_date=%s skip_reason_counts=%s",
                audit_type.code,
                query_date,
                skip_reason_counts,
            )
        if target_metrics:
            # 仅结构化脱敏指标：节点名 + 计数，不含 Key/URL
            logger.info(
                "[audit.dify] scheduler_target_metrics audit_type=%s mode=%s metrics=%s",
                audit_type.code,
                audit_run_mode,
                target_metrics,
            )
    except Exception as exc:
        db.rollback()
        status = "failed"
        pending_error = exc
        error_text = str(exc)
        if "dify_target_pool_unavailable" in error_text:
            pending_error_code = "dify_target_pool_unavailable"
            logger.error(
                "定时推送类型节点池不可用: audit_type=%s error_code=dify_target_pool_unavailable",
                getattr(audit_type, "code", ""),
            )
        else:
            # P011-8.1.2: 对 Oracle 异常归类为稳定错误码，便于按层级聚合
            try:
                from app.oracle_client import classify_oracle_error
                pending_error_code = classify_oracle_error(exc)
            except Exception:
                pending_error_code = ""
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
            audit_run_mode=audit_run_mode,
            error_code=pending_error_code,
            error_msg=str(pending_error or "")[:2000] if pending_error else "",
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
        "executor_mode": executor_mode,
        "target_metrics": target_metrics,
        "pool": pool_summary,
    }
