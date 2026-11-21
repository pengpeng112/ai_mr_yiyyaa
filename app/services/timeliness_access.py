"""病历时效的查看范围。科室归属和操作权限分别由现有账户与角色管理。"""
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.sql.expression import false

from app.models import Department, Role
from app.schemas import TimelinessAccessSettings
from app.services.dept_visibility import visible_dept_names


def read_settings(account):
    raw = account.timeliness_access_json if account is not None else None
    return TimelinessAccessSettings.model_validate_json(raw) if raw else None


def serialize_settings(db, settings):
    if settings is None:
        return None
    if settings.department_codes:
        existing = {
            code for (code,) in db.query(Department.code)
            .filter(Department.code.in_(settings.department_codes)).all()
        }
        if existing != set(settings.department_codes):
            raise HTTPException(422, "所选科室已变更，请刷新科室目录后重新选择")
    return settings.model_dump_json()


@dataclass
class TimelinessVisibility:
    # None 表示全院，空集合表示无可见科室。
    codes: set[str] | None
    default_dept: str = ""

    def apply(self, query, column):
        if self.codes is None:
            return query
        return query.filter(column.in_(self.codes) if self.codes else false())

    def allows(self, code):
        return self.codes is None or code in self.codes


def _legacy_codes(db, user):
    names = visible_dept_names(db, user)
    if names is None:
        return None
    return {code or name for code, name in db.query(Department.code, Department.name)
            .filter(Department.name.in_(names)).all()}


def timeliness_visibility(db, user, *, for_write=False):
    if getattr(user, "his_virtual", False):
        code = getattr(user, "his_dept_code", "")
        return TimelinessVisibility({code} if code and not for_write else set())

    role = db.get(Role, user.role_id) if user.role_id is not None else None
    if role and role.name == "admin":
        return TimelinessVisibility(None)
    user_settings = read_settings(user)
    settings = user_settings or read_settings(role)
    if settings is None:
        return TimelinessVisibility(_legacy_codes(db, user))

    department = db.get(Department, user.dept_id) if user.dept_id is not None else None
    home = (department.code or department.name) if department else ""
    if settings.scope == "all":
        codes = None
    elif settings.scope == "home":
        codes = {home} if home else set()
    else:
        codes = {code for (code,) in db.query(Department.code)
                 .filter(Department.code.in_(settings.department_codes)).all()}

    if for_write:
        legacy = _legacy_codes(db, user)
        if legacy is not None:
            codes = legacy if codes is None else codes & legacy
    visibility = TimelinessVisibility(codes)
    if settings.default_view == "home" and home and visibility.allows(home):
        visibility.default_dept = home
    return visibility


def timeliness_department_options(db, user):
    visibility = timeliness_visibility(db, user)
    if getattr(user, "his_virtual", False):
        departments = [{"id": 0, "code": code, "name": user.his_dept_name or code}
                       for code in visibility.codes or ()]
    else:
        departments = [{"id": dept.id, "code": dept.code or dept.name, "name": dept.name}
                       for dept in db.query(Department).order_by(Department.name)
                       if visibility.allows(dept.code or dept.name)]
    return {"departments": departments, "default_dept": visibility.default_dept,
            "all_hospital": visibility.codes is None}
