"""统计/导出口径元数据块回归（035/RP3，B5）。

背景：运行指标快照曾出现口径漂移（PPT 数字 vs 生产实测不一致）且系统无指标元数据。
本文件固化：统计响应附 `_meta`/`meta` 块（generated_at/date_from/date_to/timezone/
filters/semantics），CSV 导出审计链携带口径元数据且文件字节不变，前端统计页展示口径行。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import ExportAuditLog, PushLog
from app.routers import logs as logs_router
from app.routers import stats as stats_router


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _admin_user():
    user = SimpleNamespace(id=9, username="admin", role_id=1)
    # apply_push_log_visibility 对管理员（role_id=1）不做科室过滤
    return user


def _seed_push_logs(db):
    rows = [
        PushLog(push_time=datetime(2026, 8, 20, 9, 0), trigger_type="auto", query_date="2026-08-18",
                patient_id="P1", status="success", pushed_flag=1, severity="low", dept="内科"),
        PushLog(push_time=datetime(2026, 8, 22, 9, 0), trigger_type="auto", query_date="2026-08-21",
                patient_id="P2", status="success", pushed_flag=1, severity="high", dept="外科"),
        PushLog(push_time=datetime(2026, 8, 23, 9, 0), trigger_type="auto", query_date="2026-08-22",
                patient_id="P3", status="failed", pushed_flag=0, severity="", dept="内科"),
    ]
    for row in rows:
        db.add(row)
    db.commit()
    return rows


def _visibility_monkeypatch(monkeypatch):
    """管理员路径下 visibility 过滤为恒等（不引入 RBAC 种子数据）。

    stats/logs 路由各自 from-import 了该函数，需分别 patch 路由命名空间引用。
    """
    from app.services import dept_visibility
    identity = lambda q, user, db=None, dept_column=None: q  # noqa: E731
    monkeypatch.setattr(dept_visibility, "apply_push_log_visibility", identity)
    monkeypatch.setattr(stats_router, "apply_push_log_visibility", identity)
    monkeypatch.setattr(logs_router, "apply_push_log_visibility", identity)


_META_KEYS = {"generated_at", "timezone", "date_from", "date_to", "filters", "semantics"}
_GENERATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class TestStatsMetadataBlock:
    def test_summary_meta_complete_and_window_derived_from_data(self, monkeypatch):
        """T1：summary 响应含完整元数据块，窗口由数据 min/max query_date 推导。"""
        _visibility_monkeypatch(monkeypatch)
        db = _make_db()
        _seed_push_logs(db)
        result = stats_router.stats_summary(db=db, current_user=_admin_user())
        meta = result.meta
        assert set(meta.keys()) == _META_KEYS
        assert _GENERATED_AT_RE.match(meta["generated_at"])
        assert meta["timezone"] == "Asia/Shanghai"
        assert meta["date_from"] == "2026-08-18"
        assert meta["date_to"] == "2026-08-22"
        assert meta["semantics"] == "current-only"

    def test_daily_meta_window_matches_days_filter(self, monkeypatch):
        """T2：daily 端点 days=N → date_from=今天-N+1、date_to=今天，filters 回显。"""
        _visibility_monkeypatch(monkeypatch)
        db = _make_db()
        _seed_push_logs(db)
        result = stats_router.stats_daily(days=7, db=db, current_user=_admin_user())
        meta = result["_meta"]
        assert set(meta.keys()) == _META_KEYS
        today = datetime.now().strftime("%Y-%m-%d")
        expected_from = (datetime.now() - __import__("datetime").timedelta(days=6)).strftime("%Y-%m-%d")
        assert meta["date_to"] == today
        assert meta["date_from"] == expected_from
        assert meta["filters"] == {"days": 7}

    def test_all_stats_endpoints_carry_meta(self, monkeypatch):
        """全端点元数据块存在性：today/dept/severity/monthly/anomaly-top/dimensions。"""
        _visibility_monkeypatch(monkeypatch)
        db = _make_db()
        _seed_push_logs(db)
        user = _admin_user()

        assert stats_router.stats_today(db=db, current_user=user)["_meta"]["timezone"] == "Asia/Shanghai"
        assert stats_router.stats_dept(db=db, current_user=user)["_meta"]["semantics"] == "current-only"
        assert stats_router.stats_severity(db=db, current_user=user)["_meta"]["semantics"] == "current-only"
        assert stats_router.stats_monthly(db=db, current_user=user)["_meta"]["semantics"] == "current-only"
        anomaly = stats_router.anomaly_top(group_by="dept", db=db, current_user=user)
        assert anomaly["_meta"]["filters"]["inconsistency_only"] is True
        dims = stats_router.stats_dimensions(date_from="2026-08-01", date_to="2026-08-31", dept=None, db=db, current_user=user)
        # 维度统计联查未套当前结果过滤——semantics 必须如实标注
        assert dims["_meta"]["semantics"] == "all-results"
        assert dims["_meta"]["filters"]["date_from"] == "2026-08-01"

    def test_empty_data_window_is_none_not_fake(self, monkeypatch):
        """空数据时窗口为 None，不得伪造口径。"""
        _visibility_monkeypatch(monkeypatch)
        db = _make_db()
        result = stats_router.stats_summary(db=db, current_user=_admin_user())
        assert result.meta["date_from"] is None
        assert result.meta["date_to"] is None


class TestExportAuditMeta:
    def test_export_csv_audit_carries_meta_block(self, monkeypatch):
        """T3：CSV 导出审计仍记录（record_export_audit），filter_criteria 含口径元数据。"""
        _visibility_monkeypatch(monkeypatch)
        db = _make_db()
        logs_ = _seed_push_logs(db)

        captured = {}

        def fake_record_export_audit(**kwargs):
            captured.update(kwargs)
            audit = ExportAuditLog(
                user_id=kwargs.get("user_id") or 0,
                username=kwargs.get("username") or "",
                export_type=kwargs.get("export_type") or "",
                export_format=kwargs.get("export_format") or "",
                filter_criteria=kwargs.get("filter_criteria") or {},
                record_count=kwargs.get("record_count") or 0,
                status=kwargs.get("status") or "",
            )
            db.add(audit)

        monkeypatch.setattr(logs_router, "record_export_audit", fake_record_export_audit)

        request = Request({
            "type": "http", "method": "GET", "path": "/api/logs/export/csv",
            "headers": [(b"user-agent", b"focused-test")], "client": ("127.0.0.1", 1),
            "query_string": b"", "scheme": "http", "server": ("test", 80),
            "asgi": {"version": "3.0"},
        })
        # 直接函数调用需显式解析 Query(None) 默认值（FastAPI 注入层才会做）
        defaults = dict(
            status=None, dept=None, date_from="2026-08-01", date_to="2026-08-31",
            reviewed_flag=None, manual_override=None, skip_reason=None,
            audit_type_code=None, patient_name=None, discharge_dept_name=None,
            hide_superseded=True, include_superseded=False, alert_level=None,
        )
        response = logs_router.export_csv(
            **defaults,
            db=db,
            current_user=_admin_user(),
            request=request,
        )

        # 审计链保持
        assert captured["export_type"] == "push_log"
        assert captured["record_count"] == len(logs_)
        meta = captured["filter_criteria"]["meta"]
        assert _GENERATED_AT_RE.match(meta["generated_at"])
        assert meta["timezone"] == "Asia/Shanghai"
        assert meta["date_from"] == "2026-08-18"
        assert meta["date_to"] == "2026-08-22"
        assert meta["semantics"] == "current-only"
        assert meta["row_cap_hit"] is False
        # 响应仍是 CSV 文件下载
        assert response.media_type == "text/csv"


class TestFrontendStatsMetaDisplay:
    def test_stats_page_renders_meta_line_and_js_reads_meta(self):
        """前端断言：统计页含口径行元素；stats.js 读取 summary.meta。"""
        html = Path("static/templates/pages/audit.html").read_text(encoding="utf-8")
        assert "statsMeta" in html
        assert "生成于" in html

        js = Path("static/scripts/modules/stats.js").read_text(encoding="utf-8")
        assert "this.statsMeta = (this.summary && this.summary.meta) || null" in js

        index_html = Path("static/index.html").read_text(encoding="utf-8")
        assert "/scripts/app.js?v=20260901-stats-meta" in index_html
