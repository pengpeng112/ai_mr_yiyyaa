"""
角色管理 API
支持角色的 CRUD、权限分配、权限查询
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List

from app.database import get_db
from app.models import User, Role, Permission, RolePermission
from app.schemas import RoleInfo, PermissionInfo, MessageResponse
from app.auth import get_current_user
from app.permissions import require_role

router = APIRouter()


@router.get("", response_model=List[RoleInfo], tags=["角色管理"])
async def list_roles(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取所有角色列表
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can view roles",
        )
    
    roles = db.query(Role).all()
    
    result = []
    for r in roles:
        # 获取该角色的所有权限
        permissions = db.query(Permission).join(
            RolePermission,
            Permission.id == RolePermission.permission_id
        ).filter(
            RolePermission.role_id == r.id
        ).all()
        
        role_info = RoleInfo(
            id=r.id,
            name=r.name,
            description=r.description,
            permissions=[PermissionInfo.from_orm(p) for p in permissions],
        )
        result.append(role_info)
    
    return result


@router.get("/{role_id}", response_model=RoleInfo, tags=["角色管理"])
async def get_role(
    role_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取角色详情（包含权限）
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can view roles",
        )
    
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )
    
    # 获取该角色的所有权限
    permissions = db.query(Permission).join(
        RolePermission,
        Permission.id == RolePermission.permission_id
    ).filter(
        RolePermission.role_id == role.id
    ).all()
    
    return RoleInfo(
        id=role.id,
        name=role.name,
        description=role.description,
        permissions=[PermissionInfo.from_orm(p) for p in permissions],
    )


@router.post("/{role_id}/permissions/{permission_id}", response_model=MessageResponse, tags=["角色管理"])
async def assign_permission_to_role(
    role_id: int,
    permission_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    为角色分配权限
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can assign permissions",
        )
    
    # 检查角色是否存在
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )
    
    # 检查权限是否存在
    permission = db.query(Permission).filter(Permission.id == permission_id).first()
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found",
        )
    
    # 检查是否已分配
    existing = db.query(RolePermission).filter(
        RolePermission.role_id == role_id,
        RolePermission.permission_id == permission_id
    ).first()
    
    if existing:
        return MessageResponse(message="Permission already assigned to this role")
    
    # 分配权限
    rp = RolePermission(role_id=role_id, permission_id=permission_id)
    db.add(rp)
    db.commit()
    
    return MessageResponse(message="Permission assigned successfully")


@router.delete("/{role_id}/permissions/{permission_id}", response_model=MessageResponse, tags=["角色管理"])
async def revoke_permission_from_role(
    role_id: int,
    permission_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    从角色撤销权限
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can revoke permissions",
        )
    
    # 检查角色是否存在
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )
    
    # 查找并删除权限分配
    rp = db.query(RolePermission).filter(
        RolePermission.role_id == role_id,
        RolePermission.permission_id == permission_id
    ).first()
    
    if not rp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not assigned to this role",
        )
    
    db.delete(rp)
    db.commit()
    
    return MessageResponse(message="Permission revoked successfully")
