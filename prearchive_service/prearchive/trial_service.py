# -*- coding: utf-8 -*-
"""046 T1b 试运行（trial）执行服务。

纪律（046 §4.1.1/§T1b）：
- trial 规则集独立构建：指定 rule_keys+versions（只读正式仓内容）或已接受候选的
  suggested_dsl（结构校验通过后）；
- 执行结果只落 RUN/RULE_EVAL（is_trial=1），不写正式 MED_PREARCHIVE_RESULT、
  不推送、不入 Outbox、不改正式发布指针；
- 接受/驳回候选与 trial 执行都不改变正式引擎；
- 观察数据 API 级可查：每规则执行量/命中/unknown/人工反馈（确认缺陷/误报/待核实）。
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select

from .closed_loop_models import (
    EVAL_FAIL,
    EVAL_PASS,
    EVAL_PENDING,
    EVAL_UNKNOWN,
    RUN_COMPLETED,
    RUN_PARTIAL,
    RUN_REQUESTED,
    RUN_RUNNING,
    RunRow,
    TrialFeedbackRow,
)
from .engine import RuleEngine
from .eval_store import build_summary, source_health
from .rule_models import new_id
from .rule_repository import RuleRepository
from .rules import validate_rule as validate_dsl

TRIAL_FEEDBACK_VERDICTS = ("confirmed_defect", "false_positive", "pending_review")


class TrialService:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    # ---- 规则集构建 ----

    def build_trial_ruleset(self, trial_run_id: str) -> list:
        """trial 申请载荷 → RuleSpec 列表（正式仓内容只读，不落任何草稿）。"""
        run = self.get_run(trial_run_id)
        if run is None:
            raise ValueError(f"trial run not found: {trial_run_id}")
        payload = json.loads(run.trial_rules_json or "{}")
        repo = RuleRepository(self.session_factory)
        specs = []
        seen = set()

        for entry in payload.get("rule_keys") or []:
            rule_key = str(entry.get("rule_key") or entry)
            version = str(entry.get("rule_version") or "")
            row = (repo.get_version(rule_key, version)
                   if version else repo.latest_version(rule_key))
            if row is None:
                raise ValueError(f"rule not found in registry: {rule_key}@{version}")
            if rule_key in seen:
                continue
            specs.append(validate_dsl(json.loads(row.content_json)))
            seen.add(rule_key)

        from .closed_loop_models import MatchCandidateRow
        with self.session_factory() as session:
            for candidate_id in payload.get("candidate_ids") or []:
                row = session.get(MatchCandidateRow, str(candidate_id))
                if row is None:
                    raise ValueError(f"candidate not found: {candidate_id}")
                if row.decision != "accepted":
                    raise ValueError(
                        f"candidate {candidate_id} not accepted (decision="
                        f"{row.decision}); only accepted candidates can run in trial")
                dsl = json.loads(row.suggested_dsl_json or "{}")
                if not dsl:
                    raise ValueError(f"candidate {candidate_id} has no suggested DSL")
                spec = validate_dsl(dsl)
                if spec.rule_id in seen:
                    continue
                specs.append(spec)
                seen.add(spec.rule_id)

        for fid in payload.get("fids") or []:
            with self.session_factory() as session:
                rows = session.execute(select(MatchCandidateRow).where(
                    MatchCandidateRow.fid == int(fid),
                    MatchCandidateRow.decision == "accepted")).scalars().all()
            for row in rows:
                dsl = json.loads(row.suggested_dsl_json or "{}")
                if not dsl:
                    continue
                spec = validate_dsl(dsl)
                if spec.rule_id in seen:
                    continue
                specs.append(spec)
                seen.add(spec.rule_id)

        if not specs:
            raise ValueError("trial ruleset is empty (no rules/candidates resolved)")
        return specs

    # ---- 执行 ----

    def get_run(self, trial_run_id: str):
        with self.session_factory() as session:
            return session.get(RunRow, trial_run_id)

    def execute(self, trial_run_id: str, *, context_builder,
                catalog_provider=None) -> dict:
        """requested → running → completed/partial。

        context_builder 由调用方注入（本地=demo fixtures；生产=真实采集器，
        观察范围受 trial_scope 限制）。执行结果隔离在 RUN/RULE_EVAL(is_trial=1)。
        """
        from .context import FinishedVisit

        run = self.get_run(trial_run_id)
        if run is None:
            raise ValueError(f"trial run not found: {trial_run_id}")
        if run.status not in (RUN_REQUESTED,):
            raise ValueError(f"trial run not executable in status {run.status}")

        specs = self.build_trial_ruleset(trial_run_id)
        scope = json.loads(run.trial_scope_json or "{}")

        with self.session_factory() as session:
            row = session.get(RunRow, trial_run_id)
            row.status = RUN_RUNNING
            row.started_at = datetime.now()
            session.commit()

        engine = RuleEngine(specs, rule_version=f"trial:{trial_run_id[:8]}")
        collector = getattr(context_builder, "jhemr", None)
        patients = scope.get("patients") or []
        results = []
        summary_total: list = []
        for visit in collector.fetch_finished_visits(None, 100):
            pid = getattr(visit, "patient_id", "")
            if patients and pid not in patients:
                continue
            ctx = context_builder.build(visit)
            if ctx is None:
                continue
            output = engine.evaluate(ctx)
            evals = [dict(e, is_trial=True) for e in output.evaluations]
            # trial 逐患者逐规则落 RULE_EVAL（挂同一 trial run 下按患者分键）
            with self.session_factory() as session:
                from .closed_loop_models import RuleEvalRow
                for item in evals:
                    session.add(RuleEvalRow(
                        id=new_id(), run_id=trial_run_id,
                        rule_id=item["rule_id"],
                        rule_version=item.get("rule_version") or "",
                        event_instance_id=str(
                            item.get("event_instance_id") or "") + f"|{pid}",
                        fid=item.get("fid"),
                        status=item["status"],
                        exclusion_reason=item.get("exclusion_reason") or "",
                        reason_code=item.get("reason_code") or "",
                        evidence_json=json.dumps(item.get("evidence") or {},
                                                 ensure_ascii=False),
                        observed_at=datetime.now(),
                        is_trial=1,
                    ))
                session.commit()
            summary_total.extend(evals)
            results.append({"patient_id": pid,
                            "problem_count": output.problem_count,
                            "problems": output.problems})

        from .eval_store import EvalRunStore
        store = EvalRunStore(self.session_factory)
        catalog_count, mapped = 92, len({s.mark_item_fid for s in specs
                                          if s.mark_item_fid is not None})
        if catalog_provider:
            try:
                provided = catalog_provider()
                catalog_count = int(provided.get("catalog_count", 92))
            except Exception:
                pass
        summary = build_summary(
            evaluations=summary_total, catalog_count=catalog_count,
            mapped_catalog_count=mapped,
            source_health_map={}, rule_sources={})
        status = RUN_COMPLETED if results else RUN_PARTIAL
        with self.session_factory() as session:
            row = session.get(RunRow, trial_run_id)
            row.status = status
            row.summary_json = json.dumps(summary, ensure_ascii=False)
            row.finished_at = datetime.now()
            session.commit()
        return {"trial_run_id": trial_run_id, "status": status,
                "patients": len(results), "summary": summary,
                "results": results}

    # ---- 观察数据 ----

    def observations(self, trial_run_id: str) -> dict:
        """每规则执行量/命中/unknown/排除 + 人工反馈汇总（§6.2 观察口径）。"""
        from .closed_loop_models import RuleEvalRow
        with self.session_factory() as session:
            evals = session.execute(select(RuleEvalRow).where(
                RuleEvalRow.run_id == trial_run_id)).scalars().all()
            feedbacks = session.execute(select(TrialFeedbackRow).where(
                TrialFeedbackRow.run_id == trial_run_id)).scalars().all()

        by_rule: dict = {}
        for ev in evals:
            entry = by_rule.setdefault(ev.rule_id, {
                "rule_id": ev.rule_id, "fid": ev.fid,
                "executions": 0, "hits": 0, "pass": 0, "unknown": 0,
                "pending": 0, "excluded": 0,
                "confirmed_defect": 0, "false_positive": 0, "pending_review": 0})
            entry["executions"] += 1
            if ev.status == EVAL_FAIL:
                entry["hits"] += 1
            elif ev.status == EVAL_PASS:
                entry["pass"] += 1
            elif ev.status == EVAL_UNKNOWN:
                entry["unknown"] += 1
            elif ev.status == EVAL_PENDING:
                entry["pending"] += 1
            else:
                entry["excluded"] += 1
        for fb in feedbacks:
            entry = by_rule.get(fb.rule_id)
            if entry is not None and fb.verdict in entry:
                entry[fb.verdict] += 1

        run = self.get_run(trial_run_id)
        total = sum(e["executions"] for e in by_rule.values())
        reviewed = sum(e["confirmed_defect"] + e["false_positive"]
                       + e["pending_review"] for e in by_rule.values())
        return {
            "trial_run_id": trial_run_id,
            "status": run.status if run else "unknown",
            "rules": sorted(by_rule.values(), key=lambda e: e["rule_id"]),
            "totals": {"rules": len(by_rule), "executions": total,
                       "reviewed": reviewed,
                       "confirmed_defect": sum(e["confirmed_defect"]
                                               for e in by_rule.values()),
                       "false_positive": sum(e["false_positive"]
                                             for e in by_rule.values())},
            "summary": json.loads(run.summary_json) if run else {},
        }

    def add_feedback(self, trial_run_id: str, *, rule_id: str,
                     event_instance_id: str, verdict: str, operator,
                     note: str = "", fid=None) -> TrialFeedbackRow:
        if verdict not in TRIAL_FEEDBACK_VERDICTS:
            raise ValueError(f"verdict must be one of {TRIAL_FEEDBACK_VERDICTS}")
        with self.session_factory() as session:
            row = TrialFeedbackRow(
                id=new_id(), run_id=trial_run_id, rule_id=rule_id,
                event_instance_id=event_instance_id or "", fid=fid,
                verdict=verdict, note=note[:500], operator_id=operator.id,
                operator_name=operator.name)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row
