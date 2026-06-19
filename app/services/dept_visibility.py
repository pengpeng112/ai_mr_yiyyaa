"""
科室可见性工具 —— 统一管理员/角色多科室/用户单科室的过滤逻辑。
"""
from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import false as sql_false

from app.models import User, Role, Department, RoleDepartment, PushLog


def _role_name(db: Session, user: User) -> str:
    role = db.query(Role).filter(Role.id == user.role_id).first()
    return role.name if role else ""


def is_admin_user(db: Session, user: User) -> bool:
    return _role_name(db, user) == "admin"


def visible_dept_names(db: Session, user: User) -> list[str] | None:
    """admin 返回 None 表示全院；普通用户返回可见科室名称列表；无科室返回空列表。"""
    if is_admin_user(db, user):
        return None

    names: list[str] = []
    role_depts = (
        db.query(Department.name)
        .join(RoleDepartment, RoleDepartment.dept_id == Department.id)
        .filter(RoleDepartment.role_id == user.role_id)
        .all()
    )
    for (name,) in role_depts:
        if name and str(name).strip():
            names.append(str(name).strip())

    if not names and user.dept_id:
        dept = db.query(Department).filter(Department.id == user.dept_id).first()
        if dept and dept.name and str(dept.name).strip():
            names.append(str(dept.name).strip())

    return names


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
