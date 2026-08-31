# -*- coding: utf-8 -*-
"""fixture 假源：与真实网关同接口、行结构同真实字段名（F1/F3 v2 修正版）。

仅用于本地测试与演示（`run_service.py --fixtures`），患者数据全部虚构
（TEST 前缀 ID + 编造姓名），不含任何真实患者标识。

行结构口径：
- JHEMR pat_visit / v_blws：真实网关 SQL 别名后的归一化小写键
  （真实列名映射见 collectors.JHEMR_PAT_VISIT_COLUMN_MAP，待 P0-3⑥ 核验）；
- T_ITF 三源（HIS/手麻/LIS）：驱动返回的原生大写列名原样给适配层
  （FID/PATIENTID/FBIHID/FBINCU/REPORTNAME/FITEMNAME/FDESCNUM/FCKDATE/FUPDATE/FLOADDATE），
  F3 v2 的源差异适配（LIS=FDESCNUM、HIS=数字编码、手麻=FITEMNAME）由
  collectors.adapt_itf_rows 真实处理——假源不替它做。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .collectors import (
    HisGateway,
    JhemrGateway,
    LisGateway,
    SmGateway,
)
from .context import parse_datetime


class FixtureJhemrGateway(JhemrGateway):
    def __init__(self, pat_visits: list, blws: dict, file_index: dict = None):
        self.pat_visits = pat_visits   # 归一化键行（JHEMR_PAT_VISIT_KEYS）
        self.blws = blws               # {"pid|vid": [blws 行]}
        self.file_index = file_index or {}   # {"pid|vid": [jhmr_file_index 行]}（T2-4）

    def fetch_finished_visits(self, since, limit):
        rows = []
        for row in self.pat_visits:
            finished = row.get("finished_date_time")
            if not finished:
                continue
            finished_dt = (datetime.fromisoformat(finished)
                           if isinstance(finished, str) else finished)
            if since is not None:
                since_dt = (since if isinstance(since, datetime)
                            else datetime.fromisoformat(str(since)))
                if finished_dt <= since_dt:
                    continue
            rows.append(dict(row))
        rows.sort(key=lambda r: str(r.get("finished_date_time")))
        return rows[:limit]

    def fetch_discharge_visits(self, since, limit):
        """anchor_mode=discharge 假源：以 discharge_time 为锚点（T2-1）。"""
        rows = []
        for row in self.pat_visits:
            discharge = row.get("discharge_time")
            if not discharge:
                continue
            discharge_dt = (datetime.fromisoformat(discharge)
                            if isinstance(discharge, str) else discharge)
            if since is not None:
                since_dt = (since if isinstance(since, datetime)
                            else datetime.fromisoformat(str(since)))
                if discharge_dt <= since_dt:
                    continue
            anchored = dict(row)
            anchored["finished_date_time"] = discharge_dt
            rows.append(anchored)
        rows.sort(key=lambda r: str(r.get("finished_date_time")))
        return rows[:limit]

    def fetch_blws_status_updates(self, since, limit):
        """anchor_mode=blws_status 假源：按患者聚合文书最新修改时间（T2-1）。

        blws 行按 {"pid|vid": [...]} 键组织（行内不带患者列），pid/vid 取自键。
        """
        anchors = {}
        for key, blws_rows in self.blws.items():
            try:
                pid, vid = key.split("|", 1)
            except ValueError:
                continue
            for blws_row in blws_rows or []:
                updated = parse_datetime(blws_row.get("update_time"))
                if updated is None:
                    continue
                current = anchors.get(key)
                if current is None or updated > current:
                    anchors[key] = updated
        rows = []
        for key, anchor_dt in anchors.items():
            if since is not None:
                since_dt = (since if isinstance(since, datetime)
                            else datetime.fromisoformat(str(since)))
                if anchor_dt <= since_dt:
                    continue
            pid, vid = key.split("|", 1)
            rows.append({"patient_id": pid, "visit_id": vid, "anchor_time": anchor_dt})
        rows.sort(key=lambda r: r["anchor_time"])
        return rows[:limit]

    def fetch_pat_visit(self, patient_id, visit_id):
        for row in self.pat_visits:
            if str(row.get("patient_id")) == patient_id and str(row.get("visit_id")) == visit_id:
                return dict(row)
        return None

    def fetch_blws(self, patient_id, visit_id):
        return list(self.blws.get(f"{patient_id}|{visit_id}", []))

    def fetch_file_index(self, patient_id, visit_id):
        return [dict(r) for r in
                self.file_index.get(f"{patient_id}|{visit_id}", [])]


class _FixtureItfGatewayBase:
    """T_ITF 假源共用：按 (PATIENTID, FBIHID) 过滤，列名大小写均兼容。"""

    def __init__(self, itf_entries: Optional[list] = None):
        self.itf_entries = itf_entries or []

    def fetch_itf_entries(self, patient_id, visit_id):
        matched = []
        for raw_row in self.itf_entries:
            row = {str(k).strip().lower(): v for k, v in raw_row.items()}
            if (str(row.get("patientid")) == str(patient_id)
                    and str(row.get("fbihid")) == str(visit_id)):
                matched.append(dict(raw_row))
        return matched


class FixtureHisGateway(_FixtureItfGatewayBase, HisGateway):
    def __init__(self, itf_entries: Optional[list] = None,
                 firstpages: Optional[dict] = None):
        _FixtureItfGatewayBase.__init__(self, itf_entries)
        self.firstpages = firstpages or {}   # {"pid|vid": 首页归一化行 or None}

    def fetch_firstpage(self, patient_id, visit_id):
        return self.firstpages.get(f"{patient_id}|{visit_id}", None)


class FixtureSmGateway(_FixtureItfGatewayBase, SmGateway):
    pass


class FixtureLisGateway(_FixtureItfGatewayBase, LisGateway):
    pass


# T8-2 新七源假源（同一 _FixtureItfGatewayBase 接口；行=真实列名结构，虚构 TEST 患者）
class FixturePacsGateway(_FixtureItfGatewayBase):
    """PACS：REPORTNAME=文本、FCKDATE/FUPDATE=varchar、PDFNAME=int（被适配层忽略）。"""


class FixtureEsGateway(_FixtureItfGatewayBase):
    """内镜+超声双视图合并（VIEW_TAG 区分条目来源视图）。"""


class FixtureBlGateway(_FixtureItfGatewayBase):
    """病理假源（dbo.T_ITF_BL 13 列真实结构；2026-08-29 实测回填口径）。"""


class FixtureXtGateway(_FixtureItfGatewayBase):
    """血透假源（"T_ITF_XT" 14 列真实结构；IDNo=明显假号，适配层整列丢弃）。"""


class FixtureXdGateway(_FixtureItfGatewayBase):
    """心电 BLOCKED 骨架（对接信息待用户提供；fixture 行仅验证适配非实测结果）。"""


class FixtureDcnGateway(_FixtureItfGatewayBase):
    """电测听假源（t_itf_report 16 列小写命名真实结构）。"""


class FixtureQgjGateway(_FixtureItfGatewayBase):
    """气管镜假源（"T_ITF_HisQuery" 13 列真实结构；FBINCU/PAGECOUNT=int）。"""


# ---------------------------------------------------------------------------
# 演示数据集（虚构患者；`run_service.py --fixtures` 与 e2e 测试共用结构）
# ---------------------------------------------------------------------------
def build_demo_fixtures() -> dict:
    """返回 {jhemr, his, sm, lis} 四个假源网关。

    虚构患者（TEST 前缀）：
    - TEST0001/1 张某（普外科，手术）：缺手术安全核查表/护理单 + 缺术前小结/术前讨论/
      术后首次病程；首页源不可读（首页族整族跳过演示）；检验三报告齐（负例）
    - TEST0002/1 李某（呼吸内科，无手术）：入院记录超24h + 首页过敏空 + 诊断重复 +
      检验报告缺血常规/生化（正例群）
    - TEST0003/1 王某（普外科，手术）：文书齐全（全负例），首页过敏="无"（A13 合法）
    """
    pat_visits = [
        {
            "patient_id": "TEST0001", "visit_id": "1", "visit_number": "1",
            "patient_name": "张某某", "dept_code": "D001", "dept_name": "普外科",
            "admit_time": "2026-08-20 08:30:00", "discharge_time": "2026-08-26 09:00:00",
            "finished_date_time": "2026-08-26 10:00:00",
            "first_finished_doctor_id": "TESTDOC01", "first_finished_doctor_name": "测试医生甲",
            "attending_doctor_id": "TESTDOC01", "attending_doctor_name": "测试医生甲",
            "discharge_mode": "医嘱离院",
        },
        {
            "patient_id": "TEST0002", "visit_id": "1", "visit_number": "1",
            "patient_name": "李某某", "dept_code": "D002", "dept_name": "呼吸内科",
            "admit_time": "2026-08-19 10:00:00", "discharge_time": "2026-08-27 08:00:00",
            "finished_date_time": "2026-08-27 09:30:00",
            "first_finished_doctor_id": "TESTDOC02", "first_finished_doctor_name": "测试医生乙",
            "attending_doctor_id": "TESTDOC03", "attending_doctor_name": "测试医生丙",
            "discharge_mode": "医嘱离院",
        },
        {
            "patient_id": "TEST0003", "visit_id": "1", "visit_number": "1",
            "patient_name": "王某某", "dept_code": "D001", "dept_name": "普外科",
            "admit_time": "2026-08-21 09:00:00", "discharge_time": "2026-08-27 10:00:00",
            "finished_date_time": "2026-08-27 11:00:00",
            "first_finished_doctor_id": "TESTDOC01", "first_finished_doctor_name": "测试医生甲",
            "attending_doctor_id": "TESTDOC01", "attending_doctor_name": "测试医生甲",
            "discharge_mode": "医嘱离院",
        },
    ]
    blws = {
        # 张某：有手术记录；手术知情同意书在（排除词表防误命中演示）
        "TEST0001|1": [
            {"progress_template_name": "入院记录", "progress_status": "完成",
             "record_time": "2026-08-20 14:00:00", "finished_time": "2026-08-20 14:00:00",
             "update_time": "2026-08-26 10:05:00"},
            {"progress_template_name": "手术记录", "progress_status": "完成",
             "record_time": "2026-08-23 16:00:00", "finished_time": "2026-08-23 16:00:00",
             "update_time": "2026-08-26 10:05:00"},
            {"progress_template_name": "手术知情同意书", "progress_status": "完成",
             "record_time": "2026-08-22 10:00:00", "finished_time": "2026-08-22 10:00:00",
             "update_time": "2026-08-26 10:05:00"},
        ],
        # 李某：入院记录完成晚于入院 34h（超 24h 时限正例）
        "TEST0002|1": [
            {"progress_template_name": "入院记录", "progress_status": "完成",
             "record_time": "2026-08-20 20:00:00", "finished_time": "2026-08-20 20:00:00",
             "update_time": "2026-08-27 09:35:00"},
            {"progress_template_name": "首次病程记录", "progress_status": "完成",
             "record_time": "2026-08-19 15:00:00", "finished_time": "2026-08-19 15:00:00",
             "update_time": "2026-08-27 09:35:00"},
        ],
        # 王某：齐全（全负例）
        "TEST0003|1": [
            {"progress_template_name": "入院记录", "progress_status": "完成",
             "record_time": "2026-08-21 12:00:00", "finished_time": "2026-08-21 12:00:00",
             "update_time": "2026-08-27 11:05:00"},
            {"progress_template_name": "术前小结", "progress_status": "完成",
             "record_time": "2026-08-23 10:00:00", "finished_time": "2026-08-23 10:00:00",
             "update_time": "2026-08-27 11:05:00"},
            {"progress_template_name": "术前讨论", "progress_status": "完成",
             "record_time": "2026-08-23 11:00:00", "finished_time": "2026-08-23 11:00:00",
             "update_time": "2026-08-27 11:05:00"},
            {"progress_template_name": "手术记录", "progress_status": "完成",
             "record_time": "2026-08-24 15:00:00", "finished_time": "2026-08-24 15:00:00",
             "update_time": "2026-08-27 11:05:00"},
            {"progress_template_name": "术后首次病程记录", "progress_status": "完成",
             "record_time": "2026-08-24 17:00:00", "finished_time": "2026-08-24 17:00:00",
             "update_time": "2026-08-27 11:05:00"},
        ],
    }
    # HIS T_ITF_HIS：REPORTNAME 为数字编码（F4）；编码字典待 P0-3①——fixture 约定 1=检验医嘱
    his_entries = [
        {"FID": "H1", "PATIENTID": "TEST0001", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "1", "FCKDATE": "2026-08-21 09:00:00",
         "FUPDATE": "2026-08-26 10:30:00", "FLOADDATE": "2026-08-26 10:31:00"},
        {"FID": "H2", "PATIENTID": "TEST0002", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": 1, "FCKDATE": "2026-08-20 09:00:00",
         "FUPDATE": "2026-08-27 09:40:00", "FLOADDATE": "2026-08-27 09:41:00"},
    ]
    his_firstpages = {
        # 张某首页不可用（P0-3④ 未证实的真实状态）→ 首页族整族跳过
        "TEST0001|1": None,
        # 李某首页可读：过敏空 + 诊断重复（序号/全角数字差异）
        "TEST0002|1": {
            "available": True, "allergy_drug": "", "birth_place": "山东",
            "diagnoses": ["1.社区获得性肺炎", "２.社区获得性肺炎", "肺结核"],
            "surgeries": [],
        },
        # 王某：过敏="无"（A13 合法填写，不判空）
        "TEST0003|1": {
            "available": True, "allergy_drug": "无", "birth_place": "河北",
            "diagnoses": ["1.急性阑尾炎", "2.急性胃肠炎"], "surgeries": [],
        },
    }
    # 手麻 T_ITF_SM：名称列=REPORTNAME（P0-3② 实测 26 词，无 FITEMNAME 列）；
    # 手麻条目即手术事件旁证（麻醉/手术/介入关键词）
    sm_entries = [
        {"FID": "S1", "PATIENTID": "TEST0001", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "麻醉单", "FDESC": "MZ",
         "FCKDATE": "2026-08-23 14:00:00",
         "FUPDATE": "2026-08-26 10:40:00", "FLOADDATE": "2026-08-26 10:41:00"},
        {"FID": "S2", "PATIENTID": "TEST0001", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "术前访视", "FDESC": "SF",
         "FCKDATE": "2026-08-22 15:00:00",
         "FUPDATE": "2026-08-26 10:40:00", "FLOADDATE": "2026-08-26 10:41:00"},
        # 王某：安全核查单/手术护理单在（负例，实测词表）
        {"FID": "S3", "PATIENTID": "TEST0003", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "安全核查单", "FDESC": "HC",
         "FCKDATE": "2026-08-24 14:00:00",
         "FUPDATE": "2026-08-27 11:10:00", "FLOADDATE": "2026-08-27 11:11:00"},
        {"FID": "S4", "PATIENTID": "TEST0003", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "手术护理单", "FDESC": "HL",
         "FCKDATE": "2026-08-24 15:00:00",
         "FUPDATE": "2026-08-27 11:10:00", "FLOADDATE": "2026-08-27 11:11:00"},
        {"FID": "S5", "PATIENTID": "TEST0003", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "麻醉单", "FDESC": "MZ",
         "FCKDATE": "2026-08-24 14:30:00",
         "FUPDATE": "2026-08-27 11:10:00", "FLOADDATE": "2026-08-27 11:11:00"},
        # 王某补 T2-4 新规则负例：术前访视 + 术后随访 + 手术清点记录（实测词形"手术清点记录4"）
        {"FID": "S8", "PATIENTID": "TEST0003", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "术前访视", "FDESC": "SF",
         "FCKDATE": "2026-08-23 15:00:00",
         "FUPDATE": "2026-08-27 11:10:00", "FLOADDATE": "2026-08-27 11:11:00"},
        {"FID": "S6", "PATIENTID": "TEST0003", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "术后随访", "FDESC": "SF",
         "FCKDATE": "2026-08-25 09:00:00",
         "FUPDATE": "2026-08-27 11:10:00", "FLOADDATE": "2026-08-27 11:11:00"},
        {"FID": "S7", "PATIENTID": "TEST0003", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "手术清点记录4", "FDESC": "QD",
         "FCKDATE": "2026-08-24 16:00:00",
         "FUPDATE": "2026-08-27 11:10:00", "FLOADDATE": "2026-08-27 11:11:00"},
    ]
    # LIS dbo.vw_hisinter_T_ITF_Lis：FDESCNUM=检验类别（P0-3② 实测 15 类），
    # FITEMNAME=具体项目名；报告族规则按类别匹配。FDESC 列真实不存在（故意保留干扰键）
    lis_entries = [
        {"FID": "L1", "PATIENTID": "TEST0001", "FBIHID": "1", "FBINCU": "1",
         "FDESCNUM": "临检血液", "FITEMNAME": "血液分析(紫管)",
         "FCKDATE": "2026-08-21 10:00:00",
         "FUPDATE": "2026-08-26 10:50:00", "FLOADDATE": "2026-08-26 10:51:00"},
        {"FID": "L2", "PATIENTID": "TEST0001", "FBIHID": "1", "FBINCU": "1",
         "FDESCNUM": "生化", "FITEMNAME": "门生4（肝肾糖脂离子）（红管）",
         "FCKDATE": "2026-08-21 10:05:00",
         "FUPDATE": "2026-08-26 10:50:00", "FLOADDATE": "2026-08-26 10:51:00"},
        {"FID": "L3", "PATIENTID": "TEST0001", "FBIHID": "1", "FBINCU": "1",
         "FDESCNUM": "体液", "FITEMNAME": "尿液分析",
         "FCKDATE": "2026-08-21 10:10:00",
         "FUPDATE": "2026-08-26 10:50:00", "FLOADDATE": "2026-08-26 10:51:00"},
        # 李某：仅有体液（尿常规）→ 检验报告族缺临检血液/生化（正例）
        {"FID": "L4", "PATIENTID": "TEST0002", "FBIHID": "1", "FBINCU": "1",
         "FDESCNUM": "体液", "FITEMNAME": "尿液分析",
         "FCKDATE": "2026-08-20 11:00:00",
         "FUPDATE": "2026-08-27 09:45:00", "FLOADDATE": "2026-08-27 09:46:00"},
    ]

    # jhmr_file_index（T2-4）：topic 标题前缀时间戳=书写时间（用户拍板口径）
    file_index = {
        "TEST0001|1": [
            {"patient_id": "TEST0001", "visit_id": "1",
             "file_name": "术后首次病程记录.docx", "topic": "2026-08-25 10:00 术后首次病程记录",
             "create_date_time": "2026-08-25 10:00:00",
             "caption_date_time": "2026-08-25 10:00:00",
             "first_mr_sign_date_time": "2026-08-25 10:05:00"},
        ],
        "TEST0003|1": [
            {"patient_id": "TEST0003", "visit_id": "1",
             "file_name": "术后首次病程记录.docx", "topic": "2026-08-24 17:30 术后首次病程记录",
             "create_date_time": "2026-08-24 17:30:00",
             "caption_date_time": "2026-08-24 17:30:00",
             "first_mr_sign_date_time": "2026-08-24 17:35:00"},
        ],
    }
    # T8-2 新七源演示条目（虚构 TEST 患者；列结构=各源 13 列骨架真实口径）
    # PACS：REPORTNAME=文本、时间列=varchar、PDFNAME=int（适配层忽略）
    pacs_entries = [
        {"FID": "P1", "PATIENTID": "TEST0001", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "胸部CT平扫报告", "PDFNAME": 100231,
         "FCKDATE": "2026-08-21 11:00:00", "FUPDATE": "2026-08-26 11:00:00",
         "FLOADDATE": "2026-08-26 11:01:00"},
        {"FID": "P2", "PATIENTID": "TEST0002", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "胸部正位DR报告", "PDFNAME": 100232,
         "FCKDATE": "2026-08-20 15:00:00", "FUPDATE": "2026-08-27 10:00:00",
         "FLOADDATE": "2026-08-27 10:01:00"},
    ]
    # 内镜(T_ITF_ES)+超声(T_ITF_US) 双视图各自条目、合并为 es_itf 源
    es_entries = [
        {"FID": "E1", "PATIENTID": "TEST0001", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "胃镜检查报告", "FDESC": "ES", "VIEW_TAG": "ES",
         "FCKDATE": "2026-08-22 09:00:00", "FUPDATE": "2026-08-26 09:30:00",
         "FLOADDATE": "2026-08-26 09:31:00"},
        {"FID": "U1", "PATIENTID": "TEST0002", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "腹部超声报告", "FDESC": "US", "VIEW_TAG": "US",
         "FCKDATE": "2026-08-20 14:00:00", "FUPDATE": "2026-08-27 10:00:00",
         "FLOADDATE": "2026-08-27 10:01:00"},
    ]
    # 已实测回填四源条目（列结构=2026-08-29 平台实测真实口径，值全部虚构）
    # 病理 dbo.T_ITF_BL：13 列标准骨架
    bl_entries = [
        {"FID": "B90000001", "PATIENTID": "TEST0001", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "常规石蜡切片病理报告", "FDESC": "病理诊断描述",
         "PDFNAME": "BL20260824001.pdf", "PDFPATH": "/pitaya/pdf/2026/08/",
         "FCKDATE": "2026-08-24 10:00:00", "FUPDATE": "2026-08-26 15:00:00",
         "FLOADDATE": "2026-08-26 15:01:00", "FREPORTSTYLE": "1", "PAGECOUNT": 3},
    ]
    xd_entries = [
        {"FID": "X1", "PATIENTID": "TEST0002", "FBIHID": "1", "FBINCU": "1",
         "REPORTNAME": "常规十二导联心电图报告", "FDESC": "XD",
         "FCKDATE": "2026-08-21 08:00:00", "FUPDATE": "2026-08-27 09:00:00",
         "FLOADDATE": "2026-08-27 09:01:00"},
    ]
    # 血透 "T_ITF_XT"：14 列=标准 13+IDNo（身份证号列）——IDNo 用明显假号；
    # 适配层整列丢弃，绝不进入任何输出（PHI 红线）
    xt_entries = [
        {"FID": 91000001, "PATIENTID": "TEST0001", "FBIHID": "1", "FBINCU": 1,
         "REPORTNAME": "血液透析记录单", "FDESC": "XT",
         "PDFNAME": "XT20260823001.pdf", "PDFPATH": "/dialysis/pdf/2026/08/",
         "FCKDATE": "2026-08-23 07:00:00", "FUPDATE": "2026-08-26 07:00:00",
         "FLOADDATE": "2026-08-26 07:01:00", "FREPORTSTYLE": "1", "PAGECOUNT": 2,
         "IDNo": "FAKE-IDNO-XT-DO-NOT-USE"},
    ]
    # 电测听 t_itf_report：16 列小写命名（含新增 report_url/his_patient_id/visit_index）
    dcn_entries = [
        {"fid": "d91000001", "patientid": "TEST0002", "fbihid": "1", "fbincu": "1",
         "reportname": "纯音电测听报告", "fdesc": "DCN",
         "pdfname": "dcn20260822001.pdf", "pdfpath": "/report/pdf/2026/08/",
         "report_url": "http://report-fake.internal/dcndemo",
         "fckdate": "2026-08-22 10:00:00", "fupdate": "2026-08-27 11:00:00",
         "floaddate": "2026-08-27 11:01:00", "freportstyle": "1", "pagecount": 1,
         "his_patient_id": "", "visit_index": "1"},
    ]
    # 气管镜 "T_ITF_HisQuery"：13 列（FBINCU/PAGECOUNT=int；REPORTNAME 实测恒=呼吸内镜检查报告）
    qgj_entries = [
        {"FID": "Q91000001", "PATIENTID": "TEST0003", "FBIHID": "1", "FBINCU": 1,
         "REPORTNAME": "呼吸内镜检查报告", "FDESC": "气管镜检查描述",
         "PDFNAME": "QGJ20260825001.pdf", "PDFPATH": "/clouddb/pdf/2026/08/",
         "FCKDATE": "2026-08-25 14:00:00", "FUPDATE": "2026-08-27 14:00:00",
         "FLOADDATE": "2026-08-27 14:01:00", "FREPORTSTYLE": "1", "PAGECOUNT": 2},
    ]

    return {
        "jhemr": FixtureJhemrGateway(pat_visits, blws, file_index),
        "his": FixtureHisGateway(his_entries, his_firstpages),
        "sm": FixtureSmGateway(sm_entries),
        "lis": FixtureLisGateway(lis_entries),
        "pacs": FixturePacsGateway(pacs_entries),
        "es": FixtureEsGateway(es_entries),
        "bl": FixtureBlGateway(bl_entries),
        "xt": FixtureXtGateway(xt_entries),
        "xd": FixtureXdGateway(xd_entries),
        "dcn": FixtureDcnGateway(dcn_entries),
        "qgj": FixtureQgjGateway(qgj_entries),
    }


def build_paperless_rpa_fixtures(rpa_rows: list = None):
    """T8-1：RPA 聚合假源（TEST 前缀虚构患者；默认数据 3 行覆盖增量/复检/对账）。

    行结构=CDMS.RPA_PRINTRPT_AGGREGATED 原生大写列名子集。
    """
    from .paperless import FixturePaperlessGateway
    from pathlib import Path

    snapshot = Path(__file__).resolve().parent.parent /         "rules/paperless_items_snapshot_20260828.json"
    rows = rpa_rows or [
        {"FPATIENTID": "TEST0001", "FBIHID": "1", "FBINCU": "1",
         "COMPLETED": 1, "UPDATEAT": "2026-08-31 09:00:00",
         "CREATEAT": "2026-08-30 20:00:00", "RPTCOUNT": 7,
         "FIOFFI": "D001", "FOOFFI": "D001", "FOOFFINAME": "普外科", "LJBLHS": ""},
        {"FPATIENTID": "TEST0002", "FBIHID": "1", "FBINCU": "1",
         "COMPLETED": 1, "UPDATEAT": "2026-09-01 10:00:00",
         "CREATEAT": "2026-08-31 21:00:00", "RPTCOUNT": 3,
         "FIOFFI": "D002", "FOOFFI": "D002", "FOOFFINAME": "呼吸内科", "LJBLHS": ""},
        {"FPATIENTID": "TEST0003", "FBIHID": "1", "FBINCU": "1",
         "COMPLETED": 1, "UPDATEAT": "2026-09-01 11:00:00",
         "CREATEAT": "2026-08-31 22:00:00", "RPTCOUNT": 9,
         "FIOFFI": "D001", "FOOFFI": "D001", "FOOFFINAME": "普外科", "LJBLHS": ""},
    ]
    return FixturePaperlessGateway(snapshot, meta_rows=[], rpa_rows=rows)
