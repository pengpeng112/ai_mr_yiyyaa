"""
Static checks for the feedback UI (V1).

The tests read frontend files directly and do not require a running app.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_FEEDBACK_HTML = _STATIC_DIR / "templates" / "pages" / "feedback.html"
_FEEDBACK_CSS = _STATIC_DIR / "styles" / "pages" / "feedback.css"
_APP_JS = _STATIC_DIR / "scripts" / "app.js"
_INDEX_HTML = _STATIC_DIR / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_feedback_metrics_strip_has_full_status_cards():
    """V1：摘要条包含 已确认/已整改 卡片（后端 stats 已返回）"""
    html = _read(_FEEDBACK_HTML)

    assert "fb-metrics-strip" in html
    assert "近期不一致" in html
    assert "高风险" in html
    assert "待确认" in html
    assert "已确认" in html
    assert "已整改" in html
    assert "已关闭" in html
    assert "整改闭环率" in html


def test_feedback_v1_has_timeline_and_table_enhancement():
    """V1：闭环时间线 + 表格统一密度"""
    html = _read(_FEEDBACK_HTML)
    css = _read(_FEEDBACK_CSS)

    # 闭环时间线替代状态变更表
    assert "闭环时间线" in html
    assert "fb-timeline" in html
    assert "fb-timeline-node" in html
    assert "fb-timeline-dot" in html
    # 表格统一密度
    assert "medical-data-table" in html
    # CSS 时间线样式
    assert ".fb-timeline" in css
    assert ".fb-timeline-dot" in css
    assert ".tl-closed" in css
    assert ".tl-acknowledged" in css


def test_feedback_assets_are_cache_busted():
    html = _read(_INDEX_HTML)
    js = _read(_APP_JS)

    assert "/styles/pages/feedback.css?v=" in html
    assert "/templates/pages/feedback.html?v=" in html
    assert "./modules/feedback.js?v=" in js
