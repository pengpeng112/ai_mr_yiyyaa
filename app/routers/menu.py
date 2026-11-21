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

# 五大业务分组（2026-11-15 菜单体系重构：职责分明 + 全中文去黑话）
MENU_GROUPS: List[Dict[str, Any]] = [
    {"id": "workbench", "label": "质控总览", "icon": "", "order": 10},
    {"id": "timeliness", "label": "病历时效管理", "icon": "", "order": 20},
    {"id": "quality", "label": "内涵与终末质控", "icon": "", "order": 30},
    {"id": "governance", "label": "质控规则中心", "icon": "", "order": 40},
    {"id": "system", "label": "系统与运维", "icon": "", "order": 50},
]

# 全部 menu ID 必须保留（RoleMenu 持久身份 + 前端 route-manifest 契约测试）；
# 仅调整分组、顺序、文案。hidden=True：侧栏/导航不返回，catalog 保留供权限管理
# 与路由直达兼容（push-progress/config-runtime 保留给顶栏「任务」按钮与书签直达，
# 由前端 DIRECT_ACCESS 豁免放行）；dev_only=True：生产环境服务端过滤。
# legacy_tab：旧版 static 页签标识（信息性元数据，供跨版对照）。
MENU_CATALOG: List[Dict[str, Any]] = [
    # 1. 质控总览 (workbench)
    {
        "id": "dashboard",
        "label": "质控总览",
        "icon": "",
        "path": "/workbench",
        "group": "workbench",
        "order": 10,
        "route_name": "workbench",
        "target": {"activeMenu": "dashboard"},
        "legacy_tab": "dashboard",
        "hidden": False,
        "dev_only": False,
    },
    # 2. 病历时效管理 (timeliness) —— 医务部与临床高频专区
    {
        # 病历时效质控：解锁审批与人工豁免集中处理（2026-11-15 从月报第 2 页签独立）
        "id": "timeliness-approvals",
        "label": "解锁审批与豁免",
        "icon": "",
        "path": "/timeliness/approvals",
        "group": "timeliness",
        "order": 10,
        "route_name": "timeliness-approvals",
        "target": {"activeMenu": "timeliness-approvals"},
        "legacy_tab": "timeliness-approvals",
        "hidden": False,
        "dev_only": False,
    },
    {
        # WP02（064 D2/D5）：时效统计分析（置于 timeliness 组首位；WP-03 填充页面）
        "id": "timeliness-stats",
        "label": "时效统计分析",
        "icon": "",
        "path": "/timeliness/stats",
        "group": "timeliness",
        "order": 5,
        "route_name": "timeliness-stats",
        "target": {"activeMenu": "timeliness-stats"},
        "legacy_tab": "timeliness-stats",
        "hidden": False,
        "dev_only": False,
    },
    {
        # 病历时效质控（ai_mrzk-timeliness T6）：在院事件台账（只读）
        "id": "timeliness-events",
        "label": "在院时效台账",
        "icon": "",
        "path": "/quality/timeliness-events",
        "group": "timeliness",
        "order": 20,
        "route_name": "quality-timeliness-events",
        "target": {"activeMenu": "timeliness-events"},
        "legacy_tab": "timeliness-events",
        "hidden": False,
        "dev_only": False,
    },
    {
        # 病历时效质控（T6）：月度统计（只读；导出需 timeliness_export）
        "id": "timeliness-monthly",
        "label": "时效月度考核",
        "icon": "",
        "path": "/quality/timeliness-monthly",
        "group": "timeliness",
        "order": 30,
        "route_name": "quality-timeliness-monthly",
        "target": {"activeMenu": "timeliness-monthly"},
        "legacy_tab": "timeliness-monthly",
        "hidden": False,
        "dev_only": False,
    },
    # 3. 内涵与终末质控 (quality) —— 合并原质控业务、整改闭环与归档前形式核查
    {
        "id": "patient-qc",
        "label": "内涵质控工作台",
        "icon": "",
        "path": "/quality/patients",
        "group": "quality",
        "order": 10,
        "route_name": "quality-patients",
        "target": {"activeMenu": "patient-qc", "tab": "patients"},
        "legacy_tab": "patient-qc",
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "audit",
        "label": "AI 内涵质控记录",
        "icon": "",
        "path": "/quality/records",
        "group": "quality",
        "order": 20,
        "route_name": "quality-records",
        "target": {"activeMenu": "audit"},
        "legacy_tab": "audit",
        # WP02（064 D2）：旧重复入口侧栏隐藏（保留 ID/路由，WP-05 重定向）
        "hidden": True,
        "dev_only": False,
    },
    {
        "id": "workbench",
        "label": "归档前形式核查",
        "icon": "",
        "path": "/governance/workbench",
        "group": "quality",
        "order": 30,
        "route_name": "governance-workbench",
        "target": {"activeMenu": "workbench"},
        "legacy_tab": "workbench",
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "feedback",
        "label": "临床整改反馈",
        "icon": "",
        "path": "/closure/feedback",
        "group": "quality",
        "order": 40,
        "route_name": "closure-feedback",
        "target": {"activeMenu": "feedback"},
        "legacy_tab": "feedback",
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "relay-alert-logs",
        "label": "企微告警记录",
        "icon": "",
        "path": "/closure/alerts",
        "group": "quality",
        "order": 50,
        "route_name": "closure-alerts",
        "target": {"activeMenu": "relay-alert-logs"},
        "legacy_tab": "relay-alert-logs",
        "hidden": False,
        "dev_only": False,
    },
    # 4. 质控规则中心 (governance) —— 专门管全部规则，不混杂运维配置
    {
        # 病历时效质控（T6）：规则可视化配置（保存新版本/启停为写操作，需 timeliness_rule_edit）
        "id": "timeliness-rules",
        "label": "时效锁定规则",
        "icon": "",
        "path": "/governance/timeliness-rules",
        "group": "governance",
        "order": 10,
        "route_name": "governance-timeliness-rules",
        "target": {"activeMenu": "timeliness-rules"},
        "legacy_tab": "timeliness-rules",
        "hidden": False,
        "dev_only": False,
    },
    {
        # WP02（064 D3/D5）：归档前形式预检规则（WP-06 填充页面）
        "id": "prearchive-rules",
        "label": "归档前形式预检规则",
        "icon": "",
        "path": "/governance/prearchive-rules",
        "group": "governance",
        "order": 15,
        "route_name": "governance-prearchive-rules",
        "target": {"activeMenu": "prearchive-rules"},
        "legacy_tab": "prearchive-rules",
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "audit-types",
        "label": "内涵与预检规则",
        "icon": "",
        "path": "/governance/audit-types",
        "group": "governance",
        "order": 20,
        "route_name": "governance-audit-types",
        "target": {"activeMenu": "audit-types"},
        "legacy_tab": "audit-types",
        "hidden": False,
        "dev_only": False,
    },
    # 5. 系统与运维 (system) —— 调度、补推、数据源、接收人、权限、健康
    {
        "id": "scheduler",
        "label": "定时调度管理",
        "icon": "",
        "path": "/tasks/scheduler",
        "group": "system",
        "order": 10,
        "route_name": "tasks-scheduler",
        "target": {"activeMenu": "scheduler"},
        "legacy_tab": "scheduler",
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "push",
        "label": "手动补推与重查",
        "icon": "",
        "path": "/tasks/push",
        "group": "system",
        "order": 20,
        "route_name": "tasks-push",
        "target": {"activeMenu": "push"},
        "legacy_tab": "push",
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "push-progress",
        "label": "任务执行进度",
        "icon": "",
        "path": "/tasks/progress",
        "group": "system",
        "order": 25,
        "route_name": "tasks-progress",
        "target": {"activeMenu": "push-progress"},
        "legacy_tab": "push-progress",
        "hidden": True,  # 侧栏隐藏，由顶栏「任务」按钮与手动补推页内按钮直达
        "dev_only": False,
    },
    {
        "id": "config",
        "label": "数据源与系统配置",
        "icon": "",
        "path": "/governance/config",
        "group": "system",
        "order": 30,
        "route_name": "governance-config",
        "target": {"activeMenu": "config"},
        "legacy_tab": "config",
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "relay",
        "label": "企微接收人配置",
        "icon": "",
        "path": "/governance/relay",
        "group": "system",
        "order": 40,
        "route_name": "governance-relay",
        "target": {"activeMenu": "relay"},
        "legacy_tab": "relay",
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "access",
        "label": "用户与角色权限",
        "icon": "",
        "path": "/system/access",
        "group": "system",
        "order": 50,
        "route_name": "system-access",
        "target": {"activeMenu": "access"},
        "legacy_tab": "access",
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "health",
        "label": "系统健康状态",
        "icon": "",
        "path": "/system/health",
        "group": "system",
        "order": 60,
        "route_name": "system-health",
        "target": {"activeMenu": "health"},
        "legacy_tab": "health",
        "hidden": False,
        "dev_only": False,
    },
    {
        "id": "config-runtime",
        "label": "运行配置摘要",
        "icon": "",
        "path": "/system/runtime",
        "group": "system",
        "order": 65,
        "route_name": "system-runtime",
        "target": {"activeMenu": "config", "tab": "runtime-summary"},
        "legacy_tab": "config-runtime",
        "hidden": True,  # 与系统健康/配置页重复，侧栏隐藏，保留路由兼容
        "dev_only": False,
    },
    {
        "id": "debug",
        "label": "Dify 接口调试",
        "icon": "",
        "path": "/system/debug",
        "group": "system",
        "order": 70,
        "route_name": "system-debug",
        "target": {"activeMenu": "debug"},
        "legacy_tab": "debug",
        "hidden": False,
        "dev_only": True,
    },
    # Legacy-only hidden compatibility items（绝不可删，契约测试强校验）
    {
        "id": "oracle-status",
        "label": "Oracle 连接状态",
        "icon": "",
        "path": "/system/oracle-status",
        "group": "system",
        "order": 90,
        "route_name": "system-oracle-status",
        "target": {"activeMenu": "oracle-status"},
        "legacy_tab": "oracle-status",
        "hidden": True,
        "dev_only": False,
    },
    {
        "id": "system-logs",
        "label": "系统日志",
        "icon": "",
        "path": "/system/logs",
        "group": "system",
        "order": 100,
        "route_name": "system-logs",
        "target": {"activeMenu": "system-logs"},
        "legacy_tab": "system-logs",
        "hidden": True,
        "dev_only": False,
    },
]
MENU_MAP = {item["id"]: item for item in MENU_CATALOG}

# 默认角色菜单（RoleMenu 未分配时使用）；ID 集合保持与历史兼容。
# admin 自动包含全部非 hidden 项（hidden 兼容项由前端 DIRECT_ACCESS 豁免直达）。
MENU_CONFIG = {
    "admin": [item["id"] for item in MENU_CATALOG if not item["hidden"]],
    "dept_manager": [
        "dashboard", "timeliness-stats", "timeliness-approvals", "timeliness-events",
        "timeliness-monthly", "patient-qc", "feedback", "relay-alert-logs",
    ],
    "clinician": ["audit", "patient-qc", "feedback", "timeliness-events"],
    "timeliness_reader": ["timeliness-stats", "timeliness-approvals", "timeliness-events", "timeliness-monthly"],
    "medical_affairs": ["timeliness-stats", "timeliness-approvals", "timeliness-events", "timeliness-monthly"],
    "auditor": [
        "dashboard", "timeliness-stats", "timeliness-approvals", "timeliness-events",
        "timeliness-monthly", "patient-qc", "workbench", "feedback",
        "relay-alert-logs", "timeliness-rules", "audit-types", "prearchive-rules", "push",
    ],
}

# 角色默认首页 menu_id（产品决策建议；仅元数据，不改变授权）
ROLE_DEFAULT_HOME = {
    "admin": "dashboard",
    "dept_manager": "patient-qc",
    "auditor": "dashboard",
    "clinician": "feedback",
    "timeliness_reader": "timeliness-events",
    "medical_affairs": "timeliness-events",
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
    if assigned_menu_ids:
        # 2026-11-15 P0-4：timeliness-approvals（解锁审批与豁免）系自 timeliness-monthly
        # 拆分出的新同级菜单，历史自定义 RoleMenu 分配早于拆分、不会包含它。若该角色
        # 已授 timeliness-monthly 且默认矩阵含 timeliness-approvals，则自动补齐（插在
        # monthly 之前），线上已做过权限微调的角色无需人工重配；显式分配不含 monthly
        # 的角色不受影响（保持既有单菜单元测试语义）。
        role_defaults = MENU_CONFIG.get(role_name, [])
        if (
            "timeliness-monthly" in assigned_menu_ids
            and "timeliness-approvals" not in assigned_menu_ids
            and "timeliness-approvals" in role_defaults
        ):
            assigned_menu_ids.insert(
                assigned_menu_ids.index("timeliness-monthly"), "timeliness-approvals"
            )
        menu_ids = assigned_menu_ids
    else:
        menu_ids = MENU_CONFIG.get(role_name, [])
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
