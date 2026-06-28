"""
Static checks for the relay config UI (V1).

These tests read frontend assets directly. They do not need a server, DB,
browser, or network access.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_RELAY_HTML = _STATIC_DIR / "templates" / "pages" / "relay.html"
_CONFIG_CSS = _STATIC_DIR / "styles" / "pages" / "config.css"
_APP_JS = _STATIC_DIR / "scripts" / "app.js"
_INDEX_HTML = _STATIC_DIR / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_relay_page_has_root_class():
    html = _read(_RELAY_HTML)
    assert "page-relay-config" in html


def test_relay_summary_strip_exists():
    html = _read(_RELAY_HTML)
    assert "relay-summary-strip" in html
    assert "relay-summary-item" in html
    assert "推送状态" in html
    assert "严重度过滤" in html
    assert "护士长配置" in html


def test_relay_rules_table_has_medical_data_table():
    html = _read(_RELAY_HTML)
    assert "medical-data-table" in html


def test_relay_config_css_has_styles():
    css = _read(_CONFIG_CSS)
    assert ".page-relay-config .relay-summary-strip" in css
    assert ".page-relay-config .medical-data-table" in css


def test_relay_dept_filter_and_preview_preserved():
    html = _read(_RELAY_HTML)
    # Core features preserved
    assert "微信告警科室过滤" in html
    assert "编辑推送规则" in html
    assert "预览测试" in html
    assert "按科室查询护理负责人" in html


def test_relay_assets_are_cache_busted():
    html = _read(_INDEX_HTML)

    assert "/templates/pages/relay.html?v=20260628-relay-config-v1" in html
    assert "/styles/pages/config.css?v=20260628-relay-config-v1" in html
    assert "/scripts/app.js?v=20260628-relay-config-v1" in html
