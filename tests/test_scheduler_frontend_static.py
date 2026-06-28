"""
Static checks for the scheduler UI (V1).

These tests read frontend assets directly. They do not need a server, DB,
browser, or network access.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_SCHEDULER_HTML = _STATIC_DIR / "templates" / "pages" / "scheduler.html"
_SCHEDULER_JS = _STATIC_DIR / "scripts" / "modules" / "scheduler.js"
_SCHEDULER_CSS = _STATIC_DIR / "styles" / "pages" / "scheduler.css"
_APP_JS = _STATIC_DIR / "scripts" / "app.js"
_INDEX_HTML = _STATIC_DIR / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_scheduler_page_has_root_class():
    html = _read(_SCHEDULER_HTML)
    assert "scheduler-page" in html
    assert "page-scheduler" in html


def test_scheduler_table_has_medical_data_table():
    html = _read(_SCHEDULER_HTML)
    assert "medical-data-table" in html


def test_scheduler_shows_mode_and_status_fields():
    html = _read(_SCHEDULER_HTML)
    js = _read(_SCHEDULER_JS)

    # Three modes visible in tabs/status
    assert "每日增量" in html
    assert "出院终末" in html
    assert "执行历史" in html
    # Status fields
    assert "调度器" in html
    assert "下次执行" in html
    assert "schedulerModeLabel()" in html or "schedulerModeLabel" in html
    assert "dischargeModeLabel()" in html or "dischargeModeLabel" in html


def test_scheduler_history_columns_complete():
    html = _read(_SCHEDULER_HTML)
    # required columns
    assert 'prop="success_count"' in html
    assert 'prop="failed_count"' in html
    assert 'prop="duration_seconds"' in html
    assert "schedulerSuccessRate" in html
    assert "schedulerStatusTagType" in html


def test_scheduler_css_has_medical_table_and_pulse():
    css = _read(_SCHEDULER_CSS)
    assert ".page-scheduler .medical-data-table" in css
    assert "scheduler-pulse-dot" in css
    assert "scheduler-table-pulse" in css
    assert "@media (max-width:1100px)" in css or "@media (max-width:640px)" in css


def test_scheduler_assets_are_cache_busted():
    html = _read(_INDEX_HTML)
    js = _read(_APP_JS)

    assert "/styles/pages/scheduler.css?v=20260628-scheduler-v1" in html
    assert "/templates/pages/scheduler.html?v=20260628-scheduler-v1" in html
    assert "./modules/scheduler.js?v=20260628-scheduler-v1" in js
    # app.js version follows the latest phase; after stage 11 it becomes relay-config-v1
    assert "/scripts/app.js?v=20260628-relay-config-v1" in html
