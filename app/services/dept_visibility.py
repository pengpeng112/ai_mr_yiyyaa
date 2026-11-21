"""
科室可见性工具 —— 统一管理员/角色多科室/用户单科室的过滤逻辑。
"""
from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import false as sql_false

from app.models import User, Role, Department, RoleDepartment, PushLog
from app.services.data_scope import resolve_user_data_scope


def _role_name(db: Session, user: User) -> str:
    role = db.query(Role).filter(Role.id == user.role_id).first()
    return role.name if role else ""


def is_admin_user(db: Session, user: User) -> bool:
    return _role_name(db, user) == "admin"


def visible_dept_names(db: Session, user: User) -> list[str] | None:
    """admin 返回 None 表示全院；普通用户返回可见科室名称列表；无科室返回空列表。

    WP02（064 D5）：内部委托统一 data_scope 解析器——普通用户现在也尊重
    User/Role.timeliness_access_json 的个人/角色范围覆盖（selected/home），
    无配置时回退旧版 RoleDepartment 绑定与 dept_id（语义向后兼容）。
    """
    scope = resolve_user_data_scope(db, user)
    if scope.is_all:
        return None
    return list(scope.dept_names)


def apply_push_log_visibility(query, user: User, db: Session, dept_column=None):
    """admin 不加过滤；普通用户按可见科室名称过滤；无可见科室时返回空结果。"""
    if dept_column is None:
        dept_column = PushLog.dept
    names = visible_dept_names(db, user)
    if names is None:
        return query
    if not names:
        return query.filter(sql_false())
    return query.filter(dept_column.in_(names))
