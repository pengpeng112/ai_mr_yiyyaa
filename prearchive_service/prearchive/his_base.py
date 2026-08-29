# -*- coding: utf-8 -*-
"""T8-3（031）：HIS 基本信息视图采集（VW_user_info/VW_dept_dict/VW_pats_out_hospital）。

源=HIS@10.10.10.14（his 库）——**未登记数据资产平台（BLOCKED）**，默认 disabled、
凭据占位；三视图骨架 + fixture 驱动本地可跑。

用途接线：
① receivers 工号→企微 userid 映射数据源（VW_user_info 工号体系对齐，替代透传
   passthrough mock 的生产实现占位——P0-6 基线后落地）；
② 科室名规范化（VW_dept_dict）——规则 dept_codes 与推送科室过滤用；
③ 出院患者视图（VW_pats_out_hospital）作方案③（discharge 锚点）交叉校验数据面。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class HisBaseGateway(ABC):
    """HIS 基本信息视图网关（三视图）。"""

    @abstractmethod
    def fetch_user_by_code(self, user_code: str) -> Optional[dict]:
        """VW_user_info：工号 → 人员行（含姓名/科室/状态等归一化键）。"""

    @abstractmethod
    def fetch_dept_dict(self) -> list:
        """VW_dept_dict：科室字典行列表（dept_code/dept_name/有效标志）。"""

    @abstractmethod
    def fetch_discharged_patients(self, date_from: str, date_to: str,
                                  limit: int = 100) -> list:
        """VW_pats_out_hospital：出院患者行（方案③ discharge 锚点交叉校验）。"""


def normalize_user_row(row: Optional[dict]) -> Optional[dict]:
    """VW_user_info 原始行 → 归一化（小写键 + 最小字段）。"""
    if not isinstance(row, dict):
        return None
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    code = str(lowered.get("user_code") or _fallback_user_code(lowered) or "").strip()
    if not code:
        return None
    return {
        "user_code": code,
        "user_name": str(lowered.get("user_name") or ""),
        "dept_code": str(lowered.get("dept_code") or ""),
        "dept_name": str(lowered.get("dept_name") or ""),
        "active": _parse_active(lowered.get("active")),
        "wecom_userid": str(lowered.get("wecom_userid") or ""),   # 若视图含企微号
        "raw": lowered,
    }


def _parse_active(value) -> bool:
    """active 宽容解析（幂等：bool/int/str 都正确处理，缺省=有效）。"""
    if value is None or value == "":
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in ("0", "false", "n")


def _fallback_user_code(lowered: dict) -> str:
    """常见工号列名兜底（未登记平台，列名以实测为准回填）。"""
    for key in ("usercode", "工号", "code", "emp_no", "job_number"):
        if lowered.get(key):
            return lowered[key]
    return ""


def make_userid_mapper_from_his_base(gateway: HisBaseGateway):
    """receivers.UserIdMapper 的生产实现占位（T8-3）。

    优先取视图 wecom_userid 列；缺省回落工号透传（与 passthrough 同语义）。
    P0-6 基线（W5）后按命中率数据决定是否需要中间映射表。
    """
    def mapper(doctor_id: str) -> Optional[str]:
        if not doctor_id:
            return None
        user = gateway.fetch_user_by_code(doctor_id)   # 网关契约=已归一行
        if not isinstance(user, dict):
            return None           # 工号不在视图：不下探（不透传未知工号）
        if not user["active"]:
            return None
        return user["wecom_userid"] or user["user_code"]
    return mapper


def normalize_dept_name(dept_dict_rows: list, name: str) -> str:
    """科室名规范化（VW_dept_dict）：全角/半角与首尾空白归一后精确匹配回标准名。

    未命中返回原值（fail-open，不阻断规则/推送过滤）。
    """
    target = _normalize_text(name)
    for row in dept_dict_rows or []:
        if not isinstance(row, dict):
            continue
        lowered = {str(k).strip().lower(): v for k, v in row.items()}
        for key in ("dept_name", "name", "科室名称"):
            candidate = str(lowered.get(key) or "").strip()
            if candidate and _normalize_text(candidate) == target:
                return candidate
    return name


def _normalize_text(value: str) -> str:
    return str(value or "").strip().replace("（", "(").replace("）", ")").lower()


class SqlHisBaseGateway(HisBaseGateway):
    """真实 HIS 基本信息网关（oracle@10.10.10.14 his 库；BLOCKED 未登记平台）。

    列名为骨架占位（user_code/dept_code 等）——源登记进平台后按实测回填
    （T8-3 红线：BLOCKED 源不伪造实测结果）。
    """

    USER_SQL = (
        "SELECT user_code, user_name, dept_code, dept_name, active, wecom_userid "
        "FROM hisuser.VW_user_info WHERE user_code = :user_code"
    )
    DEPT_SQL = (
        "SELECT dept_code, dept_name, active FROM hisuser.VW_dept_dict"
    )
    DISCHARGED_SQL = (
        "SELECT patient_id, visit_number, dept_code, dept_name, discharge_date "
        "FROM hisuser.VW_pats_out_hospital "
        "WHERE discharge_date >= TO_DATE(:date_from, 'yyyy-mm-dd') "
        "  AND discharge_date < TO_DATE(:date_to, 'yyyy-mm-dd') + 1 "
        "FETCH FIRST :limit ROWS ONLY"
    )

    def __init__(self, source_config: dict, password_resolver):
        self._config = source_config or {}
        self._password_resolver = password_resolver
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from sqlalchemy import create_engine

            cfg = dict(self._config)
            cfg["password"] = self._password_resolver()
            service = cfg.get("service_name") or ""
            url = (f"oracle+cx_oracle://{cfg['user']}:{cfg['password']}"
                   f"@{cfg['host']}:{cfg.get('port', 1521)}/?service_name={service}")
            self._engine = create_engine(url, pool_pre_ping=True)
        return self._engine

    def _query(self, sql: str, params: dict) -> list:
        engine = self._get_engine()
        with engine.connect() as conn:
            from sqlalchemy import text

            return [dict(row._mapping) for row in conn.execute(text(sql), params)]

    def fetch_user_by_code(self, user_code: str):
        rows = self._query(self.USER_SQL, {"user_code": user_code})
        return normalize_user_row(rows[0]) if rows else None

    def fetch_dept_dict(self):
        return self._query(self.DEPT_SQL, {})

    def fetch_discharged_patients(self, date_from: str, date_to: str,
                                  limit: int = 100):
        return self._query(self.DISCHARGED_SQL,
                           {"date_from": date_from, "date_to": date_to,
                            "limit": int(limit)})


class FixtureHisBaseGateway(HisBaseGateway):
    """三视图假源（虚构 TEST 人员/科室，列名=归一化骨架）。"""

    def __init__(self, users: list = None, depts: list = None,
                 discharged: list = None):
        self.users = users or [
            {"user_code": "TESTDOC01", "user_name": "测试医生甲",
             "dept_code": "D001", "dept_name": "普外科", "active": "1",
             "wecom_userid": ""},
            {"user_code": "TESTDOC02", "user_name": "测试医生乙",
             "dept_code": "D002", "dept_name": "呼吸内科", "active": "1",
             "wecom_userid": "wecom-TESTDOC02"},
            {"user_code": "TESTDOC09", "user_name": "停用医生",
             "dept_code": "D001", "dept_name": "普外科", "active": "0",
             "wecom_userid": ""},
        ]
        self.depts = depts or [
            {"dept_code": "D001", "dept_name": "普外科", "active": "1"},
            {"dept_code": "D002", "dept_name": "呼吸内科", "active": "1"},
            {"dept_code": "D003", "dept_name": "心脏大血管外科", "active": "1"},
        ]
        self.discharged = discharged or [
            {"patient_id": "TEST0001", "visit_number": "1",
             "dept_code": "D001", "dept_name": "普外科",
             "discharge_date": "2026-08-26"},
        ]

    def fetch_user_by_code(self, user_code: str):
        for row in self.users:
            if str(row.get("user_code")) == str(user_code):
                return normalize_user_row(dict(row))
        return None

    def fetch_dept_dict(self):
        return [dict(r) for r in self.depts]

    def fetch_discharged_patients(self, date_from: str, date_to: str,
                                  limit: int = 100):
        result = []
        for row in self.discharged:
            d = str(row.get("discharge_date") or "")
            if date_from <= d <= date_to:
                result.append(dict(row))
        return result[:int(limit)]
