# -*- coding: utf-8 -*-
"""046 闭环管理 API（覆盖账本 / AI 匹配 / trial 申请）。

鉴权与 admin_api 同一套（X-Admin-Token + X-Actor-* 签名）；写操作要求对应权限：
- 覆盖账本读/导出：prearchive_rule_view；导入/确认：prearchive_rule_edit；
- 匹配任务：prearchive_match_run；候选接受/驳回：prearchive_match_run；
- trial 申请：prearchive_trial_manage。

T1a 只落 trial 申请契约（持久化 requested）；真实执行接线在 T1b（trigger_type=trial
的 run 由 T1b 的执行器消费）。导出走审计（coverage_export）。
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from .closed_loop_models import (
    RUN_REQUESTED,
    TRIGGER_TRIAL,
    RunRow,
)
from .coverage import (
    DEFAULT_SNAPSHOT_ID,
    build_coverage_records,
    coverage_counts,
    load_snapshot_items,
    write_coverage_json,
)
from .match_service import CoverageRepository, MatchService
from .rule_models import new_id
from .rule_repository import RuleRepository
from .rule_service import RuleService
from .admin_api import (
    ACTOR_ID_HEADER,
    ACTOR_NAME_HEADER,
    ACTOR_PERMS_HEADER,
    ACTOR_SIGNATURE_HEADER,
    ADMIN_TOKEN_HEADER,
    REQUEST_ID_HEADER,
    actor_signature,
)

PERM_VIEW = "prearchive_rule_view"
PERM_EDIT = "prearchive_rule_edit"
PERM_MATCH = "prearchive_match_run"
PERM_TRIAL = "prearchive_trial_manage"
PERM_CHECK_VIEW = "prearchive_check_view"
PERM_ISSUE_REVIEW = "prearchive_issue_review"
PERM_ISSUE_FEEDBACK = "prearchive_issue_feedback"


def _mount_actor(request: Request, admin_cfg: dict):
    """复用 admin_api 的鉴权口径（token + actor 签名），返回 Actor。"""
    from .rule_service import Actor
    from urllib.parse import unquote
    import hmac as _hmac

    admin_token = str(admin_cfg.get("admin_token") or "")
    signing_secret = str(admin_cfg.get("signing_secret") or "")
    provided = request.headers.get(ADMIN_TOKEN_HEADER, "")
    if not admin_token or admin_token.startswith("<"):
        raise HTTPException(status_code=503, detail="admin api token not configured")
    if not _hmac.compare_digest(provided, admin_token):
        raise HTTPException(status_code=401, detail="invalid admin token")
    if not signing_secret or signing_secret.startswith("<"):
        raise HTTPException(status_code=503, detail="admin signing secret not configured")
    actor_id = request.headers.get(ACTOR_ID_HEADER, "")
    raw_name = request.headers.get(ACTOR_NAME_HEADER, "")
    permissions = request.headers.get(ACTOR_PERMS_HEADER, "")
    request_id = request.headers.get(REQUEST_ID_HEADER, "")
    signature = request.headers.get(ACTOR_SIGNATURE_HEADER, "")
    expected = actor_signature(signing_secret, actor_id, raw_name, permissions,
                               request_id)
    if not signature or not _hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="invalid actor signature")
    perms = [p for p in permissions.split(",") if p.strip()]
    return Actor(id=actor_id, name=unquote(raw_name), permissions=perms)


def _require(actor, permission):
    perms = permission if isinstance(permission, (tuple, list)) else (permission,)
    if perms and not any(actor.has(p) for p in perms if p):
        raise HTTPException(status_code=403,
                            detail=f"permission denied: {perms[0]}")


def create_closed_loop_router(config: dict, session_factory,
                              repository: RuleRepository,
                              service: RuleService) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["prearchive-closed-loop"])
    admin_cfg = (config or {}).get("admin_api") or {}
    coverage_repo = CoverageRepository(session_factory)
    match_service = MatchService(session_factory)

    def _request_id(request: Request) -> str:
        return request.headers.get(REQUEST_ID_HEADER, "") or "req-unset"

    def _audit(repository: RuleRepository, **kwargs) -> None:
        repository.append_audit(**kwargs)

    # ---- 覆盖账本 ----

    @router.get("/coverage", summary="覆盖账本（92 FID 聚合检索）")
    def list_coverage(request: Request, fid: int = -1, method: str = "",
                      status: str = "", q: str = "", page: int = 1,
                      page_size: int = 50):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_VIEW)
        items, total = coverage_repo.list_coverage(
            fid=fid if fid >= 0 else None, method=method, status=status, q=q,
            page=page, page_size=min(page_size, 200))
        return {"total": total, "counts": coverage_repo.catalog_counts(),
                "items": items}

    @router.post("/coverage/import-snapshot", summary="导入评分目录快照→账本（幂等，差异预览）")
    def import_snapshot(request: Request, body: dict):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_EDIT)
        apply = bool(body.get("apply", False))
        snapshot_path = body.get("snapshot_path")
        snapshot_id = body.get("snapshot_id") or DEFAULT_SNAPSHOT_ID
        try:
            items = load_snapshot_items(snapshot_path)
            records = build_coverage_records(items, snapshot_id=snapshot_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"snapshot invalid: {exc}")
        report = coverage_repo.import_snapshot(records, apply=apply,
                                               actor_id=actor.id)
        _audit(repository, action="coverage_import",
               actor_id=actor.id, actor_name=actor.name,
               request_id=_request_id(request),
               detail={"apply": apply, "snapshot_id": snapshot_id,
                       "catalog_created": report["catalog_created"],
                       "diff": report["diff"]})
        report["snapshot_id"] = snapshot_id
        return report

    @router.post("/coverage/{fid}/confirm", summary="人工确认某 FID 覆盖（精确命中保护）")
    def confirm_coverage(fid: int, request: Request, body: dict):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_EDIT)
        try:
            rows = coverage_repo.confirm_fid(fid, actor)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        _audit(repository, action="coverage_confirm", rule_key=f"coverage:FID{fid}",
               actor_id=actor.id, actor_name=actor.name,
               reason=str(body.get("reason") or ""),
               request_id=_request_id(request), detail={"rows": rows})
        return {"ok": True, "fid": fid, "confirmed_rows": rows}

    @router.get("/coverage/export", summary="覆盖账本导出（审计留痕）")
    def export_coverage(request: Request, fmt: str = "json"):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_VIEW)
        items, total = coverage_repo.list_coverage(page=1, page_size=100000)
        _audit(repository, action="coverage_export",
               actor_id=actor.id, actor_name=actor.name,
               request_id=_request_id(request),
               detail={"rows": total, "fmt": fmt})
        return {"format": fmt, "total": total, "items": items}

    @router.post("/coverage/generate-file", summary="重生成 rules/paperless_coverage_v1.json（只写规则资产）")
    def generate_file(request: Request, body: dict):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_EDIT)
        records = build_coverage_records(load_snapshot_indices(body))
        path = write_coverage_json(records)
        _audit(repository, action="coverage_import",
               rule_key="coverage:file", actor_id=actor.id, actor_name=actor.name,
               request_id=_request_id(request),
               detail={"path": path, "count": len(records)})
        return {"ok": True, "path": path, "count": len(records),
                "counts": coverage_counts(records)}

    def load_snapshot_indices(body: dict):
        path = (body or {}).get("snapshot_path")
        return load_snapshot_items(path)

    # ---- AI 匹配 ----

    @router.post("/match/tasks", summary="创建 AI 匹配任务（stub/院内通道；相同输入复用）")
    def create_match_task(request: Request, body: dict):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_MATCH)
        fids = body.get("fids") or None
        model_name = str(body.get("model") or "stub")
        model_config = body.get("model_config") or {}
        try:
            task = match_service.create_task(
                fids=fids, actor_id=actor.id, model_name=model_name,
                model_config=model_config)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        _audit(repository, action="match_create",
               rule_key=f"match:{task.id}", actor_id=actor.id,
               actor_name=actor.name, request_id=_request_id(request),
               detail={"fids": fids, "model": model_name,
                       "input_hash": task.input_hash})
        return _task_dict(task)

    @router.post("/match/tasks/{task_id}/run", summary="执行匹配任务（同步；断点可续）")
    def run_match_task(task_id: str, request: Request):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_MATCH)
        task = match_service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
        model_client = None
        if task.model_name and task.model_name != "stub":
            model_client = _build_http_model(task.model_name,
                                             json.loads(task.model_config_json or "{}"))
        try:
            task = match_service.run_task(task_id, model_client=model_client)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _task_dict(task)

    @router.get("/match/tasks/{task_id}", summary="匹配任务状态与候选")
    def get_match_task(task_id: str, request: Request, fid: int = -1):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_VIEW)
        task = match_service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
        candidates = match_service.list_candidates(
            task_id, fid=fid if fid >= 0 else None)
        return {**_task_dict(task),
                "candidates": [_candidate_dict(c) for c in candidates]}

    @router.post("/match/tasks/{task_id}/cancel", summary="取消匹配任务")
    def cancel_match_task(task_id: str, request: Request):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_MATCH)
        task = match_service.cancel_task(task_id, actor.id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
        _audit(repository, action="match_cancel",
               rule_key=f"match:{task_id}", actor_id=actor.id,
               actor_name=actor.name, request_id=_request_id(request))
        return _task_dict(task)

    @router.post("/match/candidates/{candidate_id}/decision", summary="候选接受/驳回（留痕）")
    def decide_match_candidate(candidate_id: str, request: Request, body: dict):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_MATCH)
        decision = str(body.get("decision") or "")
        try:
            row = match_service.decide_candidate(
                candidate_id, decision, actor, note=str(body.get("note") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        _audit(repository,
               action="match_accept" if decision == "accepted" else "match_reject",
               rule_key=f"match-candidate:{candidate_id}", actor_id=actor.id,
               actor_name=actor.name, reason=str(body.get("note") or ""),
               request_id=_request_id(request), detail={"fid": row.fid})
        return _candidate_dict(row)

    # ---- trial 申请（T1a 契约；T1b 执行） ----

    @router.post("/trial/runs", summary="创建试运行申请（requested；执行在 T1b 接线）")
    def create_trial_run(request: Request, body: dict):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_TRIAL)
        rule_keys = body.get("rule_keys") or []
        candidate_ids = body.get("candidate_ids") or []
        fids = body.get("fids") or []
        if not rule_keys and not candidate_ids and not fids:
            raise HTTPException(status_code=422,
                                detail="rule_keys/candidate_ids/fids at least one required")
        scope = body.get("scope") or {}
        payload = {"rule_keys": rule_keys, "candidate_ids": candidate_ids,
                   "fids": fids}
        run_id = new_id()
        with session_factory() as session:
            run = RunRow(
                id=run_id, run_revision=1,
                patient_id="TRIAL", visit_number=f"TRIAL-{run_id[:8]}",
                trigger_type=TRIGGER_TRIAL, trigger_id="",
                is_trial=1, status=RUN_REQUESTED,
                trial_rules_json=json.dumps(payload, ensure_ascii=False),
                trial_scope_json=json.dumps(scope, ensure_ascii=False),
                requested_by=actor.id,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
        _audit(repository, action="trial_create", rule_key=f"trial:{run_id}",
               actor_id=actor.id, actor_name=actor.name,
               reason=str(body.get("reason") or ""),
               request_id=_request_id(request),
               detail={"rule_keys": rule_keys, "candidate_ids": candidate_ids,
                       "fids": fids, "scope": scope})
        return {"trial_run_id": run_id, "status": run.status,
                "trigger_type": run.trigger_type, "payload": payload,
                "scope": scope,
                "note": "requested; execution wired in T1b"}

    @router.get("/trial/runs", summary="试运行申请列表")
    def list_trial_runs(request: Request, status: str = "", limit: int = 50):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_VIEW)
        from sqlalchemy import select
        with session_factory() as session:
            stmt = select(RunRow).where(RunRow.is_trial == 1)
            if status:
                stmt = stmt.where(RunRow.status == status)
            rows = session.execute(stmt.order_by(
                RunRow.created_at.desc()).limit(min(limit, 200))).scalars().all()
        return {"items": [{
            "run_id": r.id, "status": r.status, "trigger_type": r.trigger_type,
            "requested_by": r.requested_by,
            "created_at": r.created_at.isoformat(timespec="seconds")
            if r.created_at else None,
            "trial_rules": json.loads(r.trial_rules_json or "{}"),
            "trial_scope": json.loads(r.trial_scope_json or "{}"),
        } for r in rows]}

    # ---- T5：就诊核查工作台（checks / issues） ----

    @router.get("/checks", summary="核查列表（run 聚合：缺陷/unknown/复检/投递；分页）")
    def list_checks(request: Request, dept_code: str = "", patient_id: str = "",
                    visit_number: str = "", trigger_type: str = "",
                    is_trial: int = 0, page: int = 1,
                    page_size: int | None = None, limit: int | None = None):
        """048 T2：page/page_size 分页（与旧 limit 同时显式传入时 page_size 优先）。

        旧调用只传 limit → 兼容为单页大小；total=全部筛选后的匹配 run 数
        （非本页条数）；排序 created_at+id 稳定。非法参数 422，不 500。
        """
        from .issue_service import (
            CHECKS_DEFAULT_PAGE_SIZE,
            CHECKS_MAX_PAGE_SIZE,
            browse_check_runs,
        )
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_CHECK_VIEW)
        if is_trial not in (0, 1):
            raise HTTPException(status_code=422,
                                detail="is_trial must be 0 or 1")
        if page < 1:
            raise HTTPException(status_code=422, detail="page must be >= 1")
        effective_size = (page_size if page_size is not None
                          else (limit if limit is not None
                                else CHECKS_DEFAULT_PAGE_SIZE))
        if not 1 <= effective_size <= CHECKS_MAX_PAGE_SIZE:
            raise HTTPException(
                status_code=422,
                detail=f"page_size must be in [1, {CHECKS_MAX_PAGE_SIZE}]")
        if limit is not None and not 1 <= limit <= CHECKS_MAX_PAGE_SIZE:
            raise HTTPException(
                status_code=422,
                detail=f"limit must be in [1, {CHECKS_MAX_PAGE_SIZE}]")
        runs, total, issue_counts = browse_check_runs(
            session_factory, dept_code=dept_code, patient_id=patient_id,
            visit_number=visit_number, trigger_type=trigger_type,
            is_trial=is_trial, page=page, page_size=effective_size)
        items = []
        for run in runs:
            summary = json.loads(run.summary_json or "{}")
            counts = issue_counts.get((run.patient_id, run.visit_number), {})
            items.append({
                "run_id": run.id, "run_revision": run.run_revision,
                "patient_id": run.patient_id, "visit_number": run.visit_number,
                "dept_code": run.dept_code, "dept_name": run.dept_name,
                "trigger_type": run.trigger_type, "status": run.status,
                "checked_at": run.checked_at.isoformat(timespec="seconds")
                if run.checked_at else None,
                "ruleset_revision": run.ruleset_revision,
                "origin": "paperless_rule",
                "summary": {
                    "fail_count": summary.get("fail_count", 0),
                    "unknown_count": summary.get("unknown_count", 0),
                    "pending_count": summary.get("pending_count", 0),
                    "status": summary.get("status"),
                },
                "open_issues": counts.get("open", 0),
                "rectifying_issues": counts.get("rectifying", 0),
                "resolved_issues": counts.get("resolved", 0),
            })
        return {"items": items, "total": total, "page": int(page),
                "page_size": int(effective_size)}

    @router.get("/checks/{run_id}", summary="核查详情（条款→依据→缺陷→人工状态）")
    def get_check(run_id: str, request: Request,
                  enforce_dept_code: str = ""):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_CHECK_VIEW)
        from .closed_loop_models import IssueRow, RuleEvalRow, RunRow
        from sqlalchemy import select as _select
        with session_factory() as session:
            run = session.get(RunRow, run_id)
            if run is None:
                raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
            # 048 T2：BFF 委托的科室范围强制（空=不限制；非空必须精确匹配）
            if enforce_dept_code and run.dept_code != enforce_dept_code:
                raise HTTPException(status_code=403,
                                    detail="dept scope denied for this run")
            evals = session.execute(_select(RuleEvalRow).where(
                RuleEvalRow.run_id == run_id).order_by(
                RuleEvalRow.rule_id)).scalars().all()
            issues = session.execute(_select(IssueRow).where(
                IssueRow.patient_id == run.patient_id,
                IssueRow.visit_number == run.visit_number)).scalars().all()
        issue_by_rule = {(i.rule_id, i.event_instance_id): i for i in issues}
        clauses = []
        for ev in evals:
            issue = issue_by_rule.get((ev.rule_id, ev.event_instance_id))
            clauses.append({
                "rule_id": ev.rule_id, "rule_version": ev.rule_version,
                "fid": ev.fid, "clause_id": ev.clause_id,
                "event_instance_id": ev.event_instance_id,
                "status": ev.status, "reason_code": ev.reason_code,
                "exclusion_reason": ev.exclusion_reason,
                "evidence": json.loads(ev.evidence_json or "{}"),
                "deadline": ev.deadline_at.isoformat(timespec="seconds")
                if ev.deadline_at else None,
                "issue": _issue_dict(issue) if issue is not None else None,
            })
        return {
            "run_id": run.id, "run_revision": run.run_revision,
            "patient_id": run.patient_id, "visit_number": run.visit_number,
            "dept_code": run.dept_code, "dept_name": run.dept_name,
            "trigger_type": run.trigger_type, "status": run.status,
            "checked_at": run.checked_at.isoformat(timespec="seconds")
            if run.checked_at else None,
            "data_snapshot_at": run.data_snapshot_at.isoformat(timespec="seconds")
            if run.data_snapshot_at else None,
            "ruleset_revision": run.ruleset_revision,
            "ruleset_hash": run.ruleset_hash,
            "summary": json.loads(run.summary_json or "{}"),
            "source_health": json.loads(run.source_health_json or "{}"),
            "clauses": clauses,
        }

    @router.get("/issues", summary="缺陷实例列表（人工状态分离）")
    def list_issues(request: Request, patient_id: str = "",
                    visit_number: str = "", dept_code: str = "",
                    status: str = "", limit: int = 200):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_CHECK_VIEW)
        from .issue_service import IssueService
        service = IssueService(session_factory)
        rows = service.list_issues(patient_id=patient_id,
                                   visit_number=visit_number,
                                   dept_code=dept_code, status=status,
                                   limit=limit)
        return {"items": [_issue_dict(r) for r in rows]}

    @router.get("/issues/{issue_id}", summary="缺陷详情（含人工动作历史）")
    def get_issue(issue_id: str, request: Request,
                  enforce_dept_code: str = ""):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_CHECK_VIEW)
        from .issue_service import IssueService
        service = IssueService(session_factory)
        row = service.get_issue(issue_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"issue not found: {issue_id}")
        if enforce_dept_code and row.dept_code != enforce_dept_code:
            raise HTTPException(status_code=403,
                                detail="dept scope denied for this issue")
        return {**_issue_dict(row),
                "actions": [{
                    "action": a.action, "status_from": a.status_from,
                    "status_to": a.status_to, "reason": a.reason,
                    "operator_id": a.operator_id,
                    "operator_name": a.operator_name,
                    "issue_version": a.issue_version,
                    "document_revision": a.document_revision,
                    "created_at": a.created_at.isoformat(timespec="seconds")
                    if a.created_at else None,
                } for a in service.list_actions(issue_id)]}

    @router.post("/issues/{issue_id}/actions", summary="人工动作（看过/整改/误报/关闭/复检通过）")
    def issue_action(issue_id: str, request: Request, body: dict):
        actor = _mount_actor(request, admin_cfg)
        # 医生反馈（feedback）与质控复核（review）任一权限即可；终态动作需 review
        if not (actor.has(PERM_ISSUE_FEEDBACK) or actor.has(PERM_ISSUE_REVIEW)):
            raise HTTPException(status_code=403,
                                detail="permission denied: issue feedback/review")
        action = str(body.get("action") or "")
        terminal = action in ("false_positive", "manual_closed", "recheck_passed")
        if terminal and not (actor.has(PERM_ISSUE_REVIEW) or actor.has("*")):
            raise HTTPException(status_code=403,
                                detail="terminal issue actions require "
                                       "prearchive_issue_review")
        from .issue_service import IssueConflictError, IssueService
        service = IssueService(session_factory)
        # 048 T2：BFF 委托的科室范围强制（与动作同一事务判定，先查后写）
        enforce_dept = str(body.get("enforce_dept_code") or "")
        if enforce_dept:
            target = service.get_issue(issue_id)
            if target is None:
                raise HTTPException(status_code=404,
                                    detail=f"issue not found: {issue_id}")
            if target.dept_code != enforce_dept:
                raise HTTPException(status_code=403,
                                    detail="dept scope denied for this issue")
        try:
            row = service.apply_action(
                issue_id, action=action, operator=actor,
                reason=str(body.get("reason") or ""),
                expect_issue_version=int(body.get("expect_issue_version") or 0),
                document_revision=str(body.get("document_revision") or ""))
        except IssueConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        _audit(repository, action="issue_action",
               rule_key=f"issue:{issue_id}", actor_id=actor.id,
               actor_name=actor.name, reason=str(body.get("reason") or ""),
               request_id=_request_id(request),
               detail={"action": action, "status_to": row.status})
        return _issue_dict(row)

    def _issue_dict(row) -> dict:
        return {
            "issue_id": row.id, "issue_key": row.issue_key,
            "patient_id": row.patient_id, "visit_number": row.visit_number,
            "dept_code": row.dept_code, "fid": row.fid,
            "clause_id": row.clause_id, "rule_id": row.rule_id,
            "rule_version": row.rule_version,
            "event_instance_id": row.event_instance_id,
            "severity": row.severity, "message": row.message,
            "status": row.status, "version": int(row.version or 1),
            "first_seen_at": row.first_seen_at.isoformat(timespec="seconds")
            if row.first_seen_at else None,
            "last_seen_at": row.last_seen_at.isoformat(timespec="seconds")
            if row.last_seen_at else None,
            "resolved_run_id": row.resolved_run_id,
            "document_refs": json.loads(row.document_refs_json or "[]"),
        }

    # ---- T1b：trial 执行 / 观察 / 反馈 ----

    @router.post("/trial/runs/{trial_run_id}/execute", summary="执行试运行（demo fixtures，隔离）")
    def execute_trial_run(trial_run_id: str, request: Request):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_TRIAL)
        from .trial_service import TrialService
        service = TrialService(session_factory)
        if service.get_run(trial_run_id) is None:
            raise HTTPException(status_code=404, detail=f"trial not found: {trial_run_id}")
        try:
            builder = _fixture_context_builder()
            result = service.execute(trial_run_id, context_builder=builder)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        _audit(repository, action="trial_execute",
               rule_key=f"trial:{trial_run_id}", actor_id=actor.id,
               actor_name=actor.name, request_id=_request_id(request),
               detail={"patients": result["patients"],
                       "status": result["status"]})
        return result

    @router.get("/trial/runs/{trial_run_id}/observations", summary="试运行观察数据（API 级）")
    def trial_observations(trial_run_id: str, request: Request):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_VIEW)
        from .trial_service import TrialService
        service = TrialService(session_factory)
        run = service.get_run(trial_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"trial not found: {trial_run_id}")
        return service.observations(trial_run_id)

    @router.post("/trial/runs/{trial_run_id}/feedback", summary="试运行人工反馈（确认缺陷/误报/待核实）")
    def trial_feedback(trial_run_id: str, request: Request, body: dict):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_MATCH)
        from .trial_service import TrialService
        service = TrialService(session_factory)
        run = service.get_run(trial_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"trial not found: {trial_run_id}")
        try:
            row = service.add_feedback(
                trial_run_id,
                rule_id=str(body.get("rule_id") or ""),
                event_instance_id=str(body.get("event_instance_id") or ""),
                verdict=str(body.get("verdict") or ""),
                operator=actor, note=str(body.get("note") or ""),
                fid=body.get("fid"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"ok": True, "feedback_id": row.id, "verdict": row.verdict}

    def _fixture_context_builder():
        """本地授权的合成执行通道：demo fixtures（零真实库）。"""
        from .collectors import (
            HisCollector,
            ItfSourceCollector,
            JhemrCollector,
            LisCollector,
            PatientContextBuilder,
            SmCollector,
        )
        from .fixture_sources import build_demo_fixtures
        fixtures = build_demo_fixtures()
        return PatientContextBuilder(
            jhemr=JhemrCollector(fixtures["jhemr"]),
            his=HisCollector(fixtures["his"]),
            sm=SmCollector(fixtures["sm"]),
            lis=LisCollector(fixtures["lis"]),
        )

    # ---- helpers ----

    def _build_http_model(model_name: str, model_config: dict):
        from .match_service import HttpMatchModel
        import os
        base_url = model_config.get("base_url") or os.environ.get(
            "PREARCHIVE_MATCH_BASE_URL", "")
        api_key = model_config.get("api_key") or os.environ.get(
            "PREARCHIVE_MATCH_API_KEY", "")
        model = model_config.get("model") or model_name
        if not base_url or not api_key:
            raise HTTPException(
                status_code=503,
                detail="match model channel not configured "
                       "(PREARCHIVE_MATCH_BASE_URL/API_KEY)")
        return HttpMatchModel(base_url, api_key, model)

    def _task_dict(task) -> dict:
        return {
            "task_id": task.id, "status": task.status,
            "fids": json.loads(task.fid_filter_json or "[]"),
            "input_hash": task.input_hash,
            "model": task.model_name, "prompt_version": task.prompt_version,
            "progress_done": task.progress_done,
            "progress_total": task.progress_total,
            "failed_fids": json.loads(task.failed_fids_json or "[]"),
            "duration_ms": task.duration_ms, "attempts": task.attempts,
            "created_by": task.created_by,
            "created_at": task.created_at.isoformat(timespec="seconds")
            if task.created_at else None,
        }

    def _candidate_dict(c) -> dict:
        return {
            "candidate_id": c.id, "task_id": c.task_id, "fid": c.fid,
            "clause_id": c.clause_id,
            "matched_rule_ids": json.loads(c.matched_rule_ids_json or "[]"),
            "suggested_dsl": json.loads(c.suggested_dsl_json or "{}"),
            "field_refs": json.loads(c.field_refs_json or "[]"),
            "covered_clauses": c.covered_clauses,
            "uncovered_clauses": c.uncovered_clauses,
            "rationale": c.rationale, "confidence": c.confidence,
            "blocking_reasons": json.loads(c.blocking_reasons_json or "[]"),
            "validation_ok": bool(c.validation_ok),
            "validation_errors": json.loads(c.validation_errors_json or "[]"),
            "decision": c.decision, "decided_by": c.decided_by,
            "decided_at": c.decided_at.isoformat(timespec="seconds")
            if c.decided_at else None,
            "exact_match": bool(c.exact_match),
        }

    return router
