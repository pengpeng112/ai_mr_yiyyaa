"""
Static checks for the manual push UI (V1).

The tests read frontend files directly and do not require a running app.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_PUSH_HTML = _STATIC_DIR / "templates" / "pages" / "push.html"
_PUSH_CSS = _STATIC_DIR / "styles" / "pages" / "push_compact.css"
_PUSH_JS = _STATIC_DIR / "scripts" / "modules" / "push.js"
_APP_JS = _STATIC_DIR / "scripts" / "app.js"
_INDEX_HTML = _STATIC_DIR / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_push_v1_has_clear_selection_and_duration():
    """V1：清空选择按钮 + 任务耗时显示 + 进度入口"""
    html = _read(_PUSH_HTML)
    js = _read(_PUSH_JS)

    # 清空选择
    assert "清空选择" in html
    assert "clearPushSelection" in html
    assert "clearPushSelection() {" in js
    # 耗时显示
    assert "pushDurationLabel" in html
    assert "pushDurationLabel()" in js
    assert "duration_seconds" in js
    # 进度入口
    assert "查看推送进度详情" in html


def test_push_table_has_medical_data_table_class():
    """V1：表格统一密度"""
    html = _read(_PUSH_HTML)
    css = _read(_PUSH_CSS)

    assert "medical-data-table" in html
    assert ".medical-data-table" in css


def test_push_preserves_existing_form_fields():
    """保留现有 date_mode、date_dimension、parallel、dry_run 等字段"""
    html = _read(_PUSH_HTML)

    for snippet in (
        "pushForm.date_mode",
        "pushForm.date_dimension",
        "pushForm.parallel_workers",
        "pushForm.dry_run",
        "pushForm.async_mode",
        "pushForm.parallel_audit_types",
    ):
        assert snippet in html, f"missing preserved field: {snippet}"


def test_push_assets_are_cache_busted():
    html = _read(_INDEX_HTML)
    js = _read(_APP_JS)

    assert "/styles/pages/push_compact.css?v=" in html
    assert "/templates/pages/push.html?v=" in html
    assert "./modules/push.js?v=" in js
