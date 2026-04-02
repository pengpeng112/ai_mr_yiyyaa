"""
权限检查装饰器与 RBAC 模块
支持基于角色的访问控制和科室级别的数据隔离
"""
from functools import wraps
from typing import List, Optional
from fastapi import HTTPException, status, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Role, Permission, RolePermission
from app.auth import get_current_user


def require_permission(permission_name: str):
    """
    权限检查装饰器
    检查用户是否拥有指定权限
    """
    async def permission_checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        if not current_user.role_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no role assigned",
            )
        
        # 管理员拥有所有权限，直接放行
        role = db.query(Role).filter(Role.id == current_user.role_id).first()
        if role and role.name == "admin":
            return current_user
        
        # 查询用户角色的所有权限
        permissions = db.query(Permission).join(
            RolePermission,
            Permission.id == RolePermission.permission_id
        ).filter(
            RolePermission.role_id == current_user.role_id
        ).all()
        
        permission_names = [p.name for p in permissions]
        
        if permission_name not in permission_names:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission_name}' required",
            )
        
        return current_user
    
    return permission_checker


def require_role(role_name: str):
    """
    角色检查装饰器
    检查用户是否拥有指定角色
    """
    async def role_checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        role = db.query(Role).filter(Role.id == current_user.role_id).first()
        
        if not role or role.name != role_name:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role_name}' required",
            )
        
        return current_user
    
    return role_checker


def require_dept_access(current_user: User = Depends(get_current_user)):
    """
    科室数据隔离检查
    普通用户只能访问自己科室的数据
    """
    if not current_user.dept_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no department assigned",
        )
    
    return current_user


def get_user_permissions(user_id: int, db: Session) -> List[str]:
    """获取用户的所有权限"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.role_id:
        return []
    
    permissions = db.query(Permission).join(
        RolePermission,
        Permission.id == RolePermission.permission_id
    ).filter(
        RolePermission.role_id == user.role_id
    ).all()
    
    return [p.name for p in permissions]


def get_user_role(user_id: int, db: Session) -> Optional[str]:
    """获取用户的角色名称"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.role_id:
        return None
    
    role = db.query(Role).filter(Role.id == user.role_id).first()
    return role.name if role else None


def is_admin(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> bool:
    """检查用户是否为管理员"""
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    return role and role.name == "admin"


def is_dept_manager(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> bool:
    """检查用户是否为科室主任"""
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    return role and role.name == "dept_manager"
