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

# 统一菜单目录（用于角色菜单分配与前端渲染）
MENU_CATALOG = [
    {"id": "dashboard", "label": "仪表盘", "icon": "🏠", "path": "/dashboard"},
    {"id": "patient-qc", "label": "患者质控总览", "icon": "🧑‍⚕️", "path": "/patient-qc"},
    {"id": "relay-alert-logs", "label": "前置机告警", "icon": "📨", "path": "/patient-qc"},
    {"id": "audit", "label": "审计中心", "icon": "📊", "path": "/audit"},
    {"id": "feedback", "label": "质控反馈", "icon": "💬", "path": "/feedback"},
    {"id": "push", "label": "手动推送", "icon": "🚀", "path": "/push"},
    {"id": "scheduler", "label": "定时任务", "icon": "⏰", "path": "/scheduler"},
    {"id": "relay", "label": "前置机接收人配置", "icon": "📡", "path": "/relay"},
    {"id": "config", "label": "系统配置", "icon": "⚙️", "path": "/config"},
    {"id": "audit-types", "label": "审计类型", "icon": "🧩", "path": "/audit-types"},
    {"id": "config-runtime", "label": "运行总览", "icon": "🧭", "path": "/config"},
    {"id": "access", "label": "权限管理", "icon": "👥", "path": "/access"},
    {"id": "health", "label": "系统健康", "icon": "💚", "path": "/health"},
    {"id": "debug", "label": "Dify 调试", "icon": "🔧", "path": "/debug"},
]
MENU_MAP = {item["id"]: item for item in MENU_CATALOG}

# 角色默认菜单（当未配置角色菜单分配时使用）
MENU_CONFIG = {
    "admin": [item["id"] for item in MENU_CATALOG],
    "dept_manager": ["dashboard", "patient-qc", "relay-alert-logs", "audit", "feedback", "scheduler", "health"],
    "clinician": ["dashboard", "audit", "feedback"],
    "auditor": ["dashboard", "patient-qc", "relay-alert-logs", "audit", "feedback", "health"],
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
        return {"menu": []}

    assigned_menu_ids = [
        row.menu_id
        for row in db.query(RoleMenu).filter(RoleMenu.role_id == current_user.role_id).all()
    ]
    menu_ids = assigned_menu_ids if assigned_menu_ids else MENU_CONFIG.get(role_name, [])
    menu = [MENU_MAP[mid] for mid in menu_ids if mid in MENU_MAP]

    return {
        "menu": menu,
        "role": role_name,
    }


@router.get("/menu/all", tags=["菜单"])
async def get_all_menus():
    """
    获取所有菜单配置（用于前端权限管理）
    """
    return {
        "catalog": MENU_CATALOG,
        "menus": MENU_CONFIG,
    }
