"""
用户认证与管理 API
支持登录、用户 CRUD、权限查询
"""
import os
import time
import threading
import logging
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.models import User, Role, Department, Permission, RolePermission
from app.schemas import (
    LoginRequest, LoginResponse, UserInfo, UserCreateRequest, 
    UserUpdateRequest, UserListResponse, MessageResponse,
    ChangePasswordRequest
)
from app.auth import (
    hash_password, verify_password, create_access_token, 
    get_current_user
)
from app.permissions import (
    require_role, get_user_permissions as get_user_permissions_list, get_user_role, is_admin
)

router = APIRouter()
audit_logger = logging.getLogger("audit.users")

# ---- 登录限流 ----
_login_attempts: dict = defaultdict(list)  # {username: [timestamp, ...]}
_login_lock = threading.Lock()
_MAX_LOGIN_ATTEMPTS = 5       # 窗口内最大尝试次数
_LOGIN_WINDOW_SECONDS = 300   # 5分钟窗口


def _check_login_rate_limit(username: str):
    """检查登录频率，超限则抛出 429"""
    now = time.time()
    with _login_lock:
        attempts = _login_attempts[username]
        # 清除窗口外的记录
        _login_attempts[username] = [t for t in attempts if now - t < _LOGIN_WINDOW_SECONDS]
        if len(_login_attempts[username]) >= _MAX_LOGIN_ATTEMPTS:
            raise HTTPException(
                status_code=429,
                detail=f"登录尝试过于频繁，请 {_LOGIN_WINDOW_SECONDS // 60} 分钟后重试",
            )


def _record_login_attempt(username: str):
    """记录一次登录尝试"""
    with _login_lock:
        _login_attempts[username].append(time.time())


def _clear_login_attempts(username: str):
    """登录成功后清除记录"""
    with _login_lock:
        _login_attempts.pop(username, None)


def _ensure_debug_admin_for_login(db: Session, username: str, password: str):
    """本地调试兜底：使用指定管理员账号登录时，仅在账号不存在时自动创建。"""
    debug_username = os.getenv("DEBUG_ADMIN_USERNAME", "admin")
    debug_password = os.getenv("DEBUG_ADMIN_PASSWORD", "Admin123456")

    if username != debug_username or password != debug_password:
        return

    admin_role = db.query(Role).filter(Role.name == "admin").first()
    if not admin_role:
        admin_role = Role(name="admin", description="系统管理员")
        db.add(admin_role)
        db.flush()

    user = db.query(User).filter(User.username == debug_username).first()
    if not user:
        user = User(
            username=debug_username,
            password_hash=hash_password(debug_password),
            full_name=os.getenv("DEBUG_ADMIN_FULL_NAME", "系统管理员"),
            email=os.getenv("DEBUG_ADMIN_EMAIL", "admin@local.test"),
            role_id=admin_role.id,
            is_active=True,
        )
        db.add(user)
        db.commit()


@router.post("/login", response_model=LoginResponse, tags=["认证"])
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    用户登录
    
    返回 JWT Token 和用户信息
    """
    _check_login_rate_limit(request.username)
    _ensure_debug_admin_for_login(db, request.username, request.password)
    user = db.query(User).filter(User.username == request.username).first()
    
    if not user or not verify_password(request.password, user.password_hash):
        _record_login_attempt(request.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    
    _clear_login_attempts(request.username)
    
    # 生成 Token
    access_token = create_access_token(user.id, user.username)
    
    # 获取用户权限和角色
    permissions = get_user_permissions_list(user.id, db)
    role_name = get_user_role(user.id, db)
    
    # 获取科室名称
    dept_name = None
    if user.dept_id:
        dept = db.query(Department).filter(Department.id == user.dept_id).first()
        dept_name = dept.name if dept else None
    
    user_info = UserInfo(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        dept_id=user.dept_id,
        dept_name=dept_name,
        role=role_name,
        permissions=permissions,
    )
    
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=user_info,
    )


@router.get("/me", response_model=UserInfo, tags=["认证"])
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户信息"""
    permissions = get_user_permissions_list(current_user.id, db)
    role_name = get_user_role(current_user.id, db)
    
    dept_name = None
    if current_user.dept_id:
        dept = db.query(Department).filter(Department.id == current_user.dept_id).first()
        dept_name = dept.name if dept else None
    
    return UserInfo(
        id=current_user.id,
        username=current_user.username,
        full_name=current_user.full_name,
        email=current_user.email,
        dept_id=current_user.dept_id,
        dept_name=dept_name,
        role=role_name,
        permissions=permissions,
    )


@router.post("/logout", response_model=MessageResponse, tags=["认证"])
async def logout(current_user: User = Depends(get_current_user)):
    """
    用户登出
    
    前端需要清除本地存储的 Token
    """
    return MessageResponse(message="Logged out successfully")


@router.get("", response_model=UserListResponse, tags=["用户管理"])
async def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取用户列表（仅管理员）
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can view user list",
        )
    
    # 查询用户总数
    total = db.query(User).count()
    
    # 分页查询
    users = db.query(User).offset((page - 1) * limit).limit(limit).all()
    
    # 批量预加载：一次性获取所有需要的 role_id 和 dept_id
    role_ids = {u.role_id for u in users if u.role_id}
    dept_ids = {u.dept_id for u in users if u.dept_id}
    
    roles_map = {}
    if role_ids:
        roles = db.query(Role).filter(Role.id.in_(role_ids)).all()
        roles_map = {r.id: r.name for r in roles}
    
    depts_map = {}
    if dept_ids:
        depts = db.query(Department).filter(Department.id.in_(dept_ids)).all()
        depts_map = {d.id: d.name for d in depts}
    
    # 批量获取所有权限（按 role_id 分组）
    perms_map = {}
    if role_ids:
        from sqlalchemy import tuple_
        perm_rows = db.query(RolePermission.role_id, Permission.name).join(
            Permission, Permission.id == RolePermission.permission_id
        ).filter(RolePermission.role_id.in_(role_ids)).all()
        for rid, pname in perm_rows:
            perms_map.setdefault(rid, []).append(pname)
    
    items = []
    for user in users:
        role_name = roles_map.get(user.role_id) if user.role_id else None
        dept_name = depts_map.get(user.dept_id) if user.dept_id else None
        permissions = perms_map.get(user.role_id, []) if user.role_id else []
        
        items.append(UserInfo(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            email=user.email,
            dept_id=user.dept_id,
            dept_name=dept_name,
            role=role_name,
            permissions=permissions,
        ))
    
    return UserListResponse(
        total=total,
        page=page,
        limit=limit,
        items=items,
    )


@router.post("", response_model=UserInfo, tags=["用户管理"])
async def create_user(
    request: UserCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    创建用户（仅管理员）
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can create users",
        )
    
    # 检查用户名是否已存在
    existing_user = db.query(User).filter(User.username == request.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )
    
    # 创建新用户
    new_user = User(
        username=request.username,
        password_hash=hash_password(request.password),
        full_name=request.full_name,
        email=request.email,
        dept_id=request.dept_id,
        role_id=request.role_id,
        is_active=True,
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    audit_logger.info("[AUDIT] 用户=%s id=%s 创建用户 target=%s role_id=%s dept_id=%s", current_user.username, current_user.id, new_user.username, new_user.role_id, new_user.dept_id)
    
    permissions = get_user_permissions_list(new_user.id, db)
    role_name = get_user_role(new_user.id, db)
    
    dept_name = None
    if new_user.dept_id:
        dept = db.query(Department).filter(Department.id == new_user.dept_id).first()
        dept_name = dept.name if dept else None
    
    return UserInfo(
        id=new_user.id,
        username=new_user.username,
        full_name=new_user.full_name,
        email=new_user.email,
        dept_id=new_user.dept_id,
        dept_name=dept_name,
        role=role_name,
        permissions=permissions,
    )


@router.put("/{user_id}", response_model=UserInfo, tags=["用户管理"])
async def update_user(
    user_id: int,
    request: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    编辑用户（仅管理员）
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can update users",
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # 更新字段
    if request.full_name is not None:
        user.full_name = request.full_name
    if request.email is not None:
        user.email = request.email
    if request.dept_id is not None:
        user.dept_id = request.dept_id
    if request.role_id is not None:
        user.role_id = request.role_id
    if request.is_active is not None:
        user.is_active = request.is_active
    
    user.updated_at = datetime.now()
    
    db.commit()
    db.refresh(user)
    audit_logger.info("[AUDIT] 用户=%s id=%s 更新用户 target=%s(%s)", current_user.username, current_user.id, user.username, user.id)
    
    permissions = get_user_permissions_list(user.id, db)
    role_name = get_user_role(user.id, db)
    
    dept_name = None
    if user.dept_id:
        dept = db.query(Department).filter(Department.id == user.dept_id).first()
        dept_name = dept.name if dept else None
    
    return UserInfo(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        dept_id=user.dept_id,
        dept_name=dept_name,
        role=role_name,
        permissions=permissions,
    )


@router.delete("/{user_id}", response_model=MessageResponse, tags=["用户管理"])
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    删除用户（仅管理员，实际上是禁用）
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can delete users",
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # 防止删除自己
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself",
        )
    
    # 禁用用户而不是删除
    user.is_active = False
    user.updated_at = datetime.now()

    db.commit()
    audit_logger.info("[AUDIT] 用户=%s id=%s 禁用用户 target=%s(%s)", current_user.username, current_user.id, user.username, user.id)
    
    return MessageResponse(message="User deleted successfully")


@router.post("/{user_id}/change-password", response_model=MessageResponse, tags=["用户管理"])
async def change_password(
    user_id: int,
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    修改用户密码
    
    - 用户可以修改自己的密码（需验证旧密码）
    - 管理员可以修改任何用户的密码（不需要验证旧密码）
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # 检查权限
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    is_admin = role and role.name == "admin"
    
    if user.id != current_user.id and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only change your own password",
        )
    
    # 如果不是管理员，需要验证旧密码
    if not is_admin:
        if not verify_password(request.old_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Old password is incorrect",
            )
    
    # 更新密码
    user.password_hash = hash_password(request.new_password)
    user.updated_at = datetime.now()

    db.commit()
    audit_logger.info("[AUDIT] 用户=%s id=%s 修改密码 target=%s(%s)", current_user.username, current_user.id, user.username, user.id)
    
    return MessageResponse(message="Password changed successfully")


@router.get("/{user_id}/permissions", response_model=dict, tags=["用户管理"])
async def get_user_permissions(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取用户的所有权限
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # 检查权限：用户可以查看自己的权限，管理员可以查看任何用户的权限
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    is_admin = role and role.name == "admin"
    
    if user.id != current_user.id and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only view your own permissions",
        )
    
    # 获取用户的权限
    if not user.role_id:
        return {
            "user_id": user.id,
            "username": user.username,
            "role": None,
            "permissions": [],
        }
    
    user_role = db.query(Role).filter(Role.id == user.role_id).first()
    permissions = db.query(Permission).join(
        RolePermission,
        Permission.id == RolePermission.permission_id
    ).filter(
        RolePermission.role_id == user.role_id
    ).all()
    
    return {
        "user_id": user.id,
        "username": user.username,
        "role": user_role.name if user_role else None,
        "permissions": [p.name for p in permissions],
    }
