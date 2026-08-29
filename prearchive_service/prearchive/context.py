# -*- coding: utf-8 -*-
"""归一化患者上下文与条目数据结构。

四个数据源（JHEMR / HIS / 手麻 / LIS）的采集器都把原始行（真实字段名，见 028 §1 F1/F3）
适配为这里的统一结构，规则引擎只面对统一结构，不感知各源字段差异。

字段名与真实库的对齐关系集中在 collectors.py 的列映射处（待 P0-3 实测回填微调）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

# 归一化源标识（条目层）
SRC_JHEMR_BLWS = "jhemr_blws"   # JHEMR v_blws 文书（按模板名过滤）
SRC_HIS_ITF = "his_itf"         # HIS PAPERLESS.T_ITF_HIS（REPORTNAME=数字编码）
SRC_SM_ITF = "sm_itf"           # 手麻 MEDSURGERY.T_ITF_SM
SRC_LIS_ITF = "lis_itf"         # LIS dbo.vw_hisinter_T_ITF_Lis（描述列=FDESCNUM，无 FDESC）
SRC_HIS_FIRSTPAGE = "his_firstpage"  # HIS 病案首页结构化（P0-3④ 硬闸门，可能整族不可用）

# 源标识 → 水位键（source_watermarks 用短键）
WATERMARK_KEYS = {
    SRC_JHEMR_BLWS: "jhemr",
    SRC_HIS_ITF: "his",
    SRC_HIS_FIRSTPAGE: "his",
    SRC_SM_ITF: "sm",
    SRC_LIS_ITF: "lis",
}

KNOWN_SOURCE_LABELS = set(WATERMARK_KEYS.keys())


@dataclass
class DocumentEntry:
    """一条文书/接口条目（四源归一）。"""

    source: str                       # 上面 SRC_* 之一
    report_name: str                  # 按 F3 v2 修正版取的名称列（见 collectors 各源适配）
    event_time: Optional[datetime] = None   # 业务时间（FCKDATE / 文书完成时间）
    update_time: Optional[datetime] = None  # 条目更新时间（FUPDATE）
    load_time: Optional[datetime] = None    # 进入接口表时间（FLOADDATE）
    template_name: str = ""           # JHEMR v_blws 模板名（template_field 匹配依据）
    status: str = ""                  # v_blws.progress_status 原值（值域待 P0-3③）
    raw: dict = field(default_factory=dict)

    def time_basis(self) -> Optional[datetime]:
        """条目最新时间（水位计算用）：更新时间优先，其次入表、业务时间。"""
        for t in (self.update_time, self.load_time, self.event_time):
            if t is not None:
                return t
        return None

    def match_name(self, template_field: str = "") -> str:
        """匹配用名称：JHEMR 源默认按模板名列匹配，其余按报告名列。"""
        if self.source == SRC_JHEMR_BLWS:
            field_key = template_field or "progress_template_name"
            if field_key == "progress_template_name":
                return self.template_name or self.report_name
        return self.report_name


@dataclass
class SurgeryInfo:
    """一次手术事实（手术族规则的 trigger 证据）。"""

    surgery_name: str = ""
    surgery_time: Optional[datetime] = None
    source: str = ""   # his_firstpage_operation | sm_itf_entry


@dataclass
class FirstPageData:
    """HIS 病案首页结构化数据（empty_field / duplicate 判定域）。

    available=False 表示首页源不可读（P0-3④ 未证实或 179 未开通），
    规则引擎将整族跳过（028 §3.1 条件覆盖语义）。
    """

    available: bool = False
    allergy_drug: Optional[str] = None      # 过敏药物（None/'' 视为空；'无' 合法，A13）
    birth_place: Optional[str] = None       # 出生地
    diagnoses: list = field(default_factory=list)   # 诊断名称列表（含序号原文）
    surgeries: list = field(default_factory=list)   # 手术名称列表
    raw: dict = field(default_factory=dict)


@dataclass
class FinishedVisit:
    """触发层看到的"病历已完成"事件（jhemr.pat_visit 一行）。

    检查键 = (patient_id, visit_id, finished_date_time)：完成时间更新即重检（028 A1）。
    """

    patient_id: str
    visit_id: str
    finished_date_time: datetime
    first_finished_doctor_id: str = ""
    first_finished_doctor_name: str = ""
    visit_number: str = ""
    patient_name: str = ""
    dept_code: str = ""
    dept_name: str = ""
    discharge_mode: str = ""       # 出院方式（豁免场景，如"自动出院"）


@dataclass
class PatientContext:
    """单次预检的完整患者上下文（采集器聚合产物，规则引擎唯一输入）。"""

    patient_id: str
    visit_id: str
    visit_number: str = ""
    patient_name: str = ""
    dept_code: str = ""
    dept_name: str = ""
    admit_time: Optional[datetime] = None
    discharge_time: Optional[datetime] = None
    finished_date_time: Optional[datetime] = None
    first_finished_doctor_id: str = ""
    first_finished_doctor_name: str = ""
    attending_doctor_id: str = ""      # 管床/主管医师（推送兜底）
    attending_doctor_name: str = ""
    last_doc_author_id: str = ""       # 最新文书书写医生（T2-2 降级档，029 P0-6：完成医生字段 177 无数据）
    last_doc_author_name: str = ""
    discharge_mode: str = ""
    documents: list = field(default_factory=list)      # list[DocumentEntry]
    file_index: list = field(default_factory=list)     # list[dict] jhmr_file_index 行（T2-4 时间源）
    surgeries: list = field(default_factory=list)      # list[SurgeryInfo]
    firstpage: FirstPageData = field(default_factory=FirstPageData)
    source_watermarks: dict = field(default_factory=dict)  # 源短键 -> 该源最新数据时间
    scenes: list = field(default_factory=list)         # 豁免场景标签（如"自动出院"）
    check_time: Optional[datetime] = None              # 判定时点（默认 now，测试可注入）
    collect_errors: dict = field(default_factory=dict)  # 源短键 -> 采集异常描述（fail-open 记录）

    def effective_check_time(self) -> datetime:
        return self.check_time or self.finished_date_time or datetime.now()

    def has_scene(self, scene: str) -> bool:
        return scene in self.scenes

    def watermark_for(self, source_label: str) -> Optional[datetime]:
        key = WATERMARK_KEYS.get(source_label, source_label)
        return self.source_watermarks.get(key)

    def to_public_dict(self) -> dict:
        """对外（API/推送）的最小化摘要，不带病历原文（R10 隐私）。"""
        return {
            "patient_id": self.patient_id,
            "visit_id": self.visit_id,
            "patient_name": self.patient_name,
            "dept_code": self.dept_code,
            "dept_name": self.dept_name,
            "finished_date_time": _iso(self.finished_date_time),
        }


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat(timespec="seconds") if isinstance(value, datetime) else None


def parse_topic_datetime(topic: Any) -> Optional[datetime]:
    """jhmr_file_index.topic 标题前缀时间戳解析（031 T2-4，用户拍板口径）。

    嘉和文书标题形如「2026-08-24 17:30 术后首次病程记录」或含 ISO/中文日期变体；
    只解析**前缀**时间戳（标题时间=文书书写时间判定源），解析失败返回 None。
    """
    if not isinstance(topic, str) or not topic.strip():
        return None
    import re
    from datetime import datetime as _dt

    head = topic.strip()[:32]
    m = re.match(
        r"^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?"
        r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?",
        head,
    )
    if not m:
        m2 = re.match(r"^(\d{8})(\d{4})?", head)
        if m2:
            raw = m2.group(1)
            try:
                base = _dt.strptime(raw, "%Y%m%d")
                hhmm = m2.group(2)
                if hhmm:
                    return base.replace(hour=int(hhmm[:2]), minute=int(hhmm[2:4]))
                return base
            except ValueError:
                return None
        return None
    year, month, day, hour, minute, second = m.groups()
    try:
        return _dt(
            int(year), int(month), int(day),
            int(hour or 0), int(minute or 0), int(second or 0),
        )
    except ValueError:
        return None


def parse_datetime(value: Any) -> Optional[datetime]:
    """宽容解析时间：datetime 直返；字符串按 ISO/常见格式解析；其余返回 None。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
            try:
                from datetime import datetime as _dt
                return _dt.strptime(text, fmt)
            except ValueError:
                continue
        try:
            from datetime import datetime as _dt
            return _dt.fromisoformat(text)
        except ValueError:
            return None
    return None
