"""
Static checks for the push progress UI (V1).

These tests read frontend assets directly. They do not need a server, DB,
browser, or network access.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_PUSH_PROGRESS_HTML = _STATIC_DIR / "templates" / "pages" / "push_progress.html"
_PUSH_PROGRESS_JS = _STATIC_DIR / "scripts" / "modules" / "push_progress.js"
_PUSH_PROGRESS_CSS = _STATIC_DIR / "styles" / "pages" / "push_progress.css"
_APP_JS = _STATIC_DIR / "scripts" / "app.js"
_INDEX_HTML = _STATIC_DIR / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_push_progress_page_has_root_class():
    html = _read(_PUSH_PROGRESS_HTML)
    assert "page-push-progress" in html


def test_push_progress_summary_strip_has_key_metrics():
    html = _read(_PUSH_PROGRESS_HTML)
    js = _read(_PUSH_PROGRESS_JS)

    assert "总任务" in html
    assert "运行中" in html
    assert "已完成" in html
    assert "失败" in html
    assert "平均耗时" in html
    assert "ppDurationLabel" in html
    assert "ppDurationLabel(" in js


def test_push_progress_table_has_medical_data_table_and_progress():
    html = _read(_PUSH_PROGRESS_HTML)
    assert "medical-data-table" in html
    assert "ppProgressPct" in html
    assert "ppProgressStatus" in html
    assert 'label="进度"' in html


def test_push_progress_detail_has_progress_and_error_handling():
    html = _read(_PUSH_PROGRESS_HTML)
    js = _read(_PUSH_PROGRESS_JS)

    assert "pp-detail-progress" in html
    assert "pp-detail-error" in html
    assert "viewPPLogs" in html
    assert "viewPPLogs(" in js
    assert "失败原因" in html
    assert "查看推送日志" in html


def test_push_progress_css_has_medical_table_and_pulse():
    css = _read(_PUSH_PROGRESS_CSS)
    assert ".page-push-progress .medical-data-table" in css
    assert "pp-summary-pulse" in css
    assert "pp-table-pulse" in css
    assert "@media (max-width: 1100px)" in css


def test_push_progress_assets_are_cache_busted():
    html = _read(_INDEX_HTML)
    js = _read(_APP_JS)

    assert "/styles/pages/push_progress.css?v=20260628-push-progress-v1" in html
    assert "/templates/pages/push_progress.html?v=20260628-push-progress-v1" in html
    assert "./modules/push_progress.js?v=20260628-push-progress-v1" in js
    # app.js version follows the latest phase; after stage 11 it becomes relay-config-v1
    assert "/scripts/app.js?v=20260628-relay-config-v1" in html
