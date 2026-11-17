"""JHEMR 受控写入器（病历时效质控 T8；主设计文档 §15 T8 / §14.3 调整 5 / §18.1 D3、§18.3）。

本模块是 ai_mrzk 中**唯一**允许对 JHEMR 生产库发起写操作的组件，且受三重闸门
约束（缺一不可）：

1. 闸门 1（总开关）：``timeliness.jhemr_write.enabled`` 必须为布尔 ``True``
   （默认 ``false``；字符串等非布尔值一律不放行，宁可误拦不可误写）；
2. 闸门 2（试点科室白名单）：患者所在科室代码必须在 ``timeliness.pilot_dept_codes``
   列表内（空列表 = 全部拦截）；
3. 闸门 3（语句模板白名单）：全模块只允许两个硬编码语句模板常量（模板 A 插入、
   模板 B 审批回写），方法签名一律不接受外部传入 SQL；除这些常量外不得出现任何
   写语句（测试做源码扫描）。模板 A 另受闸门 0 子开关约束（见下）。
   （2026-11-13 返工：模板 A 的 ``jhinpat_mr_monitor_items`` 字典校验 SELECT 已删除——
   活库该表列为 ``monitor_item_code`` 且专用写账号无该表 SELECT 权限，改为应用层
   常量集合 ``MONITOR_TYPE_ZERO_CODES`` 校验，不再连库查字典。）

两个语句模板：

- 模板 A（向 ``jhemr.emr_online_monitor`` 插入监控行）：**2026-11-12 用户答复 D3 闭环
  （反编译 GetMonitorNoSQL + 生产真机实证 E6 通过）后按 Q3 规范实现**——
  ``monitor_no`` 取号 = 同 ``hospital_no`` 内 ``MAX(monitor_no)+1``（首行 1，无 Sequence，
  与 JHEMR 原生一致）；``source_system_identity='AI_MRZK'`` 外插专属标记；
  ``item_code`` 入口双重校验：①不得属于 ``NATIVE_GENERATED_CODES``（JHEMR 原生
  jhinpat_mr_monitor_order 已配自动触发节点，外插会与原生行重复锁死患者——
  2026-11-10 生产已为出院记录配置 JH07.01.0004 原生触发 011）；②必须属于应用层
  常量 ``MONITOR_TYPE_ZERO_CODES``（monitor_type=0 的时效监控码，2026-11-13 对齐
  活库核实清单）；幂等防重 = ``NOT EXISTS``：同患者+住院次+监控码存在**未完成行**
  （completed_date IS NULL，含原生行）或**同一起算时间 start_date** 已有行则不重插
  （2026-11-13 返工：原「仅 AI_MRZK 行判重」既防不住原生行、又把 mul_time_flag=1
  的多次触发节点[二台手术/二次抢救/多次会诊]永久堵死；现口径=前次已完成且新
  start_date 不同的二次手术/会诊允许正常插入）。受**闸门 0 子开关**
  ``timeliness.jhemr_write.insert_monitor_enabled`` 控制（默认 false——仅限后期跨系统
  节点[手麻/危急值/抢救医嘱/输血]对接时启用）；列清单不含 ``completed_date``
  （勘误 R1/E4：该列由 JHEMR 客户端自动回填，实证见 2026-11-11 真机闭环；
  NOT EXISTS 子查询中的 ``completed_date IS NULL`` 仅为只读判定条件，非写入）；
- 模板 B（审批通过回写 ``jhemr.jhmr_monitor_limit_log``）：与 JHEMR 原生
  IPMCWidgetMRMONITORLIMIT 的更新条件一致并加 ``flag=1`` 防重复；要求
  ``rowcount == 1``，否则立即回滚并抛 ``JhemrWriteRowCountError``。

动作留痕（与 tl_action_log 模型约定一致）：

- 任一闸门不满足 → 写 ``tl_action_log(mode='BLOCKED')``，**不连库**；
- 闸门满足但 ``dry_run=True``（默认）→ 写 ``tl_action_log(mode='DRY_RUN')``，
  记录完整 SQL 与参数，**不连库**；
- 真实执行 → 先写 ``tl_action_log(mode='EXECUTED', result='executing')`` 落库，
  再连库执行，结果事后回填（成功/失败均留痕）。

写连接约束：使用**独立配置段** ``timeliness.jhemr_write``（独立账号 + 独立口令），
严禁复用只读账号 ``aizk_user``（配置了也直接拒绝）；口令来源为环境变量
``TIMELINESS_JHEMR_WRITE_PASSWORD`` 或 ``password_enc``（Fernet 解密），与只读段
同一套加解密函数，真实口令不得写入代码/配置模板/测试/日志。

红线：严禁包含任何修改 ``emr_online_monitor.completed_date`` 的语句（该列由
JHEMR 客户端/后台维护，外挂改写会与原生逻辑互相覆盖）；本任务为纯代码与本地
演练，**不连生产库执行任何写操作**。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Callable

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.config import decrypt_value
from app.timeliness.config import READONLY_USERNAME_FIXED, TimelinessError, TimelinessNotConfigured
from app.timeliness.models import TLActionLog

logger = logging.getLogger(__name__)

# 写账号口令环境变量（部署时由用户注入，不落任何文件；与只读口令环境变量分开）。
WRITE_PASSWORD_ENV_VAR = "TIMELINESS_JHEMR_WRITE_PASSWORD"

ACTION_TYPE_INSERT_MONITOR = "JHEMR_INSERT_MONITOR"
ACTION_TYPE_APPROVE = "JHEMR_APPROVE"

# ---------------------------------------------------------------------------
# 闸门 3：语句模板白名单（硬编码常量，禁止外部传入 SQL）。
# 除以下两个常量外，本模块源码不得再出现任何写语句关键词（源码扫描测试在
# tests/timeliness/test_jhemr_writer.py）。注释与异常文案一律用中文描述，避免
# 出现裸 SQL 关键词。
# ---------------------------------------------------------------------------

# 模板 A：插入监控行（2026-11-12 D3 答复后按 Q3 规范实现；受闸门 0 子开关控制，默认关闭；
# 2026-11-13 返工修订防重条件与字典校验方式）。
# - 列清单（15 列）⊆ T1 真实列核对（23 列），不含 completed_date（勘误 R1/E4）；
# - monitor_no 取号：同 hospital_no 内 MAX+1（首行 1），与 JHEMR 原生 GetMonitorNoSQL 一致；
# - 幂等防重（2026-11-13 返工口径）：同患者+住院次+监控码存在未完成行
#   （completed_date IS NULL，含 JHEMR 原生行）或同一起算时间 start_date 已有行则整条
#   不插入（NOT EXISTS，rowcount=0 → duplicate）；前次已完成且新 start_date 不同的
#   mul_time_flag=1 二次触发节点（二台手术/二次抢救/多次会诊）允许正常插入；
# - timeout_indicator=0（客户端 20191220WHL001='1' 实时算超时）、monitor_type=0、
#   total_write_times=1、finished_write_times=0 按 Q3 必填列规范硬编码。
SQL_INSERT_MONITOR_TEMPLATE = (
    "INSERT INTO jhemr.emr_online_monitor ("
    "patient_id, visit_id, name, monitor_no, item_code, item_name, start_date, "
    "end_date, timeout_indicator, monitor_type, total_write_times, finished_write_times, "
    "hospital_no, source_system_identity, dept_code"
    ") SELECT %s, %s, %s, "
    "(CASE WHEN (SELECT MAX(monitor_no) FROM jhemr.emr_online_monitor WHERE hospital_no = %s) IS NULL "
    "THEN 1 ELSE (SELECT MAX(monitor_no) + 1 FROM jhemr.emr_online_monitor WHERE hospital_no = %s) END), "
    "%s, %s, %s, %s, 0, 0, 1, 0, %s, 'AI_MRZK', %s "
    "WHERE NOT EXISTS (SELECT 1 FROM jhemr.emr_online_monitor "
    "WHERE patient_id = %s AND visit_id = %s AND item_code = %s "
    "AND (completed_date IS NULL OR start_date = %s))"
)

# 外插专属标记（审计与回滚定位依据）与院区号默认值（Q3 规范）。
SOURCE_SYSTEM_IDENTITY = "AI_MRZK"
HOSPITAL_NO_DEFAULT = "49557032X"

# ---------------------------------------------------------------------------
# 应用层监控码校验常量（2026-11-13 返工：替代对 jhemr.jhinpat_mr_monitor_items 的
# 连库字典校验 SELECT——活库该表真实列为 monitor_item_code（无 item_code 列）、
# monitor_type 为 numeric 0/1，且专用写账号 mrzk_timeliness_write 最小权限仅
# INSERT ON emr_online_monitor + UPDATE ON jhmr_monitor_limit_log，无该表 SELECT 权限，
# 原连库校验在真库必崩 ORA/42501）。
# ---------------------------------------------------------------------------

# monitor_type=0（时效监控）字典码全集：与主设计文档 §10.1 生产实测编码子集
# （app/routers/timeliness.MONITOR_ITEM_DICT，27 项）同源；测试保证两处一致。
MONITOR_TYPE_ZERO_CODES = frozenset({
    "JH04.02.001", "JH04.02.002", "JH04.02.003", "JH04.02.004", "JH04.02.005",
    "JH04.02.006", "JH04.02.007", "JH04.02.008", "JH04.02.011", "JH04.02.012",
    "JH04.02.013", "JH04.02.015", "JH04.02.016", "JH04.02.017", "JH04.02.018",
    "JH04.02.019", "JH04.02.020",
    "JH04.03.001", "JH04.03.002", "JH04.03.007", "JH04.03.010", "JH04.03.011",
    "JH04.03.012", "JH04.03.013", "JH04.03.016", "JH04.03.017", "JH04.03.018",
})

# JHEMR 原生自动生成监控码（jhinpat_mr_monitor_order 已配自动触发节点）：
# 外插这些码会与原生行重复（同患者同码多行未完成 → 患者被反复锁死），一律拒绝。
# 注：JH04.02.011（出院记录）已于 2026-11-10 在生产配置 JH07.01.0004 原生自动触发。
NATIVE_GENERATED_CODES = frozenset({
    "JH04.02.001",   # 入院记录（全院 65 模板补码+118 幽灵行销账，2026-11-10 两科试点已启用原生锁定）
    "JH04.02.002",   # 首次病程记录
    "JH04.02.006",   # 阶段小结
    "JH04.02.008",   # 首次主任/副主任查房
    "JH04.02.011",   # 出院记录（2026-11-10 起原生自动触发）
})

# 模板 B：审批通过回写（与原生审批条件一致 + flag=1 防重复；要求 rowcount==1）。
SQL_APPROVE_LIMIT_LOG_TEMPLATE = (
    "UPDATE jhemr.jhmr_monitor_limit_log SET approve_user_id=%s, approve_date_time=%s, "
    "flag=2 WHERE patient_id=%s AND visit_id=%s AND monitor_code=%s AND "
    "apply_date_time=%s AND type=%s AND hospital_no=%s AND flag=1"
)


class JhemrWriteError(TimelinessError):
    """受控写入器基础异常（入参非法、配置误用等）。"""


class JhemrWriteRowCountError(JhemrWriteError):
    """模板 B 执行后受影响行数不等于 1（0=申请行不存在或已审批，>1=键不唯一）。"""


def resolve_jhemr_write(section: dict | None) -> dict:
    """校验 ``timeliness.jhemr_write`` 并解析写连接参数（口令已解密）。

    - 与只读段相互独立：host/账号/口令均取自本段，严禁复用只读账号
      ``aizk_user``（配了同名账号直接拒绝，宁可误拦不可误写）；
    - 口令解析顺序：环境变量 TIMELINESS_JHEMR_WRITE_PASSWORD → password_enc
      （app.config.decrypt_value 解密；解密失败拒绝回退明文）；
    - 返回 dict：host/port/database/username/password/statement_timeout_ms/
      connect_timeout_seconds/sslmode。password 仅在内存中传递。
    """
    write_cfg = (section or {}).get("jhemr_write") or {}
    if not isinstance(write_cfg, dict):
        raise TimelinessNotConfigured("timeliness.jhemr_write 配置段类型错误")

    host = str(write_cfg.get("host") or "").strip()
    if not host:
        raise TimelinessNotConfigured("timeliness.jhemr_write.host 未配置（写连接须独立配置，不复用只读段）")

    username = str(write_cfg.get("username") or "").strip()
    if not username:
        raise TimelinessNotConfigured("timeliness.jhemr_write.username 未配置（须使用专用写账号）")
    if username == READONLY_USERNAME_FIXED:
        raise TimelinessNotConfigured(
            f"写账号不得复用只读账号 {READONLY_USERNAME_FIXED}（T8：读写账号必须分离）"
        )

    password = os.environ.get(WRITE_PASSWORD_ENV_VAR, "").strip()
    if not password:
        token = str(write_cfg.get("password_enc") or "").strip()
        if token:
            try:
                password = decrypt_value(token)
            except InvalidToken:
                raise RuntimeError(
                    "timeliness.jhemr_write.password_enc 解密失败"
                    "（SECRET_KEY 与密文不匹配，疑似密钥漂移），拒绝回退明文"
                ) from None
    if not password:
        raise TimelinessNotConfigured(
            f"JHEMR 写账号口令未配置：请设置环境变量 {WRITE_PASSWORD_ENV_VAR}"
            "，或在 config.json 的 timeliness.jhemr_write.password_enc 填入 Fernet 密文"
        )

    return {
        "host": host,
        "port": int(write_cfg.get("port") or 5432),
        "database": str(write_cfg.get("database") or "jhemr").strip() or "jhemr",
        "username": username,
        "password": password,
        "statement_timeout_ms": int(write_cfg.get("statement_timeout_ms") or 60000),
        "connect_timeout_seconds": int(write_cfg.get("connect_timeout_seconds") or 10),
        "sslmode": str(write_cfg.get("sslmode") or "").strip(),
    }


def _dump_params(params: dict) -> str:
    return json.dumps(params, ensure_ascii=False, sort_keys=True, default=str)


class JhemrWriter:
    """JHEMR 受控写入器：闸门 → 留痕 → （演练记录或受控执行）。"""

    def __init__(
        self,
        db: Session,
        config: dict | None,
        *,
        connect: Callable[..., Any] | None = None,
        now_fn: Callable[[], datetime] = datetime.now,
    ):
        self.db = db
        self.config = config or {}
        self._connect = connect  # 仅供测试注入假连接工厂；生产路径延迟导入 psycopg2
        self._now = now_fn
        self._section = self.config.get("timeliness") or {}
        if not isinstance(self._section, dict):
            self._section = {}

    # ---- 闸门 ----

    def _gate_enabled(self) -> tuple[bool, str]:
        """闸门 1：timeliness.jhemr_write.enabled 必须为布尔 True（严格判定）。"""
        write_cfg = self._section.get("jhemr_write") or {}
        if isinstance(write_cfg, dict) and write_cfg.get("enabled") is True:
            return True, ""
        return False, "gate1: timeliness.jhemr_write.enabled is not true (default false)"

    def _gate_pilot_dept(self, dept_code: str | None) -> tuple[bool, str]:
        """闸门 2：科室必须在 timeliness.pilot_dept_codes 白名单内。"""
        dept = str(dept_code or "").strip()
        if not dept:
            return False, "gate2: patient dept_code is empty"
        pilots = self._section.get("pilot_dept_codes") or []
        if isinstance(pilots, list) and dept in [str(x).strip() for x in pilots if str(x or "").strip()]:
            return True, ""
        return False, f"gate2: dept {dept!r} not in timeliness.pilot_dept_codes"

    # ---- 留痕 ----

    def _write_action_log(
        self,
        *,
        action_type: str,
        mode: str,
        sql_text: str | None,
        params_json: str | None,
        target: str | None,
        operator: str | None,
        result: str | None,
        event_id: int | None,
    ) -> TLActionLog:
        log = TLActionLog(
            event_id=event_id,
            action_type=action_type,
            mode=mode,
            target=target,
            operator=operator,
            created_at=self._now(),
            sql_text=sql_text,
            params_json=params_json or "{}",
            result=result,
        )
        self.db.add(log)
        self.db.commit()
        return log

    def _connect_write(self):
        """按 jhemr_write 段建立写连接（调用方负责关闭）。"""
        params = resolve_jhemr_write(self._section)
        if self._connect is None:
            import psycopg2

            connect_factory: Callable[..., Any] = psycopg2.connect
        else:
            connect_factory = self._connect
        conn_kwargs: dict[str, Any] = {
            "host": params["host"],
            "port": params["port"],
            "dbname": params["database"],
            "user": params["username"],
            "password": params["password"],
            "connect_timeout": params["connect_timeout_seconds"],
        }
        # sslmode 为可选项：仅当配置显式提供时才传（AGENTS.md Vastbase 约定）。
        if params["sslmode"]:
            conn_kwargs["sslmode"] = params["sslmode"]
        conn = connect_factory(**conn_kwargs)
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = %s", (int(params["statement_timeout_ms"]),))
        return conn

    # ---- 模板 A：插入监控行（D3 答复后实现；闸门 0 子开关默认关闭） ----

    def _gate_insert_monitor_enabled(self) -> tuple[bool, str]:
        """闸门 0（模板 A 专属子开关）：jhemr_write.insert_monitor_enabled 必须为布尔 True。

        默认 false：仅限后期跨系统节点（手麻/危急值/抢救医嘱/输血）对接时启用；
        JHEMR 原生已配节点（jhinpat_mr_monitor_order：001/002/011 等）严禁外插。
        """
        write_cfg = self._section.get("jhemr_write") or {}
        if isinstance(write_cfg, dict) and write_cfg.get("insert_monitor_enabled") is True:
            return True, ""
        return False, (
            "gate0: insert_monitor is disabled by default "
            "(timeliness.jhemr_write.insert_monitor_enabled is not true; "
            "only for future cross-system nodes, never for natively generated ones)"
        )

    def insert_monitor_row(
        self,
        *,
        patient_id: str,
        visit_id: str,
        name: str,
        item_code: str,
        item_name: str,
        start_date: datetime,
        end_date: datetime,
        dept_code: str | None,
        hospital_no: str = HOSPITAL_NO_DEFAULT,
        dry_run: bool = True,
        operator: str | None = None,
        event_id: int | None = None,
    ) -> dict[str, Any]:
        """按模板 A 外插一条监控行（D3/E6 已实证；默认演练不连库）。

        入口校验（dry_run 与真实执行均生效，闸门之前）：
        1) ``item_code`` 不得属于 ``NATIVE_GENERATED_CODES``（JHEMR 原生自动生成
           节点，外插会与原生行重复锁死患者）→ 记 BLOCKED 拒绝；
        2) ``item_code`` 必须属于 ``MONITOR_TYPE_ZERO_CODES``（monitor_type=0 时效
           监控码，应用层常量，2026-11-13 返工后不再连库查 jhinpat_mr_monitor_items）
           → 不在集合内记 BLOCKED 拒绝。

        闸门次序：入口校验 → 0 子开关（insert_monitor_enabled，默认 false）→
        1 总开关 → 2 科室白名单 →（演练 DRY_RUN 留痕，不连库）→ 真实执行：
        INSERT（rowcount=1 成功提交；rowcount=0 幂等防重命中，回滚返回 duplicate
        不抛；其他异常回滚抛出）。``monitor_no`` 由取号 CASE 自动生成；
        ``completed_date`` 永不写入（由 JHEMR 客户端回填）。
        """
        missing = [
            arg_name
            for arg_name, value in (
                ("patient_id", patient_id),
                ("visit_id", visit_id),
                ("name", name),
                ("item_code", item_code),
                ("item_name", item_name),
                ("start_date", start_date),
                ("end_date", end_date),
                ("hospital_no", hospital_no),
            )
            if value is None or str(value).strip() == ""
        ]
        if missing:
            raise JhemrWriteError(f"模板 A 入参缺失: {', '.join(missing)}")

        sql = SQL_INSERT_MONITOR_TEMPLATE
        params: list[Any] = [
            patient_id,
            visit_id,
            name,
            hospital_no,  # 取号 MAX
            hospital_no,  # 取号 MAX+1
            item_code,
            item_name,
            start_date,
            end_date,
            hospital_no,
            dept_code,
            patient_id,   # NOT EXISTS 防重（patient_id）
            visit_id,     # NOT EXISTS 防重（visit_id）
            item_code,    # NOT EXISTS 防重（item_code）
            start_date,   # NOT EXISTS 防重（start_date：同起算时间已有行不重插）
        ]
        params_json = _dump_params(
            {
                "patient_id": patient_id,
                "visit_id": visit_id,
                "name": name,
                "item_code": item_code,
                "item_name": item_name,
                "start_date": start_date,
                "end_date": end_date,
                "dept_code": dept_code,
                "hospital_no": hospital_no,
                "monitor_no": "auto: MAX(monitor_no)+1 per hospital_no (first=1)",
                "timeout_indicator": 0,
                "monitor_type": 0,
                "total_write_times": 1,
                "finished_write_times": 0,
                "source_system_identity": SOURCE_SYSTEM_IDENTITY,
                "completed_date": None,
                "dedupe": (
                    "NOT EXISTS same patient+visit+item "
                    "(completed_date IS NULL OR start_date = t0)"
                ),
            }
        )
        target = "|".join(str(x) for x in ("jhemr.emr_online_monitor", patient_id, visit_id, item_code))[:200]
        op = operator or "system"

        # 入口校验 1：JHEMR 原生自动生成监控码一律拒绝外插（dry_run 同样生效）——
        # 外插会与 jhinpat_mr_monitor_order 配置的原生自动触发行重复，患者被反复锁死。
        if item_code in NATIVE_GENERATED_CODES:
            reason = (
                f"blocked: item_code {item_code} is natively generated by JHEMR "
                "(jhinpat_mr_monitor_order auto trigger), external insert forbidden"
            )
            log = self._write_action_log(
                action_type=ACTION_TYPE_INSERT_MONITOR, mode="BLOCKED", sql_text=sql, params_json=params_json,
                target=target, operator=op, result=reason, event_id=event_id,
            )
            return {"handled": False, "executed": False, "mode": "BLOCKED", "monitor_no": None,
                    "action_log_id": log.id, "reason": reason}

        # 入口校验 2（2026-11-13 返工）：应用层 monitor_type=0 时效监控码白名单——
        # 专用写账号无 jhinpat_mr_monitor_items SELECT 权限（且活库该表无 item_code 列），
        # 原连库字典校验已删除，改为常量集合校验。
        if item_code not in MONITOR_TYPE_ZERO_CODES:
            reason = (
                f"blocked: item_code {item_code} not in MONITOR_TYPE_ZERO_CODES "
                "(monitor_type=0 timeliness codes, verified against live dict)"
            )
            log = self._write_action_log(
                action_type=ACTION_TYPE_INSERT_MONITOR, mode="BLOCKED", sql_text=sql, params_json=params_json,
                target=target, operator=op, result=reason, event_id=event_id,
            )
            return {"handled": False, "executed": False, "mode": "BLOCKED", "monitor_no": None,
                    "action_log_id": log.id, "reason": reason}

        # 闸门 0 → 1 → 2。
        ok0, reason0 = self._gate_insert_monitor_enabled()
        if not ok0:
            log = self._write_action_log(
                action_type=ACTION_TYPE_INSERT_MONITOR, mode="BLOCKED", sql_text=sql, params_json=params_json,
                target=target, operator=op, result=reason0, event_id=event_id,
            )
            return {"handled": False, "executed": False, "mode": "BLOCKED", "monitor_no": None,
                    "action_log_id": log.id, "reason": reason0}
        ok1, reason1 = self._gate_enabled()
        if not ok1:
            log = self._write_action_log(
                action_type=ACTION_TYPE_INSERT_MONITOR, mode="BLOCKED", sql_text=sql, params_json=params_json,
                target=target, operator=op, result=reason1, event_id=event_id,
            )
            return {"handled": False, "executed": False, "mode": "BLOCKED", "monitor_no": None,
                    "action_log_id": log.id, "reason": reason1}
        ok2, reason2 = self._gate_pilot_dept(dept_code)
        if not ok2:
            log = self._write_action_log(
                action_type=ACTION_TYPE_INSERT_MONITOR, mode="BLOCKED", sql_text=sql, params_json=params_json,
                target=target, operator=op, result=reason2, event_id=event_id,
            )
            return {"handled": False, "executed": False, "mode": "BLOCKED", "monitor_no": None,
                    "action_log_id": log.id, "reason": reason2}

        # 演练：只留痕（完整 SQL 与参数），不连库。
        if dry_run:
            log = self._write_action_log(
                action_type=ACTION_TYPE_INSERT_MONITOR, mode="DRY_RUN", sql_text=sql, params_json=params_json,
                target=target, operator=op, result="dry_run: statement recorded without execution",
                event_id=event_id,
            )
            return {"handled": True, "executed": False, "mode": "DRY_RUN", "monitor_no": None,
                    "action_log_id": log.id, "reason": ""}

        # 真实执行：写连接配置不完整按拦截处理（不连库，补齐后可重试）。
        try:
            resolve_jhemr_write(self._section)
        except (TimelinessNotConfigured, RuntimeError) as exc:
            reason = f"blocked: jhemr_write connection not configured ({type(exc).__name__})"
            log = self._write_action_log(
                action_type=ACTION_TYPE_INSERT_MONITOR, mode="BLOCKED", sql_text=sql, params_json=params_json,
                target=target, operator=op, result=reason, event_id=event_id,
            )
            return {"handled": False, "executed": False, "mode": "BLOCKED", "monitor_no": None,
                    "action_log_id": log.id, "reason": reason}

        log = self._write_action_log(
            action_type=ACTION_TYPE_INSERT_MONITOR, mode="EXECUTED", sql_text=sql, params_json=params_json,
            target=target, operator=op, result="executing", event_id=event_id,
        )
        conn = self._connect_write()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rowcount = int(getattr(cur, "rowcount", -1) or 0)
            if rowcount == 0:
                # NOT EXISTS 防重命中：同患者+住院次+监控码存在未完成行（含原生行）
                # 或同一起算时间 start_date 已有行，幂等不重复插入。
                conn.rollback()
                log.result = (
                    "duplicate: existing open row (completed_date IS NULL) or same start_date "
                    "for patient+visit+item, nothing written"
                )
                self.db.commit()
                return {"handled": True, "executed": False, "mode": "EXECUTED", "monitor_no": None,
                        "duplicate": True, "action_log_id": log.id,
                        "reason": "duplicate: insert skipped by NOT EXISTS guard"}
            if rowcount != 1:
                conn.rollback()
                log.result = f"failed: rowcount={rowcount} (expected 1), rolled back"
                self.db.commit()
                raise JhemrWriteRowCountError(
                    f"模板 A 受影响行数为 {rowcount}（要求 1）：已回滚，未产生任何变更"
                )
            conn.commit()
        except JhemrWriteRowCountError:
            raise
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:  # 回滚失败不掩盖原始异常
                logger.error("[timeliness] 写连接回滚失败: %s", type(exc).__name__)
            log.result = f"failed: {type(exc).__name__}, rolled back"
            self.db.commit()
            raise
        finally:
            conn.close()
        log.result = "success: rowcount=1 (monitor_no auto-assigned)"
        self.db.commit()
        return {"handled": True, "executed": True, "mode": "EXECUTED", "monitor_no": None,
                "duplicate": False, "action_log_id": log.id, "reason": ""}

    # ---- 模板 B：审批通过回写 ----

    def approve_limit_log(
        self,
        *,
        patient_id: str,
        visit_id: str,
        dept_code: str | None,
        monitor_code: str,
        apply_date_time: datetime,
        limit_type: Any,
        hospital_no: str,
        approve_user_id: str,
        approve_date_time: datetime | None = None,
        dry_run: bool = True,
        operator: str | None = None,
        event_id: int | None = None,
    ) -> dict[str, Any]:
        """审批通过：按模板 B 把一条 ``flag=1`` 的申请行回写为 ``flag=2``。

        - 任一闸门不满足 → 留痕 BLOCKED，不连库，返回 mode=BLOCKED；
        - 闸门满足且 dry_run=True（默认）→ 留痕 DRY_RUN（含完整 SQL 与参数），
          不连库；
        - 真实执行：先留痕 EXECUTED(result=executing) 再连库；受影响行数必须
          等于 1，否则立即回滚、留痕失败原因并抛 JhemrWriteRowCountError；
          连接/执行的其他异常回滚后原样抛出（留痕失败原因）。
        """
        # 入参校验：键值齐全才允许进入闸门（与 jhmr_monitor_limit_log 键列一致）。
        missing = [
            name
            for name, value in (
                ("patient_id", patient_id),
                ("visit_id", visit_id),
                ("monitor_code", monitor_code),
                ("apply_date_time", apply_date_time),
                ("limit_type", limit_type),
                ("hospital_no", hospital_no),
                ("approve_user_id", approve_user_id),
            )
            if value is None or str(value).strip() == ""
        ]
        if missing:
            raise JhemrWriteError(f"模板 B 入参缺失: {', '.join(missing)}")

        approve_dt = approve_date_time or self._now()
        sql = SQL_APPROVE_LIMIT_LOG_TEMPLATE
        params: tuple[Any, ...] = (
            approve_user_id,
            approve_dt,
            patient_id,
            visit_id,
            monitor_code,
            apply_date_time,
            limit_type,
            hospital_no,
        )
        params_json = _dump_params(
            {
                "approve_user_id": approve_user_id,
                "approve_date_time": approve_dt,
                "patient_id": patient_id,
                "visit_id": visit_id,
                "monitor_code": monitor_code,
                "apply_date_time": apply_date_time,
                "type": limit_type,
                "hospital_no": hospital_no,
            }
        )
        target = "|".join(
            str(x) for x in ("jhemr.jhmr_monitor_limit_log", patient_id, visit_id, monitor_code, apply_date_time)
        )[:200]
        op = operator or approve_user_id

        # 闸门 1 + 闸门 2（闸门 3 由模板常量结构性保证）。
        ok1, reason1 = self._gate_enabled()
        if not ok1:
            log = self._write_action_log(
                action_type=ACTION_TYPE_APPROVE, mode="BLOCKED", sql_text=sql, params_json=params_json,
                target=target, operator=op, result=reason1, event_id=event_id,
            )
            return {"handled": False, "executed": False, "mode": "BLOCKED", "rowcount": None,
                    "action_log_id": log.id, "reason": reason1}
        ok2, reason2 = self._gate_pilot_dept(dept_code)
        if not ok2:
            log = self._write_action_log(
                action_type=ACTION_TYPE_APPROVE, mode="BLOCKED", sql_text=sql, params_json=params_json,
                target=target, operator=op, result=reason2, event_id=event_id,
            )
            return {"handled": False, "executed": False, "mode": "BLOCKED", "rowcount": None,
                    "action_log_id": log.id, "reason": reason2}

        # 演练：只留痕（完整 SQL 与参数），不连库。
        if dry_run:
            log = self._write_action_log(
                action_type=ACTION_TYPE_APPROVE, mode="DRY_RUN", sql_text=sql, params_json=params_json,
                target=target, operator=op, result="dry_run: statement recorded without execution",
                event_id=event_id,
            )
            return {"handled": True, "executed": False, "mode": "DRY_RUN", "rowcount": None,
                    "action_log_id": log.id, "reason": ""}

        # 真实执行：写连接配置不完整同样按拦截处理（不连库，可补齐后重试）。
        try:
            resolve_jhemr_write(self._section)
        except (TimelinessNotConfigured, RuntimeError) as exc:
            reason = f"blocked: jhemr_write connection not configured ({type(exc).__name__})"
            log = self._write_action_log(
                action_type=ACTION_TYPE_APPROVE, mode="BLOCKED", sql_text=sql, params_json=params_json,
                target=target, operator=op, result=reason, event_id=event_id,
            )
            return {"handled": False, "executed": False, "mode": "BLOCKED", "rowcount": None,
                    "action_log_id": log.id, "reason": reason}

        # 先留痕（EXECUTED/executing）再动库；结果事后回填。
        log = self._write_action_log(
            action_type=ACTION_TYPE_APPROVE, mode="EXECUTED", sql_text=sql, params_json=params_json,
            target=target, operator=op, result="executing", event_id=event_id,
        )
        conn = self._connect_write()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, list(params))
                rowcount = int(getattr(cur, "rowcount", -1) or 0)
            if rowcount != 1:
                conn.rollback()
                log.result = f"failed: rowcount={rowcount} (expected 1), rolled back"
                self.db.commit()
                raise JhemrWriteRowCountError(
                    f"模板 B 受影响行数为 {rowcount}（要求 1）：0=申请行不存在或已审批，"
                    ">1=键不唯一；已回滚，未产生任何变更"
                )
            conn.commit()
        except JhemrWriteRowCountError:
            raise
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:  # 回滚失败不掩盖原始异常
                logger.error("[timeliness] 写连接回滚失败: %s", type(exc).__name__)
            log.result = f"failed: {type(exc).__name__}, rolled back"
            self.db.commit()
            raise
        finally:
            conn.close()
        log.result = "success: rowcount=1"
        self.db.commit()
        return {"handled": True, "executed": True, "mode": "EXECUTED", "rowcount": 1,
                "action_log_id": log.id, "reason": ""}
