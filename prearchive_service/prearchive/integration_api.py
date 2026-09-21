# -*- coding: utf-8 -*-
"""046 T7 JHEMR 集成内部 API（服务端五接口的预检侧承载）。

外部形态=主服务 `/api/integrations/jhemr/*`（JHEMR 签名认证+就诊授权+BFF 白名单）；
本模块是预检侧内部目标 `/api/integration/jhemr/*`（admin token + actor 签名，
与 closed_loop_api 同口径）。检查执行**复用 PrecheckProcessor 主链路**：
RUN(trigger=emr_submit/manual_recheck) → RULE_EVAL → RESULT upsert → ISSUE 物化 →
投递事件（治理），不复制引擎、不旁路 T2 五态语义。

契约要点（046 §T7/§T7.1）：
- POST submission-checks：幂等（同 submission_id 未终态→返回既有 check）；
  202+check_id，不同步等待采集；GET 才是查询面；
- GET submission-checks/{check_id}：完整 T7.1 汇总 schema；queued/running 未定
  计数 null + provisional=true（不用全 0 伪装检查完毕）；submission_policy=notify_only；
- view-tickets：nonce 一次性短期票据（过期/重放拒绝）；
- issues/{id}/feedback：复用 IssueService（幂等+乐观版本；「已整改」不直接改判通过）；
- rechecks：原锚点未变也生成新 run revision，返回 check_id。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .closed_loop_models import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PARTIAL,
    RUN_QUEUED,
    TRIGGER_EMR_SUBMIT,
    TRIGGER_MANUAL_RECHECK,
    IssueRow,
    RunRow,
    ViewTicketRow,
)
from .closed_loop_api import _mount_actor, _require, PERM_CHECK_VIEW, PERM_ISSUE_FEEDBACK
from .rule_models import new_id

logger = logging.getLogger("prearchive.integration")

# 终态集合（queued/running 为执行中；failed 允许重试创建新检查）
RUN_TERMINAL = (RUN_COMPLETED, RUN_PARTIAL, RUN_FAILED)

DEFAULT_TICKET_TTL_SECONDS = 300
MAX_TICKET_TTL_SECONDS = 900

# 集成服务账号最小权限集（主服务 JHEMR 签名路由构造 actor 时使用；
# 不把预检管理权限授给普通医生——046 §T7.1）
JHEMR_INTEGRATION_PERMS = (PERM_CHECK_VIEW, PERM_ISSUE_FEEDBACK)


def _iso(value) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def _placeholder_run(session_factory, *, trigger_type: str, patient_id: str,
                     visit_number: str, dept_code: str, dept_name: str,
                     requested_by: str, submission_id: str) -> RunRow:
    from .eval_store import EvalRunStore
    revision = EvalRunStore(session_factory).next_revision(patient_id, visit_number)
    with session_factory() as session:
        run = RunRow(
            id=new_id(), run_revision=revision,
            patient_id=patient_id, visit_number=visit_number,
            dept_code=dept_code, dept_name=dept_name,
            trigger_type=trigger_type, submission_id=submission_id,
            status=RUN_QUEUED, requested_by=requested_by)
        session.add(run)
        session.commit()
        session.refresh(run)
        return run


def _visit_for(processor, patient_id: str, visit_number: str):
    """锚点源 → FinishedVisit（集成入口复用主链路采集，不另建查询）。"""
    from .context import FinishedVisit, parse_datetime
    collector = getattr(processor.context_builder, "jhemr", None)
    if collector is None:
        raise HTTPException(status_code=503,
                            detail="anchor collector unavailable")
    gateway = getattr(collector, "gateway", collector)
    row = gateway.fetch_pat_visit(patient_id, str(visit_number))
    if not row:
        raise HTTPException(status_code=404,
                            detail=f"patient/visit not found: "
                                   f"{patient_id}/{visit_number}")
    finished = parse_datetime(row.get("finished_date_time"))
    if finished is None:
        raise HTTPException(status_code=422,
                            detail="anchor source lacks finished_date_time")
    return FinishedVisit(
        patient_id=str(row.get("patient_id") or patient_id),
        visit_id=str(row.get("visit_id") or visit_number),
        finished_date_time=finished,
        visit_number=str(row.get("visit_number") or visit_number),
        patient_name=str(row.get("patient_name") or ""),
        dept_code=str(row.get("dept_code") or ""),
        dept_name=str(row.get("dept_name") or ""))


def _execute_check(processor, run_id: str) -> None:
    """后台执行（BackgroundTasks）：queued → 主链路接管 → completed/partial/failed。"""
    from .closed_loop_models import RUN_FAILED
    try:
        with processor.eval_store.session_factory() as session:
            run = session.get(RunRow, run_id)
            if run is None:
                return
            patient_id, visit_number = run.patient_id, run.visit_number
            trigger_type = run.trigger_type
        visit = _visit_for(processor, patient_id, visit_number)
        processor.process(visit, trigger_type=trigger_type, run_id=run_id)
    except HTTPException as exc:
        detail = str(exc.detail)[:500]
        processor.eval_store.finish_run(run_id, RUN_FAILED, {}, {},
                                        status_detail=detail)
        logger.warning("[integration] check %s failed: %s", run_id, detail)
    except Exception as exc:  # noqa: BLE001 —— 集成检查失败落 failed，不杀进程
        processor.eval_store.finish_run(run_id, RUN_FAILED, {}, {},
                                        status_detail=str(exc)[:500])
        logger.exception("[integration] check %s crashed", run_id)


def _provisional_summary(status: str) -> dict:
    """queued/running：未定计数一律 null + provisional（046 §T7.1，不用全 0 伪装）。"""
    return {
        "schema_version": "2.0.0",
        "catalog_count": None, "mapped_catalog_count": None,
        "rule_instance_count": None, "applicable_count": None,
        "evaluated_count": None, "pass_count": None, "fail_count": None,
        "unknown_count": None, "pending_count": None,
        "excluded_count": None, "exclusion_reasons": None,
        "issue_count": None, "evaluation_coverage_pct": None,
        "required_source_checks": None, "ready_source_checks": None,
        "data_coverage_pct": None,
        "status": status, "provisional": True, "freshness": "unknown",
    }


def _check_view(session_factory, run: RunRow) -> dict:
    """RunRow → T7.1 GET schema（完整汇总/issue 引用/源健康/notify_only）。"""
    provisional = run.status in (RUN_QUEUED, "running")
    summary = (_provisional_summary(run.status) if provisional
               else json.loads(run.summary_json or "{}"))
    if not provisional:
        summary.setdefault("provisional", False)
        summary.setdefault("freshness", "unknown")
    issues = None
    if not provisional:
        with session_factory() as session:
            rows = session.execute(select(IssueRow).where(
                IssueRow.patient_id == run.patient_id,
                IssueRow.visit_number == run.visit_number,
                IssueRow.is_trial == 0)).scalars().all()
        issues = [{
            "issue_id": row.id, "issue_key": row.issue_key,
            "rule_id": row.rule_id, "fid": row.fid,
            "clause_id": row.clause_id,
            "event_instance_id": row.event_instance_id,
            "severity": row.severity, "message": row.message,
            "status": row.status, "issue_version": int(row.version or 1),
            "document_refs": json.loads(row.document_refs_json or "[]"),
            "resolved_run_id": row.resolved_run_id,
        } for row in rows]
    return {
        "schema_version": "2.0.0",
        "check_id": run.id, "run_id": run.id,
        "run_revision": run.run_revision,
        "subject": {
            "patient_id": run.patient_id, "visit_number": run.visit_number,
            "dept_code": run.dept_code, "encounter_type": "inpatient",
        },
        "trigger_type": run.trigger_type,
        "trigger_id": run.trigger_id,
        "submission_id": run.submission_id,
        "checked_at": _iso(run.checked_at),
        "data_snapshot_at": _iso(run.data_snapshot_at),
        "ruleset_revision": run.ruleset_revision,
        "summary": summary,
        "issues": issues,
        "source_health": (None if provisional
                          else json.loads(run.source_health_json or "{}")),
        "submission_policy": "notify_only",
        "status": run.status,
        "status_detail": run.status_detail or "",
    }


def create_integration_router(config: dict, session_factory,
                              repository, processor) -> APIRouter:
    router = APIRouter(prefix="/api/integration/jhemr",
                       tags=["prearchive-jhemr-integration"])
    admin_cfg = (config or {}).get("admin_api") or {}
    integration_cfg = (config or {}).get("jhemr_integration") or {}
    ticket_ttl = int(integration_cfg.get("ticket_ttl_seconds")
                     or DEFAULT_TICKET_TTL_SECONDS)

    def _audit(**kwargs) -> None:
        repository.append_audit(**kwargs)

    def _actor_headers_note(actor) -> str:
        return f"operator={actor.id}"

    # ---- 1) POST /submission-checks（幂等创建，202+check_id） ----

    @router.post("/submission-checks", status_code=202,
                summary="JHEMR 提交检查（幂等创建检查任务）")
    def create_submission_check(request: Request, body: dict,
                                background: BackgroundTasks):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_CHECK_VIEW)
        patient_id = str(body.get("patient_id") or "").strip()
        visit_number = str(body.get("visit_number") or "").strip()
        submission_id = str(body.get("submission_id") or "").strip()
        operator = body.get("operator") or {}
        if not patient_id or not visit_number:
            raise HTTPException(status_code=422,
                                detail="patient_id and visit_number required")
        if not submission_id:
            raise HTTPException(status_code=422,
                                detail="submission_id required for idempotency")
        # 幂等：同 submission_id 的既有检查直接返回（有同快照有效结果可返回，
        # 046 §T7；仅 failed 允许重试创建新检查）
        with session_factory() as session:
            existing = session.execute(select(RunRow).where(
                RunRow.submission_id == submission_id,
                RunRow.trigger_type == TRIGGER_EMR_SUBMIT,
                RunRow.status != RUN_FAILED)
            ).scalar_one_or_none()
            if existing is not None:
                return JSONResponse(status_code=200, content={
                    "check_id": existing.id, "run_id": existing.id,
                    "status": existing.status,
                    "submission_policy": "notify_only",
                    "reused": True})
        # 患者必须真实存在于锚点源（早期 404，不制造空 run）
        _visit_for(processor, patient_id, visit_number)
        run = _placeholder_run(
            session_factory, trigger_type=TRIGGER_EMR_SUBMIT,
            patient_id=patient_id, visit_number=visit_number,
            dept_code=str(body.get("dept_code") or ""),
            dept_name=str(body.get("dept_name") or ""),
            requested_by=str(operator.get("id") or actor.id),
            submission_id=submission_id)
        background.add_task(_execute_check, processor, run.id)
        _audit(action="jhemr_submission_check", rule_key=f"run:{run.id}",
               actor_id=actor.id, actor_name=actor.name,
               detail={"patient_id": patient_id, "visit_number": visit_number,
                       "submission_id": submission_id,
                       "operator_id": str(operator.get("id") or ""),
                       "request_id": str(body.get("request_id") or "")})
        return JSONResponse(status_code=202, content={
            "check_id": run.id, "run_id": run.id, "status": run.status,
            "submission_policy": "notify_only", "reused": False})

    # ---- 2) GET /submission-checks/{check_id}（T7.1 完整汇总） ----

    @router.get("/submission-checks/{check_id}",
                summary="检查结果查询（T7.1 完整 schema；queued/running=null+provisional）")
    def get_submission_check(check_id: str, request: Request):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_CHECK_VIEW)
        with session_factory() as session:
            run = session.get(RunRow, check_id)
        if run is None:
            raise HTTPException(status_code=404,
                                detail=f"check not found: {check_id}")
        return _check_view(session_factory, run)

    # ---- 3) POST /view-tickets（nonce 一次性短期票据） ----

    @router.post("/view-tickets", summary="换取短期一次性详情票据")
    def create_view_ticket(request: Request, body: dict):
        import uuid
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_CHECK_VIEW)
        patient_id = str(body.get("patient_id") or "").strip()
        visit_number = str(body.get("visit_number") or "").strip()
        operator_id = str(body.get("operator_id") or "").strip()
        if not patient_id or not visit_number or not operator_id:
            raise HTTPException(status_code=422,
                                detail="patient_id/visit_number/operator_id required")
        scope = str(body.get("scope") or "issue_view")[:64]
        ttl = min(int(body.get("ttl_seconds") or ticket_ttl),
                  MAX_TICKET_TTL_SECONDS)
        nonce = uuid.uuid4().hex
        expires_at = datetime.now() + timedelta(seconds=max(ttl, 30))
        with session_factory() as session:
            session.add(ViewTicketRow(
                id=new_id(), nonce=nonce, patient_id=patient_id,
                visit_number=visit_number, operator_id=operator_id,
                dept_code=str(body.get("dept_code") or ""), scope=scope,
                expires_at=expires_at, issued_by=actor.id))
            session.commit()
        _audit(action="view_ticket_issue", rule_key=f"ticket:{nonce[:12]}",
               actor_id=actor.id, actor_name=actor.name,
               detail={"patient_id": patient_id, "visit_number": visit_number,
                       "operator_id": operator_id, "scope": scope,
                       "ttl_seconds": ttl})
        return {"ticket_nonce": nonce, "scope": scope,
                "expires_at": _iso(expires_at),
                "note": "one-time; redeem via "
                        "/api/integration/jhemr/view-tickets/{nonce}/redeem"}

    @router.post("/view-tickets/{nonce}/redeem", summary="核销票据（一次性；过期/重放拒绝）")
    def redeem_view_ticket(nonce: str, request: Request, body: dict):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_CHECK_VIEW)
        with session_factory() as session:
            row = session.execute(select(ViewTicketRow).where(
                ViewTicketRow.nonce == nonce)).scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="ticket not found")
            if row.used_at is not None:
                raise HTTPException(status_code=409,
                                    detail="ticket already redeemed")
            if row.expires_at < datetime.now():
                raise HTTPException(status_code=403, detail="ticket expired")
            operator_id = str(body.get("operator_id") or "")
            if operator_id and operator_id != row.operator_id:
                raise HTTPException(status_code=403,
                                    detail="ticket bound to another operator")
            row.used_at = datetime.now()
            session.commit()
        _audit(action="view_ticket_redeem", rule_key=f"ticket:{nonce[:12]}",
               actor_id=actor.id, actor_name=actor.name,
               detail={"patient_id": row.patient_id,
                       "operator_id": row.operator_id})
        return {"patient_id": row.patient_id, "visit_number": row.visit_number,
                "operator_id": row.operator_id, "dept_code": row.dept_code,
                "scope": row.scope}

    # ---- 4) POST /issues/{issue_id}/feedback（幂等+版本；不改判机器结论） ----

    @router.post("/issues/{issue_id}/feedback",
                 summary="医生反馈（看过/已整改/误报/说明；乐观版本）")
    def issue_feedback(issue_id: str, request: Request, body: dict):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_ISSUE_FEEDBACK)
        from .issue_service import IssueConflictError, IssueService
        from .rule_service import Actor
        operator_body = body.get("operator") or {}
        operator = Actor(id=str(operator_body.get("id") or actor.id),
                         name=str(operator_body.get("name") or actor.name))
        service = IssueService(session_factory)
        try:
            row = service.apply_action(
                issue_id, action=str(body.get("action") or ""),
                operator=operator,
                reason=str(body.get("reason") or ""),
                expect_issue_version=int(body.get("expect_issue_version") or 0),
                document_revision=str(body.get("document_revision") or ""))
        except IssueConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        _audit(action="jhemr_issue_feedback", rule_key=f"issue:{issue_id}",
               actor_id=operator.id, actor_name=operator.name,
               reason=str(body.get("reason") or ""),
               detail={"action": str(body.get("action") or ""),
                       "status_to": row.status,
                       "note": _actor_headers_note(operator)})
        return {"issue_id": row.id, "status": row.status,
                "issue_version": int(row.version or 1),
                "resolved_run_id": row.resolved_run_id}

    # ---- 5) POST /rechecks（原锚点未变也生成新 revision） ----

    @router.post("/rechecks", status_code=202,
                summary="整改后复检（同锚点也生成新 run revision）")
    def create_recheck(request: Request, body: dict, background: BackgroundTasks):
        actor = _mount_actor(request, admin_cfg)
        _require(actor, PERM_CHECK_VIEW)
        patient_id = str(body.get("patient_id") or "").strip()
        visit_number = str(body.get("visit_number") or "").strip()
        operator = body.get("operator") or {}
        if not patient_id or not visit_number:
            raise HTTPException(status_code=422,
                                detail="patient_id and visit_number required")
        visit = _visit_for(processor, patient_id, visit_number)
        run = _placeholder_run(
            session_factory, trigger_type=TRIGGER_MANUAL_RECHECK,
            patient_id=patient_id, visit_number=visit_number,
            dept_code=visit.dept_code, dept_name=visit.dept_name,
            requested_by=str(operator.get("id") or actor.id),
            submission_id="")
        background.add_task(_execute_check, processor, run.id)
        _audit(action="recheck_request", rule_key=f"run:{run.id}",
               actor_id=actor.id, actor_name=actor.name,
               reason=str(body.get("reason") or ""),
               detail={"patient_id": patient_id, "visit_number": visit_number,
                       "operator_id": str(operator.get("id") or ""),
                       "issue_ids": body.get("issue_ids") or []})
        return JSONResponse(status_code=202, content={
            "check_id": run.id, "run_id": run.id, "status": run.status,
            "submission_policy": "notify_only"})

    return router
