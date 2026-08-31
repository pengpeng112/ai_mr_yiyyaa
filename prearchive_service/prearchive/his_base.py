# -*- coding: utf-8 -*-
"""T8-3（031）：HIS 基本信息视图采集（VW_user_info/VW_dept_dict/VW_pats_out_hospital）。

源=hisbase_oracle_10_10_10_14（Oracle，service_name=hisserver——不是 hissuer），
2026-08-29 已登记数据资产平台并端到端验证通过；默认 disabled、凭据占位，
真实连接只发生在生产受控配置。

三视图实测结构（2026-08-29 采样）：
- VW_user_info（4,278 行，7 列）：FID=工号（实测格式 000201）/FNAME=姓名/
  FDEPT=科室代码/FDOCT=科室名称（实测值是"口腔科/病案室"等——**不是医生标志位**，
  按此语义映射）/FPOSITION=职务/FUSERTYPE=用户类型；视图无 active/企微号列——
  active 缺省视为有效（fail-open），wecom_userid 缺省回落工号；
- VW_dept_dict（816 行，6 列）：FID（疑似科室代码）/FNAME（科室名）/
  FQUN/FBETO/FTYPE/FBQNT——FID 与 VW_user_info.FDEPT 的 join 命中率见交付报告；
- VW_pats_out_hospital（62,885 行，53 列）：FPATIENTID/FBIHID/FBINCU/FNAME/
  FIHDAT/FOOFFI/FGUIDANGDATE(归档日期)/FLEVWAY(离院方式)/FISSURGERY/FSURGERYCODE/
  FTRANSFUSION 等——本期仅采样接口 + 文档记录（未来出院触发交叉校验/手术触发
  证据的候选源），零触发实现。

用途接线：
① receivers.HisBaseUserIdMapper：工号→企微 userid 映射（VW_user_info 工号体系），
   config receiver.userid_mapper_source=hisbase 时启用（默认 passthrough 不变）；
② HisBaseDeptNormalizer（VW_dept_dict 代码→名称）——规则 dept_codes 匹配与
   推送文案用（receiver.dept_normalizer_source=hisbase 时启用，默认 off）；
③ VW_pats_out_hospital 出院患者视图作方案③（discharge 锚点）交叉校验数据面。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import re
import unicodedata
from typing import Optional


class HisBaseGateway(ABC):
    """HIS 基本信息视图网关（三视图）。"""

    @abstractmethod
    def fetch_user_by_code(self, user_code: str) -> Optional[dict]:
        """VW_user_info：工号（FID）→ 归一化人员行；查无返回 None。"""

    @abstractmethod
    def fetch_user_info(self) -> list:
        """VW_user_info：全量行（4,278 行级；join 命中率采样/映射缓存用）。"""

    @abstractmethod
    def fetch_dept_dict(self) -> list:
        """VW_dept_dict：科室字典行列表（实测列 FID/FNAME/FQUN/FBETO/FTYPE/FBQNT）。"""

    @abstractmethod
    def fetch_out_hospital_sample(self, limit: int = 100) -> list:
        """VW_pats_out_hospital：限量采样行（未来交叉校验候选源，本期零触发实现）。"""


def normalize_user_row(row: Optional[dict]) -> Optional[dict]:
    """VW_user_info 原始行（实测列 FID/FNAME/FDEPT/FDOCT/…）→ 归一化人员行。

    兼容旧归一化键（user_code/user_name/…，fixture 用）；实测列优先。
    视图无 active/企微号列：active 缺省=有效（fail-open），wecom_userid 缺省空。
    """
    if not isinstance(row, dict):
        return None
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    code = str(lowered.get("user_code") or lowered.get("fid")
               or _fallback_user_code(lowered) or "").strip()
    if not code:
        return None
    return {
        "user_code": code,
        "user_name": str(lowered.get("user_name") or lowered.get("fname") or ""),
        "dept_code": str(lowered.get("dept_code") or lowered.get("fdept") or ""),
        "dept_name": str(lowered.get("dept_name") or lowered.get("fdoct") or ""),
        "active": _parse_active(lowered.get("active")),
        "wecom_userid": str(lowered.get("wecom_userid") or ""),   # 视图实测无此列
        "position": str(lowered.get("fposition") or ""),
        "user_type": str(lowered.get("fusertype") or ""),
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
    """其他常见工号列名兜底。"""
    for key in ("usercode", "工号", "code", "emp_no", "job_number"):
        if lowered.get(key):
            return lowered[key]
    return ""


def normalize_dept_rows(rows: list) -> list:
    """VW_dept_dict 原始行（实测列 FID=科室代码/FNAME=科室名）→ 归一化字典行。

    兼容旧归一化键（dept_code/dept_name，fixture 用）。
    """
    normalized = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        lowered = {str(k).strip().lower(): v for k, v in row.items()}
        code = str(lowered.get("dept_code") or lowered.get("fid") or "").strip()
        name = str(lowered.get("dept_name") or lowered.get("fname") or "").strip()
        if not code and not name:
            continue
        normalized.append({
            "dept_code": code,
            "dept_name": name,
            "dept_type": str(lowered.get("ftype") or ""),
            "raw": lowered,
        })
    return normalized


def make_userid_mapper_from_his_base(gateway: HisBaseGateway):
    """receivers.UserIdMapper 的 HIS 基本信息实现（T8-3，2026-08-29 实测转正）。

    优先取视图 wecom_userid 列（实测视图无此列，恒回落工号）；
    查无/停用返回 None → DefaultReceiverResolver 继续下探兜底链。
    """
    from .receivers import HisBaseUserIdMapper

    return HisBaseUserIdMapper(gateway)


def normalize_dept_name(dept_dict_rows: list, name: str) -> str:
    """科室名规范化：全角/半角与首尾空白归一后精确匹配回标准名。

    未命中返回原值（fail-open，不阻断规则/推送过滤）。
    """
    target = _normalize_text(name)
    for row in normalize_dept_rows(dept_dict_rows):
        candidate = row["dept_name"]
        if candidate and _normalize_text(candidate) == target:
            return candidate
    return name


class HisBaseDeptNormalizer:
    """VW_dept_dict 科室规范化器：代码→标准名称，供规则 dept_codes 匹配参考与
    推送文案使用（receiver.dept_normalizer_source=hisbase 时启用，默认 off）。

    - name_for_code：科室代码 → 字典标准名（未命中返回原代码，fail-open）；
    - normalize_name：任意科室名 → 字典标准名（全角/半角/空白归一后精确匹配）。
    """

    def __init__(self, dept_dict_rows: list):
        self._rows = normalize_dept_rows(dept_dict_rows)
        self._by_code = {r["dept_code"]: r["dept_name"] for r in self._rows
                         if r["dept_code"]}

    @property
    def rows(self) -> list:
        return self._rows

    def name_for_code(self, dept_code: str) -> str:
        code = str(dept_code or "").strip()
        if not code:
            return ""
        return self._by_code.get(code, code)   # 未命中返回原代码（fail-open）

    def normalize_name(self, name: str) -> str:
        return normalize_dept_name(self._rows, name)

    def matches(self, dept_code: str, dept_name: str, allowed_values: list) -> bool:
        """规则科室范围匹配：同时接受代码、字典标准名与原始科室名。"""
        allowed = {_normalize_text(value) for value in (allowed_values or [])
                   if str(value or "").strip()}
        if not allowed:
            return True
        code = str(dept_code or "").strip()
        candidates = {code, self.name_for_code(code), self.normalize_name(dept_name)}
        return any(_normalize_text(value) in allowed for value in candidates if value)


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", "", text).lower()


class SqlHisBaseGateway(HisBaseGateway):
    """真实 HIS 基本信息网关（oracle@10.10.10.14，service_name=hisserver；
    2026-08-29 平台端到端验证通过）。SQL 按 2026-08-29 实测列结构回填。"""

    # 实测 7 列中的 6 个已知语义列（第 7 列语义未采样，不影响映射）
    USER_SQL = (
        "SELECT FID, FNAME, FDEPT, FDOCT, FPOSITION, FUSERTYPE "
        "FROM hisuser.VW_user_info WHERE FID = :user_code"
    )
    USER_INFO_SQL = (
        "SELECT FID, FNAME, FDEPT, FDOCT, FPOSITION, FUSERTYPE "
        "FROM hisuser.VW_user_info"
    )
    DEPT_SQL = (
        "SELECT FID, FNAME, FQUN, FBETO, FTYPE, FBQNT FROM hisuser.VW_dept_dict"
    )
    # 53 列中取交叉校验候选所需子集；FGUIDANGDATE=归档日期、FLEVWAY=离院方式；
    # 出院日期列语义与完整列清单待 W9 核对——本期仅限量采样，不做日期过滤
    OUT_HOSPITAL_SQL = (
        "SELECT FPATIENTID, FBIHID, FBINCU, FNAME, FIHDAT, FOOFFI, "
        "       FGUIDANGDATE, FLEVWAY "
        "FROM hisuser.VW_pats_out_hospital "
        "WHERE ROWNUM <= :limit"
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

    def fetch_user_info(self):
        return self._query(self.USER_INFO_SQL, {})

    def fetch_dept_dict(self):
        return self._query(self.DEPT_SQL, {})

    def fetch_out_hospital_sample(self, limit: int = 100):
        safe_limit = max(0, int(limit))
        if safe_limit == 0:
            return []
        return self._query(self.OUT_HOSPITAL_SQL, {"limit": safe_limit})


class FixtureHisBaseGateway(HisBaseGateway):
    """三视图假源（虚构 TEST 人员/科室；行=VW_* 实测列名结构）。"""

    def __init__(self, users: list = None, depts: list = None,
                 out_hospital: list = None):
        # VW_user_info 实测列结构（FID=工号/FNAME=姓名/FDEPT=科室代码/FDOCT=科室名称）
        self.users = users or [
            {"FID": "TESTDOC01", "FNAME": "测试医生甲",
             "FDEPT": "D001", "FDOCT": "普外科",
             "FPOSITION": "住院医师", "FUSERTYPE": "医生"},
            {"FID": "TESTDOC02", "FNAME": "测试医生乙",
             "FDEPT": "D002", "FDOCT": "呼吸内科",
             "FPOSITION": "主治医师", "FUSERTYPE": "医生"},
            {"FID": "TESTDOC09", "FNAME": "停用医生",
             "FDEPT": "D001", "FDOCT": "普外科",
             "FPOSITION": "住院医师", "FUSERTYPE": "医生",
             "active": "0"},   # 归一化键模拟停用（实测视图无 active 列）
        ]
        # VW_dept_dict 实测列结构（FID=科室代码/FNAME=科室名）
        self.depts = depts or [
            {"FID": "D001", "FNAME": "普外科", "FQUN": "", "FBETO": "",
             "FTYPE": "临床", "FBQNT": ""},
            {"FID": "D002", "FNAME": "呼吸内科", "FQUN": "", "FBETO": "",
             "FTYPE": "临床", "FBQNT": ""},
            {"FID": "D003", "FNAME": "心脏大血管外科", "FQUN": "", "FBETO": "",
             "FTYPE": "临床", "FBQNT": ""},
        ]
        # VW_pats_out_hospital 实测列子集（虚构 TEST 患者）
        self.out_hospital = out_hospital or [
            {"FPATIENTID": "TEST0001", "FBIHID": "1", "FBINCU": "1",
             "FNAME": "张某某", "FIHDAT": "2026-08-20",
             "FOOFFI": "2026-08-26", "FGUIDANGDATE": "2026-08-31",
             "FLEVWAY": "医嘱离院"},
        ]

    def fetch_user_by_code(self, user_code: str):
        for row in self.users:
            if str(row.get("FID")) == str(user_code):
                return normalize_user_row(dict(row))
        return None

    def fetch_user_info(self):
        return [dict(r) for r in self.users]

    def fetch_dept_dict(self):
        return [dict(r) for r in self.depts]

    def fetch_out_hospital_sample(self, limit: int = 100):
        return [dict(r) for r in self.out_hospital[:int(limit)]]
