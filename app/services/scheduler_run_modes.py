"""
调度运行模式服务 —— 从 scheduler.py 拆分，负责 daily_increment/discharge_final 模式转换。
"""
import copy
import logging
import re

logger = logging.getLogger(__name__)

# 出院终末模式专用 SQL：按出院日期查询全部病程+护理
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


_DISCHARGE_DATE_RE = re.compile(
    r'AND\s+a\.出院日期\s*[<>]=?\s*TO_DATE\(:query_date\s*,\s*\'[^\']*\'\)\s*(?:\+\s*1)?',
    re.IGNORECASE,
)


def _convert_for_inpatient_mode(audit_type):
    """daily_increment 模式：注入在院患者过滤条件（出院日期 IS NULL）。"""
    code = getattr(audit_type, "code", "")
    cloned = audit_type.model_copy(deep=True) if hasattr(audit_type, "model_copy") else copy.deepcopy(audit_type)

    if code == "progress_vs_nursing":
        logger.info("在院模式：progress_vs_nursing 由 scheduler_audit_runner legacy 路径注入在院过滤")
        return audit_type

    if code in ("lab_exam_vs_progress_nursing", "jyjc_vs_bcnursing"):
        RESULT_DATE_FIELDS = {
            "lab": "c.RESULT_DATE_TIME",
            "exam": "NVL(er.REPORT_TIME, em.REPORT_DATE_TIME)",
            "progress": "b.病历标题时间",
        }
        modified = 0
        for source_name, date_field in RESULT_DATE_FIELDS.items():
            source = (cloned.sources or {}).get(source_name)
            if not source or not source.query_sql:
                continue
            sql = source.query_sql
            sql = _DISCHARGE_DATE_RE.sub('', sql)
            if "{dept_filter}" in sql:
                result_filter = (
                    f"\n    AND a.出院日期 IS NULL"
                    f"\n    AND {date_field} >= TO_DATE(:query_date, 'yyyy-mm-dd')"
                    f"\n    AND {date_field} < TO_DATE(:query_date, 'yyyy-mm-dd') + 1"
                )
                sql = sql.replace("{dept_filter}", "{dept_filter}" + result_filter)
                source.query_sql = sql
                modified += 1
        if modified:
            logger.info("在院模式已转换 jyjc_vs_bcnursing %d 个源（出院日期→在院+结果日期）", modified)
        return cloned

    if code == "syssvsscbc":
        logger.info("在院模式：syssvsscbc 暂未实施 daily 在院过滤，待业务确认锚点")
        return audit_type

    logger.info("在院模式：audit_type=%s EMR 源由 data_source_loader 跨库查询在院患者", code)
    return audit_type


def resolve_audit_run_mode(sched_cfg: dict, default: str = "daily_increment") -> str:
    mode = str(sched_cfg.get("audit_run_mode") or default).strip()
    if mode not in ("daily_increment", "discharge_final"):
        return default
    return mode


def audit_type_for_run_mode(audit_type, audit_run_mode: str):
    """根据运行模式转换审计类型配置（返回原始或克隆副本）。"""
    if audit_run_mode == "daily_increment":
        return _convert_for_inpatient_mode(audit_type)
    if audit_run_mode != "discharge_final":
        return audit_type
    code = getattr(audit_type, "code", "")
    cloned = audit_type.model_copy(deep=True) if hasattr(audit_type, "model_copy") else copy.deepcopy(audit_type)

    if code == "progress_vs_nursing":
        primary = (cloned.sources or {}).get("primary")
        if primary is None:
            logger.warning("出院终末模式无法覆盖 SQL：audit_type=%s 缺少 primary source", code)
            return audit_type
        primary.query_sql = _PROGRESS_NURSING_DISCHARGE_SQL
        logger.info("出院终末模式已覆盖 progress_vs_nursing SQL，按出院日期查询全部病程+护理")
        return cloned

    if code in ("lab_exam_vs_progress_nursing", "jyjc_vs_bcnursing"):
        DISCHARGE_FILTER = "\n    AND a.\"出院日期\" >= TO_DATE(:query_date, 'yyyy-mm-dd')\n    AND a.\"出院日期\" < TO_DATE(:query_date, 'yyyy-mm-dd') + 1"
        modified_count = 0
        for source_name in ("lab", "exam", "progress"):
            source = (cloned.sources or {}).get(source_name)
            if source and source.query_sql and "{dept_filter}" in source.query_sql:
                source.query_sql = source.query_sql.replace("{dept_filter}", "{dept_filter}" + DISCHARGE_FILTER)
                modified_count += 1
        if modified_count > 0:
            logger.info("出院终末模式已覆盖 audit_type=%s 的 %d 个 bulk 源，按出院日期过滤在院患者", code, modified_count)
        else:
            logger.warning("出院终末模式无法覆盖 audit_type=%s SQL：未找到 {dept_filter}", code)
        return cloned

    if code == "syssvsscbc":
        # 在 {dept_filter} 后追加出院日期过滤（与 jyjc_vs_bcnursing 同策略）
        DISCHARGE_FILTER = (
            '\n    AND a."出院日期" >= TO_DATE(:query_date, \'yyyy-mm-dd\')'
            '\n    AND a."出院日期" < TO_DATE(:query_date, \'yyyy-mm-dd\') + 1'
        )
        modified_count = 0
        for source_name in ("frontpage", "first_progress"):
            source = (cloned.sources or {}).get(source_name)
            if source and source.query_sql and "{dept_filter}" in source.query_sql:
                source.query_sql = source.query_sql.replace("{dept_filter}", "{dept_filter}" + DISCHARGE_FILTER)
                modified_count += 1
        if modified_count > 0:
            logger.info("出院终末模式已覆盖 syssvsscbc 的 %d 个源，按出院日期过滤", modified_count)
        else:
            logger.warning("出院终末模式无法覆盖 syssvsscbc SQL：未找到 {dept_filter}")
        return cloned

    # 通用 fallback：admission_vs_first_progress / surgery_chain / discharge_vs_frontpage 等
    # 遍历所有 source，在 {dept_filter} 后追加出院日期过滤
    DISCHARGE_FILTER = (
        '\n    AND a."出院日期" >= TO_DATE(:query_date, \'yyyy-mm-dd\')'
        '\n    AND a."出院日期" < TO_DATE(:query_date, \'yyyy-mm-dd\') + 1'
    )
    modified_count = 0
    sources = cloned.sources or {}
    for source_name, source in sources.items():
        if source and source.query_sql and "{dept_filter}" in source.query_sql:
            source.query_sql = source.query_sql.replace("{dept_filter}", "{dept_filter}" + DISCHARGE_FILTER)
            modified_count += 1
    if modified_count > 0:
        logger.info("出院终末模式已覆盖 audit_type=%s 的 %d 个源，按出院日期过滤", code, modified_count)
        return cloned

    logger.info(
        "出院终末模式：audit_type=%s 未找到 {dept_filter}，通过 date_dimension=discharge_date 自动按出院日期加载",
        code,
    )
    return audit_type


# ---------------------------------------------------------------------------
# discharge_final 类型级生效性静态诊断（035/RP2）
# ---------------------------------------------------------------------------

# 有专属 discharge 转换分支的类型（audit_type_for_run_mode 内硬编码）
_DEDICATED_DISCHARGE_TYPES = {
    "progress_vs_nursing",
    "lab_exam_vs_progress_nursing",
    "jyjc_vs_bcnursing",
    "syssvsscbc",
}

# 专属转换中参与 {dept_filter} 注入的源（其余源如 fanout/EMR 不走该注入）
_DEDICATED_CONVERT_SOURCES = {
    "lab_exam_vs_progress_nursing": ("lab", "exam", "progress"),
    "jyjc_vs_bcnursing": ("lab", "exam", "progress"),
    "syssvsscbc": ("frontpage", "first_progress"),
}

# SQL 是否定义别名 a（注入过滤硬编码 a."出院日期"，无别名 a 将 ORA-00904）
_ALIAS_A_DEF_RE = re.compile(
    r'\b(?:FROM|JOIN)\s+[.\w"\u4e00-\u9fff]+\s+(?:as\s+)?a\b',
    re.IGNORECASE,
)


def _is_emr_source(source_cfg: dict) -> bool:
    """与 data_source_loader._source_backend 同口径的 EMR 后端判定（保持本模块零依赖）。"""
    backend = str(source_cfg.get("backend") or "").strip()
    if backend and backend != "default":
        return backend == "emr_vastbase"
    return str(source_cfg.get("data_source") or "").strip() == "emr_vastbase"


def discharge_effectiveness_warnings(config: dict) -> list[dict]:
    """对 scheduler_discharge.audit_type_codes 做出院模式生效性静态诊断。

    返回问题列表 [{code, source, level, detail}]；空列表=全部类型生效。
    诊断口径（与 audit_type_for_run_mode/data_source_loader 实际行为对齐）：
    - 专属转换类型：参与注入的源均无 {dept_filter} → 转换不会生效（warn）
    - EMR 源（backend/data_source=emr_vastbase）：走 _fetch_discharged_emr_records
      专用出院加载（V_QYBR 出院患者 → Vastbase 文书），query_sql 被忽略（ok）
    - SQL 源含 {dept_filter}：通用 fallback 注入；SQL 未定义别名 a → 注入的
      a."出院日期" 将 ORA-00904（warn）
    - SQL 源无 {dept_filter}：fallback 不注入，出院语义完全依赖 SQL 自身，
      若 SQL 仍按记录创建日过滤将漏出院患者（warn）
    """
    discharge_cfg = (config or {}).get("scheduler_discharge") or {}
    if not discharge_cfg.get("enabled"):
        return []
    codes = [str(c).strip() for c in discharge_cfg.get("audit_type_codes") or [] if str(c).strip()]
    if not codes:
        return []

    audit_types = {str(at.get("code") or ""): at for at in (config or {}).get("audit_types") or []}
    issues: list[dict] = []

    for code in codes:
        audit_type = audit_types.get(code)
        if audit_type is None:
            issues.append({
                "code": code,
                "source": "",
                "level": "warn",
                "detail": "audit_types 中不存在该类型，discharge 模式将零结果",
            })
            continue
        sources = audit_type.get("sources") or {}

        if code == "progress_vs_nursing":
            # 专属 SQL 整体替换（_PROGRESS_NURSING_DISCHARGE_SQL），恒生效
            continue

        if code in _DEDICATED_CONVERT_SOURCES:
            convert_sources = _DEDICATED_CONVERT_SOURCES[code]
            eligible = [
                name for name in convert_sources
                if "{dept_filter}" in str((sources.get(name) or {}).get("query_sql") or "")
            ]
            if not eligible:
                issues.append({
                    "code": code,
                    "source": "/".join(convert_sources),
                    "level": "warn",
                    "detail": "专属转换源均无 {dept_filter}，出院日期过滤不会注入",
                })
            continue

        # 通用 fallback 轨道：逐源判定
        for name, source_cfg in sources.items():
            source_cfg = source_cfg or {}
            if _is_emr_source(source_cfg):
                continue  # EMR 专用出院加载路径，恒生效
            sql = str(source_cfg.get("query_sql") or "")
            if not sql:
                issues.append({
                    "code": code,
                    "source": name,
                    "level": "warn",
                    "detail": "非 EMR 源且 query_sql 为空，discharge 模式将加载空数据",
                })
            elif "{dept_filter}" in sql:
                if not _ALIAS_A_DEF_RE.search(sql):
                    issues.append({
                        "code": code,
                        "source": name,
                        "level": "warn",
                        "detail": "SQL 含 {dept_filter} 但未定义别名 a，fallback 注入 a.\"出院日期\" 将 ORA-00904",
                    })
            else:
                issues.append({
                    "code": code,
                    "source": name,
                    "level": "warn",
                    "detail": "SQL 无 {dept_filter}，出院语义依赖 SQL 自身（按创建日过滤将漏出院患者）",
                })

    return issues
