"""
Static checks for config/admin/placeholder pages (stages 13-17).

These tests read frontend assets directly. They do not need a server, DB,
browser, or network access.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_HEALTH_HTML = _STATIC_DIR / "templates" / "pages" / "health.html"
_DEBUG_HTML = _STATIC_DIR / "templates" / "pages" / "debug.html"
_ACCESS_HTML = _STATIC_DIR / "templates" / "pages" / "access.html"
_PLACEHOLDER_HTML = _STATIC_DIR / "templates" / "pages" / "placeholder.html"
_APP_JS = _STATIC_DIR / "scripts" / "app.js"
_INDEX_HTML = _STATIC_DIR / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Stage 13: 系统健康 ──

def test_health_page_has_root_class():
    html = _read(_HEALTH_HTML)
    assert "page-health" in html


def test_health_grid_and_cards_preserved():
    html = _read(_HEALTH_HTML)
    assert "health-grid" in html
    assert "health-card" in html
    assert "单项检测" in html


# ── Stage 14: Dify 调试 ──

def test_debug_page_has_root_class():
    html = _read(_DEBUG_HTML)
    assert "page-debug" in html


def test_debug_form_and_results_preserved():
    html = _read(_DEBUG_HTML)
    assert "开始调试" in html
    assert "调试结果" in html
    assert "解析结果预览" in html


# ── Stage 15: 权限管理 ──

def test_access_page_has_root_class():
    html = _read(_ACCESS_HTML)
    assert "page-access" in html


def test_access_tables_have_medical_data_table():
    html = _read(_ACCESS_HTML)
    # At least 2 of the 4 tables should have it
    import re
    matches = re.findall(r"medical-data-table", html)
    assert len(matches) >= 4  # users, roles, permissions, departments


def test_access_tabs_preserved():
    html = _read(_ACCESS_HTML)
    for name in ("用户管理", "角色管理", "权限管理", "科室管理"):
        assert name in html


# ── Stage 16-17: Oracle 连接 / 运行日志 ──

def test_placeholder_oracle_status_has_root_class():
    html = _read(_PLACEHOLDER_HTML)
    assert "page-oracle-status" in html


def test_placeholder_system_logs_has_root_class():
    html = _read(_PLACEHOLDER_HTML)
    assert "page-system-logs" in html


def test_placeholder_pages_remain_intact():
    html = _read(_PLACEHOLDER_HTML)
    assert "Oracle 连接" in html
    assert "运行日志" in html
    assert "功能建设中" in html


# ── Version busting ──

def test_config_pages_assets_are_cache_busted():
    html = _read(_INDEX_HTML)

    assert "/templates/pages/health.html?v=20260628-config-v1" in html
    assert "/templates/pages/debug.html?v=20260628-config-v1" in html
    assert "/templates/pages/access.html?v=20260628-config-v1" in html
    assert "/templates/pages/placeholder.html?v=20260628-config-v1" in html
    assert "/scripts/app.js?v=20260628-config-v1" in html
