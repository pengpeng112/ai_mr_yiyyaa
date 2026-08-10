"""DEPRECATED — 请勿使用。

历史菜单服务，内容已与现役 `app/routers/menu.py` 不一致。
业务授权目录唯一权威为 `app.routers.menu`（MENU_CATALOG / MENU_GROUPS / MENU_CONFIG）。

删除门禁（017 WP1）：
- 全仓运行时、测试、脚本无 import 引用后可删除本文件；
- 当前保留文件仅作 deprecated 占位，避免外部未知导入瞬间 500；
- 新代码禁止从本模块读取菜单。

如需菜单配置，请使用：
    from app.routers.menu import MENU_CATALOG, MENU_CONFIG, MENU_GROUPS, build_menu_response
"""

from __future__ import annotations

import warnings

warnings.warn(
    "app.services.menu_service is deprecated; use app.routers.menu instead",
    DeprecationWarning,
    stacklevel=2,
)

# 仅导出空/兼容桩，避免误用旧目录
MENU_CONFIG = {}  # type: ignore[var-annotated]


def get_menu_for_role(role: str):
    """Deprecated stub — always returns empty list."""
    warnings.warn(
        "get_menu_for_role is deprecated; use app.routers.menu.build_menu_response",
        DeprecationWarning,
        stacklevel=2,
    )
    return []
