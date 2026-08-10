"""
菜单权限配置 API
根据用户角色动态返回菜单配置

业务授权单一来源：本文件 MENU_GROUPS / MENU_CATALOG / MENU_CONFIG。
前端 route manifest 仅为组件白名单；最终可见菜单 = 服务端授权 ∩ 本地白名单。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Role, RoleMenu, User
from app.permissions import get_user_role

router = APIRouter()

MENU_SCHEMA_VERSION = 2

# 新信息架构分组（最多 6 个一级分组）
MENU_GROUPS = [
    {"id": "workbench", "label": "工作台", "icon": "", "order": 10},
    {"id": "quality", "label": "质控中心", "icon": "", "order": 20},
    {"id": "closure", "label": "闭环管理", "icon": "", "order": 30},
    {"id": "tasks", "label": "任务中心", "icon": "", "order": 40},
    {"id": "governance", "label": "规则与配置", "icon": "", "order": 50},
    {"id": "system", "label": "系统管理", "icon": "", "order": 60},
]

# 全部 menu ID 必须保留（RoleMenu 持久身份）；仅调整分组、顺序、文案。
# hidden=True：占位未实现，导航不返回；catalog 仍保留供权限管理参考。
# dev_only=True：生产环境服务端过滤。
MENU_CATALOG = [
    {
        "id": "dashboard",
        "label": "工作台",
        "icon": "",
        "path": "/workbench",
        "group": "workbench",
        "order": 10,
        "route_name": "workbench",
        "target": {"activeMenu": "dashboard"},
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "patient-qc",
        "label": "患者质控",
        "icon": "",
        "path": "/quality/patients",
        "group": "quality",
        "order": 10,
        "route_name": "quality-patients",
        "target": {"activeMenu": "patient-qc", "tab": "patients"},
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "audit",
        "label": "质控记录",
        "icon": "",
        "path": "/quality/records",
        "group": "quality",
        "order": 20,
        "route_name": "quality-records",
        "target": {"activeMenu": "audit"},
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "relay-alert-logs",
        "label": "告警记录",
        "icon": "",
        "path": "/closure/alerts",
        "group": "closure",
        "order": 10,
        "route_name": "closure-alerts",
        "target": {"activeMenu": "relay-alert-logs"},
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "feedback",
        "label": "整改反馈",
        "icon": "",
        "path": "/closure/feedback",
        "group": "closure",
        "order": 20,
        "route_name": "closure-feedback",
        "target": {"activeMenu": "feedback"},
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "push",
        "label": "手动推送",
        "icon": "",
        "path": "/tasks/push",
        "group": "tasks",
        "order": 10,
        "route_name": "tasks-push",
        "target": {"activeMenu": "push"},
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "push-progress",
        "label": "任务进度",
        "icon": "",
        "path": "/tasks/progress",
        "group": "tasks",
        "order": 20,
        "route_name": "tasks-progress",
        "target": {"activeMenu": "push-progress"},
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "scheduler",
        "label": "定时任务",
        "icon": "",
        "path": "/tasks/scheduler",
        "group": "tasks",
        "order": 30,
        "route_name": "tasks-scheduler",
        "target": {"activeMenu": "scheduler"},
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "audit-types",
        "label": "质控类型",
        "icon": "",
        "path": "/governance/audit-types",
        "group": "governance",
        "order": 10,
        "route_name": "governance-audit-types",
        "target": {"activeMenu": "audit-types"},
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "config",
        "label": "系统配置",
        "icon": "",
        "path": "/governance/config",
        "group": "governance",
        "order": 20,
        "route_name": "governance-config",
        "target": {"activeMenu": "config"},
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "relay",
        "label": "告警推送配置",
        "icon": "",
        "path": "/governance/relay",
        "group": "governance",
        "order": 30,
        "route_name": "governance-relay",
        "target": {"activeMenu": "relay"},
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "config-runtime",
        "label": "运行总览",
        "icon": "",
        "path": "/system/runtime",
        "group": "system",
        "order": 10,
        "route_name": "system-runtime",
        "target": {"activeMenu": "config", "tab": "runtime-summary"},
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "health",
        "label": "系统健康",
        "icon": "",
        "path": "/system/health",
        "group": "system",
        "order": 20,
        "route_name": "system-health",
        "target": {"activeMenu": "health"},
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "access",
        "label": "用户与权限",
        "icon": "",
        "path": "/system/access",
        "group": "system",
        "order": 30,
        "route_name": "system-access",
        "target": {"activeMenu": "access"},
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "debug",
        "label": "Dify 调试",
        "icon": "",
        "path": "/system/debug",
        "group": "system",
        "order": 40,
        "route_name": "system-debug",
        "target": {"activeMenu": "debug"},
        "hidden": False,
        "dev_only": True,
    },
    # 占位：完成真实功能前导航隐藏；ID 保留以兼容 RoleMenu
    {
        "id": "oracle-status",
        "label": "Oracle 连接",
        "icon": "",
        "path": "/system/oracle-status",
        "group": "system",
        "order": 90,
        "route_name": "system-oracle-status",
        "target": {"activeMenu": "oracle-status"},
        "hidden": True,
        "dev_only": False,
    },
    {
        "id": "system-logs",
        "label": "运行日志",
        "icon": "",
        "path": "/system/logs",
        "group": "system",
        "order": 100,
        "route_name": "system-logs",
        "target": {"activeMenu": "system-logs"},
        "hidden": True,
        "dev_only": False,
    },
]
MENU_MAP = {item["id"]: item for item in MENU_CATALOG}

# 默认角色菜单（RoleMenu 未分配时使用）；ID 集合保持与历史兼容
MENU_CONFIG = {
    "admin": [item["id"] for item in MENU_CATALOG],
    "dept_manager": ["dashboard", "patient-qc", "audit", "feedback", "scheduler", "health"],
    "clinician": ["dashboard", "audit", "feedback"],
    "auditor": ["dashboard", "patient-qc", "audit", "feedback", "health"],
}

# 角色默认首页 menu_id（产品决策建议；仅元数据，不改变授权）
ROLE_DEFAULT_HOME = {
    "admin": "dashboard",
    "dept_manager": "patient-qc",
    "auditor": "dashboard",
    "clinician": "feedback",
}


def _runtime_environment() -> str:
    return str(os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "development").strip().lower()


def is_production_environment() -> bool:
    return _runtime_environment() in {"production", "prod"}


def filter_menu_items_for_navigation(
    items: List[Dict[str, Any]],
    *,
    production: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """导航可见过滤：隐藏占位 + 生产过滤 dev_only。"""
    prod = is_production_environment() if production is None else production
    result: List[Dict[str, Any]] = []
    for item in items:
        if not item:
            continue
        if item.get("hidden"):
            continue
        if prod and item.get("dev_only"):
            continue
        result.append(item)
    return result


def groups_for_menu_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    used: Set[str] = {str(item.get("group") or "") for item in items if item.get("group")}
    return [g for g in MENU_GROUPS if g["id"] in used]


def build_menu_response(
    menu_ids: List[str],
    role_name: str,
    *,
    production: Optional[bool] = None,
) -> Dict[str, Any]:
    raw = [MENU_MAP[mid] for mid in menu_ids if mid in MENU_MAP]
    # 保持调用方给定顺序，再按 order 稳定排序
    menu = filter_menu_items_for_navigation(raw, production=production)
    menu = sorted(menu, key=lambda x: (int(x.get("order") or 999), x.get("id") or ""))
    groups = groups_for_menu_items(menu)
    return {
        "schema_version": MENU_SCHEMA_VERSION,
        "role": role_name,
        "menu": menu,
        "groups": groups,
        "default_home": ROLE_DEFAULT_HOME.get(role_name) or (menu[0]["id"] if menu else None),
    }


def _require_admin(current_user: User, db: Session) -> None:
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can access full menu catalog",
        )


@router.get("/menu", tags=["菜单"])
async def get_menu(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取当前用户菜单配置
    优先读取角色菜单分配，未分配时使用默认角色菜单
    """
    role_name = get_user_role(current_user.id, db)
    if not role_name:
        return {
            "schema_version": MENU_SCHEMA_VERSION,
            "role": None,
            "menu": [],
            "groups": [],
            "default_home": None,
        }

    assigned_menu_ids = [
        row.menu_id
        for row in db.query(RoleMenu).filter(RoleMenu.role_id == current_user.role_id).all()
    ]
    menu_ids = assigned_menu_ids if assigned_menu_ids else MENU_CONFIG.get(role_name, [])
    return build_menu_response(menu_ids, role_name)


@router.get("/menu/all", tags=["菜单"])
async def get_all_menus(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取所有菜单配置（用于前端权限管理）
    需要管理员；与 /api/roles/menus/catalog 对齐守卫。
    """
    _require_admin(current_user, db)
    return {
        "schema_version": MENU_SCHEMA_VERSION,
        "groups": MENU_GROUPS,
        "catalog": MENU_CATALOG,
        "menus": MENU_CONFIG,
        "default_homes": ROLE_DEFAULT_HOME,
    }
