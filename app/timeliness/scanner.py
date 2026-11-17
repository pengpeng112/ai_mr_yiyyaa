"""
病历时效影子扫描任务（T4；2026-11-13 返工补齐闭环接线）。

- TimelinessScanner：定时只读扫描 → 写本地 tl_event 台账；SHADOW 模式同样
  写台账（影子模式的意义：只记账、不对 JHEMR 做任何写动作）；
- 扫描范围：在院患者 + 近 7 天出院患者 + 近 7 天手术（按患者批量读取，
  Reader 可注入假实现用于本地单测，不连生产）；
- 2026-11-13 返工（快照组装）：
  * ``snapshot["deaths"]``＝从在院+出院行提取的死亡患者（death_date_time 非空或
    discharge_disposition in ('死亡','5')——活库实证死亡患者 death_date_time 100%
    为 NULL，判定须看离院方式），供 DEATH 族规则触发；
  * 手术行注入患者住院临床科室 dept_code / doctor_in_charge_id（肝胆外科等临床
    科室才是试点 dept_scope 与科室可见性的归属科室，operation_dept_code 常为
    手术室编码仅作兜底）；``snapshot["patient_context"]`` 保留 (patient_id,
    visit_id) → 临床上下文映射供后续钩子复用；
- 2026-11-13 返工（闭环接线，run_scan 非 dry_run 生效）：
  * 自动调用 approval_sync.sync_approvals（数据=快照 approvals，结果计入摘要
    approvals_inserted / approvals_updated）；
  * WARN_ONLY / LOCK_EMR 规则的 WARNING / OVERDUE 事件经 TimelinessNotifier
    留痕提醒（D6 闸门默认 LOG_ONLY，零真实外发），成功后回填 warn_sent_at；
  * LOCK_EMR 规则（监控码非空且非 NATIVE_GENERATED_CODES）的 OVERDUE 事件经
    JhemrWriter.insert_monitor_row 外插监控行（闸门 0/1/2 多重保护；同 event_id
    已有任何 JHEMR_INSERT_MONITOR 留痕则跳过，避免每 5 分钟刷屏 BLOCKED 日志）；
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
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy.orm import Session

from app.config import load_config
from app.timeliness.approval_sync import sync_approvals
from app.timeliness.config import TimelinessPermissionMissing
from app.timeliness.engine import evaluate
from app.timeliness.engine.state import COMPLETED_LATE, COMPLETED_ON_TIME
from app.timeliness.engine.triggers import (
    EXTERNAL_TRIGGER_SOURCES,
    EXTERNAL_TRIGGER_TYPES,
    SOURCE_STATUS_NOT_CONFIGURED,
    SOURCE_STATUS_READY,
    is_death_row,
)
from app.timeliness.jhemr_writer import (
    ACTION_TYPE_INSERT_MONITOR,
    NATIVE_GENERATED_CODES,
    JhemrWriter,
)
from app.timeliness.models import (
    TLActionLog,
    TLEvent,
    TLEventHistory,
    TLRule,
    TLRuleVersion,
    TLScanRun,
)
from app.timeliness.notifier import TimelinessNotifier

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
# 2026-11-14 七规则轮：抢救医嘱回看窗口（RESCUE_REC 6h 时限，7 天覆盖足够）；
# SM 排台前看窗口（当日及未来排台，含次日）；节假日表计算视野。
RESCUE_WINDOW_DAYS = 7
SM_SCHEDULED_FORWARD_DAYS = 2
HOLIDAY_HORIZON_DAYS = 45
DEATH_ORDER_WINDOW_DAYS = 30
HOLIDAY_GRANT_HINT = (
    "补授权语句：GRANT SELECT ON jhemr.jhmr_mrreceivesignholiday TO aizk_user;"
)


class HisOracleReaderAdapter:
    """HIS/手麻 Oracle 源适配器（2026-11-14 七规则轮）。

    每个方法独立降级：单源失败（权限/连接）记日志返回空/None，不中断 JHEMR
    主扫描（任务书 §1.1 降级要求）。仅应用 Oracle 数据源可用（data_source.type
    =oracle 且连接可建立）；否则整适配器 None（调用方按无 HIS 处理）。
    """

    def __init__(self):
        from app.timeliness import his_oracle_reader

        self._mod = his_oracle_reader
        self._sm_columns: set[str] | None = None

    # -- 探针 --

    def probe(self) -> dict[str, bool | str]:
        return self._mod.probe_oracle_tables()

    # -- 死亡/料理医嘱 --

    def list_death_orders(self, since: datetime, until: datetime) -> dict[tuple[str, str], dict]:
        try:
            return self._mod.list_death_orders(since, until)
        except Exception:
            logger.exception("HIS 死亡/料理医嘱取数失败（本轮降级为空）")
            return {}

    # -- 手术（HIS 主表 + SM 排台） --

    def list_his_operations(self, since: datetime, until: datetime) -> list[dict]:
        if self._sm_columns is None:
            # 列探测失败（无权限/表缺失）时置空集：list_his_operations 内部会
            # 跳过排台源并记日志，主表数据不受影响。
            self._sm_columns = self._mod.probe_sm_columns()
        try:
            return self._mod.list_his_operations(
                since, until, sm_columns=self._sm_columns
            )
        except Exception:
            logger.exception("HIS 手术主表取数失败（回退 jhemr.operation）")
            return []

    # -- 职称字典（TTL 缓存在 his_oracle_reader 模块内） --

    def get_staff_title_map(self) -> dict[str, str] | None:
        try:
            return self._mod.get_staff_title_map()
        except Exception:
            logger.exception("HIS.STAFF_DICT 职称字典取数失败（审签职称校验降级为标题兜底）")
            return None


def build_default_his_reader() -> HisOracleReaderAdapter | None:
    """构造 HIS 适配器：应用数据源非 Oracle 或探针全失败时返回 None。

    构造本身轻量（不连库）；首次实际取数失败由各方法独立降级。
    """
    try:
        from app.config import load_config

        cfg = load_config()
        if ((cfg.get("data_source") or {}).get("type") or "oracle") != "oracle":
            logger.info("应用数据源非 Oracle，HIS 医嘱/手术/职称源不启用")
            return None
        return HisOracleReaderAdapter()
    except Exception:
        logger.exception("HIS 适配器构造失败（本轮不启用 HIS 源）")
        return None


def register_his_sources_if_available(his_reader: HisOracleReaderAdapter | None) -> bool:
    """HIS 可用时把抢救医嘱源登记为 RESCUE_ORDER 触发源（RESCUE_REC 规则生效前提）。

    返回 True=已登记。全局登记幂等（覆盖 NotConfiguredSource 缺省）。
    """
    if his_reader is None:
        return False
    try:
        his_reader._mod.register_his_rescue_source()
        return True
    except Exception:
        logger.exception("HIS 抢救源登记失败（RESCUE_ORDER 规则保持 NOT_CONFIGURED）")
        return False

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

    def list_holidays(self) -> list[dict]:
        from app.timeliness import jhemr_reader

        return jhemr_reader.list_holidays()


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


def _build_patient_context(
    inpatients: list[dict], discharges: list[dict]
) -> dict[tuple[str, str], dict]:
    """(patient_id, visit_id) → 患者住院临床上下文（科室/责任医生工号/姓名透传）。

    在院行优先（dept_code=当前科室），出院行仅补缺（dept_discharge_from）；
    ``patient_name`` 为可选透传键（reader 补齐经核实的姓名列后自动生效）。
    """
    ctx: dict[tuple[str, str], dict] = {}
    for row in inpatients + discharges:
        pair = _row_pair(row)
        if pair is None:
            continue
        entry = ctx.setdefault(pair, {})
        dept = str(row.get("dept_code") or "").strip() or str(row.get("dept_discharge_from") or "").strip()
        if dept and not entry.get("dept_code"):
            entry["dept_code"] = dept
        doctor = str(row.get("doctor_in_charge_id") or "").strip()
        if doctor and not entry.get("doctor_in_charge_id"):
            entry["doctor_in_charge_id"] = doctor
        patient_name = str(row.get("patient_name") or "").strip()
        if patient_name and not entry.get("patient_name"):
            entry["patient_name"] = patient_name
    return ctx


def _compute_non_workdays(reader: Any, now: datetime) -> set:
    """计算非工作日集合（horizon=now±45 天）。

    - 优先读 jhemr.jhmr_mrreceivesignholiday（与 JHEMR 客户端 IsTimeOut 同源）：
      周末 ∪ type=0 休息日 − type=1 调休上班日；
    - aizk_user 缺该表权限（42501）或 reader 无该能力时回退周一~周五逻辑，
      并记录补授权提示（HOLIDAY_GRANT_HINT），不中断扫描。
    """
    from datetime import date

    horizon = {
        (now + timedelta(days=offset)).date()
        for offset in range(-HOLIDAY_HORIZON_DAYS, HOLIDAY_HORIZON_DAYS + 1)
    }
    non_workdays = {d for d in horizon if d.weekday() >= 5}
    try:
        holidays = list(reader.list_holidays() or [])
    except TimelinessPermissionMissing as exc:
        logger.warning(
            "节假日表 %s 缺只读权限，工作日规则回退周一~周五（%s）",
            getattr(exc, "table_name", "jhemr.jhmr_mrreceivesignholiday"), HOLIDAY_GRANT_HINT,
        )
        return non_workdays
    except AttributeError:
        return non_workdays  # 假 Reader（fixture）无该能力：默认周末口径
    except Exception:
        logger.exception("节假日表读取异常，工作日规则回退周一~周五")
        return non_workdays

    for row in holidays:
        try:
            day = row.get("holidaydate")
            the_date = day if isinstance(day, date) else (
                datetime.fromisoformat(str(day)).date() if day not in (None, "") else None
            )
        except (ValueError, TypeError):
            continue
        if the_date is None or the_date not in horizon:
            continue
        raw_type = str(row.get("type") if row.get("type") is not None else "").strip()
        if raw_type == "0":
            non_workdays.add(the_date)      # 休息日/节假日（含工作日补休）
        elif raw_type == "1":
            non_workdays.discard(the_date)  # 调休上班日（周末上班）
    return non_workdays


def fetch_scan_snapshot(
    reader: Any,
    *,
    now: datetime,
    discharge_window_days: int = DISCHARGE_WINDOW_DAYS,
    operation_window_days: int = OPERATION_WINDOW_DAYS,
    consult_window_days: int = CONSULT_WINDOW_DAYS,
    approval_window_days: int = APPROVAL_WINDOW_DAYS,
    check_timeout: Callable[[], None] | None = None,
    his_reader: HisOracleReaderAdapter | None = None,
) -> dict[str, list[dict]]:
    """按扫描范围取数：在院 + 近 N 天出院 + 近 N 天手术（含文书/会诊/审批）。

    供 TimelinessScanner 与 T5 dry-run 接口共用；reader 缺权限时抛
    TimelinessPermissionMissing，由调用方处置。
    ``check_timeout`` 为调用方注入的活时钟超时探针（2026-11-11 修订：每次取数
    之间调用一次；elapsed 必须按真实流逝时间判定，此前用 now-started 静态差值
    导致取数阶段超时永不触发）；None=不检查（dry-run 无 4 分钟上限要求）。

    2026-11-13 返工：
    - ``deaths``＝在院+出院行中满足死亡口径的行（活库实证：死亡患者
      death_date_time 100% 为 NULL，判定看 discharge_disposition in ('死亡','5')）；
    - 手术行（拷贝，不改 Reader 原行）注入患者住院临床科室 ``dept_code`` 与
      ``doctor_in_charge_id``（临床科室才是试点 dept_scope 归属；手术室编码
      operation_dept_code 仅作兜底）；
    - ``patient_context``＝(patient_id, visit_id) → 临床上下文映射。

    2026-11-14 七规则轮：
    - HIS Oracle 可用时手术源优先 HIS.OPERATION_MASTER（+SM 排台前看 2 天），
      失败/不可用回退 jhemr.operation；
    - ``deaths`` 融合 HIS.ORDERS 死亡/料理医嘱：命中患者 t0 优先取医嘱最早
      时间（写入 death_date_time 键=DEATH_TIME_FIELDS 首选位），仅医嘱侧命中的
      患者合成新死亡行；科室/医生缺省用医嘱侧 ORDERING_DEPT/DOCTOR 补；
    - ``non_workdays``＝节假日表（缺权限回退周末）；
    - ``staff_title_map``＝HIS.STAFF_DICT 职称映射（供审签身份校验，可 None）。

    2026-11-14 补丁 3：
    - 取数顺序重排：先 deaths/operations/rescue 全部触发行到位，再合并
      inpatients+discharges+deaths+operations+rescue 的全部 (pid,vid) 为总
      pairs 后才 list_files——跨出 7 天出院窗但仍在医嘱/手术窗内的患者不再漏拉文书；
    - READY 外部源（RESCUE_ORDER）在快照阶段拉一次存
      ``external_events_by_type``，评估阶段直接复用（不再每规则重复连库）；
    - patient_context 缺 patient_name/dept_code/doctor_in_charge_id 的键经
      V_QYBR fetch_patient_visit_meta 一次性补齐并回填 operations/deaths/
      rescue 行（消除缺科室手术与缺工号记录，并为 LOCK_EMR 外插备好姓名）。
    """

    def tick() -> None:
        if check_timeout is not None:
            check_timeout()

    tick()
    inpatients = list(reader.list_inpatients() or [])
    discharges = list(reader.list_recent_discharges(discharge_window_days) or [])
    patient_context = _build_patient_context(inpatients, discharges)

    # ---- 触发行先行（deaths / operations / rescue） ----

    # 死亡行（供 DEATH 族规则触发）：从在院 + 出院行提取，出院触发会跳过这些行。
    deaths = [dict(row) for row in inpatients + discharges if is_death_row(row)]

    # HIS 死亡/料理医嘱融合（优先起算时间；仅医嘱命中患者合成行）。
    his_deaths: dict[tuple[str, str], dict] = {}
    if his_reader is not None:
        tick()
        his_deaths = his_reader.list_death_orders(
            now - timedelta(days=DEATH_ORDER_WINDOW_DAYS), now
        )
    seen_death_pairs = set()
    for row in deaths:
        pair = _row_pair(row)
        if pair is None:
            continue
        seen_death_pairs.add(pair)
        hit = his_deaths.get(pair)
        if hit:
            # 医嘱最早时间优先（DEATH_TIME_FIELDS 首选 death_date_time）。
            row["death_date_time"] = hit["death_time"]
            if not str(row.get("dept_code") or "").strip() and hit.get("dept_code"):
                row["dept_code"] = hit["dept_code"]
            if not str(row.get("doctor_in_charge_id") or "").strip() and hit.get("doctor_id"):
                row["doctor_in_charge_id"] = hit["doctor_id"]
    for pair, hit in his_deaths.items():
        if pair in seen_death_pairs:
            continue
        deaths.append({
            "patient_id": pair[0],
            "visit_id": pair[1],
            "death_date_time": hit["death_time"],
            "discharge_date_time": None,
            "discharge_disposition": "死亡",
            "dept_code": hit.get("dept_code") or None,
            "doctor_in_charge_id": hit.get("doctor_id") or None,
        })

    # 手术源：HIS 主表+排台优先；HIS 取数抛错回退 jhemr.operation（适配器已吞
    # 异常返回 []；空列表不回退——HIS 可读但窗口内确无手术是合法态）。
    operations_all: list[dict] = []
    if his_reader is not None:
        operations_all = his_reader.list_his_operations(
            now - timedelta(days=operation_window_days),
            now + timedelta(days=SM_SCHEDULED_FORWARD_DAYS),
        )
    if not his_reader or not operations_all:
        # jhemr 回退口径与原实现一致：按在院+出院患者对取。
        fallback_pairs: list[tuple[str, str]] = []
        seen_fb: set[tuple[str, str]] = set()
        for row in inpatients + discharges:
            pair = _row_pair(row)
            if pair and pair not in seen_fb:
                seen_fb.add(pair)
                fallback_pairs.append(pair)
        operations_all = list(reader.list_operations(fallback_pairs) or [])
    # 近 N 天手术窗口（按开始/结束时间任一落在窗内即纳入）。
    window_start = now - timedelta(days=operation_window_days)
    operations = []
    for row in operations_all:
        for field in ("operating_end_date", "operating_date"):
            stamp = _row_as_datetime(row.get(field))
            if stamp is not None and stamp >= window_start:
                operations.append(row)
                break

    # READY 外部源事件（RESCUE_ORDER=HIS 抢救医嘱）：快照阶段拉一次缓存。
    external_events_by_type: dict[str, list[dict]] = {}
    for trigger_type in EXTERNAL_TRIGGER_TYPES:
        source = EXTERNAL_TRIGGER_SOURCES.get(trigger_type)
        if source is not None and source.status == SOURCE_STATUS_READY:
            tick()
            try:
                external_events_by_type[trigger_type] = list(
                    source.fetch_events(now - timedelta(days=RESCUE_WINDOW_DAYS), now) or []
                )
            except Exception:
                logger.exception("外部源 %s 取数失败（本轮降级为空）", trigger_type)
                external_events_by_type[trigger_type] = []

    rescue_events = external_events_by_type.get("RESCUE_ORDER") or []

    # ---- 合并总 pairs（覆盖跨窗患者的文书拉取） ----
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add_pair(row: Mapping) -> None:
        pair = _row_pair(dict(row) if not isinstance(row, dict) else row)
        if pair and pair not in seen:
            seen.add(pair)
            pairs.append(pair)

    for row in inpatients + discharges + deaths + operations + rescue_events:
        _add_pair(row)

    # ---- V_QYBR 元信息补齐（姓名/科室/管床工号；异常降级空） ----
    if his_reader is not None and pairs:
        tick()
        def _ctx_complete(p: tuple[str, str]) -> bool:
            entry = patient_context.get(p, {})
            return bool(entry.get("patient_name") and entry.get("dept_code")
                        and entry.get("doctor_in_charge_id"))
        # 假增量修复（2026-11-14 补充）：operations/deaths/rescue 的患者排前——
        # 即使首轮命中 600 查库封顶，关键事件患者也 100% 覆盖；在院/出院常规
        # 患者靠 V_QYBR TTL 缓存跨轮增量补齐。
        event_pairs: list[tuple[str, str]] = []
        for row in operations + deaths + rescue_events:
            pair = _row_pair(row if isinstance(row, dict) else dict(row))
            if pair and pair not in event_pairs and not _ctx_complete(pair):
                event_pairs.append(pair)
        rest_pairs = [p for p in pairs if p not in set(event_pairs) and not _ctx_complete(p)]
        missing = event_pairs + rest_pairs
        if missing:
            try:
                meta = his_reader.fetch_patient_visit_meta(missing)
            except AttributeError:
                meta = {}
            for pair, info in meta.items():
                entry = patient_context.setdefault(pair, {})
                for key in ("patient_name", "dept_code", "doctor_in_charge_id"):
                    if not entry.get(key) and info.get(key):
                        entry[key] = info[key]

    def _enrich(row: dict) -> dict:
        """按 patient_context 回填缺省科室/工号/姓名（拷贝后补键，不动源行）。"""
        pair = _row_pair(row)
        entry = patient_context.get(pair) if pair else None
        if entry:
            for key in ("dept_code", "doctor_in_charge_id", "patient_name"):
                if not str(row.get(key) or "").strip() and entry.get(key):
                    row[key] = entry[key]
        return row

    operations = [_enrich(dict(row)) for row in operations]
    deaths = [_enrich(dict(row)) for row in deaths]
    rescue_events = [_enrich(dict(row)) for row in rescue_events]
    external_events_by_type["RESCUE_ORDER"] = rescue_events

    tick()
    files = list(reader.list_files(pairs) or [])
    tick()
    consult_since = now - timedelta(days=consult_window_days)
    consult_applies = list(reader.list_consult_applies(consult_since) or [])
    tick()
    approval_since = now - timedelta(days=approval_window_days)
    limit_logs = list(reader.list_limit_logs(approval_since) or [])
    tick()
    non_workdays = _compute_non_workdays(reader, now)
    staff_title_map = his_reader.get_staff_title_map() if his_reader is not None else None

    return {
        "inpatients": inpatients,
        "discharges": discharges,
        "deaths": deaths,
        "operations": operations,
        "consult_applies": consult_applies,
        "files": files,
        "approvals": limit_logs,
        "patient_context": patient_context,
        "non_workdays": sorted(non_workdays or []),
        "staff_title_map": staff_title_map or {},
        "external_events_by_type": external_events_by_type,
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
        config: dict | None = None,
        his_reader: HisOracleReaderAdapter | None = None,
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
        # 2026-11-14 七规则轮：HIS 医嘱/手术/职称源（None=不启用，全部走 JHEMR）。
        self.his_reader = his_reader
        # 2026-11-13 返工：通知/外插钩子需要的配置（timeliness + relay_alert 段）；
        # 缺省懒加载 load_config()，测试可注入 {"timeliness": {...}} 隔离。
        self._injected_config = config
        self._resolved_config: dict | None = None
        self._started_at: datetime | None = None

    # ---- 配置与闭环钩子（2026-11-13 返工） ----

    def _get_config(self) -> dict:
        if self._injected_config is not None:
            return self._injected_config
        if self._resolved_config is None:
            self._resolved_config = load_config() or {}
        return self._resolved_config

    def _sync_approvals_from_snapshot(self, snapshot: dict) -> dict[str, int]:
        """闭环 1：快照 approvals → tl_approval（幂等，支持既有行 flag 1→2 更新）。"""
        try:
            stats = sync_approvals(self.db, None, rows=snapshot.get("approvals") or [])
        except Exception:
            self.db.rollback()
            logger.exception("时效扫描：审批同步失败（不影响事件评估继续）")
            return {"approvals_inserted": 0, "approvals_updated": 0, "approval_sync_failed": 1}
        return {
            "approvals_inserted": int(stats.get("created", 0)),
            "approvals_updated": int(stats.get("updated", 0)),
            "approval_sync_failed": 0,
        }

    def _notify_rule_events(self, rule: TLRule, version: TLRuleVersion, now: datetime) -> int:
        """闭环 2：WARN_ONLY/LOCK_EMR 规则的 WARNING/OVERDUE 事件提醒留痕。

        TimelinessNotifier 受 D6 闸门保护（默认 LOG_ONLY 只写 tl_action_log 不外发）；
        通道缺省=企微（channels_json 为空按默认 WECOM 口径）。成功留痕（含幂等
        去重命中）后回填 event.warn_sent_at；BLOCKED（缺中继配置）不回填，下轮重试。
        """
        if version.action_mode not in ("WARN_ONLY", "LOCK_EMR"):
            return 0
        try:
            channels = json.loads(version.channels_json or "[]")
        except ValueError:
            channels = []
        if not isinstance(channels, list):
            channels = []
        # channels 为空=默认企微通道（D6 前 LOG_ONLY 留痕），非空=按配置通道留痕；
        # 两者都走同一提醒入口，通道差异由中继侧消息类型区分。
        notifier = TimelinessNotifier(self.db, self._get_config())
        events = (
            self.db.query(TLEvent)
            .filter(
                TLEvent.rule_code == rule.rule_code,
                TLEvent.status.in_(["WARNING", "OVERDUE"]),
                TLEvent.warn_sent_at.is_(None),
            )
            .all()
        )
        notified = 0
        for event in events:
            notify_type = "WARN" if event.status == "WARNING" else "OVERDUE"
            try:
                result = notifier.notify_event(event_uid=event.event_uid, notify_type=notify_type)
            except Exception:
                logger.warning(
                    "[timeliness] 扫描提醒留痕失败 rule=%s event=%s", rule.rule_code, event.event_uid
                )
                continue
            if result.get("handled") or "duplicate" in str(result.get("reason") or ""):
                event.warn_sent_at = now
                notified += 1
        if notified:
            self.db.commit()
        return notified

    def _has_insert_monitor_log(self, event_id: int, *, gates_open: bool = False) -> bool:
        """同 event_id 已有 JHEMR_INSERT_MONITOR 留痕则跳过。

        2026-11-14 补丁 4 防死锁：
        - 写闸未全开：沿用既有语义（任意留痕含 BLOCKED 即跳过）——闸门关闭期
          每 5 分钟一轮扫描，不去重会刷屏同一事件的 BLOCKED 日志；
        - 写闸已开（gates_open=True）：仅 EXECUTED/DRY_RUN 留痕才跳过——历史
          闸门关闭期留下的旧 BLOCKED 记录**不得阻塞**开闸后的首次真实外插。
        """
        query = self.db.query(TLActionLog.id).filter(
            TLActionLog.event_id == event_id,
            TLActionLog.action_type == ACTION_TYPE_INSERT_MONITOR,
        )
        if gates_open:
            query = query.filter(TLActionLog.mode.in_(("EXECUTED", "DRY_RUN")))
        return query.first() is not None

    def _insert_monitor_for_rule(
        self, rule: TLRule, version: TLRuleVersion, snapshot: dict, now: datetime
    ) -> tuple[int, int]:
        """闭环 3：LOCK_EMR 规则的 OVERDUE 事件外插 JHEMR 监控行（多重闸门保护）。

        - 仅 action_mode=LOCK_EMR 且 jhemr_monitor_code 非空且**非 NATIVE_GENERATED_CODES**
          （原生自动生成节点由 JHEMR 自己插，外插会重复锁死患者）；
        - JhemrWriter 内部闸门 0/1/2（insert_monitor_enabled / enabled / 试点科室）
          全开才真实连库；闸门关闭仅幂等留痕一条 BLOCKED；
        - 患者姓名未在快照中（当前 reader 未取经核实的姓名列，值域防猜测红线）：
          留痕一条 BLOCKED 后跳过，待 reader 补齐姓名列后自动放行。
        """
        if version.action_mode != "LOCK_EMR":
            return 0, 0
        item_code = str(version.jhemr_monitor_code or "").strip()
        if not item_code or item_code in NATIVE_GENERATED_CODES:
            return 0, 0
        events = (
            self.db.query(TLEvent)
            .filter(TLEvent.rule_code == rule.rule_code, TLEvent.status == "OVERDUE")
            .all()
        )
        if not events:
            return 0, 0
        # 补丁 4：写闸开启时跨过历史 BLOCKED 留痕（防开闸死锁）。
        write_cfg = ((self._get_config().get("timeliness") or {}).get("jhemr_write") or {})
        gates_open = (
            write_cfg.get("enabled") is True and write_cfg.get("insert_monitor_enabled") is True
        )
        context = snapshot.get("patient_context") or {}
        writer = JhemrWriter(self.db, self._get_config())
        attempted = inserted = 0
        for event in events:
            if event.deadline is None:
                continue  # 无截止时间（时限待定）不外插
            if self._has_insert_monitor_log(event.id, gates_open=gates_open):
                continue  # 幂等：有效留痕不重复刷（开闸时仅认 EXECUTED/DRY_RUN）
            attempted += 1
            entry = context.get((event.patient_id, event.visit_id)) or {}
            patient_name = str(entry.get("patient_name") or "").strip()
            if not patient_name:
                self.db.add(TLActionLog(
                    event_id=event.id,
                    action_type=ACTION_TYPE_INSERT_MONITOR,
                    mode="BLOCKED",
                    target="|".join(str(x) for x in (
                        "jhemr.emr_online_monitor", event.patient_id, event.visit_id, item_code,
                    ))[:200],
                    operator="timeliness_scan",
                    created_at=now,
                    params_json="{}",
                    result=(
                        "blocked: patient name not available in scan snapshot "
                        "(emr_online_monitor.name required; extend reader with a verified name column)"
                    ),
                ))
                self.db.commit()
                continue
            # 补丁 4：JH04.02.013（死亡讨论 5 工作日）客户端按 start_date+168h
            # 判锁（字典 monitor_limit=168 小时）——start_date 对齐为
            # deadline - 168h，保证客户端解锁边界与 deadline 精确一致；
            # 其余监控码仍用事件 t0 起算。
            if item_code == "JH04.02.013" and event.deadline is not None:
                start_date = event.deadline - timedelta(hours=168)
            else:
                start_date = event.t0
            outcome = writer.insert_monitor_row(
                patient_id=event.patient_id,
                visit_id=event.visit_id,
                name=patient_name,
                item_code=item_code,
                item_name=rule.rule_name,
                start_date=start_date,
                end_date=event.deadline,
                dept_code=event.dept_code,
                dry_run=False,
                operator="timeliness_scan",
                event_id=event.id,
            )
            if outcome.get("executed"):
                inserted += 1
        return attempted, inserted

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
            his_reader=self.his_reader,
        )

    def _build_rule_data(self, snapshot: dict, rule: TLRule, version: TLRuleVersion) -> dict:
        """组装备评估规则的数据快照（含该规则既有事件，保终态与幂等）。"""
        existing = (
            self.db.query(TLEvent.event_uid, TLEvent.status)
            .filter(TLEvent.rule_code == rule.rule_code)
            .all()
        )
        data = {
            "inpatients": snapshot["inpatients"],
            "discharges": snapshot["discharges"],
            "deaths": snapshot.get("deaths") or [],
            "operations": snapshot["operations"],
            "consult_applies": snapshot["consult_applies"],
            "files": snapshot["files"],
            "approvals": snapshot["approvals"],
            "existing_events": [
                {"event_uid": uid, "status": status} for uid, status in existing
            ],
            # 节假日表口径（2026-11-14：缺权限回退周末）；构造器显式注入优先。
            "non_workdays": list(self.non_workdays) or list(snapshot.get("non_workdays") or []),
            # 审签身份校验用职称映射（可空：缺失按标题职称词兜底）。
            "staff_title_map": snapshot.get("staff_title_map") or {},
        }
        # 外部触发源（2026-11-14 补丁 3：快照阶段已拉取缓存，直接复用不再连库；
        # 兼容旧快照无缓存键时回退 READY 源现场拉取）。
        if version.trigger_type in EXTERNAL_TRIGGER_TYPES:
            cached = (snapshot.get("external_events_by_type") or {}).get(version.trigger_type)
            if cached is None:
                source = EXTERNAL_TRIGGER_SOURCES.get(version.trigger_type)
                if source is not None and source.status == SOURCE_STATUS_READY:
                    since = self._started_at or self.now_fn()
                    cached = source.fetch_events(
                        since - timedelta(days=RESCUE_WINDOW_DAYS), since
                    ) or []
                else:
                    cached = []
            data["external_events"] = cached
        return data

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
                # P0（2026-11-14）：排台顺延/放宽时限使时钟态回退 PENDING 时，
                # 清空预警已发标记——重新临期时仍能正常发预警。
                if status_before in ("WARNING", "OVERDUE") and result.status == "PENDING":
                    event.warn_sent_at = None
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
            .filter(TLRule.enabled == True)  # noqa: E712 — Oracle 方言安全（is_(True) 编译为 IS 1 报 ORA-00908）
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

            # 闭环 1（2026-11-13 返工）：快照审批日志 → tl_approval（幂等；
            # JHEMR 原生审批通过的原地 UPDATE 也会被跟随，flag 1→2）。
            approval_stats = self._sync_approvals_from_snapshot(snapshot)

            rules = (
                self.db.query(TLRule)
                .filter(TLRule.enabled == True)  # noqa: E712 — Oracle 方言安全（is_(True) 编译为 IS 1 报 ORA-00908）
                .order_by(TLRule.rule_code)
                .all()
            )
            not_configured: list[str] = []
            hook_notes: list[str] = []
            total_created = total_updated = 0
            warn_notified = monitor_attempted = monitor_inserted = 0
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
                # P0（2026-11-14）：单规则评估/落库异常隔离——排台顺延、脏数据等
                # 单点问题 rollback 后记 hook_notes 继续其余规则，绝不整轮 FAILED。
                try:
                    data = self._build_rule_data(snapshot, rule, version)
                    results = evaluate(version, now=now, data=data, rule_code=rule.rule_code)
                    created, updated = self._persist_results(
                        results, rule=rule, version=version, run_id=run.id, now=now
                    )
                except Exception:
                    self.db.rollback()
                    hook_notes.append(f"rule_eval_failed:{rule.rule_code}")
                    logger.exception("时效扫描：单规则评估失败已隔离 rule=%s", rule.rule_code)
                    continue
                total_created += created
                total_updated += updated
                run.events_created = total_created
                run.events_updated = total_updated
                self.db.commit()

                # 闭环 2/3（2026-11-13 返工）：提醒留痕 + LOCK_EMR 外插钩子；
                # 单钩子失败不影响其余规则评估（记 note 后继续）。
                try:
                    warn_notified += self._notify_rule_events(rule, version, now)
                except Exception:
                    self.db.rollback()
                    hook_notes.append(f"notify_failed:{rule.rule_code}")
                    logger.exception("时效扫描：提醒钩子失败 rule=%s", rule.rule_code)
                try:
                    attempted, inserted = self._insert_monitor_for_rule(rule, version, snapshot, now)
                    monitor_attempted += attempted
                    monitor_inserted += inserted
                except Exception:
                    self.db.rollback()
                    hook_notes.append(f"monitor_insert_failed:{rule.rule_code}")
                    logger.exception("时效扫描：监控行外插钩子失败 rule=%s", rule.rule_code)

            run.status = RUN_STATUS_SUCCESS
            run.finished_at = self.now_fn()
            notes = list(not_configured)
            if approval_stats.get("approval_sync_failed"):
                notes.append("approval_sync_failed")
            notes.extend(hook_notes)
            if notes:
                run.error_text = "; ".join(
                    (["not_configured sources skipped: " + ", ".join(not_configured)] if not_configured else [])
                    + hook_notes
                    + (["approval_sync_failed"] if approval_stats.get("approval_sync_failed") else [])
                )
            self.db.commit()
            return {
                **self._summary(run, not_configured=not_configured),
                "approvals_inserted": approval_stats["approvals_inserted"],
                "approvals_updated": approval_stats["approvals_updated"],
                "warn_notified": warn_notified,
                "monitor_insert_attempted": monitor_attempted,
                "monitor_inserted": monitor_inserted,
                "hook_notes": hook_notes,
            }
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
        his_reader = build_default_his_reader()
        register_his_sources_if_available(his_reader)
        scanner = TimelinessScanner(db, JhemrModuleReader(), his_reader=his_reader)
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
