# -*- coding: utf-8 -*-
"""结果仓储：PrearchiveResult 的写入/查询/推送状态回写。

复检语义（A1）：检查键 (patient_id, visit_id, finished_date_time)；
同键重跑幂等更新；同患者新完成时间 → 新行 current=1、旧行保留 current=0。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update

from .models import (
    PUSH_PENDING,
    PUSH_SENT,
    PrearchiveResult,
)
from .receivers import Receiver


class ResultRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def upsert_result(self, *, patient_id: str, visit_id: str,
                      finished_date_time: datetime, problems: list,
                      rule_version: str, dept_code: str = "", dept_name: str = "",
                      patient_name: str = "", receiver: Optional[Receiver] = None,
                      problems_json: Optional[str] = None) -> PrearchiveResult:
        """写入一次检查结果（同检查键幂等），并维护 current 标记。"""
        if problems_json is None:
            problems_json = json.dumps(problems or [], ensure_ascii=False)
        problem_count = len(problems or [])
        severity_top = ""
        order = {"low": 1, "medium": 2, "high": 3}
        for problem in problems or []:
            if order.get(problem.get("severity"), 0) > order.get(severity_top, 0):
                severity_top = problem["severity"]

        with self.session_factory() as session:
            row = session.execute(
                select(PrearchiveResult).where(
                    PrearchiveResult.patient_id == patient_id,
                    PrearchiveResult.visit_id == visit_id,
                    PrearchiveResult.finished_date_time == finished_date_time,
                )
            ).scalar_one_or_none()

            if row is None:
                row = PrearchiveResult(
                    patient_id=patient_id,
                    visit_id=visit_id,
                    finished_date_time=finished_date_time,
                    push_wecom_status=PUSH_PENDING,
                    push_agent_status=PUSH_PENDING,
                )
                session.add(row)

            row.current = 1
            row.problem_count = problem_count
            row.severity_top = severity_top
            row.problems_json = problems_json
            row.rule_version = rule_version
            row.dept_code = dept_code
            row.dept_name = dept_name
            row.patient_name = patient_name
            if receiver is not None:
                row.doctor_id = receiver.doctor_id
                row.doctor_name = receiver.doctor_name
                row.receiver_fallback = 1 if receiver.is_fallback else 0
            row.updated_at = datetime.now()

            # 旧检查行让位（保留历史，仅摘 current）
            session.execute(
                update(PrearchiveResult)
                .where(PrearchiveResult.patient_id == patient_id,
                       PrearchiveResult.visit_id == visit_id,
                       PrearchiveResult.finished_date_time != finished_date_time,
                       PrearchiveResult.current == 1)
                .values(current=0)
            )
            session.commit()
            session.refresh(row)
            return row

    def get_current(self, patient_id: str, visit_id: str) -> Optional[PrearchiveResult]:
        with self.session_factory() as session:
            return session.execute(
                select(PrearchiveResult).where(
                    PrearchiveResult.patient_id == patient_id,
                    PrearchiveResult.visit_id == visit_id,
                    PrearchiveResult.current == 1,
                )
            ).scalar_one_or_none()

    def list_history(self, patient_id: str, visit_id: str) -> list:
        with self.session_factory() as session:
            rows = session.execute(
                select(PrearchiveResult).where(
                    PrearchiveResult.patient_id == patient_id,
                    PrearchiveResult.visit_id == visit_id,
                ).order_by(PrearchiveResult.finished_date_time.desc())
            ).scalars().all()
            return list(rows)

    def set_push_status(self, result_id: int, channel: str, status: str,
                        detail: str = "") -> bool:
        """双通道状态回写（wecom / agent）；已 sent 的通道不允许回退（去重纪律）。"""
        if channel not in ("wecom", "agent"):
            raise ValueError(f"unknown channel: {channel}")
        at_column = "push_wecom_at" if channel == "wecom" else "push_agent_at"
        status_column = ("push_wecom_status" if channel == "wecom"
                         else "push_agent_status")
        detail_column = ("push_wecom_detail" if channel == "wecom"
                         else "push_agent_detail")
        with self.session_factory() as session:
            row = session.get(PrearchiveResult, result_id)
            if row is None:
                return False
            if getattr(row, status_column) == PUSH_SENT and status != PUSH_SENT:
                return False   # 已成功推送的通道保持 sent
            setattr(row, status_column, status)
            setattr(row, detail_column, str(detail or "")[:500])
            setattr(row, at_column, datetime.now() if status == PUSH_SENT else None)
            session.commit()
            return True
