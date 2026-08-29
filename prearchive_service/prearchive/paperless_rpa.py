# -*- coding: utf-8 -*-
"""T8-1（031）：无纸化 RPA 触发模式 supplement——身份适配器 + 聚合表拉取 + 对账。

方案④（§11，用户已拍板过渡锚点）：CDMS.RPA_PRINTRPT_AGGREGATED（统计已采集完成的
患者）——UPDATEAT 为增量信号（COMPLETED 值域 1=77924/0=1 无区分度，round-3 实证）。
时效 ≈ 出院后 5 天；语义差距声明见 README §8.2（R4：④时点=签收+采集完成≠书写完成）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# RPA_PRINTRPT_AGGREGATED 实测 18 列中触发/归属所需子集（031 §11）；
# 稳定分页次键 = (UPDATEAT, FPATIENTID, FBIHID, FBINCU)（R10 禁裸 UPDATEAT 单键分页）
RPA_AGGREGATES_SQL = (
    "SELECT FPATIENTID, FBIHID, FBINCU, COMPLETED, UPDATEAT, CREATEAT, "
    "       RPTCOUNT, FIOFFI, FOOFFI, FOOFFINAME, LJBLHS "
    "FROM CDMS.RPA_PRINTRPT_AGGREGATED "
    "WHERE UPDATEAT > :since "
    "ORDER BY UPDATEAT, FPATIENTID, FBIHID, FBINCU "
    "FETCH FIRST :limit ROWS ONLY"
)   # 12c+ FETCH FIRST；11g 需 W9 核对 CDMS 版本后改 ROWNUM 子查询


class RpaIdentityAdapter:
    """(FPATIENTID, FBIHID, FBINCU) → (patient_id, visit_id) 身份适配（R10）。

    **待 W9 实测核对**（029 §2.6 未验证）：FBINCU（无纸化次数）↔ JHEMR visit_id
    的对应关系未证实，防串次；当前实现=占位 identity 透传，仅 fixture/联调用。
    生产启用前必须按 W9 核对清单③实测回填。
    """

    verified = False   # W9 核对后置 True 并替换映射实现

    def to_patient_visit(self, fpatientid, fbihid, fbincu) -> Optional[tuple]:
        pid = str(fpatientid or "").strip()
        vid = str(fbihid or "").strip()
        if not pid or not vid:
            return None
        return pid, vid

    def notes(self) -> str:
        return "待 W9 实测核对（029 §2.6 未验证）：FBINCU↔visit_id 映射未证实，现为 identity 透传"


@dataclass
class RpaAggregateRow:
    """RPA 聚合行归一化（触发锚点用子集）。"""

    patient_id: str
    visit_id: str
    fbincu: str = ""
    completed: int = 0
    update_at: Optional[datetime] = None
    create_at: Optional[datetime] = None
    rpt_count: int = 0
    in_dept: str = ""          # FIOFFI 入科
    out_dept: str = ""         # FOOFFI 出院科室编码
    out_dept_name: str = ""    # FOOFFINAME 出院科室名
    ljblhs: str = ""


def normalize_rpa_rows(rows: list) -> list:
    """RPA 聚合原始行 → RpaAggregateRow（时间宽容解析）。"""
    from .context import parse_datetime

    result = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        row = {str(k).strip().lower(): v for k, v in raw.items()}
        adapter = RpaIdentityAdapter()
        mapped = adapter.to_patient_visit(row.get("fpatientid"), row.get("fbihid"),
                                          row.get("fbincu"))
        if mapped is None:
            continue
        result.append(RpaAggregateRow(
            patient_id=mapped[0],
            visit_id=mapped[1],
            fbincu=str(row.get("fbincu") or ""),
            completed=int(row.get("completed") or 0),
            update_at=parse_datetime(row.get("updateat")),
            create_at=parse_datetime(row.get("createat")),
            rpt_count=int(row.get("rptcount") or 0),
            in_dept=str(row.get("fioffi") or ""),
            out_dept=str(row.get("fooffi") or ""),
            out_dept_name=str(row.get("fooffiname") or ""),
            ljblhs=str(row.get("ljblhs") or ""),
        ))
    return result


def reconcile_report_count(rpt_count: int, document_count: int) -> dict:
    """RPTCOUNT 采集总量对账（R3/R5：仅对账告警，**不宣称护理缺项判定**）。

    多算=无纸化报告数多于预检侧文书条目数；少算=反之。两向都只告警不定性。
    """
    rpt = int(rpt_count or 0)
    docs = int(document_count or 0)
    if rpt == docs:
        return {"status": "match", "rpt_count": rpt, "document_count": docs,
                "delta": 0}
    status = "over" if rpt > docs else "under"
    return {"status": status, "rpt_count": rpt, "document_count": docs,
            "delta": abs(rpt - docs),
            "note": "采集总量对账差（非护理缺项判定；T_MSS_CHECKDATARECORD/"
                    "RPA_PRINTRPT 明细值域列 W9 核对）"}


class PaperlessRpaCollector:
    """RPA 聚合表触发采集器（anchor_mode=paperless_rpa 数据面）。

    检查键四元组=(FPATIENTID, FBIHID, FBINCU, UPDATEAT)（R10）——复检=UPDATEAT 变化；
    仓储行 finished_date_time := UPDATEAT（current 迁移语义，G5）。
    """

    def __init__(self, gateway, identity: Optional[RpaIdentityAdapter] = None):
        self.gateway = gateway
        self.identity = identity or RpaIdentityAdapter()

    def fetch_anchor_visits(self, since, limit, anchor_mode: str = "paperless_rpa"):
        from .context import FinishedVisit

        rows = normalize_rpa_rows(
            self.gateway.fetch_completed_aggregates(since, limit))
        visits = []
        for row in rows:
            if row.update_at is None:
                continue
            visits.append(FinishedVisit(
                patient_id=row.patient_id,
                visit_id=row.visit_id,
                finished_date_time=row.update_at,
                rpt_count=row.rpt_count,          # 对账用（processor 侧）
                dept_code=row.out_dept or row.in_dept,
                dept_name=row.out_dept_name,
            ))
        visits.sort(key=lambda v: v.finished_date_time)
        return visits
