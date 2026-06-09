"""
Static checks for the phase-2 dashboard UI.

These tests read frontend assets directly. They do not need a server, DB,
browser, or network access.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_DASHBOARD_HTML = _STATIC_DIR / "templates" / "pages" / "dashboard.html"
_DASHBOARD_JS = _STATIC_DIR / "scripts" / "modules" / "dashboard.js"
_DASHBOARD_CSS = _STATIC_DIR / "styles" / "pages" / "dashboard.css"
_APP_JS = _STATIC_DIR / "scripts" / "app.js"
_INDEX_HTML = _STATIC_DIR / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_method_body(js: str, method_name: str) -> str:
    marker = f"{method_name}("
    start = js.find(marker)
    assert start != -1, f"{method_name} method not found"
    body_start = js.find("{", start)
    assert body_start != -1, f"{method_name} body not found"

    depth = 0
    for pos in range(body_start, len(js)):
        ch = js[pos]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return js[body_start : pos + 1]
    raise AssertionError(f"{method_name} body is not balanced")


def test_dashboard_template_contains_phase2_cockpit_sections():
    html = _read(_DASHBOARD_HTML)

    assert 'class="page-view page-dashboard dashboard-screen" v-loading="dashboardLoading"' in html
    assert "dashboard-command-strip" in html
    assert "今日不一致率" in html
    assert "前置机失败" in html
    assert "医生未查看" in html
    assert "dashDimensionChart" in html
    assert "质控维度分布" in html
    assert "最近前置机告警" in html
    assert "relayAlertStatusLabel(item.status)" in html


def test_dashboard_state_fields_are_declared_in_app_data():
    js = _read(_APP_JS)

    for snippet in (
        "inconsistencyRate: null",
        "relayFailed: 0",
        "relayUnviewed: 0",
        "dashboardRelayRecent: []",
        "dashboardUpdatedAt: ''",
    ):
        assert snippet in js


def test_dashboard_loads_phase2_data_sources():
    js = _read(_DASHBOARD_JS)

    assert "/api/stats/dimensions" in js
    assert "/api/patient-qc/relay-alert/summary" in js
    assert "/api/patient-qc/relay-alert/logs" in js
    assert "params: { page: 1, limit: 5 }" in js
    assert "renderDashDimensionChart" in js
    assert "dashboardRelayRecent" in js
    assert "dashboardUpdatedAt" in js


def test_dashboard_relay_navigation_sets_tab_before_loading_page():
    js = _read(_DASHBOARD_JS)
    target_body = _extract_method_body(js, "openDashboardTarget")
    relay_start = target_body.find("target === 'relay-alerts'")
    assert relay_start != -1
    relay_block = target_body[relay_start : target_body.find("return;", relay_start)]

    assert "this.patientQcTab = 'relay-alerts';" in relay_block
    assert relay_block.find("this.patientQcTab") < relay_block.find("this.switchMenu('patient-qc')")
    assert "patient_id: ''" in relay_block
    assert "status: ''" in relay_block
    assert "viewed_flag: ''" in relay_block
    assert "switchPatientQcTab" not in relay_block

    alert_body = _extract_method_body(js, "openDashboardRelayAlert")
    assert alert_body.find("this.patientQcTab = 'relay-alerts';") < alert_body.find("this.switchMenu('patient-qc')")
    assert "patient_id: patientId" in alert_body
    assert "status: ''" in alert_body
    assert "viewed_flag: ''" in alert_body
    assert "queryRelayAlertLogs" not in alert_body


def test_dashboard_css_has_scoped_phase2_layout_rules():
    css = _read(_DASHBOARD_CSS)

    for snippet in (
        ".dashboard-screen",
        ".dashboard-command-strip",
        ".panel-dimension",
        ".relay-recent-list",
        "@media (max-width: 1280px)",
        "@media (max-width: 640px)",
    ):
        assert snippet in css


def test_dashboard_phase2_assets_are_cache_busted():
    html = _read(_INDEX_HTML)
    js = _read(_APP_JS)

    assert "/styles/pages/dashboard.css?v=20260608-dashboard-phase2" in html
    assert "/scripts/app.js?v=" in html
    assert "./modules/dashboard.js?v=20260608-dashboard-phase2" in js
