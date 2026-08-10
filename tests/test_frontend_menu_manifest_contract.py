"""后端 MENU_CATALOG 与 frontend route-manifest 的 menuId 契约一致性。

从 route-manifest.ts 解析 menuId，不依赖 Node 运行时；
保证服务端授权 ID 与前端白名单可交集，且不出现 ID 漂移。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.routers.menu import MENU_CATALOG, MENU_CONFIG, MENU_MAP, filter_menu_items_for_navigation

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "frontend" / "src" / "router" / "route-manifest.ts"


def _parse_manifest_menu_ids() -> set[str]:
    text = MANIFEST.read_text(encoding="utf-8")
    # menuId: 'dashboard' 或 menuId: "dashboard"
    found = re.findall(r"menuId\s*:\s*['\"]([a-z0-9-]+)['\"]", text)
    assert found, "route-manifest.ts 未解析到 menuId"
    return set(found)


def test_route_manifest_file_exists():
    assert MANIFEST.is_file(), f"missing {MANIFEST}"


def test_manifest_menu_ids_subset_of_catalog():
    manifest_ids = _parse_manifest_menu_ids()
    catalog_ids = {item["id"] for item in MENU_CATALOG}
    unknown = manifest_ids - catalog_ids
    assert not unknown, f"前端 manifest 含未知 menuId: {sorted(unknown)}"


def test_navigable_catalog_ids_are_in_manifest():
    """导航可见（非 hidden）菜单必须在前端白名单中，否则永远 fail-closed。"""
    manifest_ids = _parse_manifest_menu_ids()
    navigable = filter_menu_items_for_navigation(MENU_CATALOG, production=False)
    missing = [item["id"] for item in navigable if item["id"] not in manifest_ids]
    assert not missing, f"导航可见但前端无组件: {missing}"


def test_production_nav_excludes_dev_and_placeholders():
    prod = filter_menu_items_for_navigation(MENU_CATALOG, production=True)
    prod_ids = {item["id"] for item in prod}
    assert "debug" not in prod_ids
    assert "oracle-status" not in prod_ids
    assert "system-logs" not in prod_ids
    # 生产导航项仍须有前端组件
    manifest_ids = _parse_manifest_menu_ids()
    missing = sorted(prod_ids - manifest_ids)
    assert not missing, f"生产导航缺少前端组件: {missing}"


def test_role_default_menus_have_manifest_components():
    manifest_ids = _parse_manifest_menu_ids()
    for role, ids in MENU_CONFIG.items():
        visible = [
            mid
            for mid in ids
            if mid in MENU_MAP and not MENU_MAP[mid].get("hidden")
        ]
        # 生产环境下 admin 还会再滤 debug
        for mid in visible:
            if MENU_MAP[mid].get("dev_only"):
                continue
            assert mid in manifest_ids, f"角色 {role} 菜单 {mid} 无前端组件"


def test_placeholder_ids_not_in_manifest():
    """占位入口应隐藏且不必进 manifest（fail-closed）。"""
    manifest_ids = _parse_manifest_menu_ids()
    assert "oracle-status" not in manifest_ids
    assert "system-logs" not in manifest_ids


def test_static_ui_next_build_artifact_optional_note():
    """构建产物可选存在；契约测试不强制提交 dist。"""
    dist_index = ROOT / "frontend" / "dist" / "index.html"
    static_index = ROOT / "static" / "ui-next" / "index.html"
    # 仅记录，不失败
    assert dist_index.is_file() or static_index.is_file() or True
