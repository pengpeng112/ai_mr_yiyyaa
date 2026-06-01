"""
审计类型配置路由。
"""
import copy
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.dify_pusher import push_to_dify
from app.models import Role, User
from app.schemas import (
    AuditTypeCloneRequest,
    AuditTypeConfig,
    AuditTypeListResponse,
    AuditTypeTestDifyRequest,
    AuditTypeTestSourceRequest,
    MessageResponse,
)
from app.services.audit_type_registry import AuditTypeRegistry
from app.services.audit_precheck import summarize_bundles
from app.services.data_source_loader import load_patient_bundles

router = APIRouter()
logger = logging.getLogger(__name__)

_NESTED_AUDIT_TYPE_COPY_KEYS = (
    "group_key",
    "payload",
    "dify",
    "response",
    "display",
)


def _require_admin(current_user: User, db: Session):
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")


def _normalize_update_body(body: dict | None) -> dict:
    """兼容用户将完整审计类型 JSON 误粘到 sources 字段的情况。"""
    normalized = copy.deepcopy(body or {})
    sources_value = normalized.get("sources")
    if not isinstance(sources_value, dict):
        return normalized

    nested_sources = sources_value.get("sources")
    if not isinstance(nested_sources, dict):
        return normalized

    looks_like_nested_audit_type = any(
        key in sources_value
        for key in ("code", "name", "description", "group_key", "payload", "response", "display")
    )
    if not looks_like_nested_audit_type:
        return normalized

    normalized["sources"] = copy.deepcopy(nested_sources)
    for key in _NESTED_AUDIT_TYPE_COPY_KEYS:
        if key in sources_value:
            normalized[key] = copy.deepcopy(sources_value[key])
    for key in ("code", "name", "description", "enabled", "sort_order", "default_for_schedule"):
        if key not in normalized and key in sources_value:
            normalized[key] = copy.deepcopy(sources_value[key])
    return normalized


def _audit_type_option(item) -> dict:
    return {
        "code": item.code,
        "name": item.name,
        "default_for_schedule": bool(item.default_for_schedule),
    }


@router.get("", response_model=AuditTypeListResponse, summary="审计类型列表")
def list_audit_types(
    enabled: bool | None = Query(None, description="是否仅返回启用项"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user, db)
    registry = AuditTypeRegistry()
    items = registry.list_enabled() if enabled is True else registry.list_all()
    return AuditTypeListResponse(items=[AuditTypeConfig.model_validate(registry.to_masked_dict(item)) for item in items])


@router.get("/options", summary="审计类型选项")
def list_audit_type_options(
    enabled: bool | None = Query(True, description="是否仅返回启用项"),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    registry = AuditTypeRegistry()
    items = registry.list_enabled() if enabled is not False else registry.list_all()
    return {"items": [_audit_type_option(item) for item in items]}


@router.get("/{code}", response_model=AuditTypeConfig, summary="审计类型详情")
def get_audit_type(
    code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user, db)
    registry = AuditTypeRegistry()
    try:
        return AuditTypeConfig.model_validate(registry.to_masked_dict(registry.get(code)))
    except KeyError:
        raise HTTPException(status_code=404, detail="audit type not found")


@router.post("", response_model=AuditTypeConfig, summary="创建审计类型")
def create_audit_type(
    body: AuditTypeConfig,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user, db)
    registry = AuditTypeRegistry()
    try:
        saved = registry.save(body)
        return AuditTypeConfig.model_validate(registry.to_masked_dict(saved))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.put("/{code}", response_model=AuditTypeConfig, summary="更新审计类型")
def update_audit_type(
    code: str,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user, db)
    registry = AuditTypeRegistry()
    try:
        current = registry.get(code)
    except KeyError:
        raise HTTPException(status_code=404, detail="audit type not found")

    body = _normalize_update_body(body)
    merged = current.model_dump()
    merged.update(copy.deepcopy(body or {}))
    merged["code"] = str(body.get("code") or code) if isinstance(body, dict) else code
    try:
        saved = registry.save(AuditTypeConfig.model_validate(merged), existing_code=code)
        return AuditTypeConfig.model_validate(registry.to_masked_dict(saved))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/{code}", response_model=MessageResponse, summary="删除审计类型")
def delete_audit_type(
    code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user, db)
    registry = AuditTypeRegistry()
    try:
        registry.delete(code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return MessageResponse(message="审计类型已删除")


@router.post("/{code}/clone", response_model=AuditTypeConfig, summary="克隆审计类型")
def clone_audit_type(
    code: str,
    body: AuditTypeCloneRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user, db)
    registry = AuditTypeRegistry()
    try:
        source = registry.get(code).model_dump()
    except KeyError:
        raise HTTPException(status_code=404, detail="audit type not found")
    source["code"] = body.new_code
    source["name"] = body.new_name
    source["default_for_schedule"] = False
    try:
        saved = registry.save(AuditTypeConfig.model_validate(source))
        return AuditTypeConfig.model_validate(registry.to_masked_dict(saved))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{code}/test-source", summary="测试审计类型数据源")
def test_audit_type_source(
    code: str,
    body: AuditTypeTestSourceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user, db)
    registry = AuditTypeRegistry()
    try:
        audit_type = registry.get(code)
    except KeyError:
        raise HTTPException(status_code=404, detail="audit type not found")

    bundles, diagnostics = load_patient_bundles(
        audit_type=audit_type,
        root_config=registry.config,
        query_date=body.query_date,
        date_dimension=body.date_dimension,
        dept_filter=body.dept_filter,
        return_diagnostics=True,
    )
    precheck = summarize_bundles(audit_type, bundles, diagnostics.get("source_row_counts"))

    return {
        "audit_type_code": audit_type.code,
        "query_date": body.query_date,
        "date_dimension": body.date_dimension,
        "bundle_count": len(bundles),
        "sample_bundle": bundles[0].bundle_id if bundles else "",
        "source_counts": {
            source_name: sum(len(bundle.sources.get(source_name, [])) for bundle in bundles)
            for source_name in audit_type.sources.keys()
        },
        "source_row_counts": diagnostics.get("source_row_counts", {}),
        "skipped_records": diagnostics.get("skipped_records", 0),
        "missing_required_bundles": diagnostics.get("missing_required_bundles", 0),
        "precheck": precheck,
        "samples": precheck.get("sample_bundles", []),
    }


@router.post("/{code}/test-dify", summary="测试审计类型 Dify")
def test_audit_type_dify(
    code: str,
    body: AuditTypeTestDifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user, db)
    registry = AuditTypeRegistry()
    try:
        audit_type = registry.get(code)
    except KeyError:
        raise HTTPException(status_code=404, detail="audit type not found")
    dify_override = audit_type.dify.model_dump()
    if dify_override.get("api_key_enc") and not dify_override.get("api_key"):
        from app.config import decrypt_value

        dify_override["api_key"] = decrypt_value(str(dify_override.get("api_key_enc") or ""))
    result = push_to_dify(
        body.mr_txt_sample,
        dify_override,
        patient_id="audit-type-test",
        dify_config_override=dify_override,
        response_paths=audit_type.response,
        parse_strategy=str((audit_type.response or {}).get("parse_strategy") or "hybrid"),
    )
    return {
        "audit_type_code": audit_type.code,
        "status": result.get("status"),
        "inconsistency": result.get("inconsistency", False),
        "severity": result.get("severity", ""),
        "risk_score": result.get("risk_score", 0),
        "parsed_output": result.get("parsed_output", {}),
    }
