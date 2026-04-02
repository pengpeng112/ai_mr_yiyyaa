"""
前端菜单配置服务
提供菜单配置、权限检查等前端所需的功能
"""

# 菜单配置（与后端保持一致）
MENU_CONFIG = {
    "admin": [
        {
            "id": "dashboard",
            "label": "仪表板",
            "icon": "📊",
            "path": "/dashboard",
            "permissions": ["view_dashboard"]
        },
        {
            "id": "users",
            "label": "用户管理",
            "icon": "👥",
            "path": "/users",
            "permissions": ["manage_users"],
            "children": [
                {"id": "users_list", "label": "用户列表", "path": "/users"},
                {"id": "users_create", "label": "创建用户", "path": "/users/create"},
                {"id": "roles", "label": "角色管理", "path": "/roles"},
                {"id": "permissions", "label": "权限管理", "path": "/permissions"},
                {"id": "departments", "label": "科室管理", "path": "/departments"},
            ]
        },
        {
            "id": "qc_reports",
            "label": "质控报告",
            "icon": "📄",
            "path": "/qc-reports",
            "permissions": ["view_reports"]
        },
        {
            "id": "feedback",
            "label": "反馈管理",
            "icon": "💬",
            "path": "/feedback",
            "permissions": ["view_feedback"]
        },
        {
            "id": "config",
            "label": "系统配置",
            "icon": "⚙️",
            "path": "/config",
            "permissions": ["manage_config"]
        },
    ],
    "dept_manager": [
        {
            "id": "dashboard",
            "label": "仪表板",
            "icon": "📊",
            "path": "/dashboard",
            "permissions": ["view_dashboard"]
        },
        {
            "id": "qc_reports",
            "label": "质控报告",
            "icon": "📄",
            "path": "/qc-reports",
            "permissions": ["view_reports"]
        },
        {
            "id": "feedback",
            "label": "反馈管理",
            "icon": "💬",
            "path": "/feedback",
            "permissions": ["view_feedback"],
            "children": [
                {"id": "feedback_list", "label": "反馈列表", "path": "/feedback"},
                {"id": "feedback_create", "label": "创建反馈", "path": "/feedback/create"},
            ]
        },
        {
            "id": "dept_stats",
            "label": "科室统计",
            "icon": "📈",
            "path": "/dept-stats",
            "permissions": ["view_reports"]
        },
    ],
    "clinician": [
        {
            "id": "dashboard",
            "label": "仪表板",
            "icon": "📊",
            "path": "/dashboard",
            "permissions": ["view_dashboard"]
        },
        {
            "id": "qc_reports",
            "label": "质控报告",
            "icon": "📄",
            "path": "/qc-reports",
            "permissions": ["view_reports"]
        },
        {
            "id": "my_feedback",
            "label": "我的反馈",
            "icon": "💬",
            "path": "/my-feedback",
            "permissions": ["view_feedback"]
        },
    ],
    "auditor": [
        {
            "id": "dashboard",
            "label": "仪表板",
            "icon": "📊",
            "path": "/dashboard",
            "permissions": ["view_dashboard"]
        },
        {
            "id": "qc_reports",
            "label": "质控报告",
            "icon": "📄",
            "path": "/qc-reports",
            "permissions": ["view_reports"]
        },
        {
            "id": "feedback",
            "label": "反馈管理",
            "icon": "💬",
            "path": "/feedback",
            "permissions": ["view_feedback"]
        },
    ],
}


def get_menu_for_role(role: str) -> list:
    """
    根据角色获取菜单配置
    """
    return MENU_CONFIG.get(role, [])


def filter_menu_by_permissions(menu: list, permissions: list) -> list:
    """
    根据权限过滤菜单
    """
    filtered = []
    
    for item in menu:
        # 检查该菜单项是否需要权限检查
        if "permissions" in item:
            # 检查用户是否拥有所需权限
            if not any(p in permissions for p in item["permissions"]):
                continue
        
        # 递归过滤子菜单
        if "children" in item:
            filtered_children = filter_menu_by_permissions(item["children"], permissions)
            if filtered_children:
                item["children"] = filtered_children
                filtered.append(item)
        else:
            filtered.append(item)
    
    return filtered


def get_breadcrumb_path(menu: list, target_id: str, path: list = None) -> list:
    """
    根据菜单 ID 获取面包屑路径
    """
    if path is None:
        path = []
    
    for item in menu:
        current_path = path + [item]
        
        if item["id"] == target_id:
            return current_path
        
        if "children" in item:
            result = get_breadcrumb_path(item["children"], target_id, current_path)
            if result:
                return result
    
    return []


def has_permission(user_permissions: list, required_permissions: list) -> bool:
    """
    检查用户是否拥有所需权限
    """
    if not required_permissions:
        return True
    
    return any(p in user_permissions for p in required_permissions)


def can_access_menu_item(menu_item: dict, user_permissions: list) -> bool:
    """
    检查用户是否可以访问菜单项
    """
    if "permissions" not in menu_item:
        return True
    
    return has_permission(user_permissions, menu_item["permissions"])


# 权限模块映射
PERMISSION_MODULES = {
    "dashboard": {
        "label": "仪表板",
        "permissions": ["view_dashboard"]
    },
    "qc_reports": {
        "label": "质控报告",
        "permissions": ["view_reports", "export_reports"]
    },
    "feedback": {
        "label": "反馈管理",
        "permissions": ["view_feedback", "create_feedback", "edit_feedback", "approve_feedback"]
    },
    "admin": {
        "label": "系统管理",
        "permissions": ["manage_users", "manage_roles", "manage_config"]
    },
}


def get_module_permissions(module: str) -> list:
    """
    获取模块所需的权限
    """
    return PERMISSION_MODULES.get(module, {}).get("permissions", [])


def get_module_label(module: str) -> str:
    """
    获取模块标签
    """
    return PERMISSION_MODULES.get(module, {}).get("label", module)
