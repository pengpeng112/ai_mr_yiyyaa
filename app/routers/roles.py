"""
角色管理 API
支持角色权限、菜单、科室分配
"""
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    Department,
    Permission,
    Role,
    RoleDepartment,
    RoleMenu,
    RolePermission,
    User,
)
from app.routers.menu import MENU_CATALOG, MENU_MAP
from app.schemas import (
    DepartmentInfo,
    MessageResponse,
    PermissionInfo,
    RoleDepartmentInfo,
    RoleInfo,
    RoleMenuInfo,
    RoleTimelinessAccessRequest,
    RoleAccessBundleRequest,
    RoleAccessBundleRequest,)
from app.services.timeliness_access import read_settings, serialize_settings

logger = logging.getLogger(__name__)

router = APIRouter()
audit_logger = logging.getLogger("audit.users")


def _require_admin(current_user: User, db: Session) -> None:
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can manage roles",
        )


def _build_role_info(db: Session, role: Role) -> RoleInfo:
    permissions = (
        db.query(Permission)
        .join(RolePermission, Permission.id == RolePermission.permission_id)
        .filter(RolePermission.role_id == role.id)
        .all()
    )
    role_menu_rows = (
        db.query(RoleMenu)
        .filter(RoleMenu.role_id == role.id)
        .order_by(RoleMenu.menu_id.asc())
        .all()
    )
    role_departments = (
        db.query(Department)
        .join(RoleDepartment, Department.id == RoleDepartment.dept_id)
        .filter(RoleDepartment.role_id == role.id)
        .order_by(Department.id.asc())
        .all()
    )

    menus = [
        RoleMenuInfo(**MENU_MAP.get(item.menu_id, {"id": item.menu_id, "label": item.menu_id}))
        for item in role_menu_rows
    ]
    departments = [RoleDepartmentInfo.model_validate({
        "id": item.id,
        "name": item.name,
        "code": item.code or "",
        "manager_id": item.manager_id,
    }) for item in role_departments]

    return RoleInfo(
        id=role.id,
        name=role.name,
        description=role.description,
        permissions=[PermissionInfo.model_validate(p) for p in permissions],
        menus=menus,
        departments=departments,
        timeliness_access=read_settings(role),
    )


@router.put("/{role_id}/access-bundle", response_model=RoleInfo, tags=["角色管理"])
def update_role_access_bundle(role_id: int,
                              body: RoleAccessBundleRequest,
                              current_user: User = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    """一次性原子保存角色菜单+权限+数据范围（WP02；仅管理员；旧逐项接口保留）。"""
    from app.services.timeliness_access import serialize_settings as _serialize_settings
    role_obj = db.query(Role).filter(Role.id == current_user.role_id).first() if current_user.role_id else None
    if not role_obj or role_obj.name != "admin":
        raise HTTPException(status_code=403, detail="Only admin can save access bundle")
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail=f"role not found: {role_id}")

    # 菜单校验
    from app.routers.menu import MENU_MAP
    menu_ids = list(dict.fromkeys(str(m) for m in body.menu_ids))
    unknown = [m for m in menu_ids if m not in MENU_MAP]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown menu ids: {unknown[:10]}")
    # 管理员保护护栏：禁止降级全院范围或移除权限管理入口（防自锁死）
    if role.name == "admin":
        if body.data_scope is not None and body.data_scope.scope != "all":
            raise HTTPException(status_code=400, detail="Administrator scope cannot be changed")
        if "access" not in menu_ids:
            raise HTTPException(status_code=400, detail="Administrator must retain access menu")
    # 权限校验
    perm_ids = list(dict.fromkeys(int(x) for x in body.permission_ids))
    valid_perm_ids = {
        pid for (pid,) in db.query(Permission.id).filter(Permission.id.in_(perm_ids)).all()
    } if perm_ids else set()
    if perm_ids and valid_perm_ids != set(perm_ids):
        raise HTTPException(status_code=400,
                            detail=f"unknown permission ids: {sorted(set(perm_ids) - valid_perm_ids)[:10]}")

    try:
        # 原子同步：菜单
        db.query(RoleMenu).filter(RoleMenu.role_id == role_id).delete()
        for mid in menu_ids:
            db.add(RoleMenu(role_id=role_id, menu_id=mid))
        # 权限
        db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
        for pid in valid_perm_ids:
            db.add(RolePermission(role_id=role_id, permission_id=pid))
        # 数据范围 JSON（管理员范围不可变）
        if body.data_scope is not None and role.name != "admin":
            role.timeliness_access_json = _serialize_settings(db, body.data_scope)
        # RoleDepartment 同步刷新（兼容旧读取路径）
        db.query(RoleDepartment).filter(RoleDepartment.role_id == role_id).delete()
        if (
            role.name != "admin"
            and body.data_scope is not None
            and body.data_scope.scope == "selected"
            and body.data_scope.department_codes
        ):
            dept_rows = db.query(Department).filter(
                Department.code.in_(body.data_scope.department_codes)
            ).all()
            for d in dept_rows:
                db.add(RoleDepartment(role_id=role_id, dept_id=d.id))
        db.commit()
        # WP02：成功后返回最新角色详情（修复：缺 return 导致响应体 None）
        return _build_role_info(db, role)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("access-bundle 保存失败已回滚: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="access bundle save failed")


@router.put("/{role_id}/timeliness-access", response_model=RoleInfo, tags=["角色管理"])
def update_timeliness_access(role_id: int,
                             body: RoleTimelinessAccessRequest,
                             current_user: User = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    from app.services.timeliness_access import read_settings as _read_settings
    _require_admin(current_user, db)
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(404, "Role not found")
    if role.name == "admin":
        raise HTTPException(400, "Administrator scope cannot be changed")
    before = role.timeliness_access_json
    role.timeliness_access_json = serialize_settings(db, body.timeliness_access)
    db.commit()
    if before != role.timeliness_access_json:
        audit_logger.info("[AUDIT] 用户=%s 更新角色时效查看范围 role=%s before=%s after=%s",
                          current_user.username, role.name, before, role.timeliness_access_json)
    return _build_role_info(db, role)


@router.get("", response_model=List[RoleInfo], tags=["角色管理"])
async def list_roles(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取所有角色列表"""
    _require_admin(current_user, db)
    roles = db.query(Role).order_by(Role.id.asc()).all()
    return [_build_role_info(db, role) for role in roles]


# ⚠️ /menus/catalog 必须在 /{role_id} 之前注册，
# 否则 FastAPI 会将 "menus" 匹配为 role_id 路径参数。
@router.get("/menus/catalog", response_model=List[RoleMenuInfo], tags=["角色管理"])
async def list_menu_catalog(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取菜单目录"""
    _require_admin(current_user, db)
    return [RoleMenuInfo(**item) for item in MENU_CATALOG]


@router.get("/{role_id}", response_model=RoleInfo, tags=["角色管理"])
async def get_role(
    role_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取角色详情（含权限、菜单、科室）"""
    _require_admin(current_user, db)
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )
    return _build_role_info(db, role)


@router.post("/{role_id}/permissions/{permission_id}", response_model=MessageResponse, tags=["角色管理"])
async def assign_permission_to_role(
    role_id: int,
    permission_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """为角色分配权限"""
    _require_admin(current_user, db)

    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    permission = db.query(Permission).filter(Permission.id == permission_id).first()
    if not permission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")

    existing = (
        db.query(RolePermission)
        .filter(RolePermission.role_id == role_id, RolePermission.permission_id == permission_id)
        .first()
    )
    if existing:
        return MessageResponse(message="Permission already assigned to this role")

    db.add(RolePermission(role_id=role_id, permission_id=permission_id))
    db.commit()
    return MessageResponse(message="Permission assigned successfully")


@router.delete("/{role_id}/permissions/{permission_id}", response_model=MessageResponse, tags=["角色管理"])
async def revoke_permission_from_role(
    role_id: int,
    permission_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从角色移除权限"""
    _require_admin(current_user, db)

    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    relation = (
        db.query(RolePermission)
        .filter(RolePermission.role_id == role_id, RolePermission.permission_id == permission_id)
        .first()
    )
    if not relation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not assigned to this role")

    db.delete(relation)
    db.commit()
    return MessageResponse(message="Permission revoked successfully")


@router.get("/{role_id}/menus", response_model=List[RoleMenuInfo], tags=["角色管理"])
async def list_role_menus(
    role_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取角色已分配菜单"""
    _require_admin(current_user, db)
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    rows = db.query(RoleMenu).filter(RoleMenu.role_id == role_id).order_by(RoleMenu.menu_id.asc()).all()
    return [RoleMenuInfo(**MENU_MAP.get(item.menu_id, {"id": item.menu_id, "label": item.menu_id})) for item in rows]


@router.post("/{role_id}/menus/{menu_id}", response_model=MessageResponse, tags=["角色管理"])
async def assign_menu_to_role(
    role_id: int,
    menu_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """为角色分配菜单"""
    _require_admin(current_user, db)

    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    if menu_id not in MENU_MAP:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found")

    existing = (
        db.query(RoleMenu)
        .filter(RoleMenu.role_id == role_id, RoleMenu.menu_id == menu_id)
        .first()
    )
    if existing:
        return MessageResponse(message="Menu already assigned to this role")

    db.add(RoleMenu(role_id=role_id, menu_id=menu_id))
    db.commit()
    return MessageResponse(message="Menu assigned successfully")


@router.delete("/{role_id}/menus/{menu_id}", response_model=MessageResponse, tags=["角色管理"])
async def revoke_menu_from_role(
    role_id: int,
    menu_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从角色移除菜单"""
    _require_admin(current_user, db)

    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    relation = (
        db.query(RoleMenu)
        .filter(RoleMenu.role_id == role_id, RoleMenu.menu_id == menu_id)
        .first()
    )
    if not relation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu not assigned to this role")

    db.delete(relation)
    db.commit()
    return MessageResponse(message="Menu revoked successfully")


@router.get("/{role_id}/departments", response_model=List[DepartmentInfo], tags=["角色管理"])
async def list_role_departments(
    role_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取角色已分配科室"""
    _require_admin(current_user, db)
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    departments = (
        db.query(Department)
        .join(RoleDepartment, Department.id == RoleDepartment.dept_id)
        .filter(RoleDepartment.role_id == role_id)
        .order_by(Department.id.asc())
        .all()
    )
    return [DepartmentInfo.model_validate(item) for item in departments]


@router.post("/{role_id}/departments/{dept_id}", response_model=MessageResponse, tags=["角色管理"])
async def assign_department_to_role(
    role_id: int,
    dept_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """为角色分配科室"""
    _require_admin(current_user, db)

    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    existing = (
        db.query(RoleDepartment)
        .filter(RoleDepartment.role_id == role_id, RoleDepartment.dept_id == dept_id)
        .first()
    )
    if existing:
        return MessageResponse(message="Department already assigned to this role")

    db.add(RoleDepartment(role_id=role_id, dept_id=dept_id))
    db.commit()
    return MessageResponse(message="Department assigned successfully")


@router.delete("/{role_id}/departments/{dept_id}", response_model=MessageResponse, tags=["角色管理"])
async def revoke_department_from_role(
    role_id: int,
    dept_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从角色移除科室"""
    _require_admin(current_user, db)

    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    relation = (
        db.query(RoleDepartment)
        .filter(RoleDepartment.role_id == role_id, RoleDepartment.dept_id == dept_id)
        .first()
    )
    if not relation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not assigned to this role")

    db.delete(relation)
    db.commit()
    return MessageResponse(message="Department revoked successfully")
