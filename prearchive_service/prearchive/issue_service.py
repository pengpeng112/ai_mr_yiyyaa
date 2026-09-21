# -*- coding: utf-8 -*-
"""046 T5/T6/T7 缺陷实例生命周期：fail 评估 → 稳定 ISSUE → 人工动作 → 复检收敛。

- issue_key = patient|visit|rule|event（同一临床问题生命周期内稳定；复检不换 ID）；
- 新 run 中同 key 的 fail → last_seen 更新（不新建）；未再 fail → resolved（记录
  resolved_run_id，接收端可据此撤销旧缺陷）；
- 人工动作 append-only（IssueActionRow），状态机与引擎结论分离：
  viewed → rectifying（医生已提交整改，待复检）→ resolved（复检通过）/
  false_positive（误报）/ manual_closed（人工关闭，原因必填）；
- 幂等 + 乐观 issue_version；动作审计可追溯。
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select, tuple_

from .closed_loop_models import (
    ISSUE_FALSE_POSITIVE,
    ISSUE_MANUAL_CLOSED,
    ISSUE_OPEN,
    ISSUE_RECTIFYING,
    ISSUE_RESOLVED,
    ISSUE_VIEWED,
    RuleEvalRow,
    RunRow,
    IssueActionRow,
    IssueRow,
)
from .rule_models import new_id

# 人工动作 → 状态流转（recheck_requested/note 不改状态）
ISSUE_ACTIONS = {
    "viewed": ISSUE_VIEWED,
    "rectified": ISSUE_RECTIFYING,
    "false_positive": ISSUE_FALSE_POSITIVE,
    "manual_closed": ISSUE_MANUAL_CLOSED,
    "recheck_passed": ISSUE_RESOLVED,
}
NON_STATE_ACTIONS = ("note", "recheck_requested")


def issue_key_for(patient_id: str, visit_number: str, rule_id: str,
                  event_instance_id: str) -> str:
    return "|".join([patient_id, visit_number, rule_id, event_instance_id or ""])


class IssueConflictError(Exception):
    """乐观版本冲突 / 非法动作。"""


class IssueService:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    # ---- 物化：run 的 fail 评估 → ISSUE upsert/resolve ----

    def materialize_for_run(self, run_id: str) -> dict:
        """run 完成（或 trial）后调用：fail→open/last_seen 更新；既往同 key
        未再 fail 且非人工终态 → resolved（复检收敛，可通知接收端撤销）。"""
        with self.session_factory() as session:
            run = session.get(RunRow, run_id)
            if run is None:
                raise ValueError(f"run not found: {run_id}")
            evals = session.execute(select(RuleEvalRow).where(
                RuleEvalRow.run_id == run_id)).scalars().all()
            trial = bool(run.is_trial)
            fail_keys = set()
            for ev in evals:
                if ev.status != "fail" or ev.is_trial != (1 if trial else 0):
                    continue
                # trial 评估不物化正式缺陷（观察态）
                if trial:
                    continue
                event_id = str(ev.event_instance_id or "")
                key = issue_key_for(run.patient_id, run.visit_number,
                                    ev.rule_id, event_id)
                fail_keys.add(key)
                evidence = json.loads(ev.evidence_json or "{}")
                row = session.execute(select(IssueRow).where(
                    IssueRow.issue_key == key)).scalar_one_or_none()
                if row is None:
                    session.add(IssueRow(
                        id=new_id(), issue_key=key,
                        patient_id=run.patient_id,
                        visit_number=run.visit_number,
                        dept_code=run.dept_code, fid=ev.fid,
                        clause_id=ev.clause_id, rule_id=ev.rule_id,
                        rule_version=ev.rule_version,
                        event_instance_id=event_id,
                        severity=evidence.get("severity", "medium"),
                        message=str(evidence.get("message") or ""),
                        status=ISSUE_OPEN,
                        first_seen_run_id=run_id, last_seen_run_id=run_id,
                        is_trial=0))
                else:
                    row.last_seen_run_id = run_id
                    row.last_seen_at = datetime.now()
                    row.rule_version = ev.rule_version
                    row.version = int(row.version or 1) + 1
                    if row.status in (ISSUE_VIEWED, ISSUE_RECTIFYING):
                        # 人工处理中再次命中：保持人工状态，仅刷新 last_seen
                        pass
                    elif row.status == ISSUE_RESOLVED:
                        # 已解决后问题复现（新版本回归/整改不彻底）→ 重开
                        row.status = ISSUE_OPEN
                        row.resolved_run_id = ""
                        session.add(IssueActionRow(
                            id=new_id(), issue_id=row.id, action="note",
                            status_from=ISSUE_RESOLVED, status_to=ISSUE_OPEN,
                            reason="复检再次命中（重开）", operator_id="system",
                            operator_name="engine",
                            issue_version=0))

            # 复检收敛：该就诊既往 open/viewed/rectifying 且本次未再 fail → resolved
            existing = session.execute(select(IssueRow).where(
                IssueRow.patient_id == run.patient_id,
                IssueRow.visit_number == run.visit_number,
                IssueRow.is_trial == 0)).scalars().all()
            resolved = 0
            resolved_issue_keys = []   # 046 T6：接收端撤销旧缺陷的锚点
            for row in existing:
                if row.issue_key in fail_keys:
                    continue
                if row.status in (ISSUE_OPEN, ISSUE_VIEWED, ISSUE_RECTIFYING) \
                        and row.last_seen_run_id != run_id:
                    row.status = ISSUE_RESOLVED
                    row.resolved_run_id = run_id
                    row.version = int(row.version or 1) + 1
                    resolved += 1
                    resolved_issue_keys.append({
                        "issue_key": row.issue_key,
                        "rule_id": row.rule_id,
                        "event_instance_id": str(row.event_instance_id or ""),
                        "fid": row.fid,
                    })
            session.commit()
        return {"fail_keys": len(fail_keys), "resolved": resolved,
                "resolved_issue_keys": resolved_issue_keys}

    # ---- 人工动作 ----

    def apply_action(self, issue_id: str, *, action: str, operator,
                     reason: str = "", expect_issue_version: int = 0,
                     document_revision: str = "") -> IssueRow:
        if action in NON_STATE_ACTIONS:
            pass
        elif action not in ISSUE_ACTIONS:
            raise IssueConflictError(
                f"unknown action: {action}; legal={sorted(ISSUE_ACTIONS)} "
                f"+ {sorted(NON_STATE_ACTIONS)}")
        if action == "manual_closed" and not (reason or "").strip():
            raise IssueConflictError("manual_closed requires a reason")
        with self.session_factory() as session:
            row = session.get(IssueRow, issue_id)
            if row is None:
                raise ValueError(f"issue not found: {issue_id}")
            current_version = self._version_of(row)
            if expect_issue_version and int(expect_issue_version) != current_version:
                raise IssueConflictError(
                    f"issue version conflict: expected {expect_issue_version}, "
                    f"got {current_version}")
            status_from = row.status
            if action in ISSUE_ACTIONS:
                # 已整改（rectifying）只允许复检通过/关闭；误报/关闭从 open/viewed
                legal_from = {
                    ISSUE_OPEN: ("viewed", "rectified", "false_positive",
                                 "manual_closed"),
                    ISSUE_VIEWED: ("rectified", "false_positive", "manual_closed"),
                    ISSUE_RECTIFYING: ("recheck_passed", "manual_closed"),
                }.get(status_from, ())
                if action not in legal_from:
                    raise IssueConflictError(
                        f"action {action} not allowed from status {status_from}")
                row.status = ISSUE_ACTIONS[action]
                if action == "recheck_passed":
                    row.resolved_run_id = row.last_seen_run_id
                row.version = int(row.version or 1) + 1
            session.add(IssueActionRow(
                id=new_id(), issue_id=issue_id, action=action,
                status_from=status_from, status_to=row.status,
                reason=str(reason or "")[:500], operator_id=operator.id,
                operator_name=operator.name,
                issue_version=current_version,
                document_revision=str(document_revision or "")[:120]))
            session.commit()
            session.refresh(row)
            return row

    @staticmethod
    def _version_of(row: IssueRow) -> int:
        return int(row.version or 1)

    # ---- 查询 ----

    def list_issues(self, *, patient_id: str = "", visit_number: str = "",
                    dept_code: str = "", status: str = "", limit: int = 200,
                    include_trial: bool = False) -> list:
        with self.session_factory() as session:
            stmt = select(IssueRow)
            if patient_id:
                stmt = stmt.where(IssueRow.patient_id == patient_id)
            if visit_number:
                stmt = stmt.where(IssueRow.visit_number == visit_number)
            if dept_code:
                stmt = stmt.where(IssueRow.dept_code == dept_code)
            if status:
                stmt = stmt.where(IssueRow.status == status)
            if not include_trial:
                stmt = stmt.where(IssueRow.is_trial == 0)
            return list(session.execute(stmt.order_by(
                IssueRow.last_seen_at.desc()).limit(min(limit, 500))).scalars().all())

    def get_issue(self, issue_id: str):
        with self.session_factory() as session:
            return session.get(IssueRow, issue_id)

    def list_actions(self, issue_id: str) -> list:
        with self.session_factory() as session:
            return list(session.execute(select(IssueActionRow).where(
                IssueActionRow.issue_id == issue_id).order_by(
                IssueActionRow.created_at)).scalars().all())


# ---- 048 T2：核查列表分页 + 有界聚合（服务层查询，路由只留鉴权/参数） ----

# 单页 (patient_id, visit_number) 组合数上限 = page_size 上限；Oracle IN 列表
# 1000 表达式限制内（每组合 2 列 → 300 组合 = 600 表达式）。
CHECKS_MAX_PAGE_SIZE = 300
CHECKS_DEFAULT_PAGE_SIZE = 100


def browse_check_runs(session_factory, *, dept_code: str = "",
                      patient_id: str = "", visit_number: str = "",
                      trigger_type: str = "", is_trial: int = 0,
                      page: int = 1, page_size: int = CHECKS_DEFAULT_PAGE_SIZE):
    """核查列表查询：真实 total（全部筛选后）+ 当前页 runs + 本页就诊的缺陷计数。

    - 排序 created_at DESC + id DESC（同秒不重不漏）；
    - 缺陷计数只查当前页 (patient_id, visit_number) 组合的正式 issue（分组聚合，
      零本页 run 不扫 issue 表）——计数语义=就诊当前缺陷状态，非历史 run 时点快照。
    返回 (runs, total, counts)；counts[(patient, visit)][status] = 数量。
    """
    stmt = select(RunRow).where(RunRow.is_trial == int(is_trial))
    if dept_code:
        stmt = stmt.where(RunRow.dept_code == dept_code)
    if patient_id:
        stmt = stmt.where(RunRow.patient_id == patient_id)
    if visit_number:
        stmt = stmt.where(RunRow.visit_number == visit_number)
    if trigger_type:
        stmt = stmt.where(RunRow.trigger_type == trigger_type)

    with session_factory() as session:
        total = session.execute(
            select(func.count()).select_from(
                stmt.order_by(None).subquery())).scalar_one()
        runs = session.execute(
            stmt.order_by(RunRow.created_at.desc(), RunRow.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).scalars().all()

        counts: dict = {}
        pairs = sorted({(r.patient_id, r.visit_number) for r in runs})
        if pairs:
            rows = session.execute(
                select(IssueRow.patient_id, IssueRow.visit_number,
                       IssueRow.status, func.count().label("cnt"))
                .where(IssueRow.is_trial == 0,
                       tuple_(IssueRow.patient_id,
                              IssueRow.visit_number).in_(pairs))
                .group_by(IssueRow.patient_id, IssueRow.visit_number,
                          IssueRow.status)
            ).all()
            for pid, visit, status, cnt in rows:
                counts.setdefault((pid, visit), {})[status] = int(cnt)
    return list(runs), int(total), counts
