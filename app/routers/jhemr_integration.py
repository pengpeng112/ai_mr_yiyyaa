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

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

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
