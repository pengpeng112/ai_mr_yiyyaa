# -*- coding: utf-8 -*-
"""054 §12 J01-J08：JHEMR FILEVERIFY(4) 第一批 v2 四行包离线合成验证工具。

定位（054 §12）：J01-J08 为纯合成离线验证与可审阅证据；需要 179 真库/真实客户端的部分
（J09-J12）走 review/uat054-20260922/j09_field_checklist.md 现场逐步操作单。

硬边界：
- 本工具零网络连接（不连 177/179/任何库）；一切执行都在进程内 SQLite 内存库完成；
- 不写任何业务库；不生成可自动执行的激活动作——输出的 SQL 文件是 dry-run 打印稿，
  与 t3_ready_package_20260922.sql 同口径（任何执行须按 054 §2/§3 批次授权）；
- 默认无参=打印用法并退出非零，防止误当成"跑一遍就完事"。

v2 修订依据（054 §1，外部复核采纳版）：
- V1 门控：第一批插入版 SETTING_SQL 用占位不命中字面量 DEPT_DISCHARGE_FROM='PILOT-PENDING'
  （任何患者不满足，误启用也零弹窗）；第二批 UPDATE 为双科室码门控
  AND p.DEPT_DISCHARGE_FROM='<PILOT_DEPT>' AND '{5}'='<PILOT_DEPT>'。
- V2 R2 文案：删除『到院记录』笔误。
- V3 R3 算法：TRUNC(SYSDATE) - TRUNC(p.DISCHARGE_DATE_TIME) > :DAYS 双 trunc 自然日差。

宿主契约证据（反编译，review/jhemr-l2-20260921/t1_wiring_evidence.md 与 C:/temp/jh050 原件）：
- 患者级重载 CustomEmrFileBusiness.cs:436；占位符 {1}=PATIENT_ID {2}=VISIT_ID {5}=当前科室；
- 命中收集：text = text + TIPMESSGE + "\\r\\n"（每条后置 CRLF，含末条，:519 等 8 处）；
- 宿主 IPMMedicalRecordOrSubSpecialBLL.cs:1686：tipMessge.Length > 150 → MessageBox.Show
  （系统消息框样式），否则 ShowInformation；btnMRCom 路径 returnFinishbyEmrFileConfig 双调用
  → 同段文案连弹两次；
- TIP_TYPE=1 命中→ref 回写+return true→宿主弹 ShowInformation 后完成继续（提示不阻断）；
- SQL 异常 catch→return true（fail-open：静默无提醒、完成继续）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "review" / "uat054-20260922"
V1_PACKAGE = REPO / "review" / "jhemr-l2-20260921" / "t3_ready_package_20260922.sql"
V2_PACKAGE = REPO / "review" / "jhemr-l2-20260921" / "t3_ready_package_v2_20260923.sql"

HOSPITAL_NO = "49557032X"
IDS = ["20260922AIQC01", "20260922AIQC02", "20260922AIQC03", "20260922AIQC04"]
PILOT_PLACEHOLDER = "PILOT-PENDING"
PILOT_DEPT = "D001"  # 合成试点科室码（仅本工具数据集；真实码由质控科指定）
OTHER_DEPT = "D002"
R3_DAYS_PLACEHOLDER = 3  # 第一批占位天数；第二批按质控制度值定稿（054 §1 V3）

TIP_R1 = "【质控提醒】存在未完成签名的病历文书，请在提交病历完成前核查确认。"
TIP_R2 = "【质控提醒】未检出出院记录类文书，提交病历完成前请核查病历完整性。"  # V2 修订
TIP_R3 = "【质控提醒】患者出院已超过3天仍未提交病历完成，请及时处理。"  # 数字随 :DAYS 同步
TIP_R4 = "【质控提醒】存在手术记录未关联/缺失的手术，请核查手术记录文书。"

# SETTING_SQL（C# Format 模板原文；单花括号 {n}=占位符，无字面量花括号——J01 断言）
SQL_R1 = (
    "select count(1) from jhmr_file_index t where t.patient_id='{1}' and t.visit_id='{2}' "
    "and t.delete_flag='0' and t.first_mr_sign_date_time is null "
    "and exists (select 1 from pat_visit g where g.patient_id='{1}' and g.visit_id='{2}' "
    "and g.dept_discharge_from='" + PILOT_PLACEHOLDER + "')"
)
SQL_R2 = (
    "select count(1) from pat_visit p where p.patient_id='{1}' and p.visit_id='{2}' "
    "and p.discharge_date_time is not null and p.dept_discharge_from='" + PILOT_PLACEHOLDER + "' "
    "and not exists (select 1 from jhmr_file_index f where f.patient_id=p.patient_id "
    "and f.visit_id=p.visit_id and f.delete_flag='0' and f.topic like '%出院记录%')"
)
SQL_R3 = (
    "select count(1) from pat_visit p where p.patient_id='{1}' and p.visit_id='{2}' "
    "and p.discharge_date_time is not null and p.dept_discharge_from='" + PILOT_PLACEHOLDER + "' "
    "and nvl(p.mr_doctor_part_status,'0') in ('0','1') "
    "and trunc(sysdate) - trunc(p.discharge_date_time) > " + str(R3_DAYS_PLACEHOLDER)
)
SQL_R4 = (
    "select count(1) from operation o where o.patient_id='{1}' and o.visit_id='{2}' "
    "and o.operation_type=0 "
    "and exists (select 1 from pat_visit g where g.patient_id='{1}' and g.visit_id='{2}' "
    "and g.dept_discharge_from='" + PILOT_PLACEHOLDER + "') "
    "and not exists (select 1 from jhmr_file_index_vs_operation v "
    "where v.patient_id=o.patient_id and v.visit_id=o.visit_id)"
)

ROWS = [
    {"rule": "R1", "id": IDS[0], "tip": TIP_R1, "sql": SQL_R1,
     "remark": "054v2-R1-未首签文书(占位门控,待质控科确认)"},
    {"rule": "R2", "id": IDS[1], "tip": TIP_R2, "sql": SQL_R2,
     "remark": "054v2-R2-缺出院记录(文案V2,待质控科确认)"},
    {"rule": "R3", "id": IDS[2], "tip": TIP_R3, "sql": SQL_R3,
     "remark": "054v2-R3-出院超时(双trunc V3,天数3占位,待定稿)"},
    {"rule": "R4", "id": IDS[3], "tip": TIP_R4, "sql": SQL_R4,
     "remark": "054v2-R4-手术关联(恒停用,试点后再评估)"},
]

RULE_CASE = {"R1": "J04", "R2": "J05", "R3": "J06"}


def formal_sql(row: dict, pilot_dept: str, days: int) -> str:
    """第二批正式版：门控改双科室码；R3 天数定稿。仅打印稿/离线模拟用，不执行。"""
    sql = row["sql"].replace("'" + PILOT_PLACEHOLDER + "'", "'" + pilot_dept + "'")
    if row["rule"] in ("R1", "R4"):
        sql = sql.replace(
            "and g.dept_discharge_from='" + pilot_dept + "')",
            "and g.dept_discharge_from='" + pilot_dept + "') and '{5}'='" + pilot_dept + "'")
    else:  # R2/R3 主查询别名 p
        sql = sql.replace(
            "and p.dept_discharge_from='" + pilot_dept + "'",
            "and p.dept_discharge_from='" + pilot_dept + "' and '{5}'='" + pilot_dept + "'")
    if row["rule"] == "R3":
        sql = sql.replace("> " + str(R3_DAYS_PLACEHOLDER), "> " + str(days))
    return sql


TIPMESSGE_LIMIT = 150  # 054 §2-1-e：TIPMESSGE varchar(150)（CHAR_USED 语义待 179 P0 实测）
SETTING_SQL_LIMIT_DEFAULT = 4000  # 待 179 P0 实测确认；工具内按最保守复核并标注


# ---------------------------------------------------------------- C# Format 模拟
FORMAT_TOKEN = re.compile(r"\{\{|\}\}|\{(\d+)\}")


def csharp_format(template: str, args: list[str]) -> str:
    """模拟 C# string.Format：{{ }} 为字面量花括号，{n} 取 args[n]。"""
    def repl(m: re.Match) -> str:
        if m.group(0) == "{{":
            return "{"
        if m.group(0) == "}}":
            return "}"
        idx = int(m.group(1))
        if idx >= len(args):
            raise IndexError(f"format index {idx} out of range (args={len(args)})")
        return args[idx]
    return FORMAT_TOKEN.sub(repl, template)


def format_args(pid: str, vid: str, dept: str) -> list[str]:
    # 占位符实参表（t1 证据 ：477-480）：{0}空 {1}PID {2}VID {3}PAT_INP_NO {4}ID_NO {5}当前科室
    # {6}入院 {7}出院 {8}-{11}空 {12}RealUserId {13}hospitalCode {14}{15}空 {16}INPATIENT_NO {17}空 {18}服务器时间
    return ["", pid, vid, "PIN-1", "IDNO-1", dept,
            "2026-09-10", "2026-09-19", "", "", "", "",
            "synthetic-u054", HOSPITAL_NO, "", "", "INP-1", "",
            "2026-09-23 08:00:00"]


# ---------------------------------------------------------------- Oracle→SQLite 方言
def to_sqlite(sql: str, sysdate: str) -> tuple[str, dict]:
    """忠实翻译（逐项可审）：nvl→ifnull；trunc(sysdate)→julianday(:sysd)；
    trunc(p.discharge_date_time)→julianday(date(...))；其余原样。返回 (sql, params)。"""
    params: dict[str, object] = {"sysd": sysdate}
    out = sql.replace("nvl(", "ifnull(")
    out = out.replace("trunc(sysdate)", "julianday(:sysd)")
    out = re.sub(r"trunc\((p\.discharge_date_time)\)", r"julianday(date(\1))", out)
    return out, params


def run_rule_sql(conn: sqlite3.Connection, template: str, pid: str, vid: str,
                 clicker_dept: str, sysdate: str) -> int:
    formatted = csharp_format(template, format_args(pid, vid, clicker_dept))
    sql, params = to_sqlite(formatted, sysdate)
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0)


# ---------------------------------------------------------------- 合成数据集
@dataclass
class Dataset:
    name: str
    visits: list[tuple] = field(default_factory=list)       # (pid, vid, discharge_dt, dept_from, mr_status)
    docs: list[tuple] = field(default_factory=list)         # (pid, vid, topic, delete_flag, first_sign)
    operations: list[tuple] = field(default_factory=list)   # (pid, vid, operation_type)
    doc_op_links: list[tuple] = field(default_factory=list) # (pid, vid)


def base_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE pat_visit (
            patient_id TEXT, visit_id TEXT, discharge_date_time TEXT,
            dept_discharge_from TEXT, mr_doctor_part_status TEXT);
        CREATE TABLE jhmr_file_index (
            patient_id TEXT, visit_id TEXT, topic TEXT,
            delete_flag TEXT, first_mr_sign_date_time TEXT);
        CREATE TABLE operation (
            patient_id TEXT, visit_id TEXT, operation_type INTEGER);
        CREATE TABLE jhmr_file_index_vs_operation (
            patient_id TEXT, visit_id TEXT);
        """
    )


def load(conn: sqlite3.Connection, ds: Dataset) -> None:
    conn.execute("DELETE FROM pat_visit"); conn.execute("DELETE FROM jhmr_file_index")
    conn.execute("DELETE FROM operation"); conn.execute("DELETE FROM jhmr_file_index_vs_operation")
    conn.executemany("INSERT INTO pat_visit VALUES (?,?,?,?,?)", ds.visits)
    conn.executemany("INSERT INTO jhmr_file_index VALUES (?,?,?,?,?)", ds.docs)
    conn.executemany("INSERT INTO operation VALUES (?,?,?)", ds.operations)
    conn.executemany("INSERT INTO jhmr_file_index_vs_operation VALUES (?,?)", ds.doc_op_links)


# J04：R1 未首签边界（正式门控+试点点击者下观察规则语义本身）
def ds_r1() -> Dataset:
    return Dataset(name="R1-未首签边界", visits=[
        ("P1", "1", "2026-09-19 10:00", PILOT_DEPT, "0"),   # 1 份未首签（普通文书）→ 命中
        ("P2", "1", "2026-09-19 10:00", PILOT_DEPT, "0"),   # 全部已签 → 不命中
        ("P3", "1", "2026-09-19 10:00", PILOT_DEPT, "0"),   # 未首签=知情同意书 → 命中（类别不区分）
        ("P4", "1", "2026-09-19 10:00", PILOT_DEPT, "0"),   # 未首签=自动生成文书 → 命中
        ("P5", "1", "2026-09-19 10:00", PILOT_DEPT, "0"),   # 未首签但 delete_flag=1 → 不命中
        ("P6", "1", "2026-09-19 10:00", OTHER_DEPT, "0"),   # 非试点科室出院 → 门控不命中
    ], docs=[
        ("P1", "1", "日常病程记录", "0", None),
        ("P2", "1", "日常病程记录", "0", "2026-09-18 09:00"),
        ("P3", "1", "手术知情同意书", "0", None),
        ("P4", "1", "自动生成文书-入院记录", "0", None),
        ("P5", "1", "出院记录", "1", None),
        ("P6", "1", "日常病程记录", "0", None),
    ])


# J05：R2 出院记录 TOPIC 变体
def ds_r2() -> Dataset:
    return Dataset(name="R2-出院记录变体", visits=[
        ("Q1", "1", "2026-09-19 10:00", PILOT_DEPT, "0"),   # 缺出院记录 → 命中
        ("Q2", "1", "2026-09-19 10:00", PILOT_DEPT, "0"),   # 有『出院记录』→ 不命中
        ("Q3", "1", "2026-09-19 10:00", PILOT_DEPT, "0"),   # 仅日间手术入出院记录 → 不命中（待质控科①）
        ("Q4", "1", "2026-09-19 10:00", PILOT_DEPT, "0"),   # 仅24小时入出院记录 → 不命中（待质控科①）
        ("Q5", "1", "2026-09-19 10:00", PILOT_DEPT, "0"),   # 仅死亡记录 → 命中（待质控科②）
        ("Q6", "1", None, PILOT_DEPT, "0"),                 # 未出院 → 不命中
    ], docs=[
        ("Q1", "1", "日常病程记录", "0", "2026-09-18 09:00"),
        ("Q2", "1", "出院记录", "0", "2026-09-19 09:00"),
        ("Q3", "1", "日间手术入出院记录", "0", "2026-09-19 09:00"),
        ("Q4", "1", "24小时入出院记录", "0", "2026-09-19 09:00"),
        ("Q5", "1", "死亡记录", "0", "2026-09-19 09:00"),
        ("Q6", "1", "日常病程记录", "0", "2026-09-18 09:00"),
    ])


# J06：R3 自然日边界（sysdate 固定 2026-09-23；DAYS=3；nd=trunc 差）
def ds_r3() -> Dataset:
    return Dataset(name="R3-自然日边界", visits=[
        ("S1", "1", "2026-09-23 08:00", PILOT_DEPT, "0"),   # nd=0 当日 → 不命中
        ("S2", "1", "2026-09-21 23:59", PILOT_DEPT, "0"),   # nd=2(D-1) → 不命中
        ("S3", "1", "2026-09-20 00:01", PILOT_DEPT, "0"),   # nd=3(D) → 不命中（严格大于）
        ("S4", "1", "2026-09-19 23:59", PILOT_DEPT, "0"),   # nd=4(D+1,跨午夜) → 命中
        ("S5", "1", "2026-09-19 00:00", PILOT_DEPT, "0"),   # nd=4(午夜整点出院) → 命中
        ("S6", "1", "2525-01-01 00:00", PILOT_DEPT, "0"),   # 未来脏日期(22025族) → 不命中
        ("S7", "1", "2026-09-19 10:00", PILOT_DEPT, "4"),   # 状态4人群 → 不命中（待裁定）
        ("S8", "1", "2026-09-19 10:00", PILOT_DEPT, None),  # 状态NULL→nvl补'0' → 命中
        ("S9", "1", "2026-09-19 10:00", PILOT_DEPT, "1"),   # 状态1 → 命中
    ])


# J03：双科室码门控四象限（R2 语义载体：缺出院记录患者）
def ds_gate() -> Dataset:
    return Dataset(name="门控四象限", visits=[
        ("G1", "1", "2026-09-19 10:00", PILOT_DEPT, "0"),   # 试点患者（缺出院记录）
        ("G2", "1", "2026-09-19 10:00", OTHER_DEPT, "0"),   # 外科患者（缺出院记录）
    ], docs=[
        ("G1", "1", "日常病程记录", "0", "2026-09-18 09:00"),
        ("G2", "1", "日常病程记录", "0", "2026-09-18 09:00"),
    ])


# ---------------------------------------------------------------- v2 SQL 打印稿
def _build_v2_text() -> str:
    lines = [
        "-- ============================================================================",
        "-- 054 v2 就绪包打印稿（DRY-RUN；本文件任何语句未获逐次批准不得执行）",
        "-- 修订：V1 占位门控 PILOT-PENDING / V2 R2 文案 / V3 R3 双 trunc（054 §1）",
        "-- 第一批=INSERT×4 全 ENABLE=0（已批 2026-09-22，179 通道前置未落实不得执行）",
        "-- 第二批=单事务三件事（未批；UPDATE SETTING_SQL 门控+R3 定稿+ENABLE=1）",
        "-- 生成：scripts/verify_fileverify_v2_20260922.py（离线工具，零连接）",
        "-- ============================================================================",
        "",
        "-- ---------- 第一批 Part 2：INSERT ×4（v2 修订版；逐行执行，禁整文件跑） ----------",
    ]
    for r in ROWS:
        sql_literal = r["sql"].replace("'", "''")
        tip_literal = r["tip"].replace("'", "''")
        remark_literal = r["remark"].replace("'", "''")
        lines += [
            f"-- {r['rule']}（{r['remark']}）",
            "INSERT INTO JHEMR.JHMR_FILE_CUM_FILEVERIFY",
            "  (ID, CHECK_TYPE, MR_CLASS, MR_CODE, CATALOG_CODE, SETTING_SQL, QUERY_FLAG, QUERY_REMARK,",
            "   QUERY_DEFAULT_VALUES, RESULT_TYPE, RESULT_VALUE, CHECK_SYMBOL, TIP_TYPE, TIPMESSGE, REMARK,",
            "   ENABLE, CREATE_USER, CREATE_DATE, HOSPITAL_NO, DATETIME)",
            "VALUES",
            f"  ('{r['id']}', 4, '*', '*', '0',",
            f"   '{sql_literal}',",
            "    '1,2', '患者ID,住院次', 'TEST|0', 1, '0', 1, 1,",
            f"    '{tip_literal}', '{remark_literal}',",
            f"    0, 'AIZK-QC', SYSDATE, '{HOSPITAL_NO}', SYSDATE);",
            "",
        ]
    lines += [
        "-- ---------- 第二批（未批；输入=质控科四问回复+试点科室码+计时预检） ----------",
        "-- 单事务三件事（054 §3；:PILOT_DEPT/:DAYS 定稿后替换字面量再执行）：",
    ]
    for r in ROWS[:3]:
        fsql = formal_sql(r, ":PILOT_DEPT", ":DAYS").replace("'", "''")
        lines.append(f"-- ① {r['rule']} SETTING_SQL 门控/算法 UPDATE（R3 同时是算法定稿）：")
        lines.append(f"-- UPDATE JHEMR.JHMR_FILE_CUM_FILEVERIFY SET SETTING_SQL='{fsql}' WHERE ID='{r['id']}';")
    lines += [
        "-- ② R3 TIPMESSGE 数字同步（天数定稿后）：",
        f"-- UPDATE JHEMR.JHMR_FILE_CUM_FILEVERIFY SET TIPMESSGE='【质控提醒】患者出院已超过:DAYS天仍未提交病历完成，请及时处理。' WHERE ID='{IDS[2]}';",
        "-- ③ 激活（R4 恒停用；激活前完成试点科真实账号科室码核对+179 计时预检）：",
        f"-- UPDATE JHEMR.JHMR_FILE_CUM_FILEVERIFY SET ENABLE=1, DATETIME=SYSDATE WHERE ID IN ('{IDS[0]}','{IDS[1]}','{IDS[2]}') AND HOSPITAL_NO='{HOSPITAL_NO}';",
        "",
        "-- ---------- 回滚（均需单独批准；054 §3） ----------",
        "-- 首选：UPDATE JHEMR.JHMR_FILE_CUM_FILEVERIFY SET ENABLE=0, DATETIME=SYSDATE WHERE ID LIKE '20260922AIQC%';（下次点击生效）",
        "-- 彻底：DELETE FROM JHEMR.JHMR_FILE_CUM_FILEVERIFY WHERE ID LIKE '20260922AIQC%';（另批一句）",
    ]
    return "\n".join(lines) + "\n"


def emit_v2_package(path: Path) -> str:
    text = _build_v2_text()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8", newline="\n")
    return text


# ---------------------------------------------------------------- J01 包静态校验
def check_package() -> dict:
    result: dict = {"case": "J01", "checks": [], "pass": True}

    def chk(name: str, ok: bool, detail: str = "") -> None:
        result["checks"].append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            result["pass"] = False

    artifact = _build_v2_text()
    found_ids = re.findall(r"'(20260922AIQC\d{2})'", artifact)
    chk("四 ID 精确=20260922AIQC01-04（集合相等；注释态第二批行亦只引用白名单）",
        set(found_ids) == set(IDS), ",".join(sorted(set(found_ids))))
    chk("INSERT INTO ×4（第一批落库仅四条）",
        len(re.findall(r"(?im)^INSERT INTO\b", artifact)) == 4)
    insert_blocks = re.findall(
        r"VALUES\s*\n\s*\('(20260922AIQC\d{2})'.*?0, 'AIZK-QC', SYSDATE", artifact, re.S)
    chk("四条 INSERT 全部 ENABLE=0（工件级：每条 VALUES 尾部 0,'AIZK-QC'）",
        sorted(insert_blocks) == IDS, str(sorted(insert_blocks)))
    chk("工件 TIP_TYPE=1 ×4（提示不阻断）", artifact.count(", 1, 1,\n") == 4)
    chk("工件 HOSPITAL_NO=49557032X", artifact.count(f"'{HOSPITAL_NO}'") >= 4)
    for r in ROWS:
        chk(f"{r['rule']} 门控=占位不命中字面量 {PILOT_PLACEHOLDER}",
            f"'{PILOT_PLACEHOLDER}'" in r["sql"])
        chk(f"{r['rule']} SQL 无字面量花括号（string.Format 契约）",
            "{{" not in r["sql"] and "}}" not in r["sql"])
        chk(f"{r['rule']} 占位符集合 ⊆ {{1,2}}",
            set(re.findall(r"\{(\d+)\}", r["sql"])) <= {"1", "2"},
            str(sorted(set(re.findall(r"\{(\d+)\}", r["sql"])))))
    chk("R2 文案已删『到院记录』笔误（V2）", "到院" not in TIP_R2, TIP_R2)
    chk("R3 双 trunc 自然日差（V3）",
        "trunc(sysdate) - trunc(p.discharge_date_time)" in SQL_R3)
    # 工件内激活语句全部处于注释态（--）；无裸 UPDATE/DELETE/COMMIT
    active_lines = [ln.strip() for ln in artifact.splitlines()
                    if ln.strip() and not ln.strip().startswith("--")]
    chk("非注释行无 UPDATE/DELETE/COMMIT/MERGE（激活与回滚全在注释态）",
        not [ln for ln in active_lines
             if re.match(r"(?i)^(UPDATE|DELETE|COMMIT|MERGE)\b", ln)],
        f"非注释行 {len(active_lines)} 条（INSERT+VALUES 续行）")
    stmt_ids = set(re.findall(r"20260922AIQC\d{2}", artifact))
    chk("工件语句仅涉及 4 白名单 ID（无范围外目标）", stmt_ids <= set(IDS),
        str(sorted(stmt_ids - set(IDS)) or "clean"))
    # 误启用模拟：ENABLE=1 + PILOT-PENDING 门控 → 零命中
    conn = sqlite3.connect(":memory:")
    base_schema(conn)
    load(conn, Dataset(name="误启用", visits=[
        ("X1", "1", "2025-01-01 00:00", "D999", "0"),
        ("X2", "1", "2025-01-01 00:00", "D999", "4")],
        docs=[("X1", "1", "日常病程记录", "0", None)]))
    hits = [run_rule_sql(conn, r["sql"], pid, "1", dept, "2026-09-23")
            for pid, dept in (("X1", "D999"), ("X2", "D999")) for r in ROWS]
    chk("误启用（ENABLE=1）模拟仍零命中（占位门控不命中）", all(h == 0 for h in hits), str(hits))
    # 原文 hash（J01：保存原文 hash）
    hashes = {}
    if V1_PACKAGE.exists():
        v1_text = V1_PACKAGE.read_text("utf-8")
        hashes["v1_t3_ready_package_20260922.sql"] = hashlib.sha256(v1_text.encode("utf-8")).hexdigest()
    hashes["v2_t3_ready_package_20260923.sql(dry-run 打印稿)"] = hashlib.sha256(artifact.encode("utf-8")).hexdigest()
    result["sha256"] = hashes
    chk("原文 hash 已记（v1 源+v2 打印稿）", len(hashes) >= 2, json.dumps(hashes, ensure_ascii=False))
    return result


# ---------------------------------------------------------------- J02 长度语义
def check_length(charset: str) -> dict:
    result: dict = {"case": "J02", "rows": [], "pass": True}
    encodings = ["utf-8", "gbk"] if charset == "both" else [charset]
    for r in ROWS:
        row = {"rule": r["rule"], "id": r["id"],
               "tip_chars": len(r["tip"]), "sql_chars": len(r["sql"])}
        for enc in encodings:
            row[f"tip_bytes_{enc}"] = len(r["tip"].encode(enc))
            row[f"sql_bytes_{enc}"] = len(r["sql"].encode(enc))
        worst_tip = max(row.get(f"tip_bytes_{e}", 0) for e in encodings)
        row["tip_within_150_worst_bytes"] = worst_tip <= TIPMESSGE_LIMIT
        if not row["tip_within_150_worst_bytes"]:
            result["pass"] = False
        worst_sql = max(row.get(f"sql_bytes_{e}", 0) for e in encodings)
        row["sql_within_limit_worst_bytes"] = worst_sql <= SETTING_SQL_LIMIT_DEFAULT
        result["rows"].append(row)
    result["note"] = (
        "离线估计不能代替 179 实际读回（J02 限制声明）；CHAR_USED=B/C 与库字符集以 179 P0"
        f"（054 §2-1-e）实测为准；SETTING_SQL 上限 {SETTING_SQL_LIMIT_DEFAULT} 为待核默认值")
    return result


def compare_readback(path: Path) -> dict:
    """读回比对算法：逐字符（含换行）精确比对；报告首个差异位。供 179 读回导出复用。"""
    payload = json.loads(path.read_text("utf-8"))
    rows = payload if isinstance(payload, list) else payload.get("rows", [])
    out = {"case": "J02-readback", "pairs": [], "pass": True}
    by_id = {r["id"]: r for r in ROWS}
    for row in rows:
        rid = row.get("ID") or row.get("id")
        base = by_id.get(rid)
        if base is None:
            out["pairs"].append({"id": rid, "error": "范围外 ID（白名单校验失败）"})
            out["pass"] = False
            continue
        for field_name, mine in (("TIPMESSGE", base["tip"]), ("SETTING_SQL", base["sql"])):
            theirs = row.get(field_name, "")
            pair = {"id": rid, "field": field_name, "equal_exact": theirs == mine,
                    "len_expected": len(mine), "len_readback": len(theirs)}
            if theirs != mine:
                i = next((i for i, (a, b) in enumerate(zip(mine, theirs)) if a != b),
                         min(len(mine), len(theirs)))
                pair["first_diff_index"] = i
                out["pass"] = False
            out["pairs"].append(pair)
    return out


# ---------------------------------------------------------------- J03 门控矩阵
def check_gate_matrix() -> dict:
    conn = sqlite3.connect(":memory:")
    base_schema(conn)
    load(conn, ds_gate())
    r2 = next(r for r in ROWS if r["rule"] == "R2")
    formal = formal_sql(r2, PILOT_DEPT, R3_DAYS_PLACEHOLDER)
    matrix = []
    for label, pid, clicker in [
        ("试点患者+试点点击者", "G1", PILOT_DEPT),
        ("试点患者+外科点击者", "G1", OTHER_DEPT),
        ("外科患者+试点点击者", "G2", PILOT_DEPT),
        ("双外科", "G2", OTHER_DEPT),
    ]:
        matrix.append({"scenario": label, "hits": run_rule_sql(conn, formal, pid, "1", clicker, "2026-09-23")})
    return {"case": "J03", "matrix": matrix,
            "expected": "仅『试点患者+试点点击者』可命中（双码同时成立）",
            "pass": [m["hits"] > 0 for m in matrix] == [True, False, False, False],
            "formal_gate_example": "AND p.DEPT_DISCHARGE_FROM='D001' AND '{5}'='D001'（合成示例码）",
            "precondition": ("护理单元码≠出院科室码时整科不弹（漏提醒，无阻断）——试点科真实账号"
                             "CurrentDeptCode 与 dept_discharge_from 同码核对为第二批前置（054 §1 V1 预检），"
                             "本工具不发明映射")}


# ---------------------------------------------------------------- J04-J06 规则边界
def check_rule(rule: str) -> dict:
    conn = sqlite3.connect(":memory:")
    base_schema(conn)
    r = next(x for x in ROWS if x["rule"] == rule)
    sysdate = "2026-09-23"
    if rule == "R1":
        ds, expect = ds_r1(), [("P1", True), ("P2", False), ("P3", True), ("P4", True),
                               ("P5", False), ("P6", False)]
        notes = ("不区分文书类别（知情同意书/自动生成文书也计入未首签）＝当前草案行为，范围待质控科"
                 "054 §4-1 裁定；delete_flag=1 不计；非试点科室患者不弹（正式门控）")
    elif rule == "R2":
        ds, expect = ds_r2(), [("Q1", True), ("Q2", False), ("Q3", False), ("Q4", False),
                               ("Q5", True), ("Q6", False)]
        notes = ("TOPIC LIKE '%出院记录%' 含日间/24小时变体＝当前草案行为，①②待质控科 054 §4-2 裁定；"
                 "死亡病例（仅死亡记录）当前会提醒；未出院不命中")
    else:
        ds, expect = ds_r3(), [("S1", False), ("S2", False), ("S3", False), ("S4", True),
                               ("S5", True), ("S6", False), ("S7", False), ("S8", True),
                               ("S9", True)]
        notes = ("严格大于 :DAYS 才命中（D=3 时 nd≥4）；双 trunc=自然日差；未来脏日期（22025 族）差为负"
                 "天然不命中；状态4人群不被覆盖＝已知限制（054 §4-3），是否纳入待质控科；天数保持参数，"
                 "制度值未定不代填。附注：v1 单 trunc(sysdate) 写法对整数阈值与双 trunc 命中集等价"
                 "（nd−frac>D ⇔ nd≥D+1，frac∈[0,1)），外部复核『早数小时命中』的描述对象应是"
                 "sysdate−trunc(dis) 变体而非 v1 实际写法；v2 双 trunc 为显式自然日语义，仍为正确采纳")
    load(conn, ds)
    formal = formal_sql(r, PILOT_DEPT, R3_DAYS_PLACEHOLDER)
    rows, ok_all = [], True
    for pid, want in expect:
        got = run_rule_sql(conn, formal, pid, "1", PILOT_DEPT, sysdate) > 0
        rows.append({"patient": pid, "expected_hit": want, "actual_hit": got, "ok": got == want})
        ok_all = ok_all and got == want
    return {"case": RULE_CASE[rule], "rule": rule, "dataset": ds.name, "rows": rows,
            "notes": notes, "pass": ok_all, "sql_executed": formal}


# ---------------------------------------------------------------- J07 拼接阈值
def host_concat(tips: list[str]) -> str:
    """宿主收集语义：text += TIPMESSGE + '\\r\\n'（每条后置 CRLF，含末条）。"""
    return "".join(t + "\r\n" for t in tips)


def check_combine_threshold() -> dict:
    combos = []
    for name, tips in [
        ("R1 单中", [TIP_R1]), ("R2 单中", [TIP_R2]), ("R3 单中", [TIP_R3]),
        ("R1+R2", [TIP_R1, TIP_R2]), ("R1+R3", [TIP_R1, TIP_R3]),
        ("R2+R3", [TIP_R2, TIP_R3]), ("R1+R2+R3 全中", [TIP_R1, TIP_R2, TIP_R3]),
    ]:
        text = host_concat(tips)
        combos.append({"combo": name, "csharp_length": len(text),
                       "style": "MessageBox.Show(系统样式)" if len(text) > 150 else "ShowInformation"})
    # 边界（合成定长文案验证宿主阈值语义；注意末条 CRLF 计入 Length → 实际切换点=文案 149 字）
    boundary = []
    for n in (147, 148, 149):
        length = len(host_concat(["测" * n]))
        boundary.append({"chars": n, "csharp_length_with_crlf": length, "crosses_150": length > 150})
    real_max = max(c["csharp_length"] for c in combos)
    expected_cross = [False, False, True]
    return {"case": "J07", "combos": combos, "boundary_147_148_149": boundary,
            "threshold_rule": "宿主 IPMMedicalRecordOrSubSpecialBLL.cs:1686 tipMessge.Length > 150",
            "concat_rule": "CustomEmrFileBusiness.cs:519 等 8 处 text += TIPMESSGE + '\\r\\n'（含末条 CRLF）",
            "double_popup": ("btnMRCom 路径 returnFinishbyEmrFileConfig 双调用 → 同段文案连弹两次"
                             "（点两次确定后完成继续，不拦截）"),
            "real_text_max_length": real_max,
            "real_texts_never_cross_150": real_max <= 150,
            "r4_always_disabled": "R4（20260922AIQC04）恒 ENABLE=0，不参与命中收集（第二批 ENABLE=1 仅 01-03）",
            "pass": [b["crosses_150"] for b in boundary] == expected_cross and real_max <= 150}


# ---------------------------------------------------------------- J08 fail-open
def check_fail_open() -> dict:
    conn = sqlite3.connect(":memory:")
    base_schema(conn)
    load(conn, ds_r2())
    r2 = next(r for r in ROWS if r["rule"] == "R2")

    def evaluate(template: str, pid: str, vid: str, dept: str) -> dict:
        """模拟患者级重载：异常 catch→return true（无提醒、完成继续）。"""
        try:
            n = run_rule_sql(conn, template, pid, vid, dept, "2026-09-23")
        except Exception as exc:  # noqa: BLE001 —— 正是被测的宿主 catch 语义
            return {"hit": False, "tip": "", "outcome": "fail-open",
                    "completion": "继续（不阻断）", "sql_error": f"{type(exc).__name__}: {exc}"}
        if n > 0:
            return {"hit": True, "tip": r2["tip"], "outcome": "hit",
                    "completion": "继续（TIP_TYPE=1 提示不阻断）"}
        return {"hit": False, "tip": "", "outcome": "business-no-hit", "completion": "继续（无提醒）"}

    broken_table = r2["sql"].replace("jhmr_file_index f", "jhmr_file_index_missing f")
    formal = formal_sql(r2, PILOT_DEPT, R3_DAYS_PLACEHOLDER)
    cases = [
        {"scenario": "SQL 异常（对象不存在）", **evaluate(broken_table, "Q1", "1", PILOT_DEPT)},
        {"scenario": "SQL 异常（语法错误）",
         **evaluate("select count(1 from pat_visit p", "Q1", "1", PILOT_DEPT)},
        {"scenario": "业务不命中（Q2 有出院记录）", **evaluate(r2["sql"], "Q2", "1", PILOT_DEPT)},
        {"scenario": "NULL 出院时间（Q6 未出院，谓词为假非异常）", **evaluate(r2["sql"], "Q6", "1", PILOT_DEPT)},
        {"scenario": "门控码不匹配（外科点击者，正式门控）", **evaluate(formal, "Q1", "1", OTHER_DEPT)},
    ]
    ok = ([c["outcome"] for c in cases] ==
          ["fail-open", "fail-open", "business-no-hit", "business-no-hit", "business-no-hit"]
          and all(c["completion"].startswith("继续") for c in cases))
    return {"case": "J08", "cases": cases,
            "diagnosis": ("『该弹没弹』排查优先看客户端 JHLog 的『个性化文书校验SQL』行与其后异常行；"
                          "fail-open（SQL 异常）与业务不命中在客户端都表现为无弹窗、完成继续——只能靠"
                          " JHLog 区分，不能以『完成继续』判定提醒成功"),
            "pass": ok}


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="054 J01-J08 离线合成验证（只读/零连接）")
    parser.add_argument("--check-package", action="store_true", help="J01 包静态校验+误启用模拟")
    parser.add_argument("--length", action="store_true", help="J02 长度语义（字符/字节）")
    parser.add_argument("--charset", choices=["utf-8", "gbk", "both"], default="both")
    parser.add_argument("--compare-readback", metavar="FILE",
                        help="J02 读回比对（JSON：[{ID,TIPMESSGE,SETTING_SQL}]，179 读回导出用）")
    parser.add_argument("--gate-matrix", action="store_true", help="J03 双科室码门控四象限")
    parser.add_argument("--rule", choices=["R1", "R2", "R3"], help="J04-J06 规则边界")
    parser.add_argument("--dataset", choices=["synthetic"], default="synthetic")
    parser.add_argument("--combine-threshold", action="store_true", help="J07 拼接与 150 阈值")
    parser.add_argument("--fail-open", action="store_true", help="J08 fail-open 区分")
    parser.add_argument("--all", action="store_true", help="J01-J08 全量（报告写 review/uat054-20260922/）")
    parser.add_argument("--emit-v2-sql", action="store_true",
                        help="输出 v2 就绪包打印稿（dry-run SQL 文件，无任何执行动作）")
    args = parser.parse_args(argv)

    if not any([args.check_package, args.length, args.compare_readback, args.gate_matrix,
                args.rule, args.combine_threshold, args.fail_open, args.all, args.emit_v2_sql]):
        parser.print_help()
        print("\n[verify_fileverify_v2] 未选择检查项。本工具只读/离线/零连接；"
              "任何 179 执行须按 054 §2/§3 批次授权逐次批准。", file=sys.stderr)
        return 2

    if args.emit_v2_sql:
        emit_v2_package(V2_PACKAGE)
        print(f"[emit] v2 打印稿 → {V2_PACKAGE}")

    results: list[dict] = []
    if args.all or args.check_package:
        results.append(check_package())
    if args.all or args.length:
        results.append(check_length(args.charset))
    if args.compare_readback:
        results.append(compare_readback(Path(args.compare_readback)))
    if args.all or args.gate_matrix:
        results.append(check_gate_matrix())
    if args.all:
        results += [check_rule("R1"), check_rule("R2"), check_rule("R3")]
    elif args.rule:
        results.append(check_rule(args.rule))
    if args.all or args.combine_threshold:
        results.append(check_combine_threshold())
    if args.all or args.fail_open:
        results.append(check_fail_open())

    overall = all(r.get("pass", True) for r in results)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"tool": "verify_fileverify_v2_20260922.py",
               "generated_at": datetime.now().isoformat(),
               "overall_pass": overall, "results": results,
               "disclaimer": "离线合成验证；不代替 179 实际读回与现场客户端验收（J09-J12）"}
    emit = OUT_DIR / "j_offline_results.json"
    emit.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n[verify_fileverify_v2] overall={'PASS' if overall else 'FAIL'} → {emit}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
