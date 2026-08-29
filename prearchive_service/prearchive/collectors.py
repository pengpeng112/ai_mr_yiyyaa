# -*- coding: utf-8 -*-
"""四源采集器：网关抽象（真实 SQL 实现 + fixture 假源）+ 归一化适配器。

数据字段以 028 §1 事实基础的 v2 修正版为准：
- F1  JHEMR.pat_visit 触发锚点：finished_date_time / first_finished_doctor_id 等；
- F3  T_ITF 条目层骨架：FID/PATIENTID/FBIHID/FBINCU/报告名/PDF名/路径/FCKDATE/FUPDATE/
     FLOADDATE/FREPORTSTYLE/PAGECOUNT；三源描述列有差异：
     * HIS  PAPERLESS.T_ITF_HIS.REPORTNAME 是 **数字编码**（F4，字典待 P0-3①）；
     * 手麻 MEDSURGERY.T_ITF_SM 报告名取 FITEMNAME（回退 REPORTNAME）；
     * LIS  dbo.vw_hisinter_T_ITF_Lis 描述列是 **FDESCNUM**（无 FDESC）；
- v_blws 文书名按模板名（progress_template_name）匹配，防知情同意书误命中（026/028 A15）。

真实网关（Sql*Gateway）只在生产配置启用时惰性建连；本地测试一律使用
fixture_sources.py 的假源（行结构一致）。所有时间列真实侧可能返回字符串，
统一经 parse_datetime 宽容解析。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional

from .context import (
    SRC_BL_ITF,
    SRC_DCN_REPORT,
    SRC_ES_ITF,
    SRC_HIS_FIRSTPAGE,
    SRC_HIS_ITF,
    SRC_JHEMR_BLWS,
    SRC_LIS_ITF,
    SRC_PACS_ITF,
    SRC_QGJ_ITF,
    SRC_SM_ITF,
    SRC_XD_ITF,
    SRC_XT_ITF,
    DocumentEntry,
    FinishedVisit,
    FirstPageData,
    PatientContext,
    SurgeryInfo,
    parse_datetime,
)

logger = logging.getLogger("prearchive.collectors")

# ---------------------------------------------------------------------------
# 原始行键约定（网关输出统一小写蛇形键；真实网关负责把各库原生列名映射到这里，
# 映射集中在此，P0-3 实测若有出入只改这里）
# ---------------------------------------------------------------------------
JHEMR_PAT_VISIT_KEYS = [
    "patient_id", "visit_id", "visit_number", "patient_name",
    "dept_code", "dept_name",
    "admit_time", "discharge_time",
    "finished_date_time", "first_finished_doctor_id", "first_finished_doctor_name",
    "attending_doctor_id", "attending_doctor_name",
    "discharge_mode",
]

# JHEMR pat_visit 真实列名 → 归一化键（F1 实证字段 + 常规扩展位；以 P0-3⑥ 别名核验为准）
JHEMR_PAT_VISIT_COLUMN_MAP = {
    "patient_id": "patient_id",
    "visit_id": "visit_id",
    "patient_name": "patient_name",
    "dept_code": "dept_code",
    "dept_name": "dept_name",
    "admission_date_time": "admit_time",
    "discharge_date_time": "discharge_time",
    "finished_date_time": "finished_date_time",
    "first_finished_doctor_id": "first_finished_doctor_id",
    "first_finished_doctor_name": "first_finished_doctor_name",
    "attending_doctor_id": "attending_doctor_id",
    "attending_doctor_name": "attending_doctor_name",
    "discharge_mode": "discharge_mode",
}

# v_blws 文书行键（progress_status 值域与时间字段语义待 P0-3③ 实测）
BLWS_ROW_KEYS = ["progress_template_name", "progress_status", "record_time",
                 "finished_time", "update_time"]

ITF_ROW_KEYS = ["fid", "patientid", "fbihid", "fbincu", "report_name",
                "fckdate", "fupdate", "floaddate"]

# 病案首页结构化行键（P0-3④ 硬闸门：177 副本是否存在待证，不可用则整族跳过）
FIRSTPAGE_ROW_KEYS = ["available", "allergy_drug", "birth_place",
                      "diagnoses", "surgeries"]

# 各源条目"名称列"取值优先级（键一律小写比较；2026-08-28 P0-3 实测修正版）
# - HIS PAPERLESS.T_ITF_HIS.REPORTNAME 仅 0/1/2 数字编码（0 与 1 条数相等=成对生成，
#   语义待信息科确认，P0-3①）；
# - 手麻 MEDSURGERY.T_ITF_SM 名称列=REPORTNAME（实测 26 词文本名；无 FITEMNAME 列）；
# - LIS dbo.vw_hisinter_T_ITF_Lis：FDESCNUM=检验**类别**（实测 15 类：临检血液/生化/
#   体液/凝血常规/发光免疫等），FITEMNAME=具体项目名——报告族规则按类别匹配更稳。
ITF_NAME_KEYS = {
    SRC_HIS_ITF: ("reportname",),                 # 数字编码（字典待 P0-3①）
    SRC_SM_ITF: ("reportname", "fdesc"),          # 实测：名称列=REPORTNAME
    SRC_LIS_ITF: ("fdescnum", "fitemname"),       # 类别优先，项目名兜底
    # T8-2 新七源：13 列标准骨架，名称列=REPORTNAME（文本）回退 FDESC；
    # PACS REPORTNAME=varchar 文本（连接器实测）；PDFNAME=int 不作名称列
    SRC_PACS_ITF: ("reportname", "fdesc"),
    SRC_ES_ITF: ("reportname", "fdesc"),          # ES+US 双视图合并一源标签
    SRC_BL_ITF: ("reportname", "fdesc"),          # BLOCKED 骨架
    SRC_XT_ITF: ("reportname", "fdesc"),
    SRC_XD_ITF: ("reportname", "fdesc"),          # BLOCKED 骨架（对接信息待用户提供）
    SRC_DCN_REPORT: ("reportname", "fdesc"),
    SRC_QGJ_ITF: ("reportname", "fdesc"),
}


def normalize_rows_lower(rows: list, column_map: Optional[dict] = None) -> list:
    """通用行归一化：列名转小写（Vastbase/OpenGauss 返回大写列名的坑），再按映射改名。

    每行输出 dict；映射中不存在但原始行有的键保留小写原样，方便排障。
    """
    normalized = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        lowered = {str(k).strip().lower(): v for k, v in row.items()}
        if column_map:
            normalized.append({column_map.get(k, k): v for k, v in lowered.items()})
        else:
            normalized.append(lowered)
    return normalized


# ---------------------------------------------------------------------------
# 网关抽象：真实实现连库，假源（fixture_sources.py）同接口返回内存数据
# ---------------------------------------------------------------------------
class JhemrGateway(ABC):
    """JHEMR（Vastbase 兼容）网关。"""

    @abstractmethod
    def fetch_finished_visits(self, since: Optional[datetime], limit: int) -> list:
        """查询 finished_date_time > since 的完成病历（触发锚点，F1）。"""

    @abstractmethod
    def fetch_discharge_visits(self, since: Optional[datetime], limit: int) -> list:
        """查询 discharge_date_time > since 的出院病历（anchor_mode=discharge，T2-1）。

        029 K1：177 副本 finished 字段族全 NULL，discharge 实测 99% 有值——
        语义退化兜底锚点（出院时点≠书写完成时点）。
        """

    @abstractmethod
    def fetch_blws_status_updates(self, since: Optional[datetime], limit: int) -> list:
        """按 v_blws.modify_date 聚合的患者级更新行（anchor_mode=blws_status，T2-1）。

        返回行含 patient_id/visit_id/anchor_time（该患者文书最新修改时间）。
        029 K5：视图全表聚合 120s 超时——生产不可用，仅联调。
        """

    @abstractmethod
    def fetch_pat_visit(self, patient_id: str, visit_id: str) -> Optional[dict]:
        """单患者 pat_visit 行（归一化键）。"""

    @abstractmethod
    def fetch_blws(self, patient_id: str, visit_id: str) -> list:
        """v_blws 文书行（归一化键，含 progress_template_name/progress_status/时间列）。"""

    @abstractmethod
    def fetch_file_index(self, patient_id: str, visit_id: str) -> list:
        """jhmr_file_index 行（T2-4 术后首程 24h 判定时间源；topic 标题含时间戳）。

        177 实测 52 列，取判定所需子集：file_name/topic/create_date_time/
        caption_date_time/first_mr_sign_date_time（031 v4.3 用户拍板口径）。
        """


class HisGateway(ABC):
    """HIS 网关：T_ITF_HIS 条目 + 病案首页结构化（若可读）。"""

    @abstractmethod
    def fetch_itf_entries(self, patient_id: str, visit_id: str) -> list:
        """T_ITF_HIS 行（归一化键，report_name 为 REPORTNAME 数字编码字符串）。"""

    @abstractmethod
    def fetch_firstpage(self, patient_id: str, visit_id: str) -> Optional[dict]:
        """首页结构化行；返回 None 表示源不可读（整族条件跳过语义）。"""


class SmGateway(ABC):
    """手麻网关：T_ITF_SM 条目。"""

    @abstractmethod
    def fetch_itf_entries(self, patient_id: str, visit_id: str) -> list:
        """T_ITF_SM 行（归一化键，报告名=FITEMNAME，回退 REPORTNAME）。"""


class LisGateway(ABC):
    """LIS 网关：dbo.vw_hisinter_T_ITF_Lis 条目（描述列=FDESCNUM）。"""

    @abstractmethod
    def fetch_itf_entries(self, patient_id: str, visit_id: str) -> list:
        """LIS 行（归一化键，report_name 取 FDESCNUM——不是 FDESC，F3 v2）。"""


# ---------------------------------------------------------------------------
# 真实 SQL 网关（惰性建连；一期原型未接生产网络，先以占位 DSN 驱动）
# ---------------------------------------------------------------------------
class _SqlGatewayBase:
    """共用：按配置惰性创建 engine（驱动缺失/网络不通时首次查询才失败，不影响导入）。"""

    def __init__(self, dsn_builder, source_config: dict, source_name: str):
        self._dsn_builder = dsn_builder
        self._config = source_config or {}
        self._source_name = source_name
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from sqlalchemy import create_engine

            url = self._dsn_builder(self._config)
            self._engine = create_engine(url, pool_pre_ping=True)
        return self._engine

    def _query(self, sql: str, params: dict) -> list:
        engine = self._get_engine()
        with engine.connect() as conn:
            from sqlalchemy import text

            result = conn.execute(text(sql), params)
            return [dict(row._mapping) for row in result]


def _pg_dsn(cfg: dict) -> str:
    ssl = str(cfg.get("sslmode") or "").strip()
    suffix = f"?sslmode={ssl}" if ssl else ""
    return (f"postgresql+psycopg2://{cfg['user']}:{cfg['password']}"
            f"@{cfg['host']}:{cfg.get('port', 5432)}/{cfg['database']}{suffix}")


def _oracle_dsn(cfg: dict) -> str:
    service = cfg.get("service_name") or ""
    return (f"oracle+cx_oracle://{cfg['user']}:{cfg['password']}"
            f"@{cfg['host']}:{cfg.get('port', 1521)}/?service_name={service}")


def _mssql_dsn(cfg: dict) -> str:
    driver = (cfg.get("odbc_driver") or "ODBC Driver 17 for SQL Server")
    return (f"mssql+pyodbc://{cfg['user']}:{cfg['password']}"
            f"@{cfg['host']}:{cfg.get('port', 1433)}/{cfg['database']}?driver={driver}")


# ---------------------------------------------------------------------------
# T8-2 新七源网关（13 列标准骨架；默认 disabled，fixture 驱动本地可跑）
# ---------------------------------------------------------------------------
class TItfEntryGateway(ABC):
    """T_ITF 条目网关基类（新七源共用接口）。"""

    @abstractmethod
    def fetch_itf_entries(self, patient_id: str, visit_id: str) -> list:
        """该源 T_ITF 行（真实列名原样，适配层统一归一）。"""


def _mysql_dsn(cfg: dict) -> str:
    return (f"mysql+pymysql://{cfg['user']}:{cfg['password']}"
            f"@{cfg['host']}:{cfg.get('port', 3306)}/{cfg['database']}")


class _SqlItfEntryGateway(_SqlGatewayBase):
    """按源参数化的 T_ITF 网关基类（SQL/DSN 由子类提供）。"""

    ITF_SQL = ""
    DSN_KIND = "mssql"   # mssql | postgresql | mysql | oracle

    def __init__(self, source_config: dict, password_resolver):
        def build(cfg):
            full = dict(cfg)
            full["password"] = password_resolver()
            return {"mssql": _mssql_dsn, "postgresql": _pg_dsn,
                    "mysql": _mysql_dsn, "oracle": _oracle_dsn}[self.DSN_KIND](full)

        super().__init__(build, source_config, self.__class__.__name__)

    def fetch_itf_entries(self, patient_id, visit_id):
        return self._query(self.ITF_SQL,
                           {"patient_id": patient_id, "visit_id": visit_id})


class SqlPacsGateway(_SqlItfEntryGateway, TItfEntryGateway):
    """PACS（GE gecris mysql）。实测类型差异：REPORTNAME=varchar 文本、PDFNAME=int、
    时间列 FCKDATE/FUPDATE=varchar——parse_datetime 容错，PDFNAME 忽略。"""

    DSN_KIND = "mysql"
    ITF_SQL = (
        "SELECT FID, PATIENTID, FBIHID, FBINCU, REPORTNAME, "
        "       FCKDATE, FUPDATE, FLOADDATE "
        "FROM T_ITF_PACS "
        "WHERE PATIENTID = :patient_id AND FBIHID = :visit_id"
    )


class SqlEsGateway(_SqlItfEntryGateway, TItfEntryGateway):
    """内镜+超声（美迪康 AnyImage mssql）——双视图合并一源标签 es_itf，条目各自独立。"""

    DSN_KIND = "mssql"
    ITF_SQL = (
        "SELECT FID, PATIENTID, FBIHID, FBINCU, REPORTNAME, FDESC, "
        "       FCKDATE, FUPDATE, FLOADDATE, 'ES' AS VIEW_TAG "
        "FROM T_ITF_ES "
        "WHERE PATIENTID = :patient_id AND FBIHID = :visit_id "
        "UNION ALL "
        "SELECT FID, PATIENTID, FBIHID, FBINCU, REPORTNAME, FDESC, "
        "       FCKDATE, FUPDATE, FLOADDATE, 'US' AS VIEW_TAG "
        "FROM T_ITF_US "
        "WHERE PATIENTID = :patient_id AND FBIHID = :visit_id"
    )


class SqlBlGateway(_SqlItfEntryGateway, TItfEntryGateway):
    """病理（千屏 pitaya mssql）。BLOCKED：平台连接器缺 sqlserver 驱动——
    骨架按 13 列标准，部署机装驱动/W9 后实测回填（不伪造实测结果）。"""

    DSN_KIND = "mssql"
    ITF_SQL = (
        "SELECT FID, PATIENTID, FBIHID, FBINCU, REPORTNAME, FDESC, "
        "       FCKDATE, FUPDATE, FLOADDATE "
        "FROM PITAYA.DBO.T_ITF_BL "
        "WHERE PATIENTID = :patient_id AND FBIHID = :visit_id"
    )


class SqlXtGateway(_SqlItfEntryGateway, TItfEntryGateway):
    """血透（盈佳 dialysis postgresql）。未登记平台——骨架，连通后实测回填。"""

    DSN_KIND = "postgresql"
    ITF_SQL = (
        "SELECT FID, PATIENTID, FBIHID, FBINCU, REPORTNAME, FDESC, "
        "       FCKDATE, FUPDATE, FLOADDATE "
        "FROM T_ITF_XT "
        "WHERE PATIENTID = :patient_id AND FBIHID = :visit_id"
    )


class SqlXdGateway(_SqlItfEntryGateway, TItfEntryGateway):
    """心电（纳龙 T_ITF_XD）。BLOCKED：实测实例两库均无 ITF 对象、库型与登记表
    不符——对接信息用户后期单独提供（031 §10/§12），骨架按标准 13 列+TODO。"""

    DSN_KIND = "mssql"   # 登记口径；真实库型待用户提供
    ITF_SQL = (
        "SELECT FID, PATIENTID, FBIHID, FBINCU, REPORTNAME, FDESC, "
        "       FCKDATE, FUPDATE, FLOADDATE "
        "FROM T_ITF_XD "   # TODO: 表名/库型待用户提供对接信息后回填
        "WHERE PATIENTID = :patient_id AND FBIHID = :visit_id"
    )


class SqlDcnGateway(_SqlItfEntryGateway, TItfEntryGateway):
    """电测听（华链 report.t_itf_report postgresql:15432）。未登记平台——骨架。"""

    DSN_KIND = "postgresql"
    ITF_SQL = (
        "SELECT FID, PATIENTID, FBIHID, FBINCU, REPORTNAME, FDESC, "
        "       FCKDATE, FUPDATE, FLOADDATE "
        "FROM t_itf_report "
        "WHERE PATIENTID = :patient_id AND FBIHID = :visit_id"
    )


class SqlQgjGateway(_SqlItfEntryGateway, TItfEntryGateway):
    """气管镜（T_ITF_HisQuery postgresql）。未登记平台——骨架。"""

    DSN_KIND = "postgresql"
    ITF_SQL = (
        "SELECT FID, PATIENTID, FBIHID, FBINCU, REPORTNAME, FDESC, "
        "       FCKDATE, FUPDATE, FLOADDATE "
        "FROM T_ITF_HisQuery "
        "WHERE PATIENTID = :patient_id AND FBIHID = :visit_id"
    )


class ItfSourceCollector:
    """新七源通用采集器：网关行 → adapt_itf_rows(source_label)。"""

    def __init__(self, gateway, source_label: str):
        self.gateway = gateway
        self.source_label = source_label

    def collect(self, patient_id: str, visit_id: str) -> list:
        return adapt_itf_rows(
            self.gateway.fetch_itf_entries(patient_id, visit_id),
            self.source_label)


class SqlJhemrGateway(_SqlGatewayBase, JhemrGateway):
    """真实 JHEMR 网关（Vastbase：列名小写归一 + 真实列映射，AGENTS 已知坑）。"""

    FINISHED_SQL = (
        "SELECT patient_id, visit_id, finished_date_time, "
        "       first_finished_doctor_id, first_finished_doctor_name, "
        "       visit_number, patient_name, dept_code, dept_name, discharge_mode "
        "FROM jhemr.pat_visit "
        "WHERE finished_date_time IS NOT NULL "
        "  AND finished_date_time > :since "
        "ORDER BY finished_date_time ASC "
        "FETCH FIRST :limit ROWS ONLY"
    )

    # jhmr_file_index（T2-4）：嘉和文书索引，topic 标题前缀含书写时间戳
    FILE_INDEX_SQL = (
        "SELECT patient_id, visit_id, file_name, topic, "
        "       create_date_time, caption_date_time, first_mr_sign_date_time "
        "FROM jhemr.jhmr_file_index "
        "WHERE patient_id = :patient_id AND visit_id = :visit_id"
    )

    # anchor_mode=discharge（T2-1）：出院时间锚点，检查键第三列=discharge 时间
    DISCHARGE_SQL = (
        "SELECT patient_id, visit_id, discharge_date_time AS finished_date_time, "
        "       first_finished_doctor_id, first_finished_doctor_name, "
        "       visit_number, patient_name, dept_code, dept_name, discharge_mode "
        "FROM jhemr.pat_visit "
        "WHERE discharge_date_time IS NOT NULL "
        "  AND discharge_date_time > :since "
        "ORDER BY discharge_date_time ASC "
        "FETCH FIRST :limit ROWS ONLY"
    )

    # anchor_mode=blws_status（T2-1）：modify_date 为 text，ISO 格式字典序与时间序一致；
    # 029 K5 实证该视图全表聚合 120s 超时——生产不可用，仅联调
    BLWS_STATUS_SQL = (
        "SELECT patient_id, visit_id, MAX(modify_date) AS anchor_time "
        "FROM jhemr.v_blws "
        "GROUP BY patient_id, visit_id "
        "HAVING MAX(modify_date) > :since "
        "ORDER BY MAX(modify_date) ASC "
        "FETCH FIRST :limit ROWS ONLY"
    )

    PAT_VISIT_SQL = (
        "SELECT patient_id, visit_id, visit_number, patient_name, dept_code, dept_name, "
        "       admission_date_time, discharge_date_time, finished_date_time, "
        "       first_finished_doctor_id, first_finished_doctor_name, "
        "       attending_doctor_id, attending_doctor_name, discharge_mode "
        "FROM jhemr.pat_visit WHERE patient_id = :patient_id AND visit_id = :visit_id"
    )

    # v_blws 真实列（2026-08-28 information_schema 实测 22 列；时间列为 text 需解析）：
    # progress_template_name/progress_status/first_save_time/finish_time_format/
    # create_date/modify_date/caption_date_time；另有 state/msg_type/doctor_guid 等
    BLWS_SQL = (
        "SELECT progress_template_name, progress_status, "
        "       first_save_time AS record_time, "
        "       finish_time_format AS finished_time, "
        "       modify_date AS update_time, "
        "       doctor_guid, doctor_name "
        "FROM jhemr.v_blws "
        "WHERE patient_id = :patient_id AND visit_id = :visit_id"
    )

    def __init__(self, source_config: dict, password_resolver):
        def build(cfg):
            full = dict(cfg)
            full["password"] = password_resolver()
            return _pg_dsn(full)

        super().__init__(build, source_config, "jhemr")

    def fetch_finished_visits(self, since, limit):
        params = {"since": since or datetime(1970, 1, 1), "limit": int(limit)}
        rows = normalize_rows_lower(self._query(self.FINISHED_SQL, params),
                                    JHEMR_PAT_VISIT_COLUMN_MAP)
        return rows

    def fetch_discharge_visits(self, since, limit):
        params = {"since": since or datetime(1970, 1, 1), "limit": int(limit)}
        return normalize_rows_lower(self._query(self.DISCHARGE_SQL, params),
                                    JHEMR_PAT_VISIT_COLUMN_MAP)

    def fetch_blws_status_updates(self, since, limit):
        params = {"since": since or datetime(1970, 1, 1), "limit": int(limit)}
        return normalize_rows_lower(self._query(self.BLWS_STATUS_SQL, params))

    def fetch_pat_visit(self, patient_id, visit_id):
        rows = normalize_rows_lower(
            self._query(self.PAT_VISIT_SQL,
                        {"patient_id": patient_id, "visit_id": visit_id}),
            JHEMR_PAT_VISIT_COLUMN_MAP)
        return rows[0] if rows else None

    def fetch_blws(self, patient_id, visit_id):
        return normalize_rows_lower(
            self._query(self.BLWS_SQL,
                        {"patient_id": patient_id, "visit_id": visit_id}))

    def fetch_file_index(self, patient_id, visit_id):
        return normalize_rows_lower(
            self._query(self.FILE_INDEX_SQL,
                        {"patient_id": patient_id, "visit_id": visit_id}))


class SqlHisGateway(_SqlGatewayBase, HisGateway):
    """真实 HIS 网关（T_ITF_HIS + 首页结构化表——表名待 P0-3④ 确认后回填）。"""

    ITF_SQL = (
        "SELECT FID, PATIENTID, FBIHID, FBINCU, REPORTNAME, "
        "       FCKDATE, FUPDATE, FLOADDATE "
        "FROM PAPERLESS.T_ITF_HIS "
        "WHERE PATIENTID = :patient_id AND FBIHID = :visit_id"
    )

    # P0-3④：首页结构化表位置待证实；闸门未过前本查询不启用（fetch_firstpage 返回 None）
    FIRSTPAGE_SQL = ""

    def __init__(self, source_config: dict, password_resolver):
        def build(cfg):
            full = dict(cfg)
            full["password"] = password_resolver()
            return _oracle_dsn(full)

        super().__init__(build, source_config, "his")

    def fetch_itf_entries(self, patient_id, visit_id):
        return self._query(self.ITF_SQL,
                           {"patient_id": patient_id, "visit_id": visit_id})

    def fetch_firstpage(self, patient_id, visit_id):
        if not self.FIRSTPAGE_SQL:   # 硬闸门：未证实可读前一律视为不可用
            return None
        rows = normalize_rows_lower(
            self._query(self.FIRSTPAGE_SQL,
                        {"patient_id": patient_id, "visit_id": visit_id}))
        return rows[0] if rows else None


class SqlSmGateway(_SqlGatewayBase, SmGateway):
    """真实手麻网关（MEDSURGERY.T_ITF_SM；名称列=REPORTNAME，实测无 FITEMNAME）。"""

    ITF_SQL = (
        "SELECT FID, PATIENTID, FBIHID, FBINCU, REPORTNAME, FDESC, "
        "       FCKDATE, FUPDATE, FLOADDATE "
        "FROM MEDSURGERY.T_ITF_SM "
        "WHERE PATIENTID = :patient_id AND FBIHID = :visit_id"
    )

    def __init__(self, source_config: dict, password_resolver):
        def build(cfg):
            full = dict(cfg)
            full["password"] = password_resolver()
            return _oracle_dsn(full)

        super().__init__(build, source_config, "sm")

    def fetch_itf_entries(self, patient_id, visit_id):
        return self._query(self.ITF_SQL,
                           {"patient_id": patient_id, "visit_id": visit_id})


class SqlLisGateway(_SqlGatewayBase, LisGateway):
    """真实 LIS 网关（dbo.vw_hisinter_T_ITF_Lis，描述列=FDESCNUM）。"""

    ITF_SQL = (
        "SELECT FID, PATIENTID, FBIHID, FBINCU, FDESCNUM, "
        "       FCKDATE, FUPDATE, FLOADDATE "
        "FROM dbo.vw_hisinter_T_ITF_Lis "
        "WHERE PATIENTID = :patient_id AND FBIHID = :visit_id"
    )

    def __init__(self, source_config: dict, password_resolver):
        def build(cfg):
            full = dict(cfg)
            full["password"] = password_resolver()
            return _mssql_dsn(full)

        super().__init__(build, source_config, "lis")

    def fetch_itf_entries(self, patient_id, visit_id):
        return self._query(self.ITF_SQL,
                           {"patient_id": patient_id, "visit_id": visit_id})


# ---------------------------------------------------------------------------
# 采集器适配器：网关原始行 → 归一化结构
# ---------------------------------------------------------------------------
class JhemrCollector:
    """触发 + 结构化层采集（pat_visit + v_blws）。"""

    ANCHOR_MODES = ("finished", "discharge", "blws_status")

    def __init__(self, gateway: JhemrGateway):
        self.gateway = gateway

    def fetch_finished_visits(self, since: Optional[datetime], limit: int) -> list:
        rows = self.gateway.fetch_finished_visits(since, limit) or []
        return self._rows_to_visits(rows)

    def fetch_anchor_visits(self, since: Optional[datetime], limit: int,
                            anchor_mode: str = "finished") -> list:
        """按 anchor_mode 取触发锚点行（T2-1）。

        - finished：完成时间锚点（现状，默认）；
        - discharge：出院时间锚点——检查键第三列=discharge_date_time；
        - blws_status：v_blws.modify_date 患者聚合"疑似完成"，锚点时间=最新修改时间，
          患者其余字段从 pat_visit 回填（缺行则留空，不阻断）。
        """
        mode = str(anchor_mode or "finished")
        if mode == "finished":
            return self.fetch_finished_visits(since, limit)
        if mode == "discharge":
            rows = self.gateway.fetch_discharge_visits(since, limit) or []
            return self._rows_to_visits(rows)
        if mode == "blws_status":
            rows = self.gateway.fetch_blws_status_updates(since, limit) or []
            visits = []
            for row in rows:
                anchor = parse_datetime(row.get("anchor_time"))
                if anchor is None:
                    continue
                pid = str(row.get("patient_id") or "")
                vid = str(row.get("visit_id") or "")
                if not pid or not vid:
                    continue
                pv = self.gateway.fetch_pat_visit(pid, vid) or {}
                visits.append(FinishedVisit(
                    patient_id=pid,
                    visit_id=vid,
                    finished_date_time=anchor,
                    first_finished_doctor_id=str(pv.get("first_finished_doctor_id") or ""),
                    first_finished_doctor_name=str(pv.get("first_finished_doctor_name") or ""),
                    visit_number=str(pv.get("visit_number") or ""),
                    patient_name=str(pv.get("patient_name") or ""),
                    dept_code=str(pv.get("dept_code") or ""),
                    dept_name=str(pv.get("dept_name") or ""),
                    discharge_mode=str(pv.get("discharge_mode") or ""),
                ))
            visits.sort(key=lambda v: v.finished_date_time)
            return visits
        raise ValueError(f"unknown anchor_mode: {anchor_mode!r}")

    def _rows_to_visits(self, rows: list) -> list:
        visits = []
        for row in rows:
            finished = parse_datetime(row.get("finished_date_time"))
            if finished is None:
                continue
            visits.append(FinishedVisit(
                patient_id=str(row.get("patient_id") or ""),
                visit_id=str(row.get("visit_id") or ""),
                finished_date_time=finished,
                first_finished_doctor_id=str(row.get("first_finished_doctor_id") or ""),
                first_finished_doctor_name=str(row.get("first_finished_doctor_name") or ""),
                visit_number=str(row.get("visit_number") or ""),
                patient_name=str(row.get("patient_name") or ""),
                dept_code=str(row.get("dept_code") or ""),
                dept_name=str(row.get("dept_name") or ""),
                discharge_mode=str(row.get("discharge_mode") or ""),
            ))
        visits = [v for v in visits if v.patient_id and v.visit_id]
        visits.sort(key=lambda v: v.finished_date_time)
        return visits

    def load_part(self, patient_id: str, visit_id: str, fallback: FinishedVisit) -> PatientContext:
        """聚合 pat_visit + v_blws 为 PatientContext（后续源再补充条目）。"""
        row = self.gateway.fetch_pat_visit(patient_id, visit_id) or {}
        context = PatientContext(
            patient_id=patient_id,
            visit_id=visit_id,
            visit_number=str(row.get("visit_number") or fallback.visit_number or ""),
            patient_name=str(row.get("patient_name") or fallback.patient_name or ""),
            dept_code=str(row.get("dept_code") or fallback.dept_code or ""),
            dept_name=str(row.get("dept_name") or fallback.dept_name or ""),
            admit_time=parse_datetime(row.get("admit_time")),
            discharge_time=parse_datetime(row.get("discharge_time")),
            finished_date_time=fallback.finished_date_time,
            first_finished_doctor_id=str(
                row.get("first_finished_doctor_id") or fallback.first_finished_doctor_id or ""),
            first_finished_doctor_name=str(
                row.get("first_finished_doctor_name") or fallback.first_finished_doctor_name or ""),
            attending_doctor_id=str(row.get("attending_doctor_id") or ""),
            attending_doctor_name=str(row.get("attending_doctor_name") or ""),
            discharge_mode=str(row.get("discharge_mode") or fallback.discharge_mode or ""),
            check_time=None,
        )
        scenes = []
        if context.discharge_mode:
            scenes.append(context.discharge_mode)
        context.scenes = scenes

        # T2-4：嘉和文书索引（time_limit 的 file_index_topic 时间源）
        context.file_index = list(
            self.gateway.fetch_file_index(patient_id, visit_id) or [])

        latest_author_time = None
        for blws_row in self.gateway.fetch_blws(patient_id, visit_id) or []:
            template = str(blws_row.get("progress_template_name") or "")
            if not template:
                continue
            doc_time = (parse_datetime(blws_row.get("update_time"))
                        or parse_datetime(blws_row.get("finished_time"))
                        or parse_datetime(blws_row.get("record_time")))
            author_id = str(blws_row.get("doctor_guid") or "")
            if author_id and doc_time is not None and (
                    latest_author_time is None or doc_time > latest_author_time):
                latest_author_time = doc_time
                context.last_doc_author_id = author_id
                context.last_doc_author_name = str(blws_row.get("doctor_name") or "")
            context.documents.append(DocumentEntry(
                source=SRC_JHEMR_BLWS,
                report_name=template,
                event_time=parse_datetime(blws_row.get("finished_time")
                                          or blws_row.get("record_time")),
                update_time=parse_datetime(blws_row.get("update_time")),
                load_time=None,
                template_name=template,
                status=str(blws_row.get("progress_status") or ""),
                raw=blws_row,
            ))
        return context


def adapt_itf_rows(rows: list, source_label: str) -> list:
    """T_ITF 类原始行（真实列名，任意大小写）→ DocumentEntry 列表。

    名称列按源适配（F3 v2 修正版，不得按统一 FDESC 取值）：
    - his_itf：REPORTNAME（数字编码，F4）；
    - sm_itf ：FITEMNAME，回退 REPORTNAME；
    - lis_itf：FDESCNUM（LIS 无 FDESC 列——即使行里混入 fdesc 也不取）。
    """
    entries = []
    for raw_row in rows or []:
        if not isinstance(raw_row, dict):
            continue
        row = {str(k).strip().lower(): v for k, v in raw_row.items()}
        name = ""
        for key in ITF_NAME_KEYS.get(source_label, ("report_name",)):
            value = row.get(key)
            if value is not None and str(value).strip():
                name = str(value).strip()
                break
        if not name:
            continue
        entries.append(DocumentEntry(
            source=source_label,
            report_name=name,
            event_time=parse_datetime(row.get("fckdate")),
            update_time=parse_datetime(row.get("fupdate")),
            load_time=parse_datetime(row.get("floaddate")),
            raw=row,
        ))
    return entries


class HisCollector:
    """HIS 条目 + 病案首页结构化。"""

    def __init__(self, gateway: HisGateway):
        self.gateway = gateway

    def collect(self, patient_id: str, visit_id: str):
        entries = adapt_itf_rows(self.gateway.fetch_itf_entries(patient_id, visit_id),
                                 SRC_HIS_ITF)
        firstpage_row = self.gateway.fetch_firstpage(patient_id, visit_id)
        firstpage = adapt_firstpage(firstpage_row)
        surgeries = []
        for op in firstpage.surgeries if isinstance(firstpage.surgeries, list) else []:
            if isinstance(op, dict):
                surgeries.append(SurgeryInfo(
                    surgery_name=str(op.get("name") or ""),
                    surgery_time=parse_datetime(op.get("time")),
                    source="his_firstpage_operation",
                ))
        return entries, firstpage, surgeries


def adapt_firstpage(row: Optional[dict]) -> FirstPageData:
    """首页原始行 → FirstPageData；row=None 或 available 非 true → 整族不可用。"""
    if not isinstance(row, dict) or not row.get("available"):
        return FirstPageData(available=False)
    diagnoses = row.get("diagnoses")
    surgeries = row.get("surgeries")
    return FirstPageData(
        available=True,
        allergy_drug=row.get("allergy_drug"),
        birth_place=row.get("birth_place"),
        diagnoses=[str(x) for x in diagnoses] if isinstance(diagnoses, list) else [],
        surgeries=surgeries if isinstance(surgeries, list) else [],
        raw=row,
    )


class SmCollector:
    """手麻条目（手术证据来源之一；词表实测：麻醉单/安全核查单/手术护理单/清点记录等）。"""

    SURGERY_NAME_KEYWORDS = ("手术", "麻醉", "介入")   # 手麻条目即手术事件旁证

    def __init__(self, gateway: SmGateway):
        self.gateway = gateway

    def collect(self, patient_id: str, visit_id: str):
        entries = adapt_itf_rows(self.gateway.fetch_itf_entries(patient_id, visit_id),
                                 SRC_SM_ITF)
        surgeries = []
        for entry in entries:
            if any(k in entry.report_name for k in self.SURGERY_NAME_KEYWORDS):
                surgeries.append(SurgeryInfo(
                    surgery_name=entry.report_name,
                    surgery_time=entry.event_time,
                    source="sm_itf_entry",
                ))
        return entries, surgeries


class LisCollector:
    """LIS 条目（报告名取 FDESCNUM——网关侧已完成映射，这里不再碰 FDESC）。"""

    def __init__(self, gateway: LisGateway):
        self.gateway = gateway

    def collect(self, patient_id: str, visit_id: str) -> list:
        return adapt_itf_rows(self.gateway.fetch_itf_entries(patient_id, visit_id),
                              SRC_LIS_ITF)


# ---------------------------------------------------------------------------
# 聚合器：四源 → 完整 PatientContext（fail-open：单源异常不阻断整检，只记 collect_errors）
# ---------------------------------------------------------------------------
class PatientContextBuilder:
    def __init__(self, jhemr: JhemrCollector, his: HisCollector,
                 sm: SmCollector, lis: LisCollector,
                 extra_itf_collectors: dict = None):
        self.jhemr = jhemr
        self.his = his
        self.sm = sm
        self.lis = lis
        # T8-2 新七源采集器 {source_label: ItfSourceCollector}；缺省不接（默认 disabled）
        self.extra_itf_collectors = dict(extra_itf_collectors or {})

    def build(self, visit: FinishedVisit, check_time: Optional[datetime] = None) -> PatientContext:
        context = self.jhemr.load_part(visit.patient_id, visit.visit_id, visit)
        context.check_time = check_time

        parts = (
            ("his", lambda: self.his.collect(visit.patient_id, visit.visit_id)),
            ("sm", lambda: self.sm.collect(visit.patient_id, visit.visit_id)),
            ("lis", lambda: self.lis.collect(visit.patient_id, visit.visit_id)),
        )
        for source_key, loader in parts:
            try:
                result = loader()
            except Exception as exc:   # noqa: BLE001 —— fail-open：单源故障不阻断
                logger.warning("[collect] source %s failed for %s/%s: %s",
                               source_key, visit.patient_id, visit.visit_id, exc)
                context.collect_errors[source_key] = f"{type(exc).__name__}: {exc}"
                continue
            if source_key == "his":
                entries, firstpage, surgeries = result
                context.documents.extend(entries)
                context.firstpage = firstpage
                context.surgeries.extend(surgeries)
            elif source_key == "sm":
                entries, surgeries = result
                context.documents.extend(entries)
                context.surgeries.extend(surgeries)
            else:
                context.documents.extend(result)

        # T8-2 新七源：同一 fail-open 语义接入 documents（R9 防“写了网关不接 builder”死代码）
        for source_label, collector in self.extra_itf_collectors.items():
            try:
                context.documents.extend(
                    collector.collect(visit.patient_id, visit.visit_id))
            except Exception as exc:   # noqa: BLE001
                logger.warning("[collect] extra source %s failed for %s/%s: %s",
                               source_label, visit.patient_id, visit.visit_id, exc)
                context.collect_errors[source_label] = f"{type(exc).__name__}: {exc}"

        context.source_watermarks = compute_source_watermarks(context)
        return context


def compute_source_watermarks(context: PatientContext) -> dict:
    """各源水位 = 该源条目最新时间（require_source_ready 判定依据，R15）。

    JHEMR 源额外以 finished_date_time 兜底（pat_visit 本身就是 JHEMR 数据）。
    """
    from .context import WATERMARK_KEYS

    watermarks: dict = {}
    for entry in context.documents:
        key = WATERMARK_KEYS.get(entry.source)
        if not key:
            continue
        t = entry.time_basis()
        if t is None:
            continue
        current = watermarks.get(key)
        if current is None or t > current:
            watermarks[key] = t
    if context.finished_date_time is not None:
        current = watermarks.get("jhemr")
        if current is None or context.finished_date_time > current:
            watermarks["jhemr"] = context.finished_date_time
    return watermarks


def source_is_ready(context: PatientContext, source_label: str,
                    tolerance_seconds: int = 0) -> bool:
    """require_source_ready 语义：该源在完成时点之后仍有数据到达 → 数据已就绪可判缺。

    源完全没有条目（水位缺失）视为未就绪；水位早于完成时间也视为未就绪
    （T_ITF 条目晚于完成时刻到达的竞态，R15）。
    """
    watermark = context.watermark_for(source_label)
    if watermark is None:
        return False
    if context.finished_date_time is None:
        return True
    tolerance = timedelta(seconds=tolerance_seconds)
    return watermark >= context.finished_date_time - tolerance
