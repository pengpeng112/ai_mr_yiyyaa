"""
Static checks for the dashboard UI (V3 dark tech cockpit).

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


def test_dashboard_template_contains_v2_cockpit_sections():
    html = _read(_DASHBOARD_HTML)

    assert "dashboard-tech-v2" in html
    assert "dashboard-command-strip" in html
    assert "今日不一致率" in html
    assert "前置机失败" in html
    assert "医生未查看" in html
    assert "dashDimensionChart" in html
    assert "dashTrendChart" in html
    assert "dashSeverityChart" in html
    assert "质控维度通过率分布" in html
    assert "ai-flow-line" in html


def test_dashboard_v3_has_kpi_tiers_and_flow_chain():
    """V3：核心/辅助 KPI 分层 + 完整闭环链路 + 科室进度条"""
    html = _read(_DASHBOARD_HTML)
    css = _read(_DASHBOARD_CSS)
    js = _read(_DASHBOARD_JS)

    # 核心 KPI（4 大卡）
    assert "dashboard-kpi-core" in html
    assert "今日核心态势" in html
    # 辅助 KPI（紧凑横排）
    assert "dashboard-kpi-aux" in html
    assert "kpi-aux-item" in html
    # 完整闭环 6 节点
    assert "完整闭环" in html
    assert "结果入库" in html
    assert "反馈闭环" in html
    # 科室进度条
    assert "dept-top-bar" in html
    assert "deptTopPct" in js
    # CSS 新分层
    assert ".dashboard-kpi-core" in css
    assert ".dashboard-kpi-aux" in css
    assert ".dept-top-bar" in css
    # 流程链路多状态
    assert "flow-danger" in css


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


def test_dashboard_loads_v2_data_sources():
    js = _read(_DASHBOARD_JS)

    assert "/api/stats/dimensions" in js
    assert "/api/patient-qc/relay-alert/summary" in js
    assert "/api/patient-qc/relay-alert/logs" in js
    assert "params: { page: 1, limit: 5 }" in js
    assert "renderDashDimensionChart" in js
    assert "dashboardRelayRecent" in js


def test_dashboard_relay_navigation_uses_dedicated_page():
    js = _read(_DASHBOARD_JS)
    target_body = _extract_method_body(js, "openDashboardTarget")
    relay_start = target_body.find("target === 'relay-alerts'")
    assert relay_start != -1
    relay_block = target_body[relay_start : target_body.find("return;", relay_start)]

    assert "this.switchMenu('relay-alert-logs')" in relay_block
    assert "patient_id: ''" in relay_block
    assert "status: ''" in relay_block
    assert "viewed_flag: ''" in relay_block

    alert_body = _extract_method_body(js, "openDashboardRelayAlert")
    assert "this.switchMenu('relay-alert-logs')" in alert_body
    assert "patient_id: patientId" in alert_body
    assert "status: ''" in alert_body
    assert "viewed_flag: ''" in alert_body


def test_dashboard_css_has_v2_layout_rules():
    css = _read(_DASHBOARD_CSS)

    for snippet in (
        ".dashboard-screen",
        ".dashboard-tech-v2",
        ".dashboard-command-strip",
        ".dashboard-flow-panel",
        ".ai-flow-line",
        ".health-list",
        "@media (max-width: 1280px)",
        "@media (max-width: 640px)",
    ):
        assert snippet in css


def test_dashboard_v2_assets_are_cache_busted():
    html = _read(_INDEX_HTML)
    js = _read(_APP_JS)

    assert "/styles/pages/dashboard.css?v=" in html
    assert "/scripts/app.js?v=" in html
    assert "./modules/dashboard.js?v=" in js


def test_dashboard_v3_colors_are_centralized():
    """V3：ECharts 深色颜色集中为 DASH_COLORS 常量，不再散落硬编码"""
    js = _read(_DASHBOARD_JS)

    assert "DASH_COLORS" in js
    assert "DASH_TOOLTIP" in js
    # 图表 series 颜色应引用常量，而非裸硬编码
    for forbidden in (
        "color: '#22d3ee'",
        "color: '#ef4444'",
        "color: '#f59e0b'",
        "color: '#3b82f6'",
    ):
        assert forbidden not in js, f"散落硬编码颜色应替换为常量: {forbidden}"
