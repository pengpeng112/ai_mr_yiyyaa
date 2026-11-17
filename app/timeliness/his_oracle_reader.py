"""HIS/手麻 Oracle 只读取数模块（病历时效质控，2026-11-14 七规则轮）。

数据源：应用既有 Oracle 实例（10.10.8.216，与 JHEMR.V_QYBR 同实例），复用
`app.utils.patient_dept_query._get_oracle_connection()` 的连接方式；**全程只读
SELECT，Oracle 11g 兼容（禁用 FETCH FIRST，统一 ROWNUM/绑定变量）**。

覆盖四类取数（任务书 §1.1 已核实列名与值域，禁止猜测）：
1. `HIS.ORDERS` 医嘱：抢救/死亡料理两类精确白名单 + 有效状态硬过滤
   （ORDER_STATUS IN ('2','3','6') 且 REPEAT_INDICATOR=0，排除 4=作废/
   5=草稿/8=医生作废——近 30 天 8000+ 条 8）；
2. `HIS.OPERATION_MASTER(+OPERATION_NAME)` 手术主表 + `SM.MED_OPERATION_MASTER`
   排台表（未下台手术的 SCHEDULED_DATE_TIME，列存在性经 probe 动态确认）；
3. `HIS.STAFF_DICT` 职称字典（内存 TTL 3600s 缓存）；
4. 权限探测 probe_oracle_tables()：ORA-00942/ORA-01031 捕获并返回明确表名，
   调用方降级跳过该外部源而不中断 JHEMR 主扫描。

口令/账号由应用 Oracle 配置解析（ConfigParser.parse_oracle_config），本模块
不新增任何凭据存储；日志不输出患者姓名与口令。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Sequence

from app.timeliness.engine.triggers import (
    EXTERNAL_EVENT_FIELDS,
    ExternalEventSource,
    register_external_source,
)

logger = logging.getLogger(__name__)

# ---- 任务书 §1.1 实证常量（禁止猜测值域） ----

# 有效医嘱状态（COMM.ORDER_STATUS_DICT 实证：4=作废、5=医生保存草稿、8=医生作废）。
VALID_ORDER_STATUSES = ("2", "3", "6")
# REPEAT_INDICATOR=0 临时医嘱（抢救/死亡料理均为一次性临时医嘱）。
TEMP_ORDER_REPEAT_INDICATOR = "0"

# 抢救医嘱精确白名单（ORDER_CODE ∪ ORDER_TEXT）。
RESCUE_ORDER_CODES = ("011104000010000", "011104000020000")
RESCUE_ORDER_TEXTS = ("院内抢救费（常规）", "院内抢救费（复杂）", "院内抢救复杂", "小抢救", "大抢救")

# 死亡/料理医嘱精确白名单（严禁 LIKE '%死亡%'——实测会误中 PD-L1 伴随诊断）。
DEATH_ORDER_CODES = ("LCSW001", "011500000010000", "GT140100001")
DEATH_ORDER_TEXTS = ("临床死亡", "死亡出院", "死亡诊断和遗体料理费", "尸体料理")

# 主治及以上职称精确集合（HIS.STAFF_DICT 实证值域；排除 "医师"/"助理医师"）。
ATTENDING_PLUS_TITLES = frozenset({"主治医师", "副主任医师", "主任医师"})

# 抢救事件合并窗口：同患者多条抢救费医嘱在 30 分钟内合并为一次抢救。
RESCUE_MERGE_WINDOW = timedelta(minutes=30)

# 职称字典 TTL 缓存（任务书：3600 秒）。
STAFF_TTL_SECONDS = 3600.0

# 探测的 5 张表（含手麻排台）。
PROBE_TABLES = (
    "HIS.ORDERS",
    "HIS.OPERATION_MASTER",
    "HIS.OPERATION_NAME",
    "SM.MED_OPERATION_MASTER",
    "HIS.STAFF_DICT",
)

SOURCE_SYSTEM_HIS_ORDERS = "rescue_order"  # 与触发类型小写对齐（evaluate 外部源过滤口径）

# SM 排台表业务列白名单（2026-11-14 补丁轮活库实证：OPERATION_SCALE 存中文
# '一'/'二'/'三'/'四'；存在 OPER_STATUS=-80 且 CANCEL_DATE_TIME IS NULL 的已取消
# 手术近 30 天 12 例——须硬过滤）。按 probe_sm_columns 动态确认后逐列读取。
SM_BUSINESS_COLUMNS = (
    "PATIENT_ID", "VISIT_ID", "OPER_ID", "DEPT_STAYED", "OPERATING_ROOM",
    "OPERATION_SCALE", "EMERGENCY_INDICATOR", "OPERATION_CLASS", "SURGEON",
    "FIRST_ASSISTANT", "ANESTHESIA_METHOD", "SCHEDULED_DATE_TIME",
    "START_DATE_TIME", "END_DATE_TIME", "OPERATION_NAME", "OPER_STATUS",
    "CANCEL_DATE_TIME",
)


class HisOracleUnavailable(RuntimeError):
    """HIS Oracle 源不可用（未配置/连不上/权限缺失），调用方应降级跳过。"""


def _get_connection():
    """复用应用既有 Oracle 连接（patient_dept_query 同款；只读用途由调用方保证）。"""
    from app.utils.patient_dept_query import _get_oracle_connection

    return _get_oracle_connection()


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _bind_in(values: tuple[str, ...], prefix: str) -> tuple[str, dict[str, str]]:
    """Oracle IN 列表展开为命名绑定（避免拼接字面量）。"""
    names = [f"{prefix}{i}" for i in range(len(values))]
    return ", ".join(f":{n}" for n in names), {n: v for n, v in zip(names, values)}


def _order_whitelist_sql(codes: tuple[str, ...], texts: tuple[str, ...], prefix: str) -> tuple[str, dict[str, str]]:
    """ORDER_CODE IN (...) OR ORDER_TEXT IN (...) 的绑定版 SQL 片段。"""
    code_sql, code_binds = _bind_in(codes, f"{prefix}c")
    text_sql, text_binds = _bind_in(texts, f"{prefix}t")
    binds = {**code_binds, **text_binds}
    return f"(o.ORDER_CODE IN ({code_sql}) OR o.ORDER_TEXT IN ({text_sql}))", binds


# ---- 1. 权限探测 ----


def probe_oracle_tables(connect: Callable[[], Any] | None = None) -> dict[str, bool | str]:
    """探测 5 张 HIS/SM 表可读性。

    返回 {表名: True|错误文本}；True=可读，错误文本如
    "ORA-00942: table or view does not exist"（捕获 DatabaseError 原文，供
    报告输出精确 GRANT 语句定位）。连接失败抛 HisOracleUnavailable。
    """
    conn_factory = connect or _get_connection
    result: dict[str, bool | str] = {}
    conn = conn_factory()
    try:
        cur = conn.cursor()
        try:
            for table in PROBE_TABLES:
                try:
                    # EXISTS 只验证权限/存在性，不拉数据（Oracle 11g 兼容）。
                    cur.execute(f"SELECT 1 FROM DUAL WHERE EXISTS (SELECT 1 FROM {table})")
                    cur.fetchall()
                    result[table] = True
                except Exception as exc:  # ORA-00942 / ORA-01031 等
                    result[table] = _as_text(getattr(exc, "message", None)) or str(exc).split("\n")[0]
        finally:
            cur.close()
    finally:
        conn.close()
    return result


def probe_sm_columns(connect: Callable[[], Any] | None = None) -> set[str]:
    """探测 SM.MED_OPERATION_MASTER 实际列名（大写集合；空=不可读/无权限）。"""
    conn_factory = connect or _get_connection
    try:
        conn = conn_factory()
    except Exception as exc:
        raise HisOracleUnavailable(f"SM 排台列探测连接失败: {exc}") from exc
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT COLUMN_NAME FROM ALL_TAB_COLUMNS "
                "WHERE OWNER = 'SM' AND TABLE_NAME = 'MED_OPERATION_MASTER'"
            )
            return {str(row[0]).upper() for row in cur.fetchall()}
        finally:
            cur.close()
    except Exception as exc:
        logger.warning("SM.MED_OPERATION_MASTER 列探测失败（降级跳过排台源）: %s", exc)
        return set()
    finally:
        conn.close()


# ---- 2. 抢救医嘱（RESCUE_ORDER 外部事件源） ----


def list_rescue_orders(
    since: datetime,
    until: datetime,
    *,
    connect: Callable[[], Any] | None = None,
) -> list[dict]:
    """取窗口内有效抢救医嘱并按 30 分钟窗口合并为抢救事件。

    - 有效硬过滤：ORDER_STATUS IN ('2','3','6') 且 REPEAT_INDICATOR=0；
    - 白名单：ORDER_CODE/ORDER_TEXT 精确集合（任务书 §1.1）；
    - t0 = COALESCE(START_DATE_TIME, ENTER_DATE_TIME)；
    - 合并：同患者（含跨住院次）30 分钟内多条 → 一次事件取最早开嘱时间，
      source_event_id 取最早那条的 "{ORDER_NO}_{ORDER_SUB_NO}"（防同次抢救
      常规+复杂两条医嘱重复锁死）；
    - 返回行=EXTERNAL_EVENT_FIELDS + trigger_type（dept_code=ORDERING_DEPT
      临床科室优先，doctor_id=DOCTOR）。
    """
    wl_sql, wl_binds = _order_whitelist_sql(RESCUE_ORDER_CODES, RESCUE_ORDER_TEXTS, "rc")
    status_sql, status_binds = _bind_in(VALID_ORDER_STATUSES, "rs")
    sql = f"""
        SELECT o.PATIENT_ID, o.VISIT_ID, o.ORDER_NO, o.ORDER_SUB_NO,
               COALESCE(o.START_DATE_TIME, o.ENTER_DATE_TIME) AS T0,
               o.ORDERING_DEPT, o.DOCTOR, o.ORDER_TEXT
        FROM HIS.ORDERS o
        WHERE o.ORDER_STATUS IN ({status_sql})
          AND o.REPEAT_INDICATOR = :rc_repeat
          AND COALESCE(o.START_DATE_TIME, o.ENTER_DATE_TIME) >= :rc_since
          AND COALESCE(o.START_DATE_TIME, o.ENTER_DATE_TIME) < :rc_until
          AND {wl_sql}
        ORDER BY o.PATIENT_ID, COALESCE(o.START_DATE_TIME, o.ENTER_DATE_TIME)
    """
    params = {
        **wl_binds,
        **status_binds,
        "rc_repeat": TEMP_ORDER_REPEAT_INDICATOR,
        "rc_since": since,
        "rc_until": until,
    }
    conn_factory = connect or _get_connection
    conn = conn_factory()
    raw: list[dict] = []
    try:
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
            for row in cur.fetchall():
                t0 = _as_dt(row[4])
                if t0 is None:
                    continue  # 时间无法解析的脏行跳过（不中断）
                raw.append({
                    "patient_id": _as_text(row[0]),
                    "visit_id": _as_text(row[1]),
                    "order_no": _as_text(row[2]),
                    "order_sub_no": _as_text(row[3]),
                    "t0": t0,
                    "dept_code": _as_text(row[5]),
                    "doctor_id": _as_text(row[6]),
                    "order_text": _as_text(row[7]),
                })
        finally:
            cur.close()
    finally:
        conn.close()

    return _merge_rescue_rows(raw)


def _merge_rescue_rows(rows: list[dict]) -> list[dict]:
    """同患者 30 分钟窗口聚类：与当前簇最早时间相差 ≤30min 归并，取最早为 t0。"""
    by_patient: dict[str, list[dict]] = {}
    for row in rows:
        by_patient.setdefault(row["patient_id"], []).append(row)

    events: list[dict] = []
    for patient_id, items in by_patient.items():
        items.sort(key=lambda r: r["t0"])
        cluster: list[dict] = []
        cluster_start: datetime | None = None
        for item in items:
            if cluster_start is None or item["t0"] - cluster_start <= RESCUE_MERGE_WINDOW:
                cluster.append(item)
                if cluster_start is None:
                    cluster_start = item["t0"]
            else:
                events.append(_rescue_event(cluster))
                cluster = [item]
                cluster_start = item["t0"]
        if cluster:
            events.append(_rescue_event(cluster))
    events.sort(key=lambda e: (e["patient_id"], e["event_time"]))
    return events


def _rescue_event(cluster: list[dict]) -> dict:
    first = min(cluster, key=lambda r: r["t0"])
    row = {name: None for name in EXTERNAL_EVENT_FIELDS}
    row.update({
        "source_system": SOURCE_SYSTEM_HIS_ORDERS,
        "source_event_id": f"{first['order_no']}_{first['order_sub_no']}",
        "patient_id": first["patient_id"],
        "visit_id": first["visit_id"],
        "event_time": first["t0"],
        "dept_code": first["dept_code"] or None,
        "doctor_id": first["doctor_id"] or None,
        "detail": {"merged_order_count": len(cluster), "order_text": first["order_text"]},
        "trigger_type": "RESCUE_ORDER",
    })
    return row


class HisRescueOrderSource(ExternalEventSource):
    """RESCUE_ORDER 外部事件源（HIS.ORDERS 抢救医嘱白名单 + 30 分钟合并）。

    fetch 失败（权限/连接）不抛出到引擎：记日志返回空列表由扫描层记
    NOT_CONFIGURED 语义之外的单轮降级（下一轮重试）。
    """

    source_system = SOURCE_SYSTEM_HIS_ORDERS

    def __init__(self, connect: Callable[[], Any] | None = None):
        self._connect = connect

    def fetch_events(self, since: Any, until: Any) -> list[dict]:
        start = _as_dt(since) or (datetime.now() - timedelta(days=7))
        end = _as_dt(until) or datetime.now()
        try:
            return list_rescue_orders(start, end, connect=self._connect)
        except Exception:
            logger.exception("HIS 抢救医嘱取数失败（本轮降级为空，下轮重试）")
            return []

    @property
    def status(self) -> str:
        return "READY"


def register_his_rescue_source(connect: Callable[[], Any] | None = None) -> None:
    """把 HIS 抢救医嘱源登记为 RESCUE_ORDER 触发源（扫描层据此拉事件）。"""
    register_external_source("RESCUE_ORDER", HisRescueOrderSource(connect))


# ---- 3. 死亡/料理医嘱 ----


def list_death_orders(
    since: datetime,
    until: datetime,
    *,
    connect: Callable[[], Any] | None = None,
) -> dict[tuple[str, str], dict]:
    """取窗口内有效死亡/料理医嘱：返回 (patient_id, visit_id) → 最早时间与科室/医生。

    同次住院多条（如 临床死亡+尸体料理）取 MIN(COALESCE(START,ENTER))；
    精确白名单（严禁 LIKE 死亡——会误中 PD-L1 伴随诊断）。
    """
    wl_sql, wl_binds = _order_whitelist_sql(DEATH_ORDER_CODES, DEATH_ORDER_TEXTS, "dc")
    status_sql, status_binds = _bind_in(VALID_ORDER_STATUSES, "ds")
    sql = f"""
        SELECT o.PATIENT_ID, o.VISIT_ID,
               MIN(COALESCE(o.START_DATE_TIME, o.ENTER_DATE_TIME)) AS DEATH_T0,
               MIN(o.ORDERING_DEPT) KEEP (DENSE_RANK FIRST ORDER BY COALESCE(o.START_DATE_TIME, o.ENTER_DATE_TIME)) AS DEPT,
               MIN(o.DOCTOR) KEEP (DENSE_RANK FIRST ORDER BY COALESCE(o.START_DATE_TIME, o.ENTER_DATE_TIME)) AS DOCTOR
        FROM HIS.ORDERS o
        WHERE o.ORDER_STATUS IN ({status_sql})
          AND o.REPEAT_INDICATOR = :dc_repeat
          AND COALESCE(o.START_DATE_TIME, o.ENTER_DATE_TIME) >= :dc_since
          AND COALESCE(o.START_DATE_TIME, o.ENTER_DATE_TIME) < :dc_until
          AND {wl_sql}
        GROUP BY o.PATIENT_ID, o.VISIT_ID
    """
    params = {
        **wl_binds,
        **status_binds,
        "dc_repeat": TEMP_ORDER_REPEAT_INDICATOR,
        "dc_since": since,
        "dc_until": until,
    }
    conn_factory = connect or _get_connection
    conn = conn_factory()
    result: dict[tuple[str, str], dict] = {}
    try:
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
            for row in cur.fetchall():
                t0 = _as_dt(row[2])
                if t0 is None:
                    continue
                result[(_as_text(row[0]), _as_text(row[1]))] = {
                    "death_time": t0,
                    "dept_code": _as_text(row[3]),
                    "doctor_id": _as_text(row[4]),
                }
        finally:
            cur.close()
    finally:
        conn.close()
    return result


# ---- 4. 手术（HIS 主表 + SM 排台） ----


def list_his_operations(
    since: datetime,
    until: datetime,
    *,
    sm_columns: set[str] | None = None,
    connect: Callable[[], Any] | None = None,
) -> list[dict]:
    """取窗口内手术（HIS.OPERATION_MASTER 实际手术 + SM 排台未下台/待开台）。

    - 名称：LEFT JOIN HIS.OPERATION_NAME n（OPERATION_NO=1 主名）；
    - 标准化列名与 jhemr.operation 对齐（operation_no/operating_date/
      operating_end_date/dept_code=DEPT_STAYED 临床科室/operator_id=SURGEON
      6 位工号），供引擎 OPERATION_START/END 与术者审签直接复用；
    - 2026-11-14 补丁轮：
      ① SM 排台读取 probe 动态确认的全部业务列（此前只取 4 列、其余传空串
        触发"空麻醉+空级别"误豁免——PREOP_SUMMARY 待决数为 0 的根因）；
      ② 硬过滤取消手术：CANCEL_DATE_TIME IS NULL AND NVL(OPER_STATUS,0) >= 0
        （活库实证 OPER_STATUS=-80 且未填取消时间 30 天 12 例）；
      ③ 开台时间=COALESCE(START_DATE_TIME, SCHEDULED_DATE_TIME)；
      ④ 消除 SM-/HIS- 前缀分裂：两表 (PATIENT_ID,VISIT_ID,OPER_ID) 同源，
        oper_id 非空时统一 operation_no=f"HIS-{oper_id}"（主表记录优先，SM 排台
        仅补充主表尚不存在的同键手术）——排台预警→开台卡口→下台归档全生命
        周期共享同一 event_uid；oper_id 为空才用 SM-SCHED- 兜底。
    """
    conn_factory = connect or _get_connection
    conn = conn_factory()
    operations: list[dict] = []
    his_triples: set[tuple[str, str, str]] = set()
    his_pairs: set[tuple[str, str]] = set()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT m.PATIENT_ID, m.VISIT_ID, m.OPER_ID, m.DEPT_STAYED,
                       m.OPERATING_ROOM, m.OPERATION_SCALE, m.EMERGENCY_INDICATOR,
                       m.OPERATION_CLASS, m.SURGEON, m.FIRST_ASSISTANT,
                       m.ANESTHESIA_METHOD, m.START_DATE_TIME, m.END_DATE_TIME,
                       n.OPERATION
                FROM HIS.OPERATION_MASTER m
                LEFT JOIN HIS.OPERATION_NAME n
                  ON m.PATIENT_ID = n.PATIENT_ID AND m.VISIT_ID = n.VISIT_ID
                 AND m.OPER_ID = n.OPER_ID AND n.OPERATION_NO = 1
                WHERE (m.START_DATE_TIME >= :op_since AND m.START_DATE_TIME < :op_until)
                   OR (m.END_DATE_TIME >= :op_since AND m.END_DATE_TIME < :op_until)
                ORDER BY m.PATIENT_ID, m.VISIT_ID, m.START_DATE_TIME
                """,
                {"op_since": since, "op_until": until},
            )
            for row in cur.fetchall():
                pid, vid = _as_text(row[0]), _as_text(row[1])
                oper_id = _as_text(row[2])
                his_triples.add((pid, vid, oper_id))
                his_pairs.add((pid, vid))
                operations.append(_normalize_his_operation(
                    patient_id=pid, visit_id=vid, oper_id=oper_id,
                    dept_stayed=_as_text(row[3]), operating_room=_as_text(row[4]),
                    operation_scale=_as_text(row[5]), emergency_indicator=_as_text(row[6]),
                    operation_class=_as_text(row[7]), surgeon=_as_text(row[8]),
                    first_assistant=_as_text(row[9]), anesthesia_method=_as_text(row[10]),
                    start=_as_dt(row[11]), end=_as_dt(row[12]),
                    operation_name=_as_text(row[13]), scheduled=False,
                ))
        finally:
            cur.close()

        # SM 排台（列存在性经 probe_sm_columns 确认后才启用；缺关键列整源跳过）。
        columns = sm_columns if sm_columns is not None else probe_sm_columns(connect=connect)
        needed = {"PATIENT_ID", "VISIT_ID", "SCHEDULED_DATE_TIME"}
        if not needed.issubset(columns):
            logger.warning(
                "SM.MED_OPERATION_MASTER 缺关键列 %s（现有 %s），排台源跳过",
                sorted(needed - columns), sorted(columns) or "不可读",
            )
            return operations
        join_exact = "OPER_ID" in columns
        # 业务列按白名单 ∩ 实际列动态拼 SELECT（缺列降级为 NULL，不误传空串豁免）。
        select_parts = []
        for name in SM_BUSINESS_COLUMNS:
            if name == "OPER_ID" and not join_exact:
                select_parts.append("NULL AS OPER_ID")
            elif name in columns:
                select_parts.append(f"s.{name}")
            else:
                select_parts.append(f"NULL AS {name}")
        anti = (
            "NOT EXISTS (SELECT 1 FROM HIS.OPERATION_MASTER h WHERE h.PATIENT_ID = s.PATIENT_ID "
            "AND h.VISIT_ID = s.VISIT_ID AND h.OPER_ID = s.OPER_ID)"
            if join_exact
            else "NOT EXISTS (SELECT 1 FROM HIS.OPERATION_MASTER h WHERE h.PATIENT_ID = s.PATIENT_ID "
            "AND h.VISIT_ID = s.VISIT_ID)"
        )
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                SELECT {", ".join(select_parts)}
                FROM SM.MED_OPERATION_MASTER s
                WHERE COALESCE(s.START_DATE_TIME, s.SCHEDULED_DATE_TIME) >= :sm_since
                  AND COALESCE(s.START_DATE_TIME, s.SCHEDULED_DATE_TIME) < :sm_until
                  AND s.CANCEL_DATE_TIME IS NULL
                  AND NVL(s.OPER_STATUS, 0) >= 0
                  AND {anti}
                ORDER BY s.PATIENT_ID, s.VISIT_ID, s.SCHEDULED_DATE_TIME
                """,
                {"sm_since": since, "sm_until": until},
            )
            col_index = {name: i for i, name in enumerate(SM_BUSINESS_COLUMNS)}
            for row in cur.fetchall():
                def _col(name: str) -> Any:
                    return row[col_index[name]]
                pid, vid = _as_text(_col("PATIENT_ID")), _as_text(_col("VISIT_ID"))
                oper_id = _as_text(_col("OPER_ID"))
                start = _as_dt(_col("START_DATE_TIME"))
                scheduled = _as_dt(_col("SCHEDULED_DATE_TIME"))
                effective = start or scheduled
                if effective is None:
                    continue
                triple = (pid, vid, oper_id)
                if oper_id and triple in his_triples:
                    continue  # 主表已有同键手术（优先保留实际记录）
                if not oper_id and (pid, vid) in his_pairs:
                    continue  # 无 OPER_ID 时的保守口径：患者已有主表手术不重复
                operations.append(_normalize_his_operation(
                    patient_id=pid, visit_id=vid, oper_id=oper_id,
                    dept_stayed=_as_text(_col("DEPT_STAYED")),
                    operating_room=_as_text(_col("OPERATING_ROOM")),
                    operation_scale=_as_text(_col("OPERATION_SCALE")),
                    emergency_indicator=_as_text(_col("EMERGENCY_INDICATOR")),
                    operation_class=_as_text(_col("OPERATION_CLASS")),
                    surgeon=_as_text(_col("SURGEON")),
                    first_assistant=_as_text(_col("FIRST_ASSISTANT")),
                    anesthesia_method=_as_text(_col("ANESTHESIA_METHOD")),
                    start=effective, end=_as_dt(_col("END_DATE_TIME")),
                    operation_name=_as_text(_col("OPERATION_NAME")), scheduled=True,
                ))
        finally:
            cur.close()
    finally:
        conn.close()
    return operations


def _normalize_his_operation(
    *, patient_id: str, visit_id: str, oper_id: str, dept_stayed: str,
    operating_room: str, operation_scale: str, emergency_indicator: str,
    operation_class: str, surgeon: str, first_assistant: str,
    anesthesia_method: str, start: datetime | None, end: datetime | None,
    operation_name: str, scheduled: bool,
) -> dict:
    # 2026-11-14 补丁轮：消除 SM-/HIS- 分裂——两表 (PATIENT_ID,VISIT_ID,OPER_ID)
    # 同源，oper_id 非空一律 "HIS-{oper_id}"（排台预警→开台卡口→下台归档共享同一
    # event_uid，换源不再产生第二条事件）；oper_id 为空的排台兜底 "SM-SCHED-时间戳"。
    if oper_id:
        operation_no = f"HIS-{oper_id}"
    elif start is not None:
        operation_no = f"SM-SCHED-{start.strftime('%Y%m%d%H%M')}"
    else:
        operation_no = ""
    return {
        "patient_id": patient_id,
        "visit_id": visit_id,
        "operation_no": operation_no,
        "operation_desc": operation_name,
        "operating_date": start,           # 排台行= SCHEDULED_DATE_TIME（开台卡口用）
        "operating_end_date": end,
        "dept_code": dept_stayed,          # 患者所在临床科室（非手术室编码）
        "operator_id": surgeon,            # 主刀 6 位工号（实证 SURGEON 存工号）
        "operator": "",
        "first_assistant_id": first_assistant,
        "emergency_indicator": emergency_indicator,
        "operation_scale": operation_scale,
        "operation_class": operation_class,
        "anesthesia_method": anesthesia_method,
        "operating_room": operating_room,
        "operation_type": None,            # HIS 源无此列（field_not_in 过滤按缺列放行）
        "source": "sm_scheduled" if scheduled else "his_operation_master",
    }


# ---- 5. 职称字典（TTL 缓存） ----


_staff_cache: dict[str, Any] = {"map": None, "fetched_at": 0.0}
_staff_lock = threading.Lock()


def get_staff_title_map(
    *, connect: Callable[[], Any] | None = None, ttl: float = STAFF_TTL_SECONDS,
) -> dict[str, str]:
    """EMP_NO/NAME → TITLE 合并映射（TTL 3600s 内存缓存，线程安全）。

    返回单个 dict：工号与姓名同键空间（工号 6 位数字、姓名中文，实测无碰撞；
    查找顺序由调用方先工号后姓名兜底）。缓存键不区分注入的 connect（本地
    测试用 reset_staff_cache() 显式清理）。
    """
    now = time.monotonic()
    with _staff_lock:
        if _staff_cache["map"] is not None and now - _staff_cache["fetched_at"] < ttl:
            return _staff_cache["map"]

    conn_factory = connect or _get_connection
    conn = conn_factory()
    merged: dict[str, str] = {}
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT EMP_NO, NAME, TITLE FROM HIS.STAFF_DICT")
            for row in cur.fetchall():
                emp_no = _as_text(row[0])
                name = _as_text(row[1])
                title = _as_text(row[2])
                if emp_no and title:
                    merged[emp_no] = title
                if name and title:
                    merged[name] = title
        finally:
            cur.close()
    finally:
        conn.close()
    with _staff_lock:
        _staff_cache["map"] = merged
        _staff_cache["fetched_at"] = time.monotonic()
    return merged


def reset_staff_cache() -> None:
    """清空职称缓存（测试与手动刷新用）。"""
    with _staff_lock:
        _staff_cache["map"] = None
        _staff_cache["fetched_at"] = 0.0


# ---- 2026-11-14 补丁 3：JHEMR.V_QYBR 患者元信息补齐 ----

# V_QYBR 实证列（应用 Oracle 账号已有 SELECT；pat_visit.pat_name 100% NULL，
# 不补齐则 LOCK_EMR 外插会 100% 因缺姓名 BLOCKED）。
V_QYBR_META_BATCH = 50
# 单轮查库封顶（超出留空下轮增量补齐；防大科室全量出院患者拖死扫描）。
V_QYBR_META_LIMIT = 600
# 进程内 TTL 缓存（2026-11-14 假增量修复）：patient_context 每轮内存重建不落库，
# 只靠 [:600] 截断会让 pairs 后半段的手术/抢救/死亡患者永远拿不到姓名——
# 已查键缓存 1 小时，未命中键才占用本轮 600 查库配额，跨轮增量补齐。
V_QYBR_META_CACHE_TTL = 3600.0
_visit_meta_cache: dict[tuple[str, str], tuple[dict, float]] = {}
_visit_meta_lock = threading.Lock()


def reset_visit_meta_cache() -> None:
    """清空 V_QYBR 元信息缓存（单测与手动刷新用）。"""
    with _visit_meta_lock:
        _visit_meta_cache.clear()


def fetch_patient_visit_meta(
    pairs: Sequence[tuple[str, str]],
    *,
    connect: Callable[[], Any] | None = None,
) -> dict[tuple[str, str], dict]:
    """按 (patient_id, visit_id) 批量查 JHEMR.V_QYBR 补齐姓名/科室/管床工号。

    - 每批 ≤200 对（Oracle 11g 兼容：("患者ID"=:p_i AND "次数"=:v_i) OR ...）；
    - 返回 (pid, vid) -> {patient_name, dept_code(所在 or 出院科室编码),
      doctor_in_charge_id(管床医生编号)}；同键多行取首行；
    - 查询异常降级返回 {}（不中断主扫描）。
    """
    normalized: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pair in pairs or ():
        try:
            pid, vid = str(pair[0]).strip(), str(pair[1]).strip()
        except (IndexError, TypeError):
            continue
        if pid and vid and (pid, vid) not in seen:
            seen.add((pid, vid))
            normalized.append((pid, vid))
    if not normalized:
        return {}

    # P0 修复（2026-11-14 部署实测）：200 对 OR 双列绑定对 V_QYBR 视图全表扫，
    # 单批可达分钟级并拖死扫描进程——改"患者ID IN 单列批量 + Python 端按
    # (pid,vid) 过滤"（IN 单列可走索引、绑定数减半），批降 50。
    # 假增量修复（同日补充）：已查键走 TTL 缓存（1h），仅未命中键占用本轮
    # 600 查库配额——pairs 后半段的手术/抢救/死亡患者跨轮也能拿到姓名。
    now = time.monotonic()
    fresh: dict[tuple[str, str], dict] = {}
    with _visit_meta_lock:
        for pair in normalized:
            cached = _visit_meta_cache.get(pair)
            if cached is not None and now - cached[1] < V_QYBR_META_CACHE_TTL:
                fresh[pair] = cached[0]
    uncached = [pair for pair in normalized if pair not in fresh]
    if len(uncached) > V_QYBR_META_LIMIT:
        logger.warning(
            "V_QYBR 元信息查库封顶：未缓存 %d 对超上限 %d，本轮仅查前 %d 对"
            "（已缓存 %d 对直接命中；其余下轮增量补齐）",
            len(uncached), V_QYBR_META_LIMIT, V_QYBR_META_LIMIT, len(fresh),
        )
        uncached = uncached[:V_QYBR_META_LIMIT]
    fetched = _fetch_visit_meta_uncached(uncached, connect=connect)
    fetched_at = time.monotonic()
    with _visit_meta_lock:
        for pair, info in fetched.items():
            _visit_meta_cache[pair] = (info, fetched_at)
    fresh.update(fetched)
    return fresh


def _fetch_visit_meta_uncached(
    normalized: list[tuple[str, str]],
    *,
    connect: Callable[[], Any] | None = None,
) -> dict[tuple[str, str], dict]:
    """按未缓存键查 V_QYBR（调用方保证 ≤V_QYBR_META_LIMIT）。"""
    if not normalized:
        return {}
    wanted = set(normalized)

    conn_factory = connect or _get_connection
    result: dict[tuple[str, str], dict] = {}
    try:
        conn = conn_factory()
    except Exception:
        logger.exception("V_QYBR 元信息连接失败（降级为空，不中断主扫描）")
        return {}
    try:
        cur = conn.cursor()
        try:
            # 2026-11-15 P0-1：V_QYBR 失效（ORA-04063/01031）自动降级基表内联视图
            # （execute_with_view_compat + 5 分钟熔断），恢复时效台账真实患者姓名。
            from app.services.oracle_patient_view_compat import execute_with_view_compat

            for offset in range(0, len(normalized), V_QYBR_META_BATCH):
                batch = normalized[offset:offset + V_QYBR_META_BATCH]
                pids = sorted({pid for pid, _ in batch})
                binds = {f"p{i}": pid for i, pid in enumerate(pids)}
                in_sql = ", ".join(f":{name}" for name in binds)
                sql = (
                    'SELECT "患者ID", "次数", "患者姓名", "所在科室编码", "出院科室编码", "管床医生编号" '
                    'FROM JHEMR.V_QYBR WHERE "患者ID" IN (' + in_sql + ")"
                )
                execute_with_view_compat(cur, sql, binds)
                for row in cur.fetchall():
                    key = (_as_text(row[0]), _as_text(row[1]))
                    if key in result or key not in wanted:
                        continue  # 同键多行取首行；同患者其他住院次不纳入
                    result[key] = {
                        "patient_name": _as_text(row[2]),
                        "dept_code": _as_text(row[3]) or _as_text(row[4]),
                        "doctor_in_charge_id": _as_text(row[5]),
                    }
        finally:
            cur.close()
    except Exception:
        logger.exception("V_QYBR 元信息查询失败（降级返回已取部分，不中断主扫描）")
    finally:
        conn.close()
    return result


# ---- 2026-11-14 P0 轮：工号→姓名映射（台账中文化展示用，TTL 同职称缓存） ----

_staff_name_cache: dict[str, Any] = {"map": None, "fetched_at": 0.0}


def get_staff_name_map(
    *, connect: Callable[[], Any] | None = None, ttl: float = STAFF_TTL_SECONDS
) -> dict[str, str]:
    """EMP_NO → NAME（HIS.STAFF_DICT，TTL 3600s；查询失败降级空表不阻断请求）。"""
    now = time.monotonic()
    with _staff_lock:
        if _staff_name_cache["map"] is not None and now - _staff_name_cache["fetched_at"] < ttl:
            return _staff_name_cache["map"]
    try:
        conn_factory = connect or _get_connection
        conn = conn_factory()
        merged: dict[str, str] = {}
        try:
            cur = conn.cursor()
            try:
                cur.execute("SELECT EMP_NO, NAME FROM HIS.STAFF_DICT")
                for row in cur.fetchall():
                    emp_no, name = _as_text(row[0]), _as_text(row[1])
                    if emp_no and name:
                        merged[emp_no] = name
            finally:
                cur.close()
        finally:
            conn.close()
    except Exception:
        logger.exception("HIS.STAFF_DICT 姓名映射取数失败（台账姓名展示降级为空）")
        return {}
    with _staff_lock:
        _staff_name_cache["map"] = merged
        _staff_name_cache["fetched_at"] = time.monotonic()
    return merged
