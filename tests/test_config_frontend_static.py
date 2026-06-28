"""
Static checks for the config UI (V1).

These tests read frontend assets directly. They do not need a server, DB,
browser, or network access.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_CONFIG_HTML = _STATIC_DIR / "templates" / "pages" / "config.html"
_CONFIG_JS = _STATIC_DIR / "scripts" / "modules" / "config.js"
_CONFIG_CSS = _STATIC_DIR / "styles" / "pages" / "config.css"
_APP_JS = _STATIC_DIR / "scripts" / "app.js"
_INDEX_HTML = _STATIC_DIR / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_config_page_has_root_class():
    html = _read(_CONFIG_HTML)
    assert "page-config" in html


def test_config_summary_strip_exists():
    html = _read(_CONFIG_HTML)
    assert "config-summary-strip" in html
    assert "config-summary-item" in html
    assert "配置风险" in html


def test_config_secret_inputs_have_safe_hints():
    html = _read(_CONFIG_HTML)
    assert "config-secret-item" in html
    assert "config-secret-hint" in html
    # 至少覆盖 Oracle/PostgreSQL/Dify/前置机密钥之一
    assert "留空不会覆盖已有密码" in html or "留空不会覆盖已有 Key" in html or "留空不会覆盖已有密钥" in html


def test_config_tabs_preserve_existing_sections():
    html = _read(_CONFIG_HTML)
    for name in (
        "Oracle 数据源", "PostgreSQL 数据源", "Dify 配置", "科室过滤",
        "推送参数", "通知渠道", "前置机推送", "运行总览",
    ):
        assert name in html


def test_config_css_has_summary_and_secret_styles():
    css = _read(_CONFIG_CSS)
    assert ".page-config .config-summary-strip" in css
    assert ".config-secret-hint" in css
    assert ".page-config .config-channel-card" in css


def test_config_assets_are_cache_busted():
    html = _read(_INDEX_HTML)
    js = _read(_APP_JS)

    assert "/styles/pages/config.css?v=20260628-relay-config-v1" in html
    assert "/templates/pages/config.html?v=20260628-config-v1" in html
    assert "./modules/config.js?v=20260628-config-v1" in js
    # app.js version follows the latest phase; after stage 11 it becomes relay-config-v1
    assert "/scripts/app.js?v=20260628-relay-config-v1" in html
