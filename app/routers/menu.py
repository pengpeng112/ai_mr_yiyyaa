"""
菜单权限配置 API
根据用户角色动态返回菜单配置
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Role
from app.auth import get_current_user
from app.permissions import get_user_role

router = APIRouter()

# 菜单配置（按角色）
MENU_CONFIG = {
    "admin": [
        {"id": "dashboard", "label": "仪表板", "icon": "📊", "path": "/dashboard"},
        {"id": "users", "label": "用户管理", "icon": "👥", "path": "/users"},
        {"id": "qc_reports", "label": "质控报告", "icon": "📄", "path": "/qc-reports"},
        {"id": "feedback", "label": "反馈管理", "icon": "💬", "path": "/feedback"},
        {"id": "config", "label": "系统配置", "icon": "⚙️", "path": "/config"},
    ],
    "dept_manager": [
        {"id": "dashboard", "label": "仪表板", "icon": "📊", "path": "/dashboard"},
        {"id": "qc_reports", "label": "质控报告", "icon": "📄", "path": "/qc-reports"},
        {"id": "feedback", "label": "反馈管理", "icon": "💬", "path": "/feedback"},
        {"id": "dept_stats", "label": "科室统计", "icon": "📈", "path": "/dept-stats"},
    ],
    "clinician": [
        {"id": "dashboard", "label": "仪表板", "icon": "📊", "path": "/dashboard"},
        {"id": "qc_reports", "label": "质控报告", "icon": "📄", "path": "/qc-reports"},
        {"id": "my_feedback", "label": "我的反馈", "icon": "💬", "path": "/my-feedback"},
    ],
    "auditor": [
        {"id": "dashboard", "label": "仪表板", "icon": "📊", "path": "/dashboard"},
        {"id": "qc_reports", "label": "质控报告", "icon": "📄", "path": "/qc-reports"},
        {"id": "feedback", "label": "反馈管理", "icon": "💬", "path": "/feedback"},
    ],
}


@router.get("/menu", tags=["菜单"])
async def get_menu(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取当前用户的菜单配置
    
    根据用户角色返回对应的菜单项
    """
    role_name = get_user_role(current_user.id, db)
    
    if not role_name:
        return {"menu": []}
    
    menu = MENU_CONFIG.get(role_name, [])
    
    return {
        "menu": menu,
        "role": role_name,
    }


@router.get("/menu/all", tags=["菜单"])
async def get_all_menus():
    """
    获取所有菜单配置（用于前端开发）
    """
    return {
        "menus": MENU_CONFIG,
    }
