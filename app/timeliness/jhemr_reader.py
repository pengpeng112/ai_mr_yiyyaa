"""
JHEMR 多表只读访问层（病历时效质控 T1）。

设计约束（主设计文档 §15 T1 / §15.0 第 4 条 / D2、D8）：
- 全部语句为只读查询；连接后立即 set_session(readonly=True, autocommit=True)
  并执行 SET statement_timeout（毫秒，来自配置）；
- 只读账号固定 aizk_user（D2）；查询遇权限不足（SQLSTATE 42501 /
  psycopg2 InsufficientPrivilege）抛 TimelinessPermissionMissing(表名)；
- SQL 全部用 %s 参数化，严禁拼接患者号；患者对每批不超过
  MAX_PAIRS_PER_BATCH=500，自动分批；
- Vastbase/openGauss 的 cursor.description 返回大写列名，统一转小写
  （AGENTS.md「Vastbase Gotchas」）。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Iterator, Sequence

from app.timeliness.config import (
    READONLY_USERNAME_FIXED,
    TimelinessPermissionMissing,
    resolve_jhemr_readonly,
)

logger = logging.getLogger(__name__)

SCHEMA_NAME = "jhemr"

# 患者对单批上限（T1 实现要求 4：一次不超过 500 对，自动分批）。
MAX_PAIRS_PER_BATCH = 500

# PostgreSQL/openGauss 权限不足的 SQLSTATE（psycopg2.errors.InsufficientPrivilege）。
SQLSTATE_INSUFFICIENT_PRIVILEGE = "42501"

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")

# T1 固定 7 张表；新增表须同步主设计文档 §18.2 的授权清单。
T_PATS_IN_HOSPITAL = "pats_in_hospital"
T_PAT_VISIT = "pat_visit"
T_JHMR_FILE_INDEX = "jhmr_file_index"
T_OPERATION = "operation"
T_EMR_TREAMENT_APPLY = "emr_treament_apply"
T_EMR_ONLINE_MONITOR = "emr_online_monitor"
T_JHMR_MONITOR_LIMIT_LOG = "jhmr_monitor_limit_log"
# 2026-11-10 §18.2 授权新增：会诊主表（急/普类别 consult_class 仅在此表）。
T_EMR_TREAMENT_APPLY_MASTER = "emr_treament_apply_master"

# 各表选取列（§15 T1 必取字段）。2026-11-10 §18.2 授权后经 sjzc 只读通道
# 对 information_schema 全列核验：下列列名全部真实存在（证据
# review/timeliness/T1_columns.json，770 列/8 表）。
_FILE_COLUMNS: tuple[str, ...] = (
    "patient_id",
    "visit_id",
    "file_unique_id",
    "mr_class",
    "topic",
    "monitor_code",
    "file_flag",
    "create_date_time",
    "first_mr_sign_date_time",
    "last_modify_date_time",
    "topic_title_name",
    "dept_code",
    "delete_flag",
    # 2026-11-14 七规则轮追加（任务书 §1.2 已核实真实存在；实证见
    # jhemr_real_columns_20261110.json）：审签身份约束（主刀审签/主治及以上
    # 查房审签）依赖的创建/文书/最后修改医师工号与姓名列。
    "creator_id",
    "creator_name",
    "topic_doctor_id",
    "topic_doctor_name",
    "last_modify_user_id",
    "last_modify_user_name",
)
_OPERATION_COLUMNS: tuple[str, ...] = (
    "patient_id",
    "visit_id",
    "operation_no",
    "operation_desc",
    "operating_date",
    "operating_end_date",  # 手术结束时间（2026-11-10 实证：operation 表唯一结束时间列）
    # 2026-11-13 返工补齐（活库实证，见 jhemr_real_columns_20261110.json）：
    # 手术科室编码常为手术室编码，责任科室优先取患者住院临床科室（scanner 注入）。
    "operation_dept_code",
    "operator_id",         # 主刀工号（责任医生优先级最高）
    "operator",            # 主刀姓名
    # 2026-11-14 扩围补齐（两列均在 jhemr_real_columns_20261110.json 实证：
    # operation_type 第 16 列 / operating_grade 第 21 列）：
    "operation_type",      # '0'=床旁/门诊小操作（扩围规则默认排除）
    "operating_grade",     # 手术等级
)
# consult_class 实证仅在 emr_treament_apply_master（8 行，稀疏），经 applyid LEFT JOIN 取。
_CONSULT_COLUMNS: tuple[str, ...] = (
    "applyid",
    "patient_id",
    "visit_id",
    "apply_type",
    "apply_date_time",
    "status",
    "treat_dept_code",
    "treat_date_time",
    # 2026-11-13 返工补齐（活库实证）：会诊申请/拟邀请科室与人员，供触发器映射
    # dept_code / responsible_doctor_id（会诊责任归属=会诊科室/医师）。
    "apply_dept_code",
    "apply_user_id",
    "treat_user_id",
    "plan_treat_dept_code",
    "plan_treat_user_id",
)


def _validate_identifier(name: str) -> str:
    """白名单校验 SQL 标识符（表/列名均为模块内常量，不放用户输入）。"""
    if not name or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"非法 SQL 标识符: {name!r}")
    return name


def _qualified(table: str) -> str:
    return f'"{SCHEMA_NAME}"."{_validate_identifier(table)}"'


def _is_insufficient_privilege(exc: BaseException) -> bool:
    """识别权限不足错误：优先 DBAPI pgcode=42501，其次异常类名/文本兜底。"""
    if getattr(exc, "pgcode", None) == SQLSTATE_INSUFFICIENT_PRIVILEGE:
        return True
    if "insufficientprivilege" in type(exc).__name__.lower():
        return True
    return "permission denied" in str(exc).lower()


def get_jhemr_readonly_connection(section: dict | None = None, *, connect: Callable[..., Any] | None = None):
    """建立 JHEMR 只读连接（调用方负责关闭）。

    - 会话立即置 readonly=True + autocommit=True；
    - 随后执行 SET statement_timeout（毫秒；失败视为环境不满足，直接抛错，
      不带超时的扫描连接不允许使用）；
    - ``connect`` 仅供测试注入假连接工厂；生产路径延迟导入 psycopg2
      （本机/容器未装驱动时模块仍可导入，便于纯单元测试）。
    """
    if connect is None:
        import psycopg2

        connect_factory: Callable[..., Any] = psycopg2.connect
    else:
        connect_factory = connect

    params = resolve_jhemr_readonly(section)
    conn_kwargs: dict[str, Any] = {
        "host": params["host"],
        "port": params["port"],
        "dbname": params["database"],
        "user": READONLY_USERNAME_FIXED,
        "password": params["password"],
        "connect_timeout": params["connect_timeout_seconds"],
    }
    # sslmode 为可选项：仅当配置显式提供时才传（AGENTS.md Vastbase 约定）。
    if params["sslmode"]:
        conn_kwargs["sslmode"] = params["sslmode"]

    conn = connect_factory(**conn_kwargs)
    conn.set_session(readonly=True, autocommit=True)
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = %s", (int(params["statement_timeout_ms"]),))
    return conn


def _normalize_pairs(patient_visits: Sequence[Sequence[Any]] | None) -> list[tuple[str, str]]:
    """规整患者对列表：去重保序，空值报错。"""
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in patient_visits or ():
        try:
            pid, vid = item[0], item[1]
        except (IndexError, TypeError) as exc:
            raise ValueError("patient_visits 元素须为 (patient_id, visit_id)") from exc
        pid = str(pid or "").strip()
        vid = str(vid or "").strip()
        if not pid or not vid:
            raise ValueError("patient_visits 中 patient_id/visit_id 不能为空")
        key = (pid, vid)
        if key not in seen:
            seen.add(key)
            pairs.append(key)
    return pairs


def _iter_batches(pairs: list[tuple[str, str]], size: int = MAX_PAIRS_PER_BATCH) -> Iterator[list[tuple[str, str]]]:
    for start in range(0, len(pairs), size):
        yield pairs[start : start + size]


def _execute_select(cur: Any, sql: str, params: Sequence[Any], *, table: str) -> list[dict]:
    """执行一条只读查询并把结果映射为小写列名的 dict 列表。"""
    try:
        cur.execute(sql, list(params))
        columns = [desc[0].lower() for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
    except Exception as exc:
        if _is_insufficient_privilege(exc):
            raise TimelinessPermissionMissing(f"{SCHEMA_NAME}.{table}") from exc
        raise


def _select_with_pairs(
    pairs: list[tuple[str, str]],
    build_sql: Callable[[list[tuple[str, str]]], tuple[str, list[Any]]],
    *,
    table: str,
    conn: Any,
) -> list[dict]:
    """按批次执行患者对过滤查询（单连接复用，批间不提交任何变更）。"""
    results: list[dict] = []
    with conn.cursor() as cur:
        for batch in _iter_batches(pairs):
            sql, params = build_sql(batch)
            results.extend(_execute_select(cur, sql, params, table=table))
    return results


def _pairs_values_sql(batch: list[tuple[str, str]]) -> str:
    """生成 WITH target(pid, vid) AS (VALUES ...) 的占位符骨架。

    VALUES 里只有 %s 占位符骨架（数量由批大小决定），患者号一律走参数。
    """
    placeholders = ", ".join(["(%s, %s)"] * len(batch))
    return f"WITH target(pid, vid) AS (VALUES {placeholders})"


def list_inpatients() -> list[dict]:
    """在院患者：pats_in_hospital 联 pat_visit。

    取 patient_id, visit_id, dept_code, admission_date_time（§10.1/E8 实证字段），
    另取 pat_visit 侧出院科室/出院时间供后续规则使用（列名 2026-11-10 实证核对通过）。
    2026-11-13 返工补齐（活库实证）：``pats_in_hospital.doctor_in_charge`` 存的是
    **中文姓名**，6 位医生工号在 ``pat_visit.doctor_in_charge_id``；另带
    attending_doctor_id / discharge_disposition / death_date_time 供责任医生映射与
    死亡口径判定（活库近 180 天 207 例死亡 death_date_time 100% 为 NULL，死亡离院
    时间记在 discharge_date_time，判定须看 discharge_disposition）。
    """
    sql = f"""
        SELECT
            p.patient_id,
            p.visit_id,
            p.dept_code,
            p.admission_date_time,
            v.dept_discharge_from,
            v.discharge_date_time,
            v.doctor_in_charge_id,
            p.doctor_in_charge,
            v.attending_doctor_id,
            v.discharge_disposition,
            v.death_date_time
        FROM {_qualified(T_PATS_IN_HOSPITAL)} p
        JOIN {_qualified(T_PAT_VISIT)} v
          ON v.patient_id = p.patient_id AND v.visit_id = p.visit_id
        ORDER BY p.patient_id, p.visit_id
    """
    conn = get_jhemr_readonly_connection()
    try:
        with conn.cursor() as cur:
            return _execute_select(cur, sql, [], table=T_PATS_IN_HOSPITAL)
    finally:
        conn.close()


def list_recent_discharges(days: int) -> list[dict]:
    """近 N 天出院患者：pat_visit，按 discharge_date_time 过滤（参数化天数）。

    2026-11-13 返工补齐：``dept_discharge_from AS dept_code``（出院记录事件的科室
    归属此前只带 dept_discharge_from，试点 dept_scope 过滤 100% 归零）；另带
    doctor_in_charge_id / doctor_in_charge / discharge_disposition / death_date_time
    （死亡口径：discharge_disposition in ('死亡','5') 或 death_date_time 非空）。
    """
    days_int = int(days)
    if days_int <= 0:
        raise ValueError("days 必须为正整数")
    sql = f"""
        SELECT
            patient_id,
            visit_id,
            dept_discharge_from AS dept_code,
            dept_discharge_from,
            discharge_date_time,
            doctor_in_charge_id,
            doctor_in_charge,
            discharge_disposition,
            death_date_time
        FROM {_qualified(T_PAT_VISIT)}
        WHERE discharge_date_time IS NOT NULL
          AND discharge_date_time >= CURRENT_TIMESTAMP - (%s * interval '1 day')
        ORDER BY discharge_date_time DESC
    """
    conn = get_jhemr_readonly_connection()
    try:
        with conn.cursor() as cur:
            return _execute_select(cur, sql, [days_int], table=T_PAT_VISIT)
    finally:
        conn.close()


def list_files(patient_visits: Sequence[Sequence[Any]]) -> list[dict]:
    """按患者住院次批量取文书索引 jhmr_file_index（T1 必取 13 列）。"""
    pairs = _normalize_pairs(patient_visits)
    if not pairs:
        return []
    select_columns = ", ".join(
        f"f.{_validate_identifier(col)}" for col in _FILE_COLUMNS
    )

    def build_sql(batch: list[tuple[str, str]]) -> tuple[str, list[Any]]:
        sql = f"""
            {_pairs_values_sql(batch)}
            SELECT {select_columns}
            FROM {_qualified(T_JHMR_FILE_INDEX)} f
            JOIN target t ON f.patient_id = t.pid AND f.visit_id = t.vid
            ORDER BY f.patient_id, f.visit_id, f.file_unique_id
        """
        params: list[Any] = []
        for pid, vid in batch:
            params.extend([pid, vid])
        return sql, params

    conn = get_jhemr_readonly_connection()
    try:
        return _select_with_pairs(pairs, build_sql, table=T_JHMR_FILE_INDEX, conn=conn)
    finally:
        conn.close()


def list_operations(patient_visits: Sequence[Sequence[Any]]) -> list[dict]:
    """按患者住院次批量取手术 operation（含 operating_end_date 结束时间，2026-11-10 实证）。"""
    pairs = _normalize_pairs(patient_visits)
    if not pairs:
        return []
    select_columns = ", ".join(
        f"o.{_validate_identifier(col)}" for col in _OPERATION_COLUMNS
    )

    def build_sql(batch: list[tuple[str, str]]) -> tuple[str, list[Any]]:
        sql = f"""
            {_pairs_values_sql(batch)}
            SELECT {select_columns}
            FROM {_qualified(T_OPERATION)} o
            JOIN target t ON o.patient_id = t.pid AND o.visit_id = t.vid
            ORDER BY o.patient_id, o.visit_id, o.operating_date
        """
        params: list[Any] = []
        for pid, vid in batch:
            params.extend([pid, vid])
        return sql, params

    conn = get_jhemr_readonly_connection()
    try:
        return _select_with_pairs(pairs, build_sql, table=T_OPERATION, conn=conn)
    finally:
        conn.close()


def list_consult_applies(since: Any) -> list[dict]:
    """取 since 起的会诊申请 emr_treament_apply，LEFT JOIN master 取 consult_class。

    2026-11-10 实证列核对：consult_class 仅存在于 emr_treament_apply_master
    （applyid 联结，master 仅 8 行稀疏，必须 LEFT JOIN 保住申请行）；急/普区分
    的值域实证 apply.apply_type=KK/YY、master.consult_class=1/2，但"急/普"与
    取值的对应口径未获业务确认，不猜测（值域防猜测红线），由 T4/规则配置裁定。
    """
    if since is None or str(since).strip() == "":
        raise ValueError("since 不能为空")
    select_columns = ", ".join(
        f"a.{_validate_identifier(col)}" for col in _CONSULT_COLUMNS
    )
    sql = f"""
        SELECT {select_columns}, m.consult_class
        FROM {_qualified(T_EMR_TREAMENT_APPLY)} a
        LEFT JOIN {_qualified(T_EMR_TREAMENT_APPLY_MASTER)} m
          ON m.applyid = a.applyid
        WHERE a.apply_date_time >= %s
        ORDER BY a.apply_date_time
    """
    conn = get_jhemr_readonly_connection()
    try:
        with conn.cursor() as cur:
            return _execute_select(cur, sql, [since], table=T_EMR_TREAMENT_APPLY)
    finally:
        conn.close()


def list_monitor_rows(
    patient_visits: Sequence[Sequence[Any]], item_codes: Sequence[str] | None = None
) -> list[dict]:
    """按患者住院次批量取原生监控行 emr_online_monitor（全部列，SELECT m.*）。

    完整列清单已实证（23 列，见 fixture）；item_codes 为监控码值过滤
    （如 JH04.02.002），作为查询参数传入，空列表/None 表示不过滤。
    """
    pairs = _normalize_pairs(patient_visits)
    if not pairs:
        return []
    codes = [str(c or "").strip() for c in (item_codes or ()) if str(c or "").strip()]

    def build_sql(batch: list[tuple[str, str]]) -> tuple[str, list[Any]]:
        # 占位符顺序 = SQL 中出现顺序：先 VALUES 的患者对，再 item_code IN 的监控码值。
        params: list[Any] = []
        for pid, vid in batch:
            params.extend([pid, vid])
        code_filter = ""
        if codes:
            code_placeholders = ", ".join(["%s"] * len(codes))
            code_filter = f"WHERE m.item_code IN ({code_placeholders})"
            params.extend(codes)
        sql = f"""
            {_pairs_values_sql(batch)}
            SELECT m.*
            FROM {_qualified(T_EMR_ONLINE_MONITOR)} m
            JOIN target t ON m.patient_id = t.pid AND m.visit_id = t.vid
            {code_filter}
            ORDER BY m.patient_id, m.visit_id
        """
        return sql, params

    conn = get_jhemr_readonly_connection()
    try:
        return _select_with_pairs(pairs, build_sql, table=T_EMR_ONLINE_MONITOR, conn=conn)
    finally:
        conn.close()


def list_limit_logs(since: Any) -> list[dict]:
    """取 since 起的超时申请/审批日志 jhmr_monitor_limit_log（全部列）。

    时间列 apply_date_time 已实证（2026-11-10）；apply_reason 列生产已天然存在
    （§2.3 步骤 1 的补列 DDL 实测不再需要）。
    """
    if since is None or str(since).strip() == "":
        raise ValueError("since 不能为空")
    sql = f"""
        SELECT l.*
        FROM {_qualified(T_JHMR_MONITOR_LIMIT_LOG)} l
        WHERE l.apply_date_time >= %s
        ORDER BY l.apply_date_time
    """
    conn = get_jhemr_readonly_connection()
    try:
        with conn.cursor() as cur:
            return _execute_select(cur, sql, [since], table=T_JHMR_MONITOR_LIMIT_LOG)
    finally:
        conn.close()


# 2026-11-14 七规则轮：院内病历签收节假日/调休表（与 JHEMR 客户端 IsTimeOut 同源）。
T_JHMR_HOLIDAY = "jhmr_mrreceivesignholiday"


def list_holidays() -> list[dict]:
    """取院内节假日/调休表 jhmr_mrreceivesignholiday（holidaydate, type）。

    type=0 休息日/节假日；type=1 调休上班日（任务书 §1.2）。aizk_user 缺该表
    SELECT 权限时抛 TimelinessPermissionMissing（SQLSTATE 42501），由扫描层
    回退周一~周五工作日逻辑并提示补授权，不中断主扫描。
    """
    sql = f"""
        SELECT h.holidaydate, h.type
        FROM {_qualified(T_JHMR_HOLIDAY)} h
        ORDER BY h.holidaydate
    """
    conn = get_jhemr_readonly_connection()
    try:
        with conn.cursor() as cur:
            return _execute_select(cur, sql, [], table=T_JHMR_HOLIDAY)
    finally:
        conn.close()
