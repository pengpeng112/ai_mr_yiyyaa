"""
APScheduler 定时任务调度模块
支持 oracle/postgresql 双数据源
"""
import logging
import os
import socket
import time
import threading
import uuid
import copy
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import load_config
from app.oracle_client import fetch_records, group_by_patient
from app.postgresql_client import fetch_pg_records
from app.database import SessionLocal
from app.models import SchedulerHistory, SchedulerRunLock
from app.services.audit_type_registry import AuditTypeRegistry
from app.services.config_parser import ConfigParser
from app.services.data_source_loader import load_patient_bundles
from app.services.push_executor import PushExecutor, PushConfig
from app.services.bulk_push_executor import BulkPushExecutor
from app.services.retention_service import run_retention_cleanup

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_last_run_info: dict = {}
_scheduler_lock = threading.Lock()
_info_lock = threading.Lock()
_RUN_LOCK_NAME = "daily_push"


_PROGRESS_NURSING_DISCHARGE_SQL = """
WITH discharged_patients AS (
  SELECT
      a.患者ID,
      a.次数,
      a.住院号,
      a.患者姓名,
      a.性别,
      a.出生日期,
      a.入院日期,
      a.入院诊断,
      a.入院病情,
      a.护理级别 AS 医嘱护理级别,
      a.所在科室名称,
      a.管床医生,
      a.出院日期
  FROM jhemr.v_qybr a
  WHERE {dept_filter}
    AND a.出院日期 >= TO_DATE(:query_date, 'yyyy-mm-dd')
    AND a.出院日期 < TO_DATE(:query_date, 'yyyy-mm-dd') + 1
),
progress AS (
  SELECT
      p.*,
      b.病历标题时间 AS 病历文书_完成时间,
      b.病历名称 AS 病历文书_名称,
      b.病历创建人 AS 病历文书_签名医师,
      b.病历内容 AS 病历文书_内容
  FROM discharged_patients p
  JOIN jhemr.v_bcjl b
    ON b.患者ID = p.患者ID
   AND b.次数 = p.次数
  WHERE b.病历标题时间 >= p.入院日期
    AND b.病历标题时间 < p.出院日期 + 1
)
SELECT
    b.*,
    c.护理记录时间 AS 护理记录_创建时间,
    c.护理单类型 AS 护理记录_文书类型,
    c.病情观察及护理措施 AS 护理记录_内容,
    c.记录人 AS 护理记录_记录人,
    c.体温 AS 护理记录_体温,
    c.心率脉搏 AS 护理记录_心率脉搏,
    c.呼吸 AS 护理记录_呼吸,
    c.血压 AS 护理记录_血压,
    c.血氧饱和度 AS 护理记录_血氧饱和度,
    c.血糖 AS 护理记录_血糖,
    c.意识神志 AS 护理记录_意识神志,
    c.氧疗_鼻导管 AS 护理记录_氧疗_鼻导管,
    c.氧疗_面罩 AS 护理记录_氧疗_面罩,
    c.入量_名称 AS 护理记录_入量_名称,
    c.入量_途径 AS 护理记录_入量_途径,
    c.入量_量 AS 护理记录_入量_量,
    c.出量_名称 AS 护理记录_出量_名称,
    c.出量_量 AS 护理记录_出量_量,
    c.尿量 AS 护理记录_尿量,
    c.皮肤情况 AS 护理记录_皮肤情况,
    c.刀口情况 AS 护理记录_刀口情况,
    c.管道护理 AS 护理记录_管道护理,
    c.高危风险 AS 护理记录_高危风险,
    c.护士签名 AS 护理记录_护士签名
FROM progress b
LEFT JOIN ydhl.v_hljl c
  ON c.患者ID = b.患者ID || '_' || b.次数
 AND c.护理记录时间 >= TRUNC(b.病历文书_完成时间)
 AND c.护理记录时间 < TRUNC(b.病历文书_完成时间) + 1
ORDER BY b.患者ID, b.次数, b.病历文书_完成时间, c.护理记录时间
"""


def get_scheduler() -> BackgroundScheduler | None:
    with _scheduler_lock:
        return _scheduler


def get_last_run_info() -> dict:
    with _info_lock:
        return dict(_last_run_info)


def _make_lock_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}:{uuid.uuid4().hex[:8]}"


def get_scheduler_lock_info() -> dict:
    db = SessionLocal()
    try:
        lock = db.query(SchedulerRunLock).filter(SchedulerRunLock.lock_name == _RUN_LOCK_NAME).first()
        if not lock:
            return {"status": "idle", "owner_id": "", "acquired_at": None, "heartbeat_at": None}
        return {
            "status": lock.status,
            "owner_id": lock.owner_id or "",
            "acquired_at": lock.acquired_at.isoformat() if lock.acquired_at else None,
            "heartbeat_at": lock.heartbeat_at.isoformat() if lock.heartbeat_at else None,
        }
    finally:
        db.close()


def _acquire_scheduler_run_lock() -> tuple[bool, str, str]:
    owner_id = _make_lock_owner()
    db = SessionLocal()
    try:
        now = datetime.now()
        updated = db.query(SchedulerRunLock).filter(
            SchedulerRunLock.lock_name == _RUN_LOCK_NAME,
            SchedulerRunLock.status != "running",
        ).update(
            {
                "owner_id": owner_id,
                "status": "running",
                "acquired_at": now,
                "heartbeat_at": now,
                "released_at": None,
            },
            synchronize_session=False,
        )
        if updated:
            db.commit()
            return True, owner_id, "acquired"

        existing = db.query(SchedulerRunLock).filter(SchedulerRunLock.lock_name == _RUN_LOCK_NAME).first()
        if existing:
            db.rollback()
            return False, existing.owner_id or "", f"scheduler lock is running by {existing.owner_id or 'unknown'}"

        db.add(SchedulerRunLock(
            lock_name=_RUN_LOCK_NAME,
            owner_id=owner_id,
            status="running",
            acquired_at=now,
            heartbeat_at=now,
        ))
        try:
            db.commit()
            return True, owner_id, "acquired"
        except Exception:
            db.rollback()
            existing = db.query(SchedulerRunLock).filter(SchedulerRunLock.lock_name == _RUN_LOCK_NAME).first()
            if existing and existing.status == "running":
                return False, existing.owner_id or "", f"scheduler lock is running by {existing.owner_id or 'unknown'}"
            raise
    finally:
        db.close()


def _release_scheduler_run_lock(owner_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(SchedulerRunLock).filter(
            SchedulerRunLock.lock_name == _RUN_LOCK_NAME,
            SchedulerRunLock.owner_id == owner_id,
            SchedulerRunLock.status == "running",
        ).update(
            {
                "status": "idle",
                "released_at": datetime.now(),
                "heartbeat_at": datetime.now(),
            },
            synchronize_session=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.error("调度运行锁释放失败 owner_id=%s", owner_id, exc_info=True)
    finally:
        db.close()


def is_scheduler_env_enabled() -> bool:
    import os
    return os.getenv("ENABLE_SCHEDULER", "true").lower() == "true"


def validate_cron_expression(cron_expr: str) -> tuple[bool, str]:
    expr = str(cron_expr or "").strip()
    parts = expr.split()
    if len(parts) != 5:
        return False, "Cron表达式必须包含5个部分: 分 时 日 月 周"
    try:
        CronTrigger.from_crontab(expr, timezone="Asia/Shanghai")
    except Exception as e:
        return False, f"Cron表达式无效: {e}"
    return True, "ok"


def _resolve_audit_run_mode(sched_cfg: dict, default: str = "daily_increment") -> str:
    mode = str(sched_cfg.get("audit_run_mode") or default).strip()
    if mode not in ("daily_increment", "discharge_final"):
        return default
    return mode


def start_scheduler():
    global _scheduler
    with _scheduler_lock:
        if _scheduler and _scheduler.running:
            logger.info("调度器已在运行，跳过重复启动")
            return

        if not is_scheduler_env_enabled():
            logger.info("调度器已通过 ENABLE_SCHEDULER=false 禁用")
            return

        _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

        config = load_config()
        sched_daily = config.get("scheduler_daily", {}) or {}
        sched_discharge = config.get("scheduler_discharge", {}) or {}

        if sched_daily or sched_discharge:
            if sched_daily.get("enabled", False):
                daily_cron = sched_daily.get("cron", "0 10 * * *")
                daily_mode = _resolve_audit_run_mode(sched_daily)
                ok, msg = _add_cron_job_with_mode("daily_push", daily_cron, daily_mode)
                if not ok:
                    _record_scheduler_error(msg)
                    logger.error("每日增量调度初始化失败: %s", msg)
                else:
                    logger.info("每日增量调度已注册: cron=%s mode=%s", daily_cron, daily_mode)

            if sched_discharge.get("enabled", False):
                discharge_cron = sched_discharge.get("cron", "0 11 * * *")
                discharge_mode = _resolve_audit_run_mode(sched_discharge, "discharge_final")
                ok, msg = _add_cron_job_with_mode("discharge_push", discharge_cron, discharge_mode)
                if not ok:
                    _record_scheduler_error(msg)
                    logger.error("出院终末调度初始化失败: %s", msg)
                else:
                    logger.info("出院终末调度已注册: cron=%s mode=%s", discharge_cron, discharge_mode)
        else:
            sched_cfg = config.get("scheduler", {}) or {}
            if sched_cfg.get("enabled", False):
                legacy_mode = _resolve_audit_run_mode(sched_cfg)
                ok, msg = _add_cron_job_with_mode("daily_push", sched_cfg.get("cron", "0 6 * * *"), legacy_mode)
                if not ok:
                    _record_scheduler_error(msg)
                    logger.error("定时任务初始化失败: %s", msg)

        _add_retention_cleanup_job()

        _scheduler.start()
        logger.info("调度器已启动")


def _record_scheduler_error(msg: str) -> None:
    with _info_lock:
        new_info = dict(_last_run_info)
        new_info["last_error"] = msg
        globals()["_last_run_info"] = new_info


def _add_cron_job_with_mode(job_id: str, cron_expr: str, audit_run_mode: str):
    valid, message = validate_cron_expression(cron_expr)
    if not valid:
        return False, message
    try:
        from functools import partial
        trigger = CronTrigger.from_crontab(cron_expr, timezone="Asia/Shanghai")
        job_func = partial(_daily_push_job_v2, audit_run_mode_override=audit_run_mode)
        _scheduler.add_job(
            job_func,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        return True, "ok"
    except Exception as e:
        logger.error("添加定时任务失败 job_id=%s: %s", job_id, e, exc_info=True)
        return False, str(e)


def shutdown_scheduler():
    global _scheduler
    with _scheduler_lock:
        if _scheduler:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("调度器已关闭")


def update_scheduler(enabled: bool, cron: str, audit_run_mode: str = "daily_increment", job_id: str = "daily_push"):
    global _scheduler
    if not is_scheduler_env_enabled():
        return {
            "applied": False,
            "message": "ENABLE_SCHEDULER=false，当前进程未启用调度器，仅保存配置",
            "next_run": None,
        }

    with _scheduler_lock:
        if not _scheduler:
            return {
                "applied": False,
                "message": "调度器未启动，配置已保存待重启后生效",
                "next_run": None,
            }

        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)

        if enabled:
            ok, msg = _add_cron_job_with_mode(job_id, cron, audit_run_mode)
            if not ok:
                _record_scheduler_error(msg)
                return {"applied": False, "message": msg, "next_run": None}
            job = _scheduler.get_job(job_id)
            next_run = str(job.next_run_time) if job and job.next_run_time else None
            logger.info("定时任务已更新: job_id=%s cron=%s mode=%s next_run=%s", job_id, cron, audit_run_mode, next_run)
            return {"applied": True, "message": "ok", "next_run": next_run}
        logger.info("定时任务已禁用: job_id=%s", job_id)
        return {"applied": True, "message": "disabled", "next_run": None}


# Deprecated: 旧版单调度器包装，请使用 _add_cron_job_with_mode()
def _add_cron_job(cron_expr: str):
    return _add_cron_job_with_mode("daily_push", cron_expr, "daily_increment")


def _add_retention_cleanup_job():
    """注册数据留存清理定时任务"""
    try:
        config = load_config()
        retention_cfg = config.get("data_retention", {}) or {}
        if not retention_cfg.get("enabled", True):
            logger.info("数据留存清理已禁用，跳过注册")
            return

        cron_expr = retention_cfg.get("cleanup_cron", "0 2 * * 0")  # 默认每周日凌晨2点
        valid, message = validate_cron_expression(cron_expr)
        if not valid:
            logger.error("数据留存清理定时任务 Cron 表达式无效: %s", message)
            return

        trigger = CronTrigger.from_crontab(cron_expr, timezone="Asia/Shanghai")
        _scheduler.add_job(
            _retention_cleanup_job,
            trigger=trigger,
            id="retention_cleanup",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        logger.info("数据留存清理定时任务已注册: cron=%s", cron_expr)
    except Exception as e:
        logger.error("注册数据留存清理定时任务失败: %s", e, exc_info=True)


def _audit_type_for_run_mode(audit_type, audit_run_mode: str):
    if audit_run_mode != "discharge_final":
        return audit_type
    if getattr(audit_type, "code", "") != "progress_vs_nursing":
        logger.warning(
            "出院终末模式暂仅支持 progress_vs_nursing 取数覆盖，当前 audit_type=%s 将使用原始配置",
            getattr(audit_type, "code", ""),
        )
        return audit_type
    cloned = audit_type.model_copy(deep=True) if hasattr(audit_type, "model_copy") else copy.deepcopy(audit_type)
    primary = (cloned.sources or {}).get("primary")
    if primary is None:
        logger.warning("出院终末模式无法覆盖 SQL：audit_type=%s 缺少 primary source", getattr(audit_type, "code", ""))
        return audit_type
    primary.query_sql = _PROGRESS_NURSING_DISCHARGE_SQL
    return cloned


def _retention_cleanup_job():
    """数据留存清理任务入口"""
    logger.info("数据留存清理任务开始执行")
    db = SessionLocal()
    try:
        config = load_config()
        retention_cfg = config.get("data_retention", {}) or {}
        result = run_retention_cleanup(db, retention_cfg)
        logger.info("数据留存清理任务完成: %s", result)
    except Exception as e:
        logger.error("数据留存清理任务异常: %s", e, exc_info=True)
    finally:
        db.close()


def _run_daily_push_for_audit_type(
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
        audit_type = _audit_type_for_run_mode(audit_type, audit_run_mode)
        payload_cfg = audit_type.payload or {}
        builder = str(payload_cfg.get("builder") or "")
        is_legacy_pn = builder == "legacy_progress_nursing"
        use_multi_source = not is_legacy_pn or audit_run_mode == "discharge_final"

        if is_legacy_pn and not use_multi_source:
            records = fetch_pg_records(db_cfg, dept_list, query_date) if data_source == "postgresql" else fetch_records(db_cfg, dept_list, query_date)
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
            date_dimension = "discharge_date" if audit_run_mode == "discharge_final" else "query_date"
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


# Deprecated: 旧版单调度器每日推送任务，已被 scheduler_daily/discharge 双调度器替代。
# 新路径：_daily_push_job_v2() + _add_cron_job_with_mode()
def _daily_push_job(query_date_override: str = None, dept_override: list = None):
    global _last_run_info
    logger.info("定时推送任务开始执行")
    start_time = time.time()

    config = load_config()
    query_date = query_date_override or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    data_source = ConfigParser.get_data_source_type(config)
    db_cfg = ConfigParser.parse_postgresql_config(config) if data_source == "postgresql" else ConfigParser.parse_oracle_config(config)
    scheduler_cfg = config.get("scheduler", {}) or {}
    scheduler_dept_filter = scheduler_cfg.get("dept_filter")
    dept_list = dept_override if dept_override is not None else (scheduler_dept_filter if scheduler_dept_filter else ConfigParser.get_department_list(config))
    push_settings = ConfigParser.get_push_settings(config)
    field_mapping = ConfigParser.get_field_mapping(config, data_source)
    registry = AuditTypeRegistry(config)
    audit_types = registry.list_default_schedule()

    total = success = failed = 0
    runtime_error = ""
    run_status = "completed"
    history_persist_errors: list[str] = []

    try:
        for audit_type in audit_types:
            payload_cfg = audit_type.payload or {}
            if str(payload_cfg.get("builder") or "") == "legacy_progress_nursing":
                records = fetch_pg_records(db_cfg, dept_list, query_date) if data_source == "postgresql" else fetch_records(db_cfg, dept_list, query_date)
                raw_rows = len(records)
                dept_config = config.get("departments", {})
                dept_field = field_mapping.get("dept", "所在科室名称")
                records = ConfigParser.filter_departments(records, dept_config, dept_field)
                filtered_rows = len(records)
                grouped = group_by_patient(records, field_mapping)
                dify_cfg = ConfigParser.parse_dify_config(config)
                persisted = ConfigParser.parse_persisted_dify_targets(config)
                if persisted:
                    executor = BulkPushExecutor(
                        dify_config=dify_cfg,
                        notify_config=config.get("notify", {}),
                        field_mapping=field_mapping,
                        dify_targets=persisted,
                    )
                else:
                    executor = PushExecutor(dify_cfg, config.get("notify", {}), field_mapping)
            else:
                bundles = load_patient_bundles(
                    audit_type=audit_type,
                    root_config=config,
                    query_date=query_date,
                    date_dimension="query_date",
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

            total += len(grouped)
            push_config = PushConfig(
                trigger_type="auto",
                query_date=query_date,
                audit_type_code=audit_type.code,
                audit_type=audit_type,
                audit_run_mode="daily_increment",
                interval_ms=push_settings["interval_ms"],
                max_retry=push_settings["max_retry"],
                notify_enabled=True,
            )
            if isinstance(executor, BulkPushExecutor):
                result = executor.execute(grouped, push_config)
            else:
                result = executor.execute(db, grouped, push_config)
            success += result.success
            failed += result.failed
            skipped = len([item for item in result.results if str(item.get("status", "")) == "skipped"])
            skip_reason_counts = {}
            for item in result.results:
                if str(item.get("status", "")) == "skipped":
                    reason = str(item.get("skip_reason", "unknown") or "unknown")
                    skip_reason_counts[reason] = int(skip_reason_counts.get(reason, 0)) + 1
            logger.info(
                "[推送漏斗] trigger=auto audit_type=%s query_date=%s raw_rows=%s filtered_rows=%s grouped=%s success=%s failed=%s skipped=%s",
                audit_type.code,
                query_date,
                raw_rows,
                filtered_rows,
                len(grouped),
                result.success,
                result.failed,
                skipped,
            )
            if skip_reason_counts:
                logger.info(
                    "[推送漏斗] trigger=auto audit_type=%s query_date=%s skip_reason_counts=%s",
                    audit_type.code,
                    query_date,
                    skip_reason_counts,
                )

        new_info = {
            "run_time": datetime.now().isoformat(),
            "query_date": query_date,
            "total": total,
            "success": success,
            "failed": failed,
            "duration_seconds": int(time.time() - start_time),
            "data_source": data_source,
            "last_error": "",
        }
        with _info_lock:
            _last_run_info = new_info

    except Exception as e:
        logger.error(f"定时推送异常: {e}", exc_info=True)
        db.rollback()
        run_status = "failed"
        runtime_error = str(e)
        new_info = {
            "run_time": datetime.now().isoformat(),
            "query_date": query_date,
            "total": total,
            "success": success,
            "failed": failed,
            "duration_seconds": int(time.time() - start_time),
            "data_source": data_source,
            "last_error": str(e),
        }
        with _info_lock:
            _last_run_info = new_info
    finally:
        duration = int(time.time() - start_time)
        history = SchedulerHistory(
            run_time=datetime.now(),
            trigger_type="auto",
            query_date=query_date,
            total_records=total,
            success_count=success,
            failed_count=failed,
            duration_seconds=duration,
            status=run_status,
        )
        try:
            db.add(history)
            db.commit()
        except Exception as persist_error:
            db.rollback()
            logger.error("定时任务历史写入失败: %s", persist_error, exc_info=True)
            persist_msg = f"history_persist_failed: {persist_error}"
            if runtime_error:
                with _info_lock:
                    new_info = dict(_last_run_info)
                    new_info["last_error"] = f"{runtime_error} | {persist_msg}"
                    _last_run_info = new_info
            else:
                with _info_lock:
                    new_info = dict(_last_run_info)
                    new_info["last_error"] = persist_msg
                    _last_run_info = new_info
        db.close()


def _daily_push_job_v2(query_date_override: str = None, dept_override: list = None, audit_type_codes_override: list[str] | None = None, audit_run_mode_override: str = "daily_increment"):
    global _last_run_info
    acquired, owner_id, message = _acquire_scheduler_run_lock()
    if not acquired:
        logger.warning("定时推送任务(v2)跳过：%s", message)
        with _info_lock:
            new_info = dict(_last_run_info)
            new_info.update({
                "run_time": datetime.now().isoformat(),
                "last_error": message,
                "lock_owner": owner_id,
            })
            _last_run_info = new_info
        return
    try:
        _daily_push_job_v2_unlocked(
            query_date_override=query_date_override,
            dept_override=dept_override,
            audit_type_codes_override=audit_type_codes_override,
            audit_run_mode=audit_run_mode_override,
        )
    finally:
        _release_scheduler_run_lock(owner_id)


def _daily_push_job_v2_unlocked(query_date_override: str = None, dept_override: list = None, audit_type_codes_override: list[str] | None = None, audit_run_mode: str = "daily_increment"):
    global _last_run_info
    logger.info("定时推送任务(v2)开始执行 mode=%s", audit_run_mode)
    start_time = time.time()

    config = load_config()
    query_date = query_date_override or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    data_source = ConfigParser.get_data_source_type(config)
    db_cfg = ConfigParser.parse_postgresql_config(config) if data_source == "postgresql" else ConfigParser.parse_oracle_config(config)
    scheduler_cfg = _resolve_scheduler_cfg(config, audit_run_mode)
    scheduler_dept_filter = scheduler_cfg.get("dept_filter")
    dept_list = dept_override if dept_override is not None else (scheduler_dept_filter if scheduler_dept_filter else ConfigParser.get_department_list(config))
    push_settings = ConfigParser.get_push_settings(config)
    field_mapping = ConfigParser.get_field_mapping(config, data_source)
    registry = AuditTypeRegistry(config)
    configured_codes = audit_type_codes_override if audit_type_codes_override is not None else scheduler_cfg.get("audit_type_codes") or []
    if not isinstance(configured_codes, list):
        configured_codes = []
    configured_codes = [str(code or "").strip() for code in configured_codes if str(code or "").strip()]
    configured_codes = list(dict.fromkeys(configured_codes))

    if configured_codes:
        audit_types = []
        for code in configured_codes:
            try:
                audit_types.append(registry.get(code))
            except KeyError:
                logger.warning("定时任务配置的审计类型不存在，已忽略: %s", code)
        if not audit_types:
            if audit_run_mode == "discharge_final":
                logger.error("出院终末调度 audit_type_codes 全部无效，拒绝回退每日默认审计类型")
                duration = int(time.time() - start_time)
                error_msg = "discharge_final audit_type_codes invalid: " + ",".join(configured_codes)
                _write_scheduler_history_safe(
                    query_date=query_date,
                    audit_type_code="__scheduler__",
                    total_records=0,
                    success_count=0,
                    failed_count=0,
                    duration_seconds=duration,
                    status="failed",
                )
                with _info_lock:
                    _last_run_info = {
                        "run_time": datetime.now().isoformat(),
                        "query_date": query_date,
                        "audit_type_codes": [],
                        "audit_run_mode": audit_run_mode,
                        "dept_filter": dept_list,
                        "total": 0,
                        "success": 0,
                        "failed": 0,
                        "duration_seconds": duration,
                        "data_source": data_source,
                        "last_error": error_msg,
                    }
                return
            else:
                logger.warning("定时任务 audit_type_codes 全部无效，回退 default_for_schedule")
                audit_types = registry.list_default_schedule()
    else:
        audit_types = registry.list_default_schedule()

    resolved_audit_type_codes = [item.code for item in audit_types]

    total = 0
    success = 0
    failed = 0
    runtime_error = ""
    history_persist_errors: list[str] = []
    audit_type_errors: list[str] = []

    try:
        for audit_type in audit_types:
            try:
                summary = _run_daily_push_for_audit_type(
                    config=config,
                    data_source=data_source,
                    db_cfg=db_cfg,
                    audit_type=audit_type,
                    query_date=query_date,
                    dept_list=dept_list,
                    push_settings=push_settings,
                    field_mapping=field_mapping,
                    audit_run_mode=audit_run_mode,
                )
            except Exception as exc:
                message = f"{audit_type.code}: {exc}"
                audit_type_errors.append(message)
                logger.error("定时推送单个审计类型失败，继续执行后续类型: %s", message, exc_info=True)
                continue
            total += int(summary.get("total", 0))
            success += int(summary.get("success", 0))
            failed += int(summary.get("failed", 0))
            if summary.get("history_persist_error"):
                history_persist_errors.append(str(summary["history_persist_error"]))

        last_error = " | ".join([*audit_type_errors, *history_persist_errors])
        new_info = {
            "run_time": datetime.now().isoformat(),
            "query_date": query_date,
            "audit_type_codes": resolved_audit_type_codes,
            "audit_run_mode": audit_run_mode,
            "dept_filter": dept_list,
            "total": total,
            "success": success,
            "failed": failed,
            "duration_seconds": int(time.time() - start_time),
            "data_source": data_source,
            "last_error": last_error,
        }
        with _info_lock:
            _last_run_info = new_info
    except Exception as exc:
        logger.error("定时推送异常: %s", exc, exc_info=True)
        runtime_error = str(exc)
        last_error = runtime_error
        if history_persist_errors:
            last_error = f"{runtime_error} | {' | '.join(history_persist_errors)}"
        new_info = {
            "run_time": datetime.now().isoformat(),
            "query_date": query_date,
            "audit_type_codes": resolved_audit_type_codes,
            "audit_run_mode": audit_run_mode,
            "dept_filter": dept_list,
            "total": total,
            "success": success,
            "failed": failed,
            "duration_seconds": int(time.time() - start_time),
            "data_source": data_source,
            "last_error": last_error,
        }
        with _info_lock:
            _last_run_info = new_info
        raise


def _resolve_scheduler_cfg(config: dict, audit_run_mode: str) -> dict:
    if audit_run_mode == "discharge_final":
        discharge = config.get("scheduler_discharge") or {}
        if discharge:
            return discharge
        return {
            "enabled": False,
            "audit_run_mode": "discharge_final",
            "audit_type_codes": ["progress_vs_nursing"],
            "dept_filter": [],
            "cron": "0 11 * * *",
            "schedule_mode": "daily",
            "daily_time": "11:00",
        }
    daily = config.get("scheduler_daily") or {}
    if daily:
        return daily
    return config.get("scheduler", {}) or {}


def _write_scheduler_history_safe(
    query_date: str,
    audit_type_code: str,
    total_records: int,
    success_count: int,
    failed_count: int,
    duration_seconds: int,
    status: str,
) -> str:
    db = SessionLocal()
    try:
        history = SchedulerHistory(
            run_time=datetime.now(),
            trigger_type="auto",
            query_date=query_date,
            audit_type_code=audit_type_code,
            total_records=total_records,
            success_count=success_count,
            failed_count=failed_count,
            duration_seconds=duration_seconds,
            status=status,
        )
        db.add(history)
        db.commit()
        return ""
    except Exception as exc:
        db.rollback()
        msg = f"history_persist_failed: {exc}"
        logger.error("调度历史写入失败: %s", msg, exc_info=True)
        return msg
    finally:
        db.close()


def trigger_now(_query_date: str = None, _dept_override: list = None, audit_type_codes: list[str] | None = None, _audit_run_mode: str = "daily_increment") -> str:
    import threading
    import uuid

    task_id = str(uuid.uuid4())[:8]

    def _run():
        try:
            _daily_push_job_v2(
                query_date_override=_query_date,
                dept_override=_dept_override,
                audit_type_codes_override=audit_type_codes,
                audit_run_mode_override=_audit_run_mode,
            )
        except Exception as e:
            logger.error("手动触发推送线程发生未处理异常: %s", e, exc_info=True)
            with _info_lock:
                new_info = dict(_last_run_info)
                new_info["last_error"] = f"trigger_thread_crash: {e}"
                globals()["_last_run_info"] = new_info

    t = threading.Thread(target=_run, daemon=True, name=f"push-{task_id}")
    t.start()
    return task_id
