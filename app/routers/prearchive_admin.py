"""预检规则中心 BFF 路由（039 T6 / §9.2；041 T3 权限双修）。

- 开关关闭（默认）：全部端点 503 feature-disabled，不触网；
  既有 `/api/audit-types/prearchive` 只读接口不受影响；
- 每个端点显式声明权限（六个 additive 权限，仅 admin 默认拥有）；
  041 起读端点（settings/rules/versions/dry-run/diff/outbox/fields/audit/
  delivery-logs）也从 login-only 收紧为 `prearchive_rule_view`；
- `_proxy` 内 `current_user_has_permission` 双保险真实现（admin 全通过、
  其余查角色权限），签名 actor 权限来自 `get_user_permissions` 查库
  （User ORM 无 permissions 属性，禁止裸 User 进签名）；
- 预检服务不可用/超时/坏 JSON → 502，主服务与其他页面照常可用；
- 只代理白名单目标，绝不透传任意路径/头。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User
from app.permissions import get_user_permissions, require_permission
from app.services.prearchive_admin_client import (
    PrearchiveAdminClient,
    PrearchiveAdminDisabled,
    PrearchiveAdminUnavailable,
)

logger = logging.getLogger(__name__)
router = APIRouter()

PERM_VIEW = "prearchive_rule_view"
PERM_EDIT = "prearchive_rule_edit"
PERM_APPROVE = "prearchive_rule_approve"
PERM_PUBLISH = "prearchive_rule_publish"
PERM_INTEGRATION = "prearchive_integration_manage"
PERM_RETRY = "prearchive_delivery_retry"
# admin 短路径签名用全集：与 require_permission 的「admin 拥有全部」语义一致，
# 避免 admin 角色 DB 未 seed 某新权限时 BFF 放行而 sidecar 403 的分叉。
ALL_PREARCHIVE_PERMS = (PERM_VIEW, PERM_EDIT, PERM_APPROVE, PERM_PUBLISH,
                        PERM_INTEGRATION, PERM_RETRY)

_client = PrearchiveAdminClient()   # 进程级默认；测试/热切换经 _get_client 重读 env


def _get_client() -> PrearchiveAdminClient:
    """每次调用按当前 env 构造（开销可忽略）：开关热切换不需要重启主服务。"""
    return PrearchiveAdminClient()


def _is_admin_role(current_user: User, db: Session) -> bool:
    if not current_user.role_id:
        return False
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    return bool(role and role.name == "admin")


def effective_actor_permissions(current_user: User, db: Session) -> list[str]:
    """签名用权限全集：查库取用户权限；admin 角色并上六权限全集（require_permission 同语义）。"""
    perms = set(get_user_permissions(current_user.id, db))
    if _is_admin_role(current_user, db):
        perms.update(ALL_PREARCHIVE_PERMS)
    return sorted(perms)


def current_user_has_permission(current_user: User, permission: str,
                                db: Session) -> bool:
    """双保险真实现：与 require_permission 同语义（admin 全通过，其余查角色权限）。"""
    if _is_admin_role(current_user, db):
        return True
    return permission in get_user_permissions(current_user.id, db)


def _proxy(method: str, path_template: str, current_user: User,
           permission: str, db: Session, params: dict | None = None,
           query: dict | None = None, json_body: dict | None = None) -> JSONResponse:
    if not current_user_has_permission(current_user, permission, db):
        raise HTTPException(status_code=403, detail="permission denied")
    # 签名 actor 用显式权限 namespace（User ORM 没有 permissions 属性，
    # 041 T3：禁止把裸 User 传进 _headers 当权限容器）
    actor = SimpleNamespace(id=current_user.id, username=current_user.username,
                            permissions=effective_actor_permissions(current_user, db))
    try:
        result = _get_client().call(method, path_template, actor,
                                    params=params, query=query, json_body=json_body)
    except PrearchiveAdminDisabled:
        raise HTTPException(status_code=503,
                            detail="prearchive admin BFF is disabled")
    except PrearchiveAdminUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return JSONResponse(status_code=result["status"], content=result["json"],
                        headers={"X-Bff-Request-Id": result["request_id"]})


def _require(permission: str):
    return Depends(require_permission(permission))


@router.get("/prearchive-admin/settings", summary="规则中心设置与运行模式")
def get_settings(current_user: User = _require(PERM_VIEW),
                 db: Session = Depends(get_db)):
    return _proxy("GET", "/api/admin/settings", current_user, PERM_VIEW, db)


@router.get("/prearchive-admin/rules", summary="规则列表（分页/筛选）")
def list_rules(domain: str = "", track: str = "", status: str = "",
               page: int = 1, page_size: int = 50,
               current_user: User = _require(PERM_VIEW),
               db: Session = Depends(get_db)):
    return _proxy("GET", "/api/admin/rules", current_user, PERM_VIEW, db,
                  query={"domain": domain, "track": track, "status": status,
                         "page": page, "page_size": page_size})


@router.post("/prearchive-admin/rules", summary="新建规则草稿")
def create_rule(body: dict, current_user: User = _require(PERM_EDIT),
                db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/rules", current_user, PERM_EDIT, db,
                  json_body=body)


@router.get("/prearchive-admin/rules/{rule_key}/versions", summary="规则版本历史")
def list_versions(rule_key: str, current_user: User = _require(PERM_VIEW),
                  db: Session = Depends(get_db)):
    return _proxy("GET", "/api/admin/rules/{rule_key}/versions", current_user,
                  PERM_VIEW, db, params={"rule_key": rule_key})


@router.put("/prearchive-admin/rules/{rule_key}/draft", summary="修改规则草稿")
def update_draft(rule_key: str, body: dict, current_user: User = _require(PERM_EDIT),
                 db: Session = Depends(get_db)):
    return _proxy("PUT", "/api/admin/rules/{rule_key}/draft", current_user, PERM_EDIT,
                  db, params={"rule_key": rule_key}, json_body=body)


@router.post("/prearchive-admin/rules/{rule_key}/validate", summary="校验规则")
def validate_rule(rule_key: str, body: dict, current_user: User = _require(PERM_EDIT),
                  db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/rules/{rule_key}/validate", current_user,
                  PERM_EDIT, db, params={"rule_key": rule_key}, json_body=body)


@router.post("/prearchive-admin/rules/{rule_key}/dry-run", summary="试运行（demo fixtures）")
def dry_run(rule_key: str, body: dict, current_user: User = _require(PERM_VIEW),
            db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/rules/{rule_key}/dry-run", current_user,
                  PERM_VIEW, db, params={"rule_key": rule_key}, json_body=body)


@router.post("/prearchive-admin/rules/{rule_key}/approve", summary="审批规则")
def approve(rule_key: str, body: dict, current_user: User = _require(PERM_APPROVE),
            db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/rules/{rule_key}/approve", current_user,
                  PERM_APPROVE, db, params={"rule_key": rule_key}, json_body=body)


@router.post("/prearchive-admin/rules/{rule_key}/publish", summary="发布规则")
def publish(rule_key: str, body: dict, current_user: User = _require(PERM_PUBLISH),
            db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/rules/{rule_key}/publish", current_user,
                  PERM_PUBLISH, db, params={"rule_key": rule_key}, json_body=body)


@router.post("/prearchive-admin/rules/{rule_key}/rollback", summary="回滚规则")
def rollback(rule_key: str, body: dict, current_user: User = _require(PERM_PUBLISH),
             db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/rules/{rule_key}/rollback", current_user,
                  PERM_PUBLISH, db, params={"rule_key": rule_key}, json_body=body)


@router.post("/prearchive-admin/rules/{rule_key}/retire", summary="退役规则")
def retire(rule_key: str, body: dict, current_user: User = _require(PERM_PUBLISH),
           db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/rules/{rule_key}/retire", current_user,
                  PERM_PUBLISH, db, params={"rule_key": rule_key}, json_body=body)


@router.get("/prearchive-admin/rules/{rule_key}/diff", summary="版本差异")
def diff(rule_key: str, version_a: str, version_b: str,
         current_user: User = _require(PERM_VIEW),
         db: Session = Depends(get_db)):
    return _proxy("GET", "/api/admin/rules/{rule_key}/diff", current_user, PERM_VIEW,
                  db, params={"rule_key": rule_key},
                  query={"version_a": version_a, "version_b": version_b})


@router.get("/prearchive-admin/destinations", summary="投递目标列表")
def list_destinations(current_user: User = _require(PERM_INTEGRATION),
                      db: Session = Depends(get_db)):
    return _proxy("GET", "/api/admin/destinations", current_user, PERM_INTEGRATION, db)


@router.post("/prearchive-admin/destinations", summary="维护投递目标（非敏感）")
def upsert_destination(body: dict, current_user: User = _require(PERM_INTEGRATION),
                       db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/destinations", current_user, PERM_INTEGRATION,
                  db, json_body=body)


@router.post("/prearchive-admin/destinations/{code}/contract-test",
             summary="目标合成契约测试")
def contract_test(code: str, current_user: User = _require(PERM_INTEGRATION),
                  db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/destinations/{code}/contract-test",
                  current_user, PERM_INTEGRATION, db, params={"code": code})


@router.get("/prearchive-admin/outbox", summary="Outbox 投递状态")
def list_outbox(status: str = "", destination_code: str = "",
                current_user: User = _require(PERM_VIEW),
                db: Session = Depends(get_db)):
    return _proxy("GET", "/api/admin/outbox", current_user, PERM_VIEW, db,
                  query={"status": status, "destination_code": destination_code})


@router.post("/prearchive-admin/outbox/{outbox_id}/retry", summary="人工重试投递")
def retry_outbox(outbox_id: str, current_user: User = _require(PERM_RETRY),
                 db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/outbox/{outbox_id}/retry", current_user,
                  PERM_RETRY, db, params={"outbox_id": outbox_id})


@router.get("/prearchive-admin/fields", summary="Canonical fields 注册")
def list_fields(current_user: User = _require(PERM_VIEW),
                db: Session = Depends(get_db)):
    return _proxy("GET", "/api/admin/fields", current_user, PERM_VIEW, db)


@router.get("/prearchive-admin/audit", summary="规则中心管理审计")
def list_audit(rule_key: str = "", action: str = "",
               current_user: User = _require(PERM_VIEW),
               db: Session = Depends(get_db)):
    return _proxy("GET", "/api/admin/audit", current_user, PERM_VIEW, db,
                  query={"rule_key": rule_key, "action": action})


@router.get("/prearchive-admin/delivery-logs", summary="投递尝试日志")
def list_delivery_logs(event_id: str = "", current_user: User = _require(PERM_VIEW),
                       db: Session = Depends(get_db)):
    return _proxy("GET", "/api/admin/delivery-logs", current_user, PERM_VIEW, db,
                  query={"event_id": event_id})
