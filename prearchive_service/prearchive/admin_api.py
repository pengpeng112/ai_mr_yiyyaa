# -*- coding: utf-8 -*-
"""预检服务内部管理 API（039 §9.1）：规则中心 / 目标 / Outbox / 字段注册 / 审计。

鉴权（与患者查询 X-Precheck-Token 完全独立）：
- ``X-Admin-Token``：管理服务令牌（config.admin_api.admin_token）；
- ``X-Actor-Id`` / ``X-Actor-Name`` / ``X-Actor-Permissions`` / ``X-Request-Id``：
  主服务 BFF 签名的操作者身份；
- ``X-Actor-Signature``：HMAC-SHA256(signing_secret, f"{actor_id}|{actor_name}|{permissions}|{request_id}")。
  预检服务必须验签落审计——不信任裸 header。

所有写操作要求 actor 具备对应权限（prearchive_rule_edit / approve / publish /
integration_manage / delivery_retry）；dry-run 只用 demo fixtures，不查真实库。
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request

from .rule_models import RuleVersionRow
from .rule_repository import RuleConflictError, RuleNotFoundError, RuleRepository
from .rule_service import Actor, RuleService, rule_registry_settings
from .rules import RuleValidationError

ADMIN_TOKEN_HEADER = "X-Admin-Token"
ACTOR_ID_HEADER = "X-Actor-Id"
ACTOR_NAME_HEADER = "X-Actor-Name"
ACTOR_PERMS_HEADER = "X-Actor-Permissions"
REQUEST_ID_HEADER = "X-Request-Id"
ACTOR_SIGNATURE_HEADER = "X-Actor-Signature"

PERM_VIEW = "prearchive_rule_view"
PERM_EDIT = "prearchive_rule_edit"
PERM_APPROVE = "prearchive_rule_approve"
PERM_PUBLISH = "prearchive_rule_publish"
PERM_INTEGRATION = "prearchive_integration_manage"
PERM_RETRY = "prearchive_delivery_retry"


def actor_signature(signing_secret: str, actor_id: str, actor_name: str,
                    permissions: str, request_id: str) -> str:
    message = f"{actor_id}|{actor_name}|{permissions}|{request_id}"
    return hmac.new(signing_secret.encode("utf-8"), message.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def create_admin_router(config: dict, repository: RuleRepository,
                        service: RuleService) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["prearchive-admin"])
    admin_cfg = (config or {}).get("admin_api") or {}
    admin_token = str(admin_cfg.get("admin_token") or "")
    signing_secret = str(admin_cfg.get("signing_secret") or "")

    def _authenticated_actor(request: Request, required_permission: str) -> Actor:
        provided = request.headers.get(ADMIN_TOKEN_HEADER, "")
        if not admin_token or admin_token.startswith("<"):
            raise HTTPException(status_code=503, detail="admin api token not configured")
        if not hmac.compare_digest(provided, admin_token):
            raise HTTPException(status_code=401, detail="invalid admin token")
        if not signing_secret or signing_secret.startswith("<"):
            raise HTTPException(status_code=503, detail="admin signing secret not configured")
        actor_id = request.headers.get(ACTOR_ID_HEADER, "")
        # HTTP 头仅 ASCII：操作者姓名由 BFF 侧 percent-encode；签名对线上原始
        # 值计算（两侧一致），解码只用于展示与审计。
        raw_actor_name = request.headers.get(ACTOR_NAME_HEADER, "")
        permissions = request.headers.get(ACTOR_PERMS_HEADER, "")
        request_id = request.headers.get(REQUEST_ID_HEADER, "")
        signature = request.headers.get(ACTOR_SIGNATURE_HEADER, "")
        expected = actor_signature(signing_secret, actor_id, raw_actor_name,
                                   permissions, request_id)
        if not signature or not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=401, detail="invalid actor signature")
        perms = [p for p in permissions.split(",") if p.strip()]
        actor = Actor(id=actor_id, name=unquote(raw_actor_name), permissions=perms)
        if required_permission and not actor.has(required_permission):
            raise HTTPException(status_code=403,
                                detail=f"permission denied: {required_permission}")
        return actor

    def _request_id(request: Request) -> str:
        return request.headers.get(REQUEST_ID_HEADER, "") or "req-unset"

    def _rule_row_dict(row: RuleVersionRow) -> dict:
        return {
            "rule_key": row.rule_key,
            "domain": row.domain,
            "track": row.track,
            "origin": row.origin,
            "rule_version": row.rule_version,
            "set_version": row.set_version,
            "status": row.status,
            "content": json.loads(row.content_json),
            "content_sha256": row.content_sha256,
            "draft_edit_version": row.draft_edit_version,
            "created_by": row.created_by,
            "approved_by": row.approved_by,
            "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
            "published_at": row.published_at.isoformat(timespec="seconds") if row.published_at else None,
        }

    def _error(exc: Exception) -> HTTPException:
        if isinstance(exc, RuleNotFoundError):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, RuleConflictError):
            return HTTPException(status_code=409, detail=str(exc))
        if isinstance(exc, RuleValidationError):
            return HTTPException(status_code=422, detail=str(exc))
        return HTTPException(status_code=400, detail=str(exc))

    # ---- 治理概览 ----

    @router.get("/settings", summary="规则中心设置与运行模式")
    def get_settings(request: Request):
        _authenticated_actor(request, PERM_VIEW)
        return rule_registry_settings(config)

    # ---- 规则 CRUD / 生命周期 ----

    @router.get("/rules", summary="规则列表（分页/筛选）")
    def list_rules(request: Request, domain: str = "", track: str = "",
                   status: str = "", page: int = 1, page_size: int = 50):
        _authenticated_actor(request, PERM_VIEW)
        rows, total = repository.list_rules(domain=domain, track=track,
                                            status=status, page=page,
                                            page_size=min(page_size, 200))
        pointers = {p.rule_key: p.published_version
                    for p in repository.list_pointers()}
        return {
            "total": total,
            "items": [{
                **_rule_row_dict(row),
                "published_version": pointers.get(row.rule_key, ""),
            } for row in rows],
        }

    @router.post("/rules", summary="新建草稿")
    def create_rule(request: Request, body: dict):
        actor = _authenticated_actor(request, PERM_EDIT)
        try:
            row = service.create_draft(
                body, actor,
                domain=str(body.get("_domain") or "medical_record"),
                track=str(body.get("_track") or "main"),
                origin=str(body.get("_origin") or "manual"),
                request_id=_request_id(request))
        except (RuleNotFoundError, RuleConflictError, RuleValidationError,
                ValueError) as exc:
            raise _error(exc) from exc
        return _rule_row_dict(row)

    @router.get("/rules/{rule_key}/versions", summary="不可变版本历史")
    def list_versions(rule_key: str, request: Request):
        _authenticated_actor(request, PERM_VIEW)
        return {"items": [_rule_row_dict(row)
                          for row in repository.list_versions(rule_key)]}

    @router.put("/rules/{rule_key}/draft", summary="修改草稿（乐观锁）")
    def update_draft(rule_key: str, request: Request, body: dict):
        actor = _authenticated_actor(request, PERM_EDIT)
        rule_version = str(body.get("rule_version") or "")
        expect = int(body.get("expect_edit_version") or 0)
        content = body.get("content")
        if not isinstance(content, dict):
            raise HTTPException(status_code=422, detail="content must be an object")
        try:
            row = service.update_draft(rule_key, rule_version, content,
                                       expect, actor, request_id=_request_id(request))
        except (RuleNotFoundError, RuleConflictError, RuleValidationError,
                ValueError) as exc:
            raise _error(exc) from exc
        return _rule_row_dict(row)

    @router.post("/rules/{rule_key}/validate", summary="Schema+语义校验")
    def validate_rule_endpoint(rule_key: str, request: Request, body: dict):
        actor = _authenticated_actor(request, PERM_VIEW)
        try:
            return service.validate(rule_key, str(body.get("rule_version") or ""),
                                    actor, request_id=_request_id(request))
        except (RuleNotFoundError, RuleConflictError) as exc:
            raise _error(exc) from exc

    @router.post("/rules/{rule_key}/dry-run", summary="试运行（仅 demo fixtures）")
    def dry_run_rule(rule_key: str, request: Request, body: dict):
        _authenticated_actor(request, PERM_VIEW)
        rule_version = str(body.get("rule_version") or "")
        row = repository.get_version(rule_key, rule_version)
        if row is None:
            raise HTTPException(status_code=404, detail=f"{rule_key}@{rule_version}")
        from .engine import RuleEngine
        from .rules import validate_rule as validate_dsl
        spec = validate_dsl(json.loads(row.content_json))
        engine = RuleEngine([spec], rule_version=rule_version)
        results = []
        try:
            from .collectors import (
                HisCollector,
                ItfSourceCollector,
                JhemrCollector,
                LisCollector,
                PatientContextBuilder,
                SmCollector,
            )
            from .context import (
                SRC_BL_ITF,
                SRC_DCN_REPORT,
                SRC_ES_ITF,
                SRC_PACS_ITF,
                SRC_QGJ_ITF,
                SRC_XD_ITF,
                SRC_XT_ITF,
            )
            from .fixture_sources import build_demo_fixtures
            fixtures = build_demo_fixtures()
            new_labels = {
                "pacs": SRC_PACS_ITF, "es": SRC_ES_ITF, "bl": SRC_BL_ITF,
                "xt": SRC_XT_ITF, "xd": SRC_XD_ITF, "dcn": SRC_DCN_REPORT,
                "qgj": SRC_QGJ_ITF,
            }
            extras = {label: ItfSourceCollector(fixtures[name], label)
                      for name, label in new_labels.items()
                      if fixtures.get(name) is not None}
            jhemr_collector = JhemrCollector(fixtures["jhemr"])
            builder = PatientContextBuilder(
                jhemr=jhemr_collector,
                his=HisCollector(fixtures["his"]),
                sm=SmCollector(fixtures["sm"]),
                lis=LisCollector(fixtures["lis"]),
                extra_itf_collectors=extras,
            )
            for visit in jhemr_collector.fetch_finished_visits(None, 10):
                ctx = builder.build(visit)
                if ctx is None:
                    continue
                output = engine.evaluate(ctx)
                results.append({
                    "patient_id": ctx.patient_id,       # demo fixtures 全虚构数据
                    "visit_id": ctx.visit_id,
                    "problem_count": output.problem_count,
                    "problems": output.problems,
                    "notices": output.notices,
                })
        except Exception as exc:  # noqa: BLE001 —— fixtures 缺失时降级报告
            return {"ok": False, "reason": f"demo fixtures unavailable: {exc}",
                    "rule_key": rule_key, "rule_version": rule_version}
        return {"ok": True, "rule_key": rule_key, "rule_version": rule_version,
                "fixture_results": results}

    @router.post("/rules/{rule_key}/approve", summary="审批")
    def approve_rule(rule_key: str, request: Request, body: dict):
        actor = _authenticated_actor(request, PERM_APPROVE)
        try:
            row = service.approve(rule_key, str(body.get("rule_version") or ""),
                                  actor, reason=str(body.get("reason") or ""),
                                  request_id=_request_id(request))
        except (RuleNotFoundError, RuleConflictError) as exc:
            raise _error(exc) from exc
        return _rule_row_dict(row)

    @router.post("/rules/{rule_key}/publish", summary="发布并更新指针")
    def publish_rule(rule_key: str, request: Request, body: dict):
        actor = _authenticated_actor(request, PERM_PUBLISH)
        try:
            return service.publish(
                rule_key, str(body.get("rule_version") or ""), actor,
                reason=str(body.get("reason") or ""),
                request_id=_request_id(request),
                expect_pointer_version=body.get("expect_pointer_version"))
        except (RuleNotFoundError, RuleConflictError) as exc:
            raise _error(exc) from exc

    @router.post("/rules/{rule_key}/rollback", summary="回滚发布指针")
    def rollback_rule(rule_key: str, request: Request, body: dict):
        actor = _authenticated_actor(request, PERM_PUBLISH)
        try:
            return service.rollback(rule_key, str(body.get("to_version") or ""),
                                    actor, reason=str(body.get("reason") or ""),
                                    request_id=_request_id(request))
        except (RuleNotFoundError, RuleConflictError) as exc:
            raise _error(exc) from exc

    @router.get("/rules/{rule_key}/diff", summary="版本差异")
    def diff_rules(rule_key: str, request: Request, version_a: str,
                   version_b: str):
        _authenticated_actor(request, PERM_VIEW)
        try:
            return service.diff(rule_key, version_a, version_b)
        except RuleNotFoundError as exc:
            raise _error(exc) from exc

    @router.post("/rules/{rule_key}/retire", summary="退役规则版本")
    def retire_rule(rule_key: str, request: Request, body: dict):
        actor = _authenticated_actor(request, PERM_PUBLISH)
        try:
            row = service.retire(rule_key, str(body.get("rule_version") or ""),
                                 actor, reason=str(body.get("reason") or ""),
                                 request_id=_request_id(request))
        except (RuleNotFoundError, RuleConflictError) as exc:
            raise _error(exc) from exc
        return _rule_row_dict(row)

    # ---- 目标 ----

    @router.get("/destinations", summary="目标列表（非敏感）")
    def list_destinations(request: Request):
        _authenticated_actor(request, PERM_INTEGRATION)
        return {"items": [row.to_public_dict()
                          for row in repository.list_destinations()]}

    @router.post("/destinations", summary="目标配置维护（非敏感字段）")
    def upsert_destination(request: Request, body: dict):
        actor = _authenticated_actor(request, PERM_INTEGRATION)
        code = str(body.get("code") or "").strip()
        if not code:
            raise HTTPException(status_code=422, detail="code required")
        fields = {"code": code}
        existing = repository.get_destination(code)
        for key in ("kind", "base_url", "endpoint", "auth_type", "schema_version"):
            if key in body:
                fields[key] = str(body[key])
        if "enabled" in body:
            fields["enabled"] = 1 if body["enabled"] else 0
        if "timeout_seconds" in body:
            fields["timeout_seconds"] = int(body["timeout_seconds"])
        if "max_attempts" in body:
            fields["max_attempts"] = int(body["max_attempts"])
        if "allow_insecure_internal_http" in body:
            fields["allow_insecure_internal_http"] = \
                1 if body["allow_insecure_internal_http"] else 0
        if "send_severities" in body:
            fields["send_severities_json"] = json.dumps(
                list(body["send_severities"] or []))
        # secret_ref：空值不覆盖已有引用（039 §7.1）
        secret_ref = str(body.get("secret_ref") or "").strip()
        if secret_ref:
            fields["secret_ref"] = secret_ref
        elif existing is not None:
            fields["secret_ref"] = existing.secret_ref
        row = repository.upsert_destination(updated_by=actor.id, **fields)
        repository.append_audit(
            action="config_update", rule_key=f"destination:{code}",
            actor_id=actor.id, actor_name=actor.name,
            request_id=_request_id(request),
            detail={"keys": sorted(fields.keys()),
                    "config_version": row.config_version})
        return row.to_public_dict()

    @router.post("/destinations/{code}/contract-test", summary="合成数据契约测试")
    def contract_test(code: str, request: Request):
        actor = _authenticated_actor(request, PERM_INTEGRATION)
        from .destinations import (DestinationError, build_delivery_headers,
                                   mask_url_for_log, resolve_destination)
        from .result_contract import build_contract_test_envelope
        try:
            destination = resolve_destination(repository, code)
        except DestinationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        envelope = build_contract_test_envelope(code)
        body = envelope.model_dump_json().encode("utf-8")
        try:
            headers = build_delivery_headers(destination, body)
        except DestinationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        repository.append_audit(
            action="contract_test", rule_key=f"destination:{code}",
            actor_id=actor.id, actor_name=actor.name,
            request_id=_request_id(request),
            detail={"url": mask_url_for_log(destination.url),
                    "event_id": envelope.event_id,
                    "note": "synthetic contract test (no real patient)"})
        # 阶段 A 不真实外发：返回待发送预览（真实发送在 B 阶段经授权执行）
        return {
            "ok": True,
            "destination": code,
            "url": mask_url_for_log(destination.url),
            "event_id": envelope.event_id,
            "event_type": envelope.event_type,
            "headers_sent": sorted(headers.keys()),
            "preview_only": True,
            "note": "stage-A contract test builds the request without sending; "
                    "real send requires authorized destination + delivery enabled",
        }

    # ---- Outbox ----

    @router.get("/outbox", summary="投递状态")
    def list_outbox(request: Request, status: str = "", destination_code: str = "",
                    limit: int = 100, offset: int = 0):
        _authenticated_actor(request, PERM_VIEW)
        rows = repository.list_outbox(status=status,
                                      destination_code=destination_code,
                                      limit=min(limit, 500), offset=offset)
        return {"items": [{
            "id": row.id,
            "event_id": row.event_id,
            "destination_code": row.destination_code,
            "status": row.status,
            "attempts": row.attempts,
            "next_retry_at": row.next_retry_at.isoformat(timespec="seconds")
            if row.next_retry_at else None,
            "last_http_status": row.last_http_status,
            "last_error": row.last_error,
            "created_at": row.created_at.isoformat(timespec="seconds")
            if row.created_at else None,
        } for row in rows]}

    @router.post("/outbox/{outbox_id}/retry", summary="人工重试（记录操作者）")
    def retry_outbox(outbox_id: str, request: Request):
        actor = _authenticated_actor(request, PERM_RETRY)
        from .outbox import DeliveryWorker
        worker = DeliveryWorker(repository, delivery_enabled=True)
        ok = worker.retry_manual(outbox_id, actor)
        if not ok:
            raise HTTPException(status_code=409,
                                detail="outbox not retryable or not found")
        return {"ok": True, "outbox_id": outbox_id}

    # ---- 字段注册 / 审计 ----

    @router.get("/fields", summary="可配置 canonical fields（含就绪状态）")
    def list_fields(request: Request):
        _authenticated_actor(request, PERM_VIEW)
        from .field_registry import CANONICAL_FIELDS
        return {"items": CANONICAL_FIELDS}

    @router.get("/audit", summary="管理审计（append-only）")
    def list_audit(request: Request, rule_key: str = "", action: str = "",
                   limit: int = 100, offset: int = 0):
        _authenticated_actor(request, PERM_VIEW)
        rows = repository.list_audit(rule_key=rule_key, action=action,
                                     limit=min(limit, 500), offset=offset)
        return {"items": [{
            "id": row.id,
            "action": row.action,
            "rule_key": row.rule_key,
            "version_from": row.version_from,
            "version_to": row.version_to,
            "actor_id": row.actor_id,
            "actor_name": row.actor_name,
            "reason": row.reason,
            "request_id": row.request_id,
            "created_at": row.created_at.isoformat(timespec="seconds")
            if row.created_at else None,
        } for row in rows]}

    @router.get("/delivery-logs", summary="投递尝试日志（脱敏）")
    def list_delivery_logs(request: Request, event_id: str = "", limit: int = 100):
        _authenticated_actor(request, PERM_VIEW)
        rows = repository.list_delivery_logs(event_id=event_id,
                                             limit=min(limit, 500))
        return {"items": [{
            "event_id": row.event_id,
            "destination_code": row.destination_code,
            "attempt": row.attempt,
            "http_status": row.http_status,
            "outcome": row.outcome,
            "receiver_reference": row.receiver_reference,
            "detail": row.detail,
            "created_at": row.created_at.isoformat(timespec="seconds")
            if row.created_at else None,
        } for row in rows]}

    return router
