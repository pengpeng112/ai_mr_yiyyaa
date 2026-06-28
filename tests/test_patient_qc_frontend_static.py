"""
Static checks for the patient QC and relay-alert UI.

The tests read frontend files directly and do not require a running app.
Relay alert was split from patient_qc.html into relay_alert.html.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_PATIENT_QC_HTML = _STATIC_DIR / "templates" / "pages" / "patient_qc.html"
_RELAY_ALERT_HTML = _STATIC_DIR / "templates" / "pages" / "relay_alert.html"
_PATIENT_QC_JS = _STATIC_DIR / "scripts" / "modules" / "patient_qc.js"
_PATIENT_QC_CSS = _STATIC_DIR / "styles" / "pages" / "patient_qc.css"
_APP_JS = _STATIC_DIR / "scripts" / "app.js"
_INDEX_HTML = _STATIC_DIR / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_relay_alert_page_contains_workbench_sections():
    html = _read(_RELAY_ALERT_HTML)

    assert "relay-alert-summary-strip" in html
    assert "告警总数" in html
    assert "发送成功率" in html
    assert "医生查看率" in html
    assert "resetRelayAlertFilter" in html
    assert "openRelayAlertDetail(scope.row)" in html
    assert 'v-model="relayAlertDetailVisible"' in html
    assert 'size="min(92vw, 520px)"' in html
    assert "前置机告警详情" in html


def test_relay_alert_state_fields_are_declared():
    js = _read(_APP_JS)

    assert "relayAlertSummary:" in js
    assert "success_rate: null" in js
    assert "view_rate: null" in js
    assert "relayAlertDetailVisible: false" in js
    assert "relayAlertDetail: null" in js


def test_patient_qc_js_uses_existing_relay_alert_apis():
    js = _read(_PATIENT_QC_JS)

    assert "/api/patient-qc/relay-alert/logs" in js
    assert "/api/patient-qc/relay-alert/summary" in js
    assert "/api/patient-qc/relay-alert/retry/" in js
    assert "resetRelayAlertFilter()" in js
    assert "openRelayAlertDetail(row)" in js


def test_relay_alert_label_helpers_exist():
    """relayAlertStatusLabel and other label helpers are defined in app.js."""
    js = _read(_APP_JS)

    assert "relayAlertStatusLabel" in js
    assert "relayAlertSeverityLabel" in js
    assert "relayAlertViewedLabel" in js


def test_relay_alert_summary_follows_current_filters():
    js = _read(_PATIENT_QC_JS)

    assert "const f = this.relayAlertFilter || {};" in js
    assert "if (f.patient_id) params.patient_id = f.patient_id;" in js
    assert "if (f.status) params.status = f.status;" in js
    assert "params.viewed_flag = f.viewed_flag;" in js
    assert "apiGet('/api/patient-qc/relay-alert/summary', { params })" in js


def test_patient_qc_phase3_css_exists():
    css = _read(_PATIENT_QC_CSS)

    for snippet in (
        ".relay-alert-summary-strip",
        ".relay-alert-summary-card",
        ".relay-alert-detail-grid",
        ".relay-alert-detail-section",
        "@media (max-width:1100px)",
        "@media (max-width:640px)",
    ):
        assert snippet in css


def test_patient_qc_assets_are_cache_busted():
    html = _read(_INDEX_HTML)
    js = _read(_APP_JS)

    assert "/styles/pages/patient_qc.css?v=" in html
    assert "/templates/pages/patient_qc.html?v=" in html
    assert "/scripts/app.js?v=" in html
    assert "./modules/patient_qc.js?v=" in js


def test_patient_qc_v1_has_summary_strip_and_fixed_columns():
    """V1：顶部摘要条 + 表格固定列 + 页面根 class"""
    html = _read(_PATIENT_QC_HTML)
    css = _read(_PATIENT_QC_CSS)
    js = _read(_PATIENT_QC_JS)

    # 页面根 class 隔离钩子
    assert "page-patient-qc" in html
    # 顶部摘要条
    assert "pq-summary-strip" in html
    assert "总病例" in html
    assert "本页高危" in html
    assert "本页待处理" in html
    # 表格固定列
    assert 'fixed="left"' in html
    assert "medical-data-table" in html
    # 页统计计算方法
    assert "pqPageStats()" in html
    assert "pqPageStats() {" in js or "pqPageStats()" in js
    # CSS 摘要条样式
    assert ".pq-summary-strip" in css
    assert ".medical-data-table" in css
