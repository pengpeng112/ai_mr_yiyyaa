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
    SRC_HIS_FIRSTPAGE,
    SRC_HIS_ITF,
    SRC_JHEMR_BLWS,
    SRC_LIS_ITF,
    SRC_SM_ITF,
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

# 各源条目"名称列"取值优先级（键一律小写比较；F3 v2 修正版）
ITF_NAME_KEYS = {
    SRC_HIS_ITF: ("reportname",),                 # F4：REPORTNAME 是数字编码
    SRC_SM_ITF: ("fitemname", "reportname"),      # 手麻首选 FITEMNAME
    SRC_LIS_ITF: ("fdescnum",),                   # F3 v2：LIS 描述列=FDESCNUM，无 FDESC
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
    def fetch_pat_visit(self, patient_id: str, visit_id: str) -> Optional[dict]:
        """单患者 pat_visit 行（归一化键）。"""

    @abstractmethod
    def fetch_blws(self, patient_id: str, visit_id: str) -> list:
        """v_blws 文书行（归一化键，含 progress_template_name/progress_status/时间列）。"""


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

    PAT_VISIT_SQL = (
        "SELECT patient_id, visit_id, visit_number, patient_name, dept_code, dept_name, "
        "       admission_date_time, discharge_date_time, finished_date_time, "
        "       first_finished_doctor_id, first_finished_doctor_name, "
        "       attending_doctor_id, attending_doctor_name, discharge_mode "
        "FROM jhemr.pat_visit WHERE patient_id = :patient_id AND visit_id = :visit_id"
    )

    BLWS_SQL = (
        "SELECT progress_template_name, progress_status, "
        "       first_record_time AS record_time, "
        "       finished_date_time AS finished_time, "
        "       last_update_time AS update_time "
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
    """真实手麻网关（MEDSURGERY.T_ITF_SM）。"""

    ITF_SQL = (
        "SELECT FID, PATIENTID, FBIHID, FBINCU, FITEMNAME, REPORTNAME, "
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

    def __init__(self, gateway: JhemrGateway):
        self.gateway = gateway

    def fetch_finished_visits(self, since: Optional[datetime], limit: int) -> list:
        rows = self.gateway.fetch_finished_visits(since, limit) or []
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

        for blws_row in self.gateway.fetch_blws(patient_id, visit_id) or []:
            template = str(blws_row.get("progress_template_name") or "")
            if not template:
                continue
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
    """手麻条目（手术证据来源之一）。"""

    SURGERY_NAME_KEYWORDS = ("手术",)

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
                 sm: SmCollector, lis: LisCollector):
        self.jhemr = jhemr
        self.his = his
        self.sm = sm
        self.lis = lis

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

        context.source_watermarks = compute_source_watermarks(context)
        return context


def compute_source_watermarks(context: PatientContext) -> dict:
    """各源水位 = 该源条目最新时间（require_source_ready 判定依据，R15）。

    JHEMR 源额外以 finished_date_time 兜底（pat_visit 本身就是 JHEMR 数据）。
    """
    watermarks: dict = {}
    for entry in context.documents:
        key = {"jhemr_blws": "jhemr", "his_itf": "his", "sm_itf": "sm",
               "lis_itf": "lis"}.get(entry.source)
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
