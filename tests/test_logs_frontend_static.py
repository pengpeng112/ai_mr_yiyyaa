"""
Static checks for the push logs (audit) UI (V1).

The tests read frontend files directly and do not require a running app.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_AUDIT_HTML = _STATIC_DIR / "templates" / "pages" / "audit.html"
_LOGS_CSS = _STATIC_DIR / "styles" / "pages" / "logs.css"
_LOGS_JS = _STATIC_DIR / "scripts" / "modules" / "logs.js"
_APP_JS = _STATIC_DIR / "scripts" / "app.js"
_INDEX_HTML = _STATIC_DIR / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_logs_summary_has_success_count():
    """V1：统计条包含成功计数"""
    html = _read(_AUDIT_HTML)
    js = _read(_LOGS_JS)
    app = _read(_APP_JS)

    assert "cs-success" in html
    assert "成功" in html
    assert "success:" in js
    assert "success: 0" in app


def test_logs_export_has_loading_guard():
    """V1：导出按钮 loading 防重复"""
    html = _read(_AUDIT_HTML)
    js = _read(_LOGS_JS)
    app = _read(_APP_JS)

    assert "logExportLoading" in html
    assert ":loading=\"logExportLoading\"" in html
    assert ":disabled=\"logExportLoading\"" in html
    assert "if (this.logExportLoading) return;" in js
    assert "this.logExportLoading = true;" in js
    assert "this.logExportLoading = false;" in js
    assert "logExportLoading: false" in app


def test_logs_json_has_copy_button():
    """V1：JSON 块有复制按钮"""
    html = _read(_AUDIT_HTML)
    js = _read(_LOGS_JS)

    assert "copyLogJson" in html
    assert "copyLogJson(" in js


def test_logs_table_has_medical_data_table_class():
    """V1：表格统一密度"""
    html = _read(_AUDIT_HTML)
    css = _read(_LOGS_CSS)

    assert "medical-data-table" in html
    assert ".medical-data-table" in css


def test_logs_assets_are_cache_busted():
    html = _read(_INDEX_HTML)
    js = _read(_APP_JS)

    assert "/styles/pages/logs.css?v=" in html
    assert "/templates/pages/audit.html?v=" in html
    assert "./modules/logs.js?v=" in js
