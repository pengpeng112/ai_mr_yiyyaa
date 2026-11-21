# -*- coding: utf-8 -*-
"""全院统一 RBAC 数据范围解析器（064 总计划 WP02 任务 1，用户拍板 D5）。

统一三套割裂的科室权限口径（dept_visibility / timeliness_access / prearchive_admin）：
- 三种范围：all（全院）/ home（仅本人所属科室）/ selected（指定多科室）；
- 用户个人覆盖（User.timeliness_access_json）优先于角色默认（Role.timeliness_access_json），
  再回退旧版 RoleDepartment 绑定（legacy_role_dept），最后安全降级 home/空集；
- **绝无科室归属的普通用户绝不放大成全院**——安全默认拒绝（空集）。

自包含实现（不 import dept_visibility/timeliness_access，避免循环 import）；
两个旧模块的对外签名与返回结构保持不变（见各自文件内的委托注释）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import false as sql_false

from app.models import Department, PushLog, QCFeedback, QCRecordAlertLog, Role, RoleDepartment, User
from app.timeliness.models import TLEvent
from app.schemas import TimelinessAccessSettings

ScopeLiteral = Literal["all", "home", "selected"]


@dataclass(frozen=True)
class ResolvedDataScope:
    scope: ScopeLiteral
    source: str  # "admin" | "user" | "role" | "legacy_role_dept" | "default"
    dept_codes: tuple[str, ...]
    dept_names: tuple[str, ...]
    dept_ids: tuple[int, ...]
    label: str   # 中文展示标签

    @property
    def is_all(self) -> bool:
        return self.scope == "all"


def _is_admin(db: Session, user: User) -> bool:
    role = db.query(Role).filter(Role.id == user.role_id).first() if user.role_id else None
    return bool(role and role.name == "admin")


def _read_scope_settings(entity) -> TimelinessAccessSettings | None:
    raw = getattr(entity, "timeliness_access_json", None) if entity is not None else None
    if not raw:
        return None
    try:
        return TimelinessAccessSettings.model_validate_json(raw)
    except Exception:  # noqa: BLE001 — 损坏 JSON 按未配置处理
        return None


def _home_triplet(db: Session, user: User) -> tuple[tuple[str, ...], tuple[str, ...], tuple[int, ...]]:
    dept_id = getattr(user, "dept_id", None)
    if dept_id is None:
        return (), (), ()
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        return (), (), ()
    code = (dept.code or dept.name or "").strip()
    name = (dept.name or code).strip()
    return (code,) if code else (), (name,) if name else (), (dept.id,)


def _resolve_selected_triplet(
    db: Session, department_codes: list[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[int, ...]]:
    """department_codes 兼容传 code 或 id（字符串数字视为 id 候选）。"""
    codes = [str(c or "").strip() for c in (department_codes or []) if str(c or "").strip()]
    if not codes:
        return (), (), ()
    int_ids: set[int] = set()
    for c in codes:
        if c.isdigit():
            int_ids.add(int(c))
    rows = db.query(Department).filter(
        Department.code.in_(codes) | Department.name.in_(codes) | Department.id.in_(int_ids)
    ).all() if int_ids else db.query(Department).filter(
        Department.code.in_(codes) | Department.name.in_(codes)
    ).all()
    ordered: list[Department] = []
    seen_ids: set[int] = set()
    for want in codes:  # 保持调用方给定顺序去重（兼容 code / name / 数字 id）
        for d in rows:
            if d.id in seen_ids:
                continue
            if d.code == want or d.name == want or (want.isdigit() and str(d.id) == want):
                ordered.append(d)
                seen_ids.add(d.id)
    return (
        tuple((d.code or d.name or "").strip() for d in ordered),
        tuple((d.name or "").strip() for d in ordered),
        tuple(d.id for d in ordered),
    )


def _label_for(scope: str, source: str, names: tuple[str, ...]) -> str:
    if scope == "all":
        return "全院"
    if scope == "home" and names:
        return f"仅本科室（{names[0]}）"
    if scope == "selected":
        return f"指定 {len(names)} 个科室"
    if source == "default":
        return "未配置（默认仅本科室）"
    return "无可见科室"


def resolve_user_data_scope(db: Session, user: User) -> ResolvedDataScope:
    """解析用户生效数据范围（优先级见模块 docstring）。"""
    if _is_admin(db, user):
        return ResolvedDataScope("all", "admin", (), (), (), "全院")

    # Step 2：用户个人覆盖
    settings = _read_scope_settings(user)
    source = "user"
    # Step 3：角色默认
    if settings is None and user.role_id is not None:
        role = db.query(Role).filter(Role.id == user.role_id).first()
        settings = _read_scope_settings(role)
        source = "role"

    if settings is not None:
        if settings.scope == "all":
            return ResolvedDataScope("all", source, (), (), (), "全院")
        if settings.scope == "home":
            codes, names, ids = _home_triplet(db, user)
            if codes:
                return ResolvedDataScope("home", source, codes, names, ids,
                                         _label_for("home", source, names))
            # home 但无科室归属 → 安全空集（绝不放大）
            return ResolvedDataScope("home", source, (), (), (), "无可见科室")
        codes, names, ids = _resolve_selected_triplet(db, settings.department_codes)
        if codes:
            return ResolvedDataScope("selected", source, codes, names, ids,
                                     _label_for("selected", source, names))
        return ResolvedDataScope("selected", source, (), (), (), "无可见科室")

    # Step 4：旧版 RoleDepartment 绑定
    if user.role_id is not None:
        role_depts = (
            db.query(Department)
            .join(RoleDepartment, RoleDepartment.dept_id == Department.id)
            .filter(RoleDepartment.role_id == user.role_id)
            .all()
        )
        if role_depts:
            ordered = sorted(role_depts, key=lambda d: d.id)
            codes = tuple((d.code or d.name or "").strip() for d in ordered)
            names = tuple((d.name or "").strip() for d in ordered)
            ids = tuple(d.id for d in ordered)
            return ResolvedDataScope("selected", "legacy_role_dept", codes, names, ids,
                                     _label_for("selected", "legacy_role_dept", names))

    # Step 5：默认安全最小权限（home；无科室则空集）
    codes, names, ids = _home_triplet(db, user)
    if codes:
        return ResolvedDataScope("home", "default", codes, names, ids,
                                 _label_for("home", "default", names))
    return ResolvedDataScope("home", "default", (), (), (), "无可见科室")


def user_effective_scope_payload(db: Session, user: User) -> dict:
    """UserInfo.effective_scope 只读字段（批量计算入口见 users.py 预解析）。"""
    scope = resolve_user_data_scope(db, user)
    return {
        "scope": scope.scope,
        "source": scope.source,
        "label": scope.label,
        "dept_count": len(scope.dept_codes),
    }


# ---- 标准查询过滤辅助（Oracle/SQLite 兼容；空集安全拒绝） ----


def _scope_dept_terms(scope: ResolvedDataScope, column):
    """按 names | codes 构造 IN 条件；全空返回 None（调用方落 sql_false）。"""
    terms = {t for t in (*scope.dept_names, *scope.dept_codes) if t}
    if scope.is_all:
        return None
    if not terms:
        return None
    return column.in_(sorted(terms))


def apply_pushlog_scope(query, scope: ResolvedDataScope, model=PushLog):
    """PushLog.dept 匹配 names | codes；all 原样返回；空集安全拒绝。"""
    terms = _scope_dept_terms(scope, model.dept)
    if scope.is_all:
        return query
    if terms is None:
        return query.filter(sql_false())
    return query.filter(terms)


def apply_alert_scope(query, scope: ResolvedDataScope, model=QCRecordAlertLog):
    """QCRecordAlertLog.dept 匹配 names | codes。"""
    terms = _scope_dept_terms(scope, model.dept)
    if scope.is_all:
        return query
    if terms is None:
        return query.filter(sql_false())
    return query.filter(terms)


def apply_feedback_scope(query, scope: ResolvedDataScope, model=QCFeedback):
    """QCFeedback 按 dept_id.in_(ids)；无 ids 时回退关联 PushLog.dept 匹配。"""
    if scope.is_all:
        return query
    if scope.dept_ids:
        return query.filter(model.dept_id.in_(scope.dept_ids))
    terms = _scope_dept_terms(scope, PushLog.dept)
    if terms is None:
        return query.filter(sql_false())
    return query.join(PushLog, PushLog.id == model.push_log_id).filter(terms)


def apply_tlevent_scope(query, scope: ResolvedDataScope, model=TLEvent):
    """TLEvent.dept_code.in_(codes)；all 原样返回；空集安全拒绝。"""
    if scope.is_all:
        return query
    if not scope.dept_codes:
        return query.filter(sql_false())
    return query.filter(model.dept_code.in_(scope.dept_codes))
