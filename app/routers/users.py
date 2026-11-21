"""
用户认证与管理 API
支持登录、用户 CRUD、权限查询
"""
import time
import threading
import logging
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Response, status, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.models import User, Role, Department, Permission, RolePermission, RoleDepartment
from app.schemas import (
    LoginRequest, LoginResponse, UserInfo, UserCreateRequest,
    UserUpdateRequest, UserListResponse, MessageResponse,
    ChangePasswordRequest,
    UserBatchUpdateRequest,
)
from app.auth import (
    AUTH_COOKIE_NAME, JWT_EXPIRATION_HOURS, auth_cookie_secure,
    hash_password, verify_password, verify_setup_password, create_access_token,
    get_current_user
)
from app.permissions import (
    require_role, get_user_permissions as get_user_permissions_list, get_user_role, is_admin
)
from app.services.timeliness_access import read_settings, serialize_settings

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


@router.post("/login", response_model=LoginResponse, tags=["认证"])
async def login(request: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """
    用户登录

    返回 JWT Token 和用户信息；同时下发 HttpOnly Cookie（SameSite=Strict）。
    Bearer 兼容期保留：access_token 仍随响应体返回。
    """
    _check_login_rate_limit(request.username)
    user = db.query(User).filter(User.username == request.username).first()
    
    verify = verify_setup_password if user and user.password_setup_required else verify_password
    if not user or not verify(request.password, user.password_hash):
        _record_login_attempt(request.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    
    if not user.is_active or user.directory_pending:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    if user.password_setup_required:
        raise HTTPException(status_code=403, detail="请先从企业微信验证身份，设置个人密码后再登录电脑端")
    
    _clear_login_attempts(request.username)
    
    # 生成 Token
    access_token = create_access_token(user.id, user.username, auth_method="password")
    
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
        is_active=user.is_active,
    )
    
    # HttpOnly Cookie：浏览器会话主通道（023 P1-03）
    response.set_cookie(
        AUTH_COOKIE_NAME,
        access_token,
        max_age=JWT_EXPIRATION_HOURS * 3600,
        httponly=True,
        samesite="strict",
        secure=auth_cookie_secure(),
        path="/",
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
        is_active=current_user.is_active,
    )


@router.post("/logout", response_model=MessageResponse, tags=["认证"])
async def logout(response: Response, current_user: User = Depends(get_current_user)):
    """
    用户登出

    服务端清除认证 Cookie；前端同时清理本地存储的 Token
    """
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return MessageResponse(message="Logged out successfully")


@router.get("", response_model=UserListResponse, tags=["用户管理"])
async def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=100),
    role_id: int | None = Query(None),
    unassigned_role: bool = Query(False),
    dept_id: int | None = Query(None),
    is_active: bool | None = Query(None),
    directory_pending: bool | None = Query(None),
    scope: str | None = Query(None, description="all|home|selected 按生效数据范围过滤"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取用户列表（仅管理员）；WP02 追加可选筛选（旧参数 page/limit/q 不变）。
    scope 筛选：全量取数后内存精筛（≤2,383 行），分页 total 精确。
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can view user list",
        )
    
    query = db.query(User)
    keyword = (q or "").strip()
    if keyword:
        query = query.filter(or_(User.username.contains(keyword, autoescape=True),
                                 User.full_name.contains(keyword, autoescape=True)))
    if role_id is not None:
        query = query.filter(User.role_id == role_id)
    if unassigned_role:
        query = query.filter(User.role_id.is_(None))
    if dept_id is not None:
        query = query.filter(User.dept_id == dept_id)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if directory_pending is not None:
        query = query.filter(User.directory_pending == directory_pending)

    # scope 筛选：全量取数内存精筛（显式配置两类：个人覆盖 + 角色默认；见 DELIVERY 说明）
    scope_filter_active = scope in ("all", "home", "selected")
    if scope_filter_active:
        from app.services.timeliness_access import read_settings as _read_settings
        candidates = query.order_by(User.id).all()
        role_json_map = {}
        for r in db.query(Role).all():
            role_json_map[r.id] = _read_settings(r)
        legacy_role_ids = {
            rid for (rid,) in db.query(RoleDepartment.role_id).distinct().all()
        }
        scoped_users = []
        for u in candidates:
            settings = _read_settings(u) or role_json_map.get(u.role_id)
            if settings is not None:
                effective = settings.scope
            elif u.role_id in legacy_role_ids:
                effective = "selected"
            elif u.dept_id:
                effective = "home"
            else:
                effective = "home"  # default（无科室 → 空集，scope 名仍归 home）
            if effective == scope:
                scoped_users.append(u)
        total = len(scoped_users)
        users = scoped_users[(page - 1) * limit: (page - 1) * limit + limit]
    else:
        total = query.count()
        users = query.order_by(User.id).offset((page - 1) * limit).limit(limit).all()
    
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
        perm_rows = db.query(RolePermission.role_id, Permission.name).join(
            Permission, Permission.id == RolePermission.permission_id
        ).filter(RolePermission.role_id.in_(role_ids)).all()
        for rid, pname in perm_rows:
            perms_map.setdefault(rid, []).append(pname)
    
    items = []
    scopes_map = _bulk_effective_scopes(db, users) if users else {}
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
            is_active=user.is_active,
            directory_pending=user.directory_pending,
            timeliness_access=read_settings(user),
            effective_scope=scopes_map.get(user.id),
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
        timeliness_access_json=serialize_settings(db, request.timeliness_access),
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
        is_active=new_user.is_active,
        timeliness_access=read_settings(new_user),
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
    
    if user.directory_pending and request.is_active is True:
        role_id = request.role_id if "role_id" in request.model_fields_set else user.role_id
        if role_id is None or db.get(Role, role_id) is None:
            raise HTTPException(422, "请先分配角色，再启用同步账号")
        user.directory_pending = False

    # 更新字段
    if request.full_name is not None:
        user.full_name = request.full_name
    if request.email is not None:
        user.email = request.email
    if 'dept_id' in request.model_fields_set:
        user.dept_id = request.dept_id
    if 'role_id' in request.model_fields_set:
        user.role_id = request.role_id
    if request.is_active is not None:
        user.is_active = request.is_active
    old_access = user.timeliness_access_json
    if "timeliness_access" in request.model_fields_set:
        user.timeliness_access_json = serialize_settings(db, request.timeliness_access)
    
    user.updated_at = datetime.now()
    
    db.commit()
    db.refresh(user)
    if old_access != user.timeliness_access_json:
        audit_logger.info("[AUDIT] 用户=%s 更新时效查看范围 target=%s before=%s after=%s",
                          current_user.username, user.username, old_access, user.timeliness_access_json)
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
        is_active=user.is_active,
        directory_pending=user.directory_pending,
        timeliness_access=read_settings(user),
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
    user.directory_pending = False
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
    - 管理员重置他人无需旧密码；修改自己的密码仍需验证旧密码
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
    
    # 修改自己的密码始终需要旧密码；管理员重置他人才可免旧密码
    if user.id == current_user.id or not is_admin:
        if not verify_password(request.old_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Old password is incorrect",
            )
    
    # 更新密码
    user.password_hash = hash_password(request.new_password)
    user.password_setup_required = False
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


# ---- WP02（064 D5）：统一数据范围批量解析（禁止 N+1） ----

def _bulk_effective_scopes(db: Session, users: list) -> dict[int, dict]:
    """批量解析 effective_scope：预取 role/user JSON 与 RoleDepartment/Department 映射后内存解析。"""
    from app.services.data_scope import ResolvedDataScope, _resolve_selected_triplet, _label_for
    from app.schemas import TimelinessAccessSettings

    role_ids = {u.role_id for u in users if u.role_id}
    dept_ids = {u.dept_id for u in users if u.dept_id}
    roles = {r.id: r for r in db.query(Role).filter(Role.id.in_(role_ids)).all()} if role_ids else {}
    depts = {d.id: d for d in db.query(Department).filter(Department.id.in_(dept_ids)).all()} if dept_ids else {}
    # RoleDepartment 绑定（legacy）
    legacy_map: dict[int, list] = {}
    if role_ids:
        from sqlalchemy import or_ as _or
        binds = list(role_ids)
        rows = db.query(RoleDepartment.role_id, Department).join(
            Department, Department.id == RoleDepartment.dept_id
        ).filter(RoleDepartment.role_id.in_(binds)).all()
        for rid, d in rows:
            legacy_map.setdefault(rid, []).append(d)

    def _read_json(entity):
        raw = getattr(entity, "timeliness_access_json", None) if entity is not None else None
        if not raw:
            return None
        try:
            return TimelinessAccessSettings.model_validate_json(raw)
        except Exception:
            return None

    def _triplet_from_codes(codes):
        codes = [str(c or "").strip() for c in codes or [] if str(c or "").strip()]
        if not codes:
            return (), (), ()
        int_ids = {int(c) for c in codes if c.isdigit()}
        q = db.query(Department).filter(
            Department.code.in_(codes) | Department.name.in_(codes)
        )
        if int_ids:
            q = q.filter(
                (Department.code.in_(codes)) | (Department.name.in_(codes)) | (Department.id.in_(int_ids))
            )
        rows = q.all()
        ordered, seen = [], set()
        for want in codes:
            for d in rows:
                if d.id in seen:
                    continue
                if d.code in codes or d.name in codes:
                    ordered.append(d)
                    seen.add(d.id)
        return (
            tuple((d.code or d.name or "").strip() for d in ordered),
            tuple((d.name or "").strip() for d in ordered),
            tuple(d.id for d in ordered),
        )

    result: dict[int, dict] = {}
    for u in users:
        role = roles.get(u.role_id) if u.role_id else None
        is_admin = bool(role and role.name == "admin")
        settings = _read_json(u)
        source = "user"
        if settings is None:
            settings = _read_json(role)
            source = "role"
        if is_admin:
            payload = {"scope": "all", "source": "admin", "label": "全院", "dept_count": 0}
        elif settings is not None:
            if settings.scope == "all":
                payload = {"scope": "all", "source": source, "label": "全院", "dept_count": 0}
            elif settings.scope == "home":
                d = depts.get(u.dept_id) if u.dept_id else None
                if d:
                    code = (d.code or d.name or "").strip()
                    payload = {"scope": "home", "source": source,
                               "label": f"仅本科室（{d.name or code}）", "dept_count": 1}
                else:
                    payload = {"scope": "home", "source": source,
                               "label": "无可见科室", "dept_count": 0}
            else:
                codes, names, ids = _triplet_from_codes(settings.department_codes)
                payload = {"scope": "selected", "source": source,
                           "label": f"指定 {len(names)} 个科室", "dept_count": len(codes)}
        else:
            legacy = legacy_map.get(u.role_id) if u.role_id else None
            if legacy:
                payload = {"scope": "selected", "source": "legacy_role_dept",
                           "label": f"指定 {len(legacy)} 个科室", "dept_count": len(legacy)}
            elif u.dept_id and u.dept_id in depts:
                d = depts[u.dept_id]
                payload = {"scope": "home", "source": "default",
                           "label": f"仅本科室（{d.name or d.code}）", "dept_count": 1}
            else:
                payload = {"scope": "home", "source": "default",
                           "label": "无可见科室", "dept_count": 0}
        result[u.id] = payload
    return result


@router.post("/batch-update", response_model=UserListResponse, tags=["用户管理"])
async def batch_update_users(
    body: UserBatchUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量更新用户角色/状态/数据范围（WP02；仅管理员；单批 ≤200）。

    安全护栏：禁禁用自己；禁禁用或降权最后一个活跃 admin；写操作审计日志。
    """
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only admin can batch update users")

    user_ids = list(dict.fromkeys(body.user_ids))
    if len(user_ids) > 200:
        raise HTTPException(status_code=400, detail="batch size limited to 200 users")
    targets = db.query(User).filter(User.id.in_(user_ids)).all()
    found_ids = {u.id for u in targets}
    missing = [uid for uid in user_ids if uid not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail=f"users not found: {missing[:10]}")

    active_admins = [
        u for u in db.query(User).join(Role, Role.id == User.role_id)
        .filter(Role.name == "admin", User.is_active == True).all()  # noqa: E712
    ]
    active_admin_ids = {u.id for u in active_admins}

    if body.is_active is False:
        if current_user.id in user_ids:
            raise HTTPException(status_code=400, detail="cannot deactivate yourself")
        # 目标中含 admin 且将导致最后一个活跃 admin 被禁用 → 拒绝
        will_disable_admins = [aid for aid in user_ids if aid in active_admin_ids]
        if len(active_admins) - len(will_disable_admins) < 1:
            raise HTTPException(status_code=400,
                                detail="cannot deactivate the last active admin")

    if body.role_id is not None and body.is_active is False:
        # 降权+禁用组合下同样校验：目标 admin 被移出 admin 角色
        will_lose_admin = [aid for aid in user_ids if aid in active_admin_ids]
        if len(active_admins) - len(will_lose_admin) < 1:
            raise HTTPException(status_code=400,
                                detail="cannot demote the last active admin")

    new_role = None
    if body.role_id is not None:
        new_role = db.query(Role).filter(Role.id == body.role_id).first()
        if not new_role:
            raise HTTPException(status_code=404, detail=f"role not found: {body.role_id}")

    scope_json = None
    if body.data_scope is not None and body.data_scope.mode != "inherit_role":
        from app.services.timeliness_access import serialize_settings
        from app.schemas import TimelinessAccessSettings
        settings = TimelinessAccessSettings(
            scope=body.data_scope.mode,
            department_codes=sorted(set(body.data_scope.department_codes or [])),
            default_view="home",
        )
        scope_json = serialize_settings(db, settings)  # 校验科室存在性（422 语义与既有一致）

    changed = 0
    for user in targets:
        if body.role_id is not None:
            user.role_id = body.role_id
        if body.is_active is not None:
            user.is_active = body.is_active
        if body.data_scope is not None:
            # inherit_role → 清空个人覆盖回角色默认
            user.timeliness_access_json = scope_json
        changed += 1

    # 审计日志（脱敏：只记操作者与数量，不记目标身份明细）
    import logging as _logging
    _logging.getLogger("audit.users").info(
        "batch update users: operator=%s changed=%d role_id=%s is_active=%s scope_mode=%s",
        current_user.username, changed,
        body.role_id, body.is_active,
        body.data_scope.mode if body.data_scope else None,
    )
    db.commit()

    # 返回更新后的整页（按请求 user_ids 顺序返回这些用户的最新状态）
    refreshed = db.query(User).filter(User.id.in_(user_ids)).order_by(User.id).all()
    scopes = _bulk_effective_scopes(db, refreshed)
    items = []
    for user in refreshed:
        role_name = None
        r = db.query(Role).filter(Role.id == user.role_id).first() if user.role_id else None
        role_name = r.name if r else None
        dept_name = None
        d = db.query(Department).filter(Department.id == user.dept_id).first() if user.dept_id else None
        dept_name = d.name if d else None
        items.append(UserInfo(
            id=user.id, username=user.username, full_name=user.full_name,
            email=user.email, dept_id=user.dept_id, dept_name=dept_name,
            role=role_name, permissions=[], is_active=user.is_active,
            directory_pending=user.directory_pending,
            timeliness_access=read_settings(user),
            effective_scope=scopes.get(user.id),
        ))
    return UserListResponse(total=len(items), page=1, limit=len(items), items=items)
