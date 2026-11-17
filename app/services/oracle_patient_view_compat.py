# -*- coding: utf-8 -*-
"""Oracle 患者视图兼容/降级辅助（2026-11-15 P0-1：应用侧永久免疫 V_QYBR/V_CYBR 失效）。

背景（2026-11-15 线上只读实证）：
- `10.10.8.216` 的 `JHEMR.V_CYBR` 历史上因 Oracle 视图不继承角色权限处于
  INVALID（ORA-01031），连带 `JHEMR.V_QYBR` 报 `ORA-04063: view "JHEMR.V_QYBR" 有错误`，
  导致原有 AI 质控取数全断；
- 会话账号对底层基表 `HIS.PAT_VISIT / PAT_MASTER_INDEX / PATS_IN_HOSPITAL /
  DEPT_DICT / STAFF_DICT / DIAGNOSIS / OPERATION` 与在院视图 `JHEMR.V_ZYBR`
  均可正常 SELECT（all_tab_columns 实证存档
  review/timeliness/his_columns_probe_20261115.json；40 列契约逐列一致）。

本模块提供：
1. `is_invalid_view_error()`——识别 ORA-04063 / ORA-01031（含中文服务端文案）；
2. 5 分钟进程内熔断记忆（`mark_view_broken` / `is_view_broken`）——一旦视图失效，
   5 分钟内所有取数入口直接走等价 SQL，不再每次先撞错浪费连接；
3. `inline_patient_visit_view()`——基于 HIS 基表的等价只读内联括号视图，严格对齐
   V_QYBR/V_CYBR/V_ZYBR 的 40 列契约（列名逐列一致）；
4. `inline_inpatient_view()`——在院场景用同构在院视图 V_ZYBR 平替（零基表 JOIN 成本）；
5. `rewrite_view_refs()`——受控表名重写：仅把 `jhemr.v_qybr` / `jhemr.v_cybr`
   token 替换为内联括号视图（保留原别名与其余 SQL 文本），不篡改数据库存储的
   原始配置文本；
6. `execute_with_view_compat()`——统一执行包装：原 SQL 先行（熔断期内直接重写），
   捕获视图失效错误 → 熔断记录 → 重写重试一次。

降级口径披露（写进代码供后续维护者判断）：
- 核心消费列（患者ID/次数/住院号/患者姓名/入院日期/出院日期/所在·出院·入院科室
  编码与名称/管床医生编号与姓名/是否出院）从基表精确映射；
- 诊断列（入院诊断/出院主诊断/其他诊断1..5）与手术列（手术/手术日期/手术1..5 及
  日期1..5）按 DIAGNOSIS.DIAGNOSIS_TYPE+DIAGNOSIS_NO、OPERATION.OPERATION_NO
  排序 ROW_NUMBER 尽力映射（服务端诊断类型取值字典未授权实证，降级场景为展示
  用途、语义偏差可接受）；
- 年龄列按 `TRUNC(MONTHS_BETWEEN(入院日期, 出生日期)/12)` 计算；
- 门诊医师/护理级别暂以 NULL 兜底（基表无直接等价列，降级场景非关键消费列）；
- 内联 SQL 仅限受控降级重试使用，调用方均带患者/日期级过滤条件（严禁无界全表扫）。
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any

# ---- 40 列契约（与 JHEMR.V_QYBR / V_CYBR / V_ZYBR 逐列一致，2026-11-15 all_tab_columns 实证） ----
PATIENT_VIEW_COLUMNS: tuple[str, ...] = (
    "患者ID", "次数", "住院号", "患者姓名", "出生日期", "性别", "年龄",
    "入院日期", "出院日期", "入院诊断", "入院病情", "管床医生编号", "管床医生",
    "门诊医师", "护理级别", "所在科室编码", "所在科室名称", "是否出院",
    "入院科室编码", "入院科室名称", "出院科室编码", "出院科室名称",
    "出院主诊断", "出院其他诊断1", "出院其他诊断2", "出院其他诊断3",
    "出院其他诊断4", "出院其他诊断5", "手术", "手术日期",
    "手术1", "手术日期1", "手术2", "手术日期2", "手术3", "手术日期3",
    "手术4", "手术日期4", "手术5", "手术日期5",
)

# 受控重写只匹配这两个视图 token（大小写不敏感、词边界）。
_VIEW_REF_PATTERN = re.compile(r"\bjhemr\.(v_qybr|v_cybr)\b", re.IGNORECASE)

# 视图失效错误识别：ORA-04063（视图/包有错误）、ORA-01031（权限不足导致视图
# 编译失败）；同时兼容中文服务端/驱动文案「有错误」组合。
_INVALID_VIEW_MARKERS = (
    "ora-04063",
    "ora-01031",
    "view \"jhemr.v_qybr\" 有错误",
    "view \"jhemr.v_cybr\" 有错误",
    "有错误",
)

# ---- 5 分钟进程内熔断记忆（key = 视图逻辑名，如 "jhemr.v_qybr"） ----
_BROKEN_TTL_SECONDS = 300.0
_broken_until: dict[str, float] = {}
_broken_lock = threading.Lock()


def is_invalid_view_error(exc: BaseException | None) -> bool:
    """判断异常是否为患者视图失效类错误（ORA-04063 / ORA-01031）。"""
    if exc is None:
        return False
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _INVALID_VIEW_MARKERS)


def mark_view_broken(name: str = "jhemr.v_qybr") -> None:
    """记录视图失效：5 分钟内 `is_view_broken` 返回 True（直接走降级 SQL）。"""
    with _broken_lock:
        _broken_until[str(name).strip().lower()] = time.monotonic() + _BROKEN_TTL_SECONDS


def is_view_broken(name: str = "jhemr.v_qybr") -> bool:
    with _broken_lock:
        deadline = _broken_until.get(str(name).strip().lower())
        if deadline is None:
            return False
        if time.monotonic() >= deadline:
            # 熔断窗口过期：清除并恢复直连尝试
            _broken_until.pop(str(name).strip().lower(), None)
            return False
        return True


def reset_broken_state() -> None:
    """清空熔断状态（单测与配置变更后手动恢复用）。"""
    with _broken_lock:
        _broken_until.clear()


# ---- 等价内联括号视图 ----

_INLINE_FROM_CLAUSE = """
FROM his.PAT_VISIT v
JOIN his.PAT_MASTER_INDEX m ON m.PATIENT_ID = v.PATIENT_ID
LEFT JOIN his.DEPT_DICT adm_dept ON adm_dept.DEPT_CODE = v.DEPT_ADMISSION_TO
LEFT JOIN his.DEPT_DICT dis_dept ON dis_dept.DEPT_CODE = v.DEPT_DISCHARGE_FROM
LEFT JOIN his.STAFF_DICT st ON st.EMP_NO = v.DOCTOR_IN_CHARGE
LEFT JOIN (
    SELECT PATIENT_ID, VISIT_ID, DIAGNOSIS_DESC,
           ROW_NUMBER() OVER (PARTITION BY PATIENT_ID, VISIT_ID
                              ORDER BY DIAGNOSIS_TYPE, DIAGNOSIS_NO) AS dx_rn
    FROM his.DIAGNOSIS
) dx ON dx.PATIENT_ID = v.PATIENT_ID AND dx.VISIT_ID = v.VISIT_ID
     AND dx.dx_rn BETWEEN 1 AND 7
LEFT JOIN (
    SELECT PATIENT_ID, VISIT_ID, OPERATION_DESC, OPERATING_DATE,
           ROW_NUMBER() OVER (PARTITION BY PATIENT_ID, VISIT_ID
                              ORDER BY OPERATION_NO) AS op_rn
    FROM his.OPERATION
) op ON op.PATIENT_ID = v.PATIENT_ID AND op.VISIT_ID = v.VISIT_ID
     AND op.op_rn BETWEEN 1 AND 6
"""


def _inline_select_prefix() -> str:
    # 列序契约：入院诊断(dx_rn=1)、出院主诊断(dx_rn=2)、出院其他诊断1..5(dx_rn=3..7)；
    # 手术 6 组：手术/手术日期(op_rn=1)、手术1..5 与手术日期1..5(op_rn=2..6)。
    dx_cols = []
    for idx in range(1, 6):
        dx_cols.append(
            f"MAX(CASE WHEN dx.dx_rn = {idx + 2} THEN dx.DIAGNOSIS_DESC END) "
            f'AS "出院其他诊断{idx}"'
        )
    op_pairs = []
    for idx in range(0, 6):
        suffix = "" if idx == 0 else str(idx)
        op_pairs.append(
            f"MAX(CASE WHEN op.op_rn = {idx + 1} THEN op.OPERATION_DESC END) AS \"手术{suffix}\""
        )
        op_pairs.append(
            f"MAX(CASE WHEN op.op_rn = {idx + 1} THEN op.OPERATING_DATE END) AS \"手术日期{suffix}\""
        )
    return (
        'SELECT v.PATIENT_ID AS "患者ID", v.VISIT_ID AS "次数", v.INP_NO AS "住院号", '
        'm.NAME AS "患者姓名", m.DATE_OF_BIRTH AS "出生日期", m.SEX AS "性别", '
        'MAX(TRUNC(MONTHS_BETWEEN(v.ADMISSION_DATE_TIME, m.DATE_OF_BIRTH) / 12)) AS "年龄", '
        'v.ADMISSION_DATE_TIME AS "入院日期", v.DISCHARGE_DATE_TIME AS "出院日期", '
        'MAX(CASE WHEN dx.dx_rn = 1 THEN dx.DIAGNOSIS_DESC END) AS "入院诊断", '
        'v.PAT_ADM_CONDITION AS "入院病情", '
        'v.DOCTOR_IN_CHARGE AS "管床医生编号", st.NAME AS "管床医生", '
        'NULL AS "门诊医师", NULL AS "护理级别", '
        'v.DEPT_ADMISSION_TO AS "所在科室编码", adm_dept.DEPT_NAME AS "所在科室名称", '
        "MAX(CASE WHEN v.DISCHARGE_DATE_TIME IS NULL THEN '0' ELSE '1' END) AS \"是否出院\", "
        'v.DEPT_ADMISSION_TO AS "入院科室编码", adm_dept.DEPT_NAME AS "入院科室名称", '
        'v.DEPT_DISCHARGE_FROM AS "出院科室编码", dis_dept.DEPT_NAME AS "出院科室名称", '
        'MAX(CASE WHEN dx.dx_rn = 2 THEN dx.DIAGNOSIS_DESC END) AS "出院主诊断", '
        + ", ".join(dx_cols) + ", "
        + ", ".join(op_pairs)
    )


def inline_patient_visit_view(*, discharged_only: bool = False, alias: str | None = None) -> str:
    """出院/全量患者等价内联括号视图（基于 HIS 基表，40 列契约对齐）。

    - discharged_only=True 时在括号视图内部下推 `出院日期 IS NOT NULL`
      （供 v_cybr 语义与出院终末过滤场景，避免全院历史扫描）；
    - 返回形如 `( SELECT ... )` 的文本；alias 由调用方按原 SQL 位置自行保留
      （`rewrite_view_refs` 不会动原别名 token）。
    """
    inner = _inline_select_prefix() + _INLINE_FROM_CLAUSE
    # 诊断/手术列为 ROW_NUMBER 展开后的聚合映射（MAX(CASE)），须按原生列分组；
    # 所有原生非聚合列均已列入 GROUP BY（年龄/是否出院已用 MAX 包裹）。
    inner += (
        ' GROUP BY v.PATIENT_ID, v.VISIT_ID, v.INP_NO, m.NAME, m.DATE_OF_BIRTH, m.SEX, '
        'v.ADMISSION_DATE_TIME, v.DISCHARGE_DATE_TIME, v.PAT_ADM_CONDITION, '
        'v.DOCTOR_IN_CHARGE, st.NAME, v.DEPT_ADMISSION_TO, adm_dept.DEPT_NAME, '
        'v.DEPT_DISCHARGE_FROM, dis_dept.DEPT_NAME'
    )
    if discharged_only:
        inner = (
            "SELECT * FROM ( " + inner + " ) WHERE \"出院日期\" IS NOT NULL"
        )
    return "(" + inner + ")"


def inline_inpatient_view() -> str:
    """在院场景平替括号视图：`jhemr.v_zybr` 与 v_qybr 同构 40 列（在院子集）。"""
    return "(SELECT * FROM jhemr.v_zybr)"


def rewrite_view_refs(sql: str, *, discharged_only: bool = False, prefer_inpatient: bool = False) -> str:
    """受控表名重写：把 jhemr.v_qybr / jhemr.v_cybr token 替换为等价内联括号视图。

    - 仅当调用方在捕获视图失效错误（或熔断期内）时调用；其余 SQL 文本
      （别名、WHERE、绑定占位符）零改动，不触碰数据库存储的原始配置文本；
    - prefer_inpatient=True 且 discharged_only=False：在院场景优先 V_ZYBR 平替
      （同构 40 列、零基表 JOIN 成本）；v_cybr 引用不受 prefer_inpatient 影响。
    """
    text = str(sql or "")
    if not text:
        return text

    def _replace(match: re.Match) -> str:
        view = match.group(1).lower()
        if view == "v_cybr":
            # v_cybr 语义=出院患者：无论调用方参数如何，恒在括号视图内下推出院过滤
            return inline_patient_visit_view(discharged_only=True)
        if prefer_inpatient and not discharged_only:
            return inline_inpatient_view()
        return inline_patient_visit_view(discharged_only=discharged_only)

    return _VIEW_REF_PATTERN.sub(_replace, text)


def execute_with_view_compat(
    cur: Any,
    sql: str,
    params: Any = None,
    *,
    prefer_inpatient: bool = False,
    discharged_only: bool = False,
):
    """带视图失效降级的执行包装（供各取数入口复用）。

    - 熔断期内（5 分钟窗口）直接重写 SQL 执行，不再先撞错浪费连接；
    - 首次执行原 SQL：捕获 ORA-04063/ORA-01031 → `mark_view_broken` → 重写重试一次；
    - 其余异常原样抛出（连接池/网络类由调用方既有容错处理）。
    """
    if is_view_broken("jhemr.v_qybr") or is_view_broken("jhemr.v_cybr"):
        rewritten = rewrite_view_refs(
            sql, discharged_only=discharged_only, prefer_inpatient=prefer_inpatient
        )
        return cur.execute(rewritten, params) if params is not None else cur.execute(rewritten)
    try:
        return cur.execute(sql, params) if params is not None else cur.execute(sql)
    except Exception as exc:
        if not is_invalid_view_error(exc):
            raise
        mark_view_broken("jhemr.v_qybr")
        mark_view_broken("jhemr.v_cybr")
        rewritten = rewrite_view_refs(
            sql, discharged_only=discharged_only, prefer_inpatient=prefer_inpatient
        )
        return cur.execute(rewritten, params) if params is not None else cur.execute(rewritten)
