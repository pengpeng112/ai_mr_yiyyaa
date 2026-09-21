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
from app.models import Department, Role, User
from app.auth import get_current_user
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
# 046 T1a 新增业务权限（显式迁移脚本落库；admin 角色经 require_permission 全通过）
PERM_MATCH = "prearchive_match_run"
PERM_TRIAL = "prearchive_trial_manage"
PERM_CHECK_VIEW = "prearchive_check_view"
PERM_ISSUE_REVIEW = "prearchive_issue_review"
PERM_ISSUE_FEEDBACK = "prearchive_issue_feedback"
# admin 短路径签名用全集：与 require_permission 的「admin 拥有全部」语义一致，
# 避免 admin 角色 DB 未 seed 某新权限时 BFF 放行而 sidecar 403 的分叉。
ALL_PREARCHIVE_PERMS = (PERM_VIEW, PERM_EDIT, PERM_APPROVE, PERM_PUBLISH,
                        PERM_INTEGRATION, PERM_RETRY, PERM_MATCH, PERM_TRIAL,
                        PERM_CHECK_VIEW, PERM_ISSUE_REVIEW, PERM_ISSUE_FEEDBACK)

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
           permission: str | tuple[str, ...], db: Session,
           params: dict | None = None,
           query: dict | None = None, json_body: dict | None = None) -> JSONResponse:
    # 048 T2：permission 支持任一集合（issue 动作 = feedback 或 review——
    # 与端点依赖和预检侧契约一致；此前硬编码 feedback 使 review-only 角色 403）
    perms = permission if isinstance(permission, (tuple, list)) else (permission,)
    if not any(current_user_has_permission(current_user, p, db) for p in perms):
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


# ---- 046 T1a：覆盖账本 / AI 匹配 / trial BFF ----


@router.get("/prearchive-admin/coverage", summary="覆盖账本（92 FID 聚合检索）")
def list_coverage(fid: int = -1, method: str = "", status: str = "", q: str = "",
                  page: int = 1, page_size: int = 50,
                  current_user: User = _require(PERM_VIEW),
                  db: Session = Depends(get_db)):
    return _proxy("GET", "/api/admin/coverage", current_user, PERM_VIEW, db,
                  query={"fid": fid if fid >= 0 else None, "method": method,
                         "status": status, "q": q, "page": page,
                         "page_size": page_size})


@router.post("/prearchive-admin/coverage/import-snapshot",
             summary="导入评分目录快照（幂等，差异预览）")
def import_coverage_snapshot(body: dict,
                             current_user: User = _require(PERM_EDIT),
                             db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/coverage/import-snapshot", current_user,
                  PERM_EDIT, db, json_body=body)


@router.post("/prearchive-admin/coverage/{fid}/confirm",
             summary="人工确认某 FID 覆盖（精确命中保护）")
def confirm_coverage(fid: int, body: dict,
                     current_user: User = _require(PERM_EDIT),
                     db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/coverage/{fid}/confirm", current_user,
                  PERM_EDIT, db, params={"fid": fid}, json_body=body)


@router.get("/prearchive-admin/coverage/export", summary="覆盖账本导出（审计）")
def export_coverage(current_user: User = _require(PERM_VIEW),
                    db: Session = Depends(get_db)):
    return _proxy("GET", "/api/admin/coverage/export", current_user, PERM_VIEW, db)


@router.post("/prearchive-admin/match/tasks", summary="创建 AI 匹配任务")
def create_match_task(body: dict, current_user: User = _require(PERM_MATCH),
                      db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/match/tasks", current_user, PERM_MATCH, db,
                  json_body=body)


@router.post("/prearchive-admin/match/tasks/{task_id}/run", summary="执行匹配任务")
def run_match_task(task_id: str, current_user: User = _require(PERM_MATCH),
                   db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/match/tasks/{task_id}/run", current_user,
                  PERM_MATCH, db, params={"task_id": task_id})


@router.get("/prearchive-admin/match/tasks/{task_id}", summary="匹配任务状态与候选")
def get_match_task(task_id: str, fid: int = -1,
                   current_user: User = _require(PERM_VIEW),
                   db: Session = Depends(get_db)):
    return _proxy("GET", "/api/admin/match/tasks/{task_id}", current_user,
                  PERM_VIEW, db, params={"task_id": task_id},
                  query={"fid": fid if fid >= 0 else None})


@router.post("/prearchive-admin/match/tasks/{task_id}/cancel", summary="取消匹配任务")
def cancel_match_task(task_id: str, current_user: User = _require(PERM_MATCH),
                      db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/match/tasks/{task_id}/cancel", current_user,
                  PERM_MATCH, db, params={"task_id": task_id})


@router.post("/prearchive-admin/match/candidates/{candidate_id}/decision",
             summary="候选接受/驳回")
def decide_match_candidate(candidate_id: str, body: dict,
                           current_user: User = _require(PERM_MATCH),
                           db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/match/candidates/{candidate_id}/decision",
                  current_user, PERM_MATCH, db,
                  params={"candidate_id": candidate_id}, json_body=body)


@router.post("/prearchive-admin/trial/runs", summary="创建试运行申请")
def create_trial_run(body: dict, current_user: User = _require(PERM_TRIAL),
                     db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/trial/runs", current_user, PERM_TRIAL, db,
                  json_body=body)


@router.get("/prearchive-admin/trial/runs", summary="试运行申请列表")
def list_trial_runs(status: str = "", limit: int = 50,
                    current_user: User = _require(PERM_VIEW),
                    db: Session = Depends(get_db)):
    return _proxy("GET", "/api/admin/trial/runs", current_user, PERM_VIEW, db,
                  query={"status": status, "limit": limit})


# ---- 046 T5：trial 执行 / 观察 / 反馈 BFF ----


@router.post("/prearchive-admin/trial/runs/{trial_run_id}/execute",
             summary="执行试运行（demo fixtures，隔离）")
def execute_trial_run(trial_run_id: str,
                      current_user: User = _require(PERM_TRIAL),
                      db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/trial/runs/{trial_run_id}/execute",
                  current_user, PERM_TRIAL, db,
                  params={"trial_run_id": trial_run_id})


@router.get("/prearchive-admin/trial/runs/{trial_run_id}/observations",
            summary="试运行观察数据")
def trial_observations(trial_run_id: str,
                       current_user: User = _require(PERM_VIEW),
                       db: Session = Depends(get_db)):
    return _proxy("GET", "/api/admin/trial/runs/{trial_run_id}/observations",
                  current_user, PERM_VIEW, db,
                  params={"trial_run_id": trial_run_id})


@router.post("/prearchive-admin/trial/runs/{trial_run_id}/feedback",
             summary="试运行人工反馈")
def trial_feedback(trial_run_id: str, body: dict,
                   current_user: User = _require(PERM_MATCH),
                   db: Session = Depends(get_db)):
    return _proxy("POST", "/api/admin/trial/runs/{trial_run_id}/feedback",
                  current_user, PERM_MATCH, db,
                  params={"trial_run_id": trial_run_id}, json_body=body)


# ---- 046 T5：核查工作台 BFF（checks / issues；科室范围隔离） ----


def _user_dept_code(current_user: User, db: Session) -> str:
    if not current_user.dept_id:
        return ""
    dept = db.query(Department).filter(Department.id == current_user.dept_id).first()
    return (dept.code or dept.name) if dept else ""


def _scoped_dept_for_checks(current_user: User, db: Session) -> str | None:
    """dept_manager/clinician（无 review 权限）强制限定本科室；admin/auditor 全量。

    返回 None=不限制；""=无科室（空结果）；其他=强制科室码。
    """
    if current_user_has_permission(current_user, PERM_ISSUE_REVIEW, db):
        return None
    return _user_dept_code(current_user, db) or "__no_dept__"


def _require_any(*perms: str):
    """任一权限即可（issue 动作：feedback 或 review）。"""
    from app.permissions import get_user_permissions

    async def checker(current_user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
        if _is_admin_role(current_user, db):
            return current_user
        user_perms = set(get_user_permissions(current_user.id, db))
        if user_perms & set(perms):
            return current_user
        raise HTTPException(status_code=403,
                            detail=f"permission denied: any of {list(perms)}")
    return checker


@router.get("/prearchive-admin/checks", summary="核查列表（科室范围隔离；分页）")
def list_checks(dept_code: str = "", patient_id: str = "",
                visit_number: str = "", trigger_type: str = "",
                is_trial: int = 0, page: int = 1, page_size: int = 0,
                limit: int = 0,
                current_user: User = _require(PERM_CHECK_VIEW),
                db: Session = Depends(get_db)):
    scoped = _scoped_dept_for_checks(current_user, db)
    query = {"dept_code": scoped if scoped is not None else (dept_code or None),
             "patient_id": patient_id or None,
             "visit_number": visit_number or None,
             "trigger_type": trigger_type or None,
             "is_trial": is_trial, "page": page,
             "page_size": page_size if page_size > 0 else None,
             "limit": limit if limit > 0 else None}
    return _proxy("GET", "/api/admin/checks", current_user, PERM_CHECK_VIEW, db,
                  query=query)


@router.get("/prearchive-admin/checks/{run_id}", summary="核查详情（科室范围强制）")
def get_check(run_id: str, current_user: User = _require(PERM_CHECK_VIEW),
              db: Session = Depends(get_db)):
    scoped = _scoped_dept_for_checks(current_user, db)
    return _proxy("GET", "/api/admin/checks/{run_id}", current_user,
                  PERM_CHECK_VIEW, db, params={"run_id": run_id},
                  query={"enforce_dept_code": scoped} if scoped is not None else None)


@router.get("/prearchive-admin/issues", summary="缺陷实例列表")
def list_issues(patient_id: str = "", visit_number: str = "",
                dept_code: str = "", status: str = "", limit: int = 200,
                current_user: User = _require(PERM_CHECK_VIEW),
                db: Session = Depends(get_db)):
    scoped = _scoped_dept_for_checks(current_user, db)
    return _proxy("GET", "/api/admin/issues", current_user, PERM_CHECK_VIEW, db,
                  query={"patient_id": patient_id or None,
                         "visit_number": visit_number or None,
                         "dept_code": scoped if scoped is not None
                         else (dept_code or None),
                         "status": status or None, "limit": limit})


@router.get("/prearchive-admin/issues/{issue_id}", summary="缺陷详情（动作历史；科室范围强制）")
def get_issue(issue_id: str, current_user: User = _require(PERM_CHECK_VIEW),
              db: Session = Depends(get_db)):
    scoped = _scoped_dept_for_checks(current_user, db)
    return _proxy("GET", "/api/admin/issues/{issue_id}", current_user,
                  PERM_CHECK_VIEW, db, params={"issue_id": issue_id},
                  query={"enforce_dept_code": scoped} if scoped is not None else None)


@router.post("/prearchive-admin/issues/{issue_id}/actions",
             summary="人工动作（feedback/review 任一权限；终态需 review；科室范围强制）")
def issue_action(issue_id: str, body: dict,
                 current_user: User = Depends(_require_any(
                     PERM_ISSUE_FEEDBACK, PERM_ISSUE_REVIEW)),
                 db: Session = Depends(get_db)):
    scoped = _scoped_dept_for_checks(current_user, db)
    if scoped is not None:
        # 预检侧在动作事务内校验 issue.dept_code（403 越科室）
        body = {**body, "enforce_dept_code": scoped}
    return _proxy("POST", "/api/admin/issues/{issue_id}/actions",
                  current_user, (PERM_ISSUE_FEEDBACK, PERM_ISSUE_REVIEW), db,
                  params={"issue_id": issue_id}, json_body=body)
