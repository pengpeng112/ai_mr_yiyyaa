"""
病历时效影子扫描任务（T4）。

- TimelinessScanner：定时只读扫描 → 写本地 tl_event 台账；SHADOW 模式同样
  写台账（影子模式的意义：只记账、不对 JHEMR 做任何写动作）；
- 扫描范围：在院患者 + 近 7 天出院患者 + 近 7 天手术（按患者批量读取，
  Reader 可注入假实现用于本地单测，不连生产）；
- 只处理 tl_rule.enabled=True 的规则；每次扫描写 tl_scan_run，状态变化写
  tl_event_history；单次扫描软超时上限 4 分钟，超时记失败不重试；
- 只读账号缺 SELECT 权限（TimelinessPermissionMissing）时在 tl_scan_run.
  error_text 记录缺权限表名并安全退出（D2：不得换账号）；
- register_timeliness_job()：供 app/scheduler.py 的 start_scheduler 追加调用，
  任务 ID/锁名固定 timeliness_scan；timeliness.enabled=false 时不注册；
  运行锁复用 app/services/scheduler_lock_service 现有加锁函数。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Sequence

from sqlalchemy.orm import Session

from app.config import load_config
from app.timeliness.config import TimelinessPermissionMissing
from app.timeliness.engine import evaluate
from app.timeliness.engine.triggers import (
    EXTERNAL_TRIGGER_SOURCES,
    EXTERNAL_TRIGGER_TYPES,
    SOURCE_STATUS_NOT_CONFIGURED,
)
from app.timeliness.models import TLEvent, TLEventHistory, TLRule, TLRuleVersion, TLScanRun
from app.timeliness.engine.state import COMPLETED_LATE, COMPLETED_ON_TIME

logger = logging.getLogger(__name__)

# 任务 ID 与 DB 运行锁名（主设计文档 §15 T4：固定名，禁止另起名字）。
SCAN_JOB_ID = "timeliness_scan"
SCAN_LOCK_NAME = "timeliness_scan"

# 单次扫描软超时上限（4 分钟）：规则间/取数间检查，超时记 FAILED 不重试。
SCAN_TIMEOUT_SECONDS = 240

# 扫描窗口（天）：近 7 天出院 / 近 7 天手术 / 会诊与审批日志取数窗。
DISCHARGE_WINDOW_DAYS = 7
OPERATION_WINDOW_DAYS = 7
CONSULT_WINDOW_DAYS = 7
APPROVAL_WINDOW_DAYS = 7

# 扫描批次状态取值（tl_scan_run.status，自由文本列）。
RUN_STATUS_RUNNING = "RUNNING"
RUN_STATUS_SUCCESS = "SUCCESS"
RUN_STATUS_SKIPPED = "SKIPPED"
RUN_STATUS_FAILED = "FAILED"

# 引擎侧"已完成"状态（对账与统计共用）。
ENGINE_COMPLETED_STATUSES = (COMPLETED_ON_TIME, COMPLETED_LATE)


class TimelinessScanTimeout(RuntimeError):
    """单次扫描超过软超时上限（4 分钟默认）。"""


class JhemrModuleReader:
    """生产 Reader：薄封装 jhemr_reader 模块函数（每次调用独立只读连接）。

    仅在 timeliness 配置齐全时可用；权限不足由底层抛 TimelinessPermissionMissing。
    """

    def list_inpatients(self) -> list[dict]:
        from app.timeliness import jhemr_reader

        return jhemr_reader.list_inpatients()

    def list_recent_discharges(self, days: int) -> list[dict]:
        from app.timeliness import jhemr_reader

        return jhemr_reader.list_recent_discharges(days)

    def list_files(self, patient_visits: Sequence[Sequence[Any]]) -> list[dict]:
        from app.timeliness import jhemr_reader

        return jhemr_reader.list_files(patient_visits)

    def list_operations(self, patient_visits: Sequence[Sequence[Any]]) -> list[dict]:
        from app.timeliness import jhemr_reader

        return jhemr_reader.list_operations(patient_visits)

    def list_consult_applies(self, since: Any) -> list[dict]:
        from app.timeliness import jhemr_reader

        return jhemr_reader.list_consult_applies(since)

    def list_limit_logs(self, since: Any) -> list[dict]:
        from app.timeliness import jhemr_reader

        return jhemr_reader.list_limit_logs(since)


def _default_acquire_lock() -> tuple[bool, str, str]:
    from app.services.scheduler_lock_service import acquire_scheduler_run_lock

    return acquire_scheduler_run_lock(SCAN_LOCK_NAME)


def _default_release_lock(owner_id: str) -> None:
    from app.services.scheduler_lock_service import release_scheduler_run_lock

    release_scheduler_run_lock(owner_id, SCAN_LOCK_NAME)


def _row_pair(row: dict) -> tuple[str, str] | None:
    pid = str(row.get("patient_id") or "").strip()
    vid = str(row.get("visit_id") or "").strip()
    return (pid, vid) if pid and vid else None


def _row_as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def fetch_scan_snapshot(
    reader: Any,
    *,
    now: datetime,
    discharge_window_days: int = DISCHARGE_WINDOW_DAYS,
    operation_window_days: int = OPERATION_WINDOW_DAYS,
    consult_window_days: int = CONSULT_WINDOW_DAYS,
    approval_window_days: int = APPROVAL_WINDOW_DAYS,
    check_timeout: Callable[[], None] | None = None,
) -> dict[str, list[dict]]:
    """按扫描范围取数：在院 + 近 N 天出院 + 近 N 天手术（含文书/会诊/审批）。

    供 TimelinessScanner 与 T5 dry-run 接口共用；reader 缺权限时抛
    TimelinessPermissionMissing，由调用方处置。
    ``check_timeout`` 为调用方注入的活时钟超时探针（2026-11-11 修订：每次取数
    之间调用一次；elapsed 必须按真实流逝时间判定，此前用 now-started 静态差值
    导致取数阶段超时永不触发）；None=不检查（dry-run 无 4 分钟上限要求）。
    """

    def tick() -> None:
        if check_timeout is not None:
            check_timeout()

    tick()
    inpatients = list(reader.list_inpatients() or [])
    discharges = list(reader.list_recent_discharges(discharge_window_days) or [])

    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in inpatients + discharges:
        pair = _row_pair(row)
        if pair and pair not in seen:
            seen.add(pair)
            pairs.append(pair)

    tick()
    files = list(reader.list_files(pairs) or [])
    tick()
    operations_all = list(reader.list_operations(pairs) or [])
    # 近 N 天手术窗口（按开始/结束时间任一落在窗内即纳入）。
    window_start = now - timedelta(days=operation_window_days)
    operations = []
    for row in operations_all:
        for field in ("operating_end_date", "operating_date"):
            stamp = _row_as_datetime(row.get(field))
            if stamp is not None and stamp >= window_start:
                operations.append(row)
                break

    tick()
    consult_since = now - timedelta(days=consult_window_days)
    consult_applies = list(reader.list_consult_applies(consult_since) or [])
    tick()
    approval_since = now - timedelta(days=approval_window_days)
    limit_logs = list(reader.list_limit_logs(approval_since) or [])

    return {
        "inpatients": inpatients,
        "discharges": discharges,
        "operations": operations,
        "consult_applies": consult_applies,
        "files": files,
        "approvals": limit_logs,
        "patients_scanned": len(seen),
    }


class TimelinessScanner:
    """影子扫描器：读 JHEMR 快照 → 引擎评估 → 写本地台账。

    依赖全部可注入（reader/锁函数/时钟/超时），便于本地假数据单测；
    生产入口为 _timeliness_scan_job / scripts/timeliness/run_shadow_scan_once.py。
    """

    def __init__(
        self,
        db: Session,
        reader: Any,
        *,
        now_fn: Callable[[], datetime] = datetime.now,
        timeout_seconds: int = SCAN_TIMEOUT_SECONDS,
        acquire_lock: Callable[[], tuple[bool, str, str]] | None = None,
        release_lock: Callable[[str], None] | None = None,
        discharge_window_days: int = DISCHARGE_WINDOW_DAYS,
        operation_window_days: int = OPERATION_WINDOW_DAYS,
        consult_window_days: int = CONSULT_WINDOW_DAYS,
        approval_window_days: int = APPROVAL_WINDOW_DAYS,
        non_workdays: Sequence[Any] | None = None,
    ):
        self.db = db
        self.reader = reader
        self.now_fn = now_fn
        self.timeout_seconds = int(timeout_seconds)
        self.acquire_lock = acquire_lock or _default_acquire_lock
        self.release_lock = release_lock or _default_release_lock
        self.discharge_window_days = discharge_window_days
        self.operation_window_days = operation_window_days
        self.consult_window_days = consult_window_days
        self.approval_window_days = approval_window_days
        self.non_workdays = list(non_workdays or [])
        self._started_at: datetime | None = None

    # ---- 基础工具 ----

    def _elapsed_seconds(self) -> float:
        return (self.now_fn() - self._started_at).total_seconds()

    def _check_timeout(self) -> None:
        if self._elapsed_seconds() > self.timeout_seconds:
            raise TimelinessScanTimeout(
                f"scan timeout after {int(self._elapsed_seconds())}s "
                f"(limit {self.timeout_seconds}s)"
            )

    # ---- 数据快照 ----

    def _fetch_snapshot(self, now: datetime) -> dict[str, list[dict]]:
        """按扫描范围取数：在院 + 近 N 天出院 + 近 N 天手术（含文书/会诊/审批）。"""
        return fetch_scan_snapshot(
            self.reader,
            now=now,
            discharge_window_days=self.discharge_window_days,
            operation_window_days=self.operation_window_days,
            consult_window_days=self.consult_window_days,
            approval_window_days=self.approval_window_days,
            check_timeout=self._check_timeout,   # 活时钟：取数阶段同样受 4 分钟上限约束
        )

    def _build_rule_data(self, snapshot: dict, rule: TLRule, version: TLRuleVersion) -> dict:
        """组装备评估规则的数据快照（含该规则既有事件，保终态与幂等）。"""
        existing = (
            self.db.query(TLEvent.event_uid, TLEvent.status)
            .filter(TLEvent.rule_code == rule.rule_code)
            .all()
        )
        return {
            "inpatients": snapshot["inpatients"],
            "discharges": snapshot["discharges"],
            "operations": snapshot["operations"],
            "consult_applies": snapshot["consult_applies"],
            "files": snapshot["files"],
            "approvals": snapshot["approvals"],
            "existing_events": [
                {"event_uid": uid, "status": status} for uid, status in existing
            ],
            # D9 非工作日口径未定：先由调用方传入空集合（全部视为工作日）。
            "non_workdays": list(self.non_workdays),
        }

    def _persist_results(
        self,
        results: list[Any],
        *,
        rule: TLRule,
        version: TLRuleVersion,
        run_id: int,
        now: datetime,
    ) -> tuple[int, int]:
        """把引擎结果落台账：新事件插入+建历史；既有事件刷新+状态变化记历史。"""
        existing = {
            event.event_uid: event
            for event in self.db.query(TLEvent)
            .filter(TLEvent.rule_code == rule.rule_code)
            .all()
        }
        created = updated = 0
        for result in results:
            event = existing.get(result.event_uid)
            source_ref = {"source_unique_id": result.source_unique_id}
            if event is None:
                event = TLEvent(
                    event_uid=result.event_uid,
                    rule_code=rule.rule_code,
                    rule_version_id=result.rule_version_id or version.id,
                    patient_id=result.patient_id,
                    visit_id=result.visit_id,
                    dept_code=result.dept_code,
                    responsible_doctor_id=result.responsible_doctor_id,
                    t0=result.t0,
                    deadline=result.deadline,
                    status=result.status,
                    matched_file_unique_id=result.matched_file_unique_id,
                    completed_at=result.completed_at,
                    overdue_minutes=result.overdue_minutes,
                    warn_sent_at=None,
                    last_scan_at=now,
                    created_at=now,
                    updated_at=now,
                    source_ref_json=json.dumps(source_ref, ensure_ascii=False),
                )
                self.db.add(event)
                self.db.flush()
                self.db.add(
                    TLEventHistory(
                        event_id=event.id,
                        from_status=None,
                        to_status=result.status,
                        scan_run_id=run_id,
                        reason="scan created",
                        created_at=now,
                    )
                )
                created += 1
            else:
                status_before = event.status
                event.rule_version_id = result.rule_version_id or version.id
                event.dept_code = result.dept_code or event.dept_code
                event.responsible_doctor_id = (
                    result.responsible_doctor_id or event.responsible_doctor_id
                )
                event.t0 = result.t0
                event.deadline = result.deadline
                event.status = result.status
                event.matched_file_unique_id = result.matched_file_unique_id
                event.completed_at = result.completed_at
                event.overdue_minutes = result.overdue_minutes
                event.last_scan_at = now
                event.updated_at = now
                if status_before != result.status:
                    self.db.add(
                        TLEventHistory(
                            event_id=event.id,
                            from_status=status_before,
                            to_status=result.status,
                            scan_run_id=run_id,
                            reason="scan updated",
                            created_at=now,
                        )
                    )
                updated += 1
        return created, updated

    # ---- 主流程 ----

    def dry_run(self) -> dict:
        """取数并按当前启用规则试算，不写任何台账（不建 tl_scan_run/tl_event）。

        供 scripts/timeliness/run_shadow_scan_once.py --dry-run 与运维预检使用：
        只返回将命中/维持的事件统计与状态直方图，绝不写库、不加锁。
        """
        self._started_at = self.now_fn()
        now = self._started_at
        snapshot = self._fetch_snapshot(now)
        rules = (
            self.db.query(TLRule)
            .filter(TLRule.enabled.is_(True))
            .order_by(TLRule.rule_code)
            .all()
        )
        per_rule: dict[str, dict] = {}
        for rule in rules:
            version = (
                self.db.query(TLRuleVersion)
                .filter(TLRuleVersion.id == rule.current_version_id)
                .first()
                if rule.current_version_id
                else None
            )
            if version is None:
                continue
            data = self._build_rule_data(snapshot, rule, version)
            results = evaluate(version, now=now, data=data, rule_code=rule.rule_code)
            histogram: dict[str, int] = {}
            would_create = would_update = 0
            existing_status = {row["event_uid"]: row["status"] for row in data["existing_events"]}
            for result in results:
                histogram[result.status] = histogram.get(result.status, 0) + 1
                if result.event_uid in existing_status:
                    would_update += 1
                else:
                    would_create += 1
            per_rule[rule.rule_code] = {
                "version_no": version.version_no,
                "trigger_type": version.trigger_type,
                "events": len(results),
                "would_create": would_create,
                "would_update": would_update,
                "status_histogram": histogram,
            }
        return {
            "dry_run": True,
            "now": now.isoformat(timespec="seconds"),
            "patients_scanned": snapshot["patients_scanned"],
            "rules_evaluated": len(per_rule),
            "per_rule": per_rule,
        }


    def run_scan(self) -> dict:
        """执行一次影子扫描并返回摘要；任何失败都落 tl_scan_run 后安全返回。"""
        self._started_at = self.now_fn()
        now = self._started_at
        run = TLScanRun(started_at=now, status=RUN_STATUS_RUNNING, patients_scanned=0,
                        events_created=0, events_updated=0)
        self.db.add(run)
        self.db.commit()

        acquired = False
        owner_id = ""
        try:
            acquired, owner_id, reason = self.acquire_lock()
            if not acquired:
                run.status = RUN_STATUS_SKIPPED
                run.error_text = f"scheduler lock not acquired: {reason}"
                run.finished_at = self.now_fn()
                self.db.commit()
                logger.warning("时效影子扫描跳过（锁被占用）: %s", reason)
                return self._summary(run, skipped=True, reason=reason)

            snapshot = self._fetch_snapshot(now)
            run.patients_scanned = int(snapshot["patients_scanned"])

            rules = (
                self.db.query(TLRule)
                .filter(TLRule.enabled.is_(True))
                .order_by(TLRule.rule_code)
                .all()
            )
            not_configured: list[str] = []
            total_created = total_updated = 0
            for rule in rules:
                self._check_timeout()
                version = (
                    self.db.query(TLRuleVersion)
                    .filter(TLRuleVersion.id == rule.current_version_id)
                    .first()
                    if rule.current_version_id
                    else None
                )
                if version is None:
                    logger.warning("规则 %s 缺当前版本，跳过", rule.rule_code)
                    continue
                if version.trigger_type in EXTERNAL_TRIGGER_TYPES:
                    source = EXTERNAL_TRIGGER_SOURCES.get(version.trigger_type)
                    if source is None or source.status == SOURCE_STATUS_NOT_CONFIGURED:
                        not_configured.append(rule.rule_code)
                        logger.warning(
                            "规则 %s 触发源 %s 未配置（NOT_CONFIGURED），本轮跳过",
                            rule.rule_code, version.trigger_type,
                        )
                        continue
                data = self._build_rule_data(snapshot, rule, version)
                results = evaluate(version, now=now, data=data, rule_code=rule.rule_code)
                created, updated = self._persist_results(
                    results, rule=rule, version=version, run_id=run.id, now=now
                )
                total_created += created
                total_updated += updated
                run.events_created = total_created
                run.events_updated = total_updated
                self.db.commit()

            run.status = RUN_STATUS_SUCCESS
            run.finished_at = self.now_fn()
            if not_configured:
                run.error_text = "not_configured sources skipped: " + ", ".join(not_configured)
            self.db.commit()
            return self._summary(run, not_configured=not_configured)
        except TimelinessPermissionMissing as exc:
            self.db.rollback()
            run.status = RUN_STATUS_FAILED
            run.error_text = (
                f"permission missing on table {exc.table_name}: "
                "aizk_user lacks SELECT (D2: do not switch account; see §18.2 grants)"
            )
            run.finished_at = self.now_fn()
            self.db.commit()
            logger.error("时效影子扫描因缺权限终止: %s", exc)
            return self._summary(run, failed=True, reason=exc.table_name)
        except TimelinessScanTimeout as exc:
            self.db.rollback()
            run.status = RUN_STATUS_FAILED
            run.error_text = f"{exc}; partial results committed, no retry this run"
            run.finished_at = self.now_fn()
            self.db.commit()
            logger.error("时效影子扫描超时终止: %s", exc)
            return self._summary(run, failed=True, reason=str(exc))
        except Exception as exc:
            self.db.rollback()
            run.status = RUN_STATUS_FAILED
            run.error_text = f"scan failed: {type(exc).__name__}: {exc}"
            run.finished_at = self.now_fn()
            self.db.commit()
            logger.exception("时效影子扫描异常终止")
            return self._summary(run, failed=True, reason=str(exc))
        finally:
            if acquired:
                try:
                    self.release_lock(owner_id)
                except Exception:
                    logger.exception("释放时效扫描运行锁失败 owner=%s", owner_id)

    @staticmethod
    def _summary(run: TLScanRun, *, skipped: bool = False, failed: bool = False,
                 reason: str = "", not_configured: Sequence[str] = ()) -> dict:
        return {
            "scan_run_id": run.id,
            "status": run.status,
            "patients_scanned": run.patients_scanned or 0,
            "events_created": run.events_created or 0,
            "events_updated": run.events_updated or 0,
            "error_text": run.error_text or "",
            "skipped": skipped,
            "failed": failed,
            "reason": reason,
            "not_configured": list(not_configured),
        }


# ---- 调度注册与任务入口（app/scheduler.py 只追加一次调用） ----


def _timeliness_scan_job():
    """APScheduler 任务入口：独立会话执行一次影子扫描，结束即关闭会话。"""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        scanner = TimelinessScanner(db, JhemrModuleReader())
        summary = scanner.run_scan()
        logger.info("时效影子扫描完成: %s", summary)
    except Exception:
        db.rollback()
        logger.exception("时效影子扫描任务异常")
    finally:
        db.close()


def register_timeliness_job(scheduler: Any, *, config: dict | None = None) -> bool:
    """把 timeliness_scan 任务注册进调度器；timeliness.enabled=false 时不注册。

    返回 True=已注册；False=未注册（未启用/配置非法/注册失败，均记日志）。
    """
    cfg = config if config is not None else load_config()
    section = (cfg or {}).get("timeliness") or {}
    if not isinstance(section, dict) or not section.get("enabled"):
        logger.info("timeliness.enabled=false，不注册时效影子扫描任务")
        return False
    try:
        raw_interval = section.get("scan_interval_minutes")
        interval_minutes = int(5 if raw_interval in (None, "") else raw_interval)
    except (TypeError, ValueError):
        logger.error("timeliness.scan_interval_minutes 非法: %r，不注册时效扫描任务",
                     section.get("scan_interval_minutes"))
        return False
    if interval_minutes < 1:
        logger.error("timeliness.scan_interval_minutes 须 >=1 分钟: %s，不注册", interval_minutes)
        return False
    try:
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler.add_job(
            _timeliness_scan_job,
            trigger=IntervalTrigger(minutes=interval_minutes, timezone="Asia/Shanghai"),
            id=SCAN_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
        logger.info("时效影子扫描任务已注册: job_id=%s interval=%smin lock=%s",
                    SCAN_JOB_ID, interval_minutes, SCAN_LOCK_NAME)
        return True
    except Exception:
        logger.exception("时效影子扫描任务注册失败 job_id=%s", SCAN_JOB_ID)
        return False
