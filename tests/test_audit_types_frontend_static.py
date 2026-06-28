"""
Static checks for the audit types UI (V1).

These tests read frontend assets directly. They do not need a server, DB,
browser, or network access.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_AUDIT_TYPES_HTML = _STATIC_DIR / "templates" / "pages" / "audit_types.html"
_AUDIT_TYPES_JS = _STATIC_DIR / "scripts" / "modules" / "audit_types.js"
_AUDIT_TYPES_CSS = _STATIC_DIR / "styles" / "pages" / "audit_types.css"
_APP_JS = _STATIC_DIR / "scripts" / "app.js"
_INDEX_HTML = _STATIC_DIR / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_audit_types_page_has_root_class():
    html = _read(_AUDIT_TYPES_HTML)
    assert "page-admin" in html
    assert "page-audit-types" in html


def test_audit_types_summary_strip_exists():
    html = _read(_AUDIT_TYPES_HTML)
    assert "audit-type-summary-strip" in html
    assert "audit-type-summary-item" in html
    assert "审计类型" in html
    assert "已启用" in html
    assert "默认调度" in html


def test_audit_types_tables_have_medical_data_table():
    html = _read(_AUDIT_TYPES_HTML)
    assert "medical-data-table" in html


def test_audit_types_safety_hint_in_guide():
    html = _read(_AUDIT_TYPES_HTML)
    assert "Dify 主输入变量保持" in html
    assert "mr_txt" in html


def test_audit_types_css_has_summary_and_table_styles():
    css = _read(_AUDIT_TYPES_CSS)
    assert ".page-audit-types .audit-type-summary-strip" in css
    assert ".page-audit-types .medical-data-table" in css
    assert "@media (max-width: 1100px)" in css


def test_audit_types_assets_are_cache_busted():
    html = _read(_INDEX_HTML)
    js = _read(_APP_JS)

    assert "/styles/pages/audit_types.css?v=20260628-audit-types-v1" in html
    assert "/templates/pages/audit_types.html?v=20260628-audit-types-v1" in html
    assert "./modules/audit_types.js?v=20260628-audit-types-v1" in js
    # app.js version follows latest phase; final version is config-v1
    assert "/scripts/app.js?v=20260628-config-v1" in html
