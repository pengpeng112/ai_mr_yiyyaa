"""历史重跑前端静态契约检查。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_push_page_has_historical_rerun_mode():
    html = (ROOT / "static" / "templates" / "pages" / "push.html").read_text(encoding="utf-8")
    assert "historical_reaudit" in html
    assert "预检候选" in html
    assert "确认并创建批次" in html
    assert "重跑原因" in html


def test_push_js_has_historical_rerun_api_calls():
    js = (ROOT / "static" / "scripts" / "modules" / "push.js").read_text(encoding="utf-8")
    assert "/api/push/historical-rerun/preview" in js
    assert "/api/push/historical-rerun/batches" in js
    assert "previewHistoricalRerun" in js
    assert "confirmHistoricalRerunBatch" in js
    assert "controlHistoricalRerunBatch" in js


def test_app_js_has_hist_rerun_state():
    app = (ROOT / "static" / "scripts" / "app.js").read_text(encoding="utf-8")
    assert "run_mode" in app
    assert "histRerunPreview" in app
    assert "reaudit_reason" in app
