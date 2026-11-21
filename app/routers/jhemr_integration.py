"""JHEMR 集成外部路由（046 T7）：/api/integrations/jhemr/*。

- 认证=JHEMR 服务端 HMAC 签名（X-Jhemr-* 四件套）：绑定 client_id、method、
  path、请求体 sha256、timestamp、nonce；限时钟偏差（默认 ±300s）+ nonce 重放
  拒绝（进程内缓存，TTL=2×偏差窗）。**不是**用户 JWT——医生身份由请求体
  operator 携带并全程审计（服务账号身份≠医生就诊权限，046 §T7.1）。
- 就诊授权：签名可信的 JHEMR 服务端才可查询/复检其正在提交的就诊；详情页
  访问必须走一次性票据（view-tickets），nonce 绑定 patient+visit+operator。
- 转发：仅经 BFF 白名单目标（/api/integration/jhemr/*，见
  prearchive_admin_client.ALLOWED_TARGETS）；actor=集成服务账号（最小权限集，
  不携带预检管理权限）。
- 开关：JHEMR_INTEGRATION_ENABLED（默认 false→503，零网络）；凭据走
  JHEMR_INTEGRATION_CLIENT_ID / JHEMR_INTEGRATION_HMAC_SECRET 环境变量。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import uuid
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, defer as orm_defer

from app.database import get_db
from app.services.prearchive_admin_client import (
    PrearchiveAdminClient,
    PrearchiveAdminDisabled,
    PrearchiveAdminUnavailable,
)

logger = logging.getLogger(__name__)
router = APIRouter()

ENV_ENABLED = "JHEMR_INTEGRATION_ENABLED"
ENV_CLIENT_ID = "JHEMR_INTEGRATION_CLIENT_ID"
ENV_SECRET = "JHEMR_INTEGRATION_HMAC_SECRET"

CLOCK_SKEW_SECONDS = 300
CLIENT_ID_HEADER = "X-Jhemr-Client-Id"
TIMESTAMP_HEADER = "X-Jhemr-Timestamp"
NONCE_HEADER = "X-Jhemr-Nonce"
SIGNATURE_HEADER = "X-Jhemr-Signature"

# 集成服务账号最小权限（与预检侧 integration_api 要求一致；不含管理权限）
JHEMR_SERVICE_ACTOR_ID = "jhemr-integration"
JHEMR_SERVICE_PERMS = ("prearchive_check_view", "prearchive_issue_feedback")

# nonce 重放缓存（单进程；TTL=2×偏差窗后清理）
_seen_nonces: dict[str, float] = {}


def _prune_nonces(now: float) -> None:
    horizon = now - CLOCK_SKEW_SECONDS * 2
    if len(_seen_nonces) > 10000:   # 防御性上限
        for nonce, ts in list(_seen_nonces.items()):
            if ts < horizon:
                _seen_nonces.pop(nonce, None)


def build_signature(secret: str, client_id: str, method: str, path: str,
                    body: bytes, timestamp: str, nonce: str) -> str:
    """共用签名（046 §T7.1）：绑定方法/路径/体哈希/时间戳/nonce/目标系统。"""
    body_hash = hashlib.sha256(body or b"").hexdigest()
    message = "\n".join([client_id, method.upper(), path, body_hash,
                         timestamp, nonce])
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _verify_request(request: Request, body: bytes) -> None:
    enabled = str(os.environ.get(ENV_ENABLED, "false")).strip().lower() \
        in ("1", "true", "yes", "on")
    if not enabled:
        raise HTTPException(status_code=503,
                            detail="jhemr integration is disabled")
    expected_client = os.environ.get(ENV_CLIENT_ID, "")
    secret = os.environ.get(ENV_SECRET, "")
    if not expected_client or not secret:
        raise HTTPException(status_code=503,
                            detail="jhemr integration not configured")

    client_id = request.headers.get(CLIENT_ID_HEADER, "")
    timestamp = request.headers.get(TIMESTAMP_HEADER, "")
    nonce = request.headers.get(NONCE_HEADER, "")
    signature = request.headers.get(SIGNATURE_HEADER, "")
    if not all((client_id, timestamp, nonce, signature)):
        raise HTTPException(status_code=401,
                            detail="missing jhemr signature headers")
    if not hmac.compare_digest(client_id, expected_client):
        raise HTTPException(status_code=401, detail="unknown jhemr client")
    try:
        ts = int(timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid timestamp")
    now = time.time()
    if abs(now - ts) > CLOCK_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="timestamp out of range")
    _prune_nonces(now)
    if nonce in _seen_nonces:
        raise HTTPException(status_code=401, detail="nonce replayed")
    expected = build_signature(secret, client_id, request.method,
                               request.url.path, body, timestamp, nonce)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="invalid signature")
    _seen_nonces[nonce] = now


def _proxy(method: str, path_template: str, *, params: dict | None = None,
           json_body: dict | None = None) -> JSONResponse:
    """集成服务账号经 BFF 白名单调用预检内部接口。"""
    actor = SimpleNamespace(id=JHEMR_SERVICE_ACTOR_ID,
                            username="JHEMR-Integration",
                            permissions=list(JHEMR_SERVICE_PERMS))
    try:
        result = PrearchiveAdminClient().call(
            method, path_template, actor, params=params, json_body=json_body)
    except PrearchiveAdminDisabled:
        raise HTTPException(status_code=503,
                            detail="prearchive admin BFF is disabled")
    except PrearchiveAdminUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return JSONResponse(status_code=result["status"], content=result["json"],
                        headers={"X-Bff-Request-Id": result["request_id"]})


@router.post("/integrations/jhemr/submission-checks",
             summary="JHEMR 提交病历检查（幂等创建检查任务，202+check_id）")
async def create_submission_check(request: Request):
    body = await request.body()
    _verify_request(request, body)
    payload = await request.json()
    forwarded = {
        "request_id": payload.get("request_id") or uuid.uuid4().hex,
        "patient_id": payload.get("patient_id"),
        "visit_number": payload.get("visit_number"),
        "operator": payload.get("operator") or {},
        "dept_code": payload.get("dept") or payload.get("dept_code") or "",
        "submission_id": payload.get("submission_id"),
        "document_refs": payload.get("document_refs") or [],
        "submitted_at": payload.get("submitted_at") or "",
    }
    return _proxy("POST", "/api/integration/jhemr/submission-checks",
                  json_body=forwarded)


@router.get("/integrations/jhemr/submission-checks/{check_id}",
            summary="检查结果查询（T7.1 完整汇总；未完成不返回假 pass）")
async def get_submission_check(check_id: str, request: Request):
    body = await request.body()
    _verify_request(request, body)
    return _proxy("GET", "/api/integration/jhemr/submission-checks/{check_id}",
                  params={"check_id": check_id})


@router.post("/integrations/jhemr/view-tickets",
             summary="换取短期一次性详情票据（nonce 绑定就诊+操作者）")
async def create_view_ticket(request: Request):
    body = await request.body()
    _verify_request(request, body)
    payload = await request.json()
    forwarded = {
        "patient_id": payload.get("patient_id"),
        "visit_number": payload.get("visit_number"),
        "operator_id": (payload.get("operator") or {}).get("id")
        or payload.get("operator_id"),
        "dept_code": payload.get("dept_code") or "",
        "scope": payload.get("scope") or "issue_view",
        "ttl_seconds": payload.get("ttl_seconds"),
    }
    return _proxy("POST", "/api/integration/jhemr/view-tickets",
                  json_body=forwarded)


@router.post("/integrations/jhemr/view-tickets/{nonce}/redeem",
             summary="核销一次性票据（过期/重放/换人拒绝）")
async def redeem_view_ticket(nonce: str, request: Request):
    body = await request.body()
    _verify_request(request, body)
    payload = await request.json()
    return _proxy("POST",
                  "/api/integration/jhemr/view-tickets/{nonce}/redeem",
                  params={"nonce": nonce},
                  json_body={"operator_id": payload.get("operator_id") or ""})


@router.post("/integrations/jhemr/issues/{issue_id}/feedback",
             summary="医生反馈（看过/已整改/误报/说明；幂等+版本）")
async def issue_feedback(issue_id: str, request: Request):
    body = await request.body()
    _verify_request(request, body)
    payload = await request.json()
    forwarded = {
        "action": payload.get("action"),
        "reason": payload.get("reason") or "",
        "expect_issue_version": payload.get("expect_issue_version") or 0,
        "document_revision": payload.get("document_revision") or "",
        "operator": payload.get("operator") or {},
    }
    return _proxy("POST", "/api/integration/jhemr/issues/{issue_id}/feedback",
                  params={"issue_id": issue_id}, json_body=forwarded)


@router.post("/integrations/jhemr/rechecks",
             summary="整改后复检（同锚点也生成新 revision；返回 check_id）")
async def create_recheck(request: Request):
    body = await request.body()
    _verify_request(request, body)
    payload = await request.json()
    forwarded = {
        "patient_id": payload.get("patient_id"),
        "visit_number": payload.get("visit_number"),
        "operator": payload.get("operator") or {},
        "reason": payload.get("reason") or "",
        "issue_ids": payload.get("issue_ids") or [],
    }
    return _proxy("POST", "/api/integration/jhemr/rechecks",
                  json_body=forwarded)


# ---- WP06（064 总计划）：AI 高危问题 JHEMR 提交前提醒（路线 B 主推） ----
#
# 路线 B（主推）：嘉和客户端在医生提交病历前调用本接口，拉取该患者未闭环的高危
# AI 内涵质控问题，在客户端弹窗提醒（block_submit=True 的规则可阻断提交）。
# 路线 A（兼容）：177 FILEVERIFY 受控写入（056 v4）——消费同一份
# `jhemr_reminder_policy` 策略（delivery_mode in ("fileverify_write", "both")），
# 后续启用写回时直接复用策略开关，无需改任何数据模型。
def _policy_supports_fileverify(policy: Any) -> bool:
    """路线 A（FILEVERIFY 写入）策略判定——与路线 B 共用同一份 jhemr_reminder_policy。"""
    return str(getattr(policy, "delivery_mode", "") or "") in ("fileverify_write", "both")


def _reminder_stage_matches(policy: Any, stage: str) -> bool:
    return str(getattr(policy, "trigger_stage", "") or "") == str(stage or "").strip()


_SEVERITY_LABELS = {"high": "高危", "medium": "中危", "low": "低危"}
_REMINDER_LOG_LIMIT = 20


@router.get(
    "/integrations/jhemr/ai-reminders",
    summary="JHEMR 提交病历前 AI 高危提醒拉取（路线 B；只读幂等，HMAC 鉴权）",
)
async def get_jhemr_ai_reminders(
    request: Request,
    patient_id: str = Query(..., min_length=1, description="患者ID（HIS 患者主索引号）"),
    visit_id: int | None = Query(None, description="住院次（可选，缺省=该患者全部住院次）"),
    doctor_code: str | None = Query(None, description="医生工号（可选，仅入审计日志）"),
    stage: str = Query("before_submit", description="触发阶段：before_submit/on_save/before_discharge"),
    db: Session = Depends(get_db),
):
    """嘉和客户端提交病历前拉取该患者未闭环 AI 高危提醒（严控 <100ms）。

    - 鉴权与总开关复用 _verify_request（JHEMR_INTEGRATION_ENABLED + HMAC 四件套）；
    - 二级开关 `jhemr_ai_reminder.enabled`（config.json 顶层，默认 false）：关闭时
      返回 200 + disabled=true（便于嘉和端联调时区分「未配置」与「无提醒」）；
    - 查询强制 defer 全部 4 个 CLOB（零大字段加载）+ apply_current_result_filter
      （排除被终末覆盖的历史结果）；排除已复核/已整改闭环记录；
    - 无任何规则开启 jhemr_reminder_policy 时直接返回空列表（不查库）。
    """
    _ = doctor_code  # 预留：写入提醒访问审计（当前只读链路先不落库）
    body = await request.body()
    _verify_request(request, body)

    from app.config import load_config
    from app.models import AuditConclusion, AuditDimensionResult, PushLog
    from app.services.audit_type_registry import AuditTypeRegistry
    from app.services.current_result_filter import apply_current_result_filter

    config = load_config()
    reminder_switch = bool((config.get("jhemr_ai_reminder") or {}).get("enabled"))

    def _empty(*, disabled: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "patient_id": patient_id,
            "visit_id": visit_id,
            "stage": stage,
            "delivery_mode": "pull_api",
            "has_reminders": False,
            "should_block": False,
            "count": 0,
            "items": [],
        }
        if disabled:
            payload["disabled"] = True
        return payload

    if not reminder_switch:
        return _empty(disabled=True)

    # 1) 筛选开启提醒策略且命中通道/阶段的启用规则
    registry = AuditTypeRegistry(config=config)
    policies: list[tuple[Any, Any]] = []
    for item in registry.list_enabled():
        policy = item.jhemr_reminder_policy
        if policy is None or not bool(policy.enabled):
            continue
        if str(policy.delivery_mode) not in ("pull_api", "both"):
            continue
        if not _reminder_stage_matches(policy, stage):
            continue
        policies.append((item, policy))
    if not policies:
        return _empty()

    # 2) 查 PushLog：defer 4 CLOB + current-result filter + 排除已复核/已整改闭环
    enabled_codes = sorted({item.code for item, _ in policies})
    all_severities = sorted({
        severity
        for _, policy in policies
        for severity in (policy.severities or ["high"])
    })
    exclude_reviewed = all(bool(policy.exclude_reviewed) for _, policy in policies)

    q = db.query(PushLog).options(
        orm_defer(PushLog.mr_text),
        orm_defer(PushLog.ai_result),
        orm_defer(PushLog.request_json),
        orm_defer(PushLog.response_json),
    )
    q = apply_current_result_filter(q)
    q = q.filter(
        PushLog.patient_id == patient_id,
        PushLog.status == "success",
        PushLog.audit_type_code.in_(enabled_codes),
        PushLog.severity.in_(all_severities),
    )
    if visit_id is not None:
        q = q.filter(PushLog.visit_number == str(visit_id))
    if exclude_reviewed:
        # 已复核（reviewed_flag==1）排除；历史 NULL 行按未复核保留（口径与 /logs 一致）
        q = q.filter(or_(PushLog.reviewed_flag.is_(None), PushLog.reviewed_flag == 0))
    logs = q.order_by(PushLog.push_time.desc()).limit(_REMINDER_LOG_LIMIT).all()
    if not logs:
        return _empty()

    # 2b) 整改闭环排除：QCFeedback 已整改/已关闭的推送记录不再提醒
    from app.models import QCFeedback

    log_ids = [log.id for log in logs]
    closed_log_ids: set[int] = set()
    for feedback in (
        db.query(QCFeedback.push_log_id)
        .filter(
            QCFeedback.push_log_id.in_(log_ids),
            QCFeedback.status.in_(("rectified", "closed")),
        )
        .all()
    ):
        if feedback.push_log_id:
            closed_log_ids.add(int(feedback.push_log_id))
    logs = [log for log in logs if log.id not in closed_log_ids]
    if not logs:
        return _empty()

    # 3) 左连结论与维度拼装提醒列表
    conclusion_map: dict[int, Any] = {}
    for conclusion in (
        db.query(AuditConclusion)
        .filter(AuditConclusion.push_log_id.in_([log.id for log in logs]))
        .all()
    ):
        conclusion_map.setdefault(conclusion.push_log_id, conclusion)
    dims_by_log: dict[int, list[Any]] = {}
    for dim in (
        db.query(AuditDimensionResult)
        .filter(AuditDimensionResult.push_log_id.in_([log.id for log in logs]))
        .all()
    ):
        dims_by_log.setdefault(dim.push_log_id, []).append(dim)

    type_name_map = {item.code: (item.name or item.code) for item, _ in policies}
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    block_codes = {
        item.code
        for item, policy in policies
        if bool(policy.block_submit)
    }

    items: list[dict[str, Any]] = []
    for log in logs:
        audit_type_code = log.audit_type_code or "unknown"
        audit_type_name = type_name_map.get(audit_type_code, audit_type_code)
        policy = next((p for i, p in policies if i.code == audit_type_code), None)
        if policy and bool(policy.exclude_reviewed) and int(log.reviewed_flag or 0) == 1:
            continue
        severity = str(
            log.severity
            or (conclusion_map.get(log.id).severity if conclusion_map.get(log.id) else "")
            or "high"
        )
        allowed = policy.severities if policy else ["high"]
        if severity not in allowed:
            continue
        severity_label = _SEVERITY_LABELS.get(severity, severity)
        summary = ""
        top_dim = None
        dims = sorted(
            dims_by_log.get(log.id, []),
            key=lambda d: severity_rank.get(str(d.severity or ""), 9),
        )
        for dim in dims:
            if str(dim.severity or "") in allowed:
                top_dim = dim
                break
        if top_dim is not None:
            summary = str(top_dim.issue_summary or top_dim.recommendation or "").strip()
        if not summary:
            conclusion = conclusion_map.get(log.id)
            summary = str(
                (conclusion.overall_qc_summary if conclusion else "")
                or (conclusion.overall_conclusion if conclusion else "")
                or ""
            ).strip()
        title = str(getattr(top_dim, "dimension", "") or "") if top_dim is not None else audit_type_name
        template = str(policy.message_template) if policy else "【AI内涵质控提醒】发现{severity}风险（{audit_type_name}）：{summary}"
        try:
            message = template.format(
                severity=severity_label,
                audit_type_name=audit_type_name,
                summary=(summary or "存在未闭环质控问题")[:200],
            )
        except (KeyError, IndexError):
            message = f"【AI内涵质控提醒】{severity_label}（{audit_type_name}）：{summary[:200]}"
        items.append({
            "log_id": log.id,
            "audit_type_code": audit_type_code,
            "audit_type_name": audit_type_name,
            "severity": severity,
            "severity_label": severity_label,
            "block_submit": bool(audit_type_code in block_codes),
            "title": title or audit_type_name,
            "message": message,
            "push_time": log.push_time.isoformat() if log.push_time else None,
            "detail_path": (
                f"/ui-next/#/quality/patient-detail?patient_id={patient_id}"
                f"&visit_number={log.visit_number or visit_id or ''}"
            ),
        })

    items.sort(key=lambda x: (severity_rank.get(str(x["severity"]), 9), str(x["push_time"] or "")))
    should_block = any(bool(item["block_submit"]) for item in items)
    return {
        "patient_id": patient_id,
        "visit_id": visit_id,
        "stage": stage,
        "delivery_mode": "pull_api",
        "has_reminders": bool(items),
        "should_block": should_block,
        "count": len(items),
        "items": items,
    }


