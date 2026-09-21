# -*- coding: utf-8 -*-
"""046 T2 评估存储与公共汇总模型（T7.1 schema 在此实现，T7 GET 复用）。

- EvalRunStore：RUN（同就诊复检 revision 递增）+ RULE_EVAL（run×rule×event 唯一）；
- source_health：源健康面（healthy/error，来自 collect_errors；RPA 模式水位门
  禁用不影响源故障判定）；
- build_summary：046 §T7.1 终态汇总字段与算术约束（计数守恒/覆盖率分母 null/
  queued 未定计数 null）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from .closed_loop_models import (
    EVAL_FAIL,
    EVAL_NOT_APPLICABLE,
    EVAL_PASS,
    EVAL_PENDING,
    EVAL_UNKNOWN,
    RUN_RUNNING,
    RuleEvalRow,
    RunRow,
)
from .context import WATERMARK_KEYS
from .rule_models import new_id

SUMMARY_SCHEMA_VERSION = "2.0.0"

APPLICABLE_STATUSES = (EVAL_PASS, EVAL_FAIL, EVAL_UNKNOWN, EVAL_PENDING)


def source_health(ctx) -> dict:
    """源健康面：短键 → {status: healthy|error, detail}。

    有采集错误的源一律 error（不能作为"不存在结论"依据）；无错误按 healthy。
    """
    errors = getattr(ctx, "collect_errors", None) or {}
    health = {}
    for label, key in WATERMARK_KEYS.items():
        if key in errors:
            health.setdefault(key, {"status": "error",
                                    "detail": str(errors[key])[:200]})
        else:
            health.setdefault(key, {"status": "healthy", "detail": ""})
    return health


def build_summary(*, evaluations: list, catalog_count: int,
                  mapped_catalog_count: int,
                  source_health_map: Optional[dict] = None,
                  rule_sources: Optional[dict] = None,
                  issue_count: Optional[int] = None,
                  provisional: bool = False,
                  freshness: str = "unknown") -> dict:
    """046 §T7.1 汇总。算术约束：

    - applicable_count = pass+fail+unknown+pending；
    - evaluated_count = pass+fail；
    - rule_instance_count = applicable_count + excluded_count；
    - evaluation_coverage_pct = evaluated/applicable×100，分母 0 → null；
    - data_coverage_pct 同理分母 0 → null；
    - 全排除/零规则不得显示"全部通过"（status=not_run + reason）。
    """
    counts = {EVAL_PASS: 0, EVAL_FAIL: 0, EVAL_UNKNOWN: 0, EVAL_PENDING: 0}
    exclusion_reasons: dict[str, int] = {}
    excluded = 0
    for item in evaluations or []:
        status = item.get("status")
        if status in counts:
            counts[status] += 1
        else:
            # not_applicable / disabled / dept_excluded / exempt_scene 等全部计入
            # excluded（T7.1：rule_instance_count = applicable + excluded）
            excluded += 1
            if status == EVAL_NOT_APPLICABLE:
                reason = item.get("reason_code") or "not_applicable"
            else:
                reason = item.get("exclusion_reason") or \
                    item.get("reason_code") or "other"
            exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1

    applicable = counts[EVAL_PASS] + counts[EVAL_FAIL] + counts[EVAL_UNKNOWN] \
        + counts[EVAL_PENDING]
    evaluated = counts[EVAL_PASS] + counts[EVAL_FAIL]
    rule_instance_count = applicable + excluded

    # 数据源核验对（适用实例 × 其规则引用的源）
    health = source_health_map or {}
    sources_by_rule = rule_sources or {}
    required_pairs = 0
    ready_pairs = 0
    for item in evaluations or []:
        if item.get("status") not in APPLICABLE_STATUSES:
            continue
        for src in sources_by_rule.get(item.get("rule_id"), []):
            required_pairs += 1
            key = WATERMARK_KEYS.get(src, src)
            if health.get(key, {}).get("status") == "healthy":
                ready_pairs += 1
    data_coverage = round(ready_pairs / required_pairs * 100, 2) \
        if required_pairs else None
    eval_coverage = round(evaluated / applicable * 100, 2) if applicable else None

    fail_count = counts[EVAL_FAIL]
    if issue_count is None:
        issue_count = fail_count

    if rule_instance_count == 0:
        status = "not_run"
    elif fail_count:
        status = "fail"
    elif evaluated == applicable and applicable > 0:
        status = "pass"
    elif counts[EVAL_UNKNOWN]:
        status = "unknown"
    else:
        status = "pending"

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "catalog_count": catalog_count,
        "mapped_catalog_count": mapped_catalog_count,
        "rule_instance_count": rule_instance_count,
        "applicable_count": applicable,
        "evaluated_count": evaluated,
        "pass_count": counts[EVAL_PASS],
        "fail_count": fail_count,
        "unknown_count": counts[EVAL_UNKNOWN],
        "pending_count": counts[EVAL_PENDING],
        "excluded_count": excluded,
        "exclusion_reasons": exclusion_reasons,
        "issue_count": issue_count,
        "evaluation_coverage_pct": eval_coverage,
        "required_source_checks": required_pairs,
        "ready_source_checks": ready_pairs,
        "data_coverage_pct": data_coverage,
        "status": status,
        "provisional": provisional,
        "freshness": freshness,
    }


class EvalRunStore:
    """RUN + RULE_EVAL 持久化（046 §3.2 检查任务/运行 + 单规则评估）。"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def next_revision(self, patient_id: str, visit_number: str) -> int:
        with self.session_factory() as session:
            rows = session.execute(
                select(RunRow.run_revision).where(
                    RunRow.patient_id == patient_id,
                    RunRow.visit_number == visit_number)
            ).scalars().all()
        return (max(rows) + 1) if rows else 1

    def start_run(self, *, patient_id: str, visit_number: str,
                  trigger_type: str, trigger_id: str = "",
                  snapshot_id: str = "", ruleset_revision: str = "",
                  ruleset_hash: str = "", is_trial: bool = False,
                  requested_by: str = "", dept_code: str = "",
                  dept_name: str = "", submission_id: str = "",
                  run_id: str = "") -> RunRow:
        with self.session_factory() as session:
            # 046 T7：集成入口（emr_submit/manual_recheck）预创建占位 run 后由
            # 主链路接管——保留既有 run_revision/submission_id/requested_by
            # （revision 在占位创建时已定，不重算：占位行本身已入 max）
            if run_id:
                existing = session.get(RunRow, run_id)
                if existing is not None:
                    existing.trigger_type = trigger_type
                    existing.trigger_id = trigger_id
                    existing.snapshot_id = snapshot_id
                    existing.ruleset_revision = ruleset_revision
                    existing.ruleset_hash = ruleset_hash
                    existing.status = RUN_RUNNING
                    existing.started_at = datetime.now()
                    session.commit()
                    session.refresh(existing)
                    return existing
            revision = self.next_revision(patient_id, visit_number)
            run = RunRow(
                id=run_id or new_id(), run_revision=revision,
                patient_id=patient_id, visit_number=visit_number,
                dept_code=dept_code, dept_name=dept_name,
                trigger_type=trigger_type, trigger_id=trigger_id,
                submission_id=submission_id, snapshot_id=snapshot_id,
                ruleset_revision=ruleset_revision, ruleset_hash=ruleset_hash,
                is_trial=1 if is_trial else 0, status=RUN_RUNNING,
                requested_by=requested_by, started_at=datetime.now(),
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

    def record_evals(self, run_id: str, evaluations: list,
                     is_trial: bool = False) -> int:
        """写入逐规则评估（同 run 重写=先删后插，保持幂等）。"""
        from sqlalchemy import delete
        with self.session_factory() as session:
            # bulk DELETE 立即执行（ORM delete 走 unit-of-work 会在 INSERT 之后）
            session.execute(delete(RuleEvalRow).where(RuleEvalRow.run_id == run_id))
            count = 0
            for item in evaluations or []:
                session.add(RuleEvalRow(
                    id=new_id(), run_id=run_id,
                    rule_id=str(item.get("rule_id") or ""),
                    rule_version=str(item.get("rule_version") or ""),
                    event_instance_id=str(item.get("event_instance_id") or ""),
                    fid=item.get("fid"),
                    clause_id=str(item.get("clause_id") or ""),
                    status=str(item.get("status") or EVAL_UNKNOWN),
                    exclusion_reason=str(item.get("exclusion_reason") or ""),
                    reason_code=str(item.get("reason_code") or ""),
                    evidence_json=json.dumps(item.get("evidence") or {},
                                             ensure_ascii=False),
                    observed_at=datetime.now(),
                    deadline_at=_parse_dt(item.get("deadline")),
                    is_trial=1 if is_trial else 0,
                ))
                count += 1
            session.commit()
        return count

    def finish_run(self, run_id: str, status: str, summary: dict,
                   source_health_map: dict, result_id=None,
                   status_detail: str = "", checked_at=None,
                   data_snapshot_at=None) -> Optional[RunRow]:
        with self.session_factory() as session:
            run = session.get(RunRow, run_id)
            if run is None:
                return None
            run.status = status
            run.status_detail = status_detail[:500]
            run.summary_json = json.dumps(summary, ensure_ascii=False)
            run.source_health_json = json.dumps(source_health_map,
                                                 ensure_ascii=False)
            run.finished_at = datetime.now()
            run.checked_at = checked_at or datetime.now()
            run.data_snapshot_at = data_snapshot_at or datetime.now()
            if result_id is not None:
                run.result_id = result_id
            session.commit()
            session.refresh(run)
            return run

    def get_run(self, run_id: str) -> Optional[RunRow]:
        with self.session_factory() as session:
            return session.get(RunRow, run_id)

    def latest_run(self, patient_id: str, visit_number: str,
                   include_trial: bool = False) -> Optional[RunRow]:
        with self.session_factory() as session:
            stmt = select(RunRow).where(
                RunRow.patient_id == patient_id,
                RunRow.visit_number == visit_number)
            if not include_trial:
                stmt = stmt.where(RunRow.is_trial == 0)
            return session.execute(stmt.order_by(
                RunRow.run_revision.desc()).limit(1)).scalars().first()

    def list_evals(self, run_id: str) -> list:
        with self.session_factory() as session:
            return list(session.execute(
                select(RuleEvalRow).where(RuleEvalRow.run_id == run_id)
                .order_by(RuleEvalRow.rule_id)).scalars().all())


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
