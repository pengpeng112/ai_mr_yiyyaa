"""
权限管理 API
支持权限的查询、创建、编辑
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import User, Role, Permission
from app.schemas import PermissionInfo, MessageResponse
from app.auth import get_current_user

router = APIRouter()


class PermissionCreateRequest(BaseModel):
    name: str = Field(..., description="权限名称")
    description: str = Field("", description="权限描述")
    module: str = Field("", description="所属模块")


class PermissionUpdateRequest(BaseModel):
    description: Optional[str] = Field(None, description="权限描述")
    module: Optional[str] = Field(None, description="所属模块")


@router.get("", response_model=List[PermissionInfo], tags=["权限管理"])
async def list_permissions(
    module: Optional[str] = Query(None, description="按模块过滤"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取所有权限列表
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can view permissions",
        )
    
    query = db.query(Permission)
    
    if module:
        query = query.filter(Permission.module == module)
    
    permissions = query.all()
    
    return [PermissionInfo.from_orm(p) for p in permissions]


@router.get("/{permission_id}", response_model=PermissionInfo, tags=["权限管理"])
async def get_permission(
    permission_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取权限详情
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can view permissions",
        )
    
    permission = db.query(Permission).filter(Permission.id == permission_id).first()
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found",
        )
    
    return PermissionInfo.from_orm(permission)


@router.post("", response_model=PermissionInfo, tags=["权限管理"])
async def create_permission(
    request: PermissionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    创建新权限（仅管理员）
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can create permissions",
        )
    
    # 检查权限名称是否已存在
    existing = db.query(Permission).filter(Permission.name == request.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Permission name already exists",
        )
    
    # 创建新权限
    permission = Permission(
        name=request.name,
        description=request.description,
        module=request.module,
    )
    
    db.add(permission)
    db.commit()
    db.refresh(permission)
    
    return PermissionInfo.from_orm(permission)


@router.put("/{permission_id}", response_model=PermissionInfo, tags=["权限管理"])
async def update_permission(
    permission_id: int,
    request: PermissionUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    编辑权限（仅管理员）
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can update permissions",
        )
    
    permission = db.query(Permission).filter(Permission.id == permission_id).first()
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found",
        )
    
    # 更新字段
    if request.description is not None:
        permission.description = request.description
    if request.module is not None:
        permission.module = request.module
    
    db.commit()
    db.refresh(permission)
    
    return PermissionInfo.from_orm(permission)


@router.delete("/{permission_id}", response_model=MessageResponse, tags=["权限管理"])
async def delete_permission(
    permission_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    删除权限（仅管理员）
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can delete permissions",
        )
    
    permission = db.query(Permission).filter(Permission.id == permission_id).first()
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found",
        )
    
    # 删除该权限的所有角色关联
    from app.models import RolePermission
    db.query(RolePermission).filter(RolePermission.permission_id == permission_id).delete()
    
    # 删除权限
    db.delete(permission)
    db.commit()
    
    return MessageResponse(message="Permission deleted successfully")
