"""
菜单权限配置 API
根据用户角色动态返回菜单配置
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import RoleMenu, User
from app.permissions import get_user_role

router = APIRouter()

MENU_GROUPS = [
    {"id": "workbench", "label": "工作台", "icon": "🏠", "order": 10},
    {"id": "qc", "label": "质控业务", "icon": "🧑‍⚕️", "order": 20},
    {"id": "push", "label": "推送与调度", "icon": "🚀", "order": 30},
    {"id": "config", "label": "配置中心", "icon": "⚙️", "order": 40},
    {"id": "admin", "label": "系统管理", "icon": "👥", "order": 50},
    {"id": "ops", "label": "运维工具", "icon": "🛠️", "order": 60},
]

MENU_CATALOG = [
    {"id": "dashboard", "label": "仪表盘", "icon": "🏠", "path": "/dashboard", "group": "workbench", "order": 10, "target": {"activeMenu": "dashboard"}, "hidden": False, "dev_only": False},
    {"id": "patient-qc", "label": "患者质控总览", "icon": "🧑‍⚕️", "path": "/patient-qc", "group": "qc", "order": 20, "target": {"activeMenu": "patient-qc", "tab": "patients"}, "hidden": False, "dev_only": False},
    {"id": "relay-alert-logs", "label": "前置机告警", "icon": "📨", "path": "/patient-qc", "group": "qc", "order": 21, "target": {"activeMenu": "patient-qc", "tab": "relay-alerts"}, "hidden": False, "dev_only": False},
    {"id": "relay", "label": "前置机接收人配置", "icon": "📡", "path": "/relay", "group": "qc", "order": 22, "target": {"activeMenu": "relay"}, "hidden": False, "dev_only": False},
    {"id": "audit", "label": "审计中心", "icon": "📊", "path": "/audit", "group": "qc", "order": 23, "target": {"activeMenu": "audit"}, "hidden": False, "dev_only": False},
    {"id": "feedback", "label": "质控反馈", "icon": "💬", "path": "/feedback", "group": "qc", "order": 24, "target": {"activeMenu": "feedback"}, "hidden": False, "dev_only": False},
    {"id": "push", "label": "手动推送", "icon": "🚀", "path": "/push", "group": "push", "order": 30, "target": {"activeMenu": "push"}, "hidden": False, "dev_only": False},
    {"id": "scheduler", "label": "定时任务", "icon": "⏰", "path": "/scheduler", "group": "push", "order": 31, "target": {"activeMenu": "scheduler"}, "hidden": False, "dev_only": False},
    {"id": "config", "label": "系统配置", "icon": "⚙️", "path": "/config", "group": "config", "order": 40, "target": {"activeMenu": "config"}, "hidden": False, "dev_only": False},
    {"id": "audit-types", "label": "审计类型", "icon": "🧩", "path": "/audit-types", "group": "config", "order": 41, "target": {"activeMenu": "audit-types"}, "hidden": False, "dev_only": False},
    {"id": "config-runtime", "label": "运行总览", "icon": "🧭", "path": "/config", "group": "config", "order": 42, "target": {"activeMenu": "config", "tab": "runtime-summary"}, "hidden": False, "dev_only": False},
    {"id": "access", "label": "权限管理", "icon": "👥", "path": "/access", "group": "admin", "order": 50, "target": {"activeMenu": "access"}, "hidden": False, "dev_only": False},
    {"id": "health", "label": "系统健康", "icon": "💚", "path": "/health", "group": "ops", "order": 60, "target": {"activeMenu": "health"}, "hidden": False, "dev_only": False},
    {"id": "debug", "label": "Dify 调试", "icon": "🔧", "path": "/debug", "group": "ops", "order": 61, "target": {"activeMenu": "debug"}, "hidden": False, "dev_only": True},
]
MENU_MAP = {item["id"]: item for item in MENU_CATALOG}

MENU_CONFIG = {
    "admin": [item["id"] for item in MENU_CATALOG],
    "dept_manager": ["dashboard", "patient-qc", "audit", "feedback", "scheduler", "health"],
    "clinician": ["dashboard", "audit", "feedback"],
    "auditor": ["dashboard", "patient-qc", "audit", "feedback", "health"],
}


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
        return {"menu": [], "groups": []}

    assigned_menu_ids = [
        row.menu_id
        for row in db.query(RoleMenu).filter(RoleMenu.role_id == current_user.role_id).all()
    ]
    menu_ids = assigned_menu_ids if assigned_menu_ids else MENU_CONFIG.get(role_name, [])
    menu = [MENU_MAP[mid] for mid in menu_ids if mid in MENU_MAP]

    return {
        "menu": menu,
        "groups": MENU_GROUPS,
        "role": role_name,
    }


@router.get("/menu/all", tags=["菜单"])
async def get_all_menus():
    """
    获取所有菜单配置（用于前端权限管理）
    """
    return {
        "groups": MENU_GROUPS,
        "catalog": MENU_CATALOG,
        "menus": MENU_CONFIG,
    }
