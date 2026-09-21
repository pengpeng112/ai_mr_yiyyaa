"""046 T9a 修复的专项测试（045 D1/D2 见 test_gate_scripts_20260906.py；本文件为
09-09 ST-001/ST-002/ST-005/OBS-1）。

- ST-002：4173 占用时按服务身份决定复用或改用空闲备选端口（PLAYWRIGHT_BASE_URL 注入）；
- ST-001：feedback_stats.get_top_issues 非空过滤 LENGTH>0（SQLite 行为 + Oracle 方言编译断言）；
- ST-005：scheduler-daily/discharge 空 body=200 且磁盘配置零改动（兼容语义，不改 422）；
- OBS-1：demo 凭据只在 demo 通道注册/展示，主服务启动不 seed demo 用户。

全部为纯函数/monkeypatch/内存库单测，不起真实服务、不杀任何外部进程。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_gates_20260906 as run_gates

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- ST-002：预览端口身份核验


def test_st002_free_4173_uses_default_port():
    port, note, env = run_gates.resolve_preview_port(
        is_busy=lambda p: False, fetch=lambda: "", markers=set())
    assert port == 4173 and note == "" and env is None


def test_st002_occupied_same_build_reuses():
    markers = {"/ui-next/assets/index-ABC123.js"}
    port, note, env = run_gates.resolve_preview_port(
        is_busy=lambda p: p == 4173,
        fetch=lambda: f'<script src="{list(markers)[0]}"></script>',
        markers=markers)
    assert port == 4173 and env is None and "identity-verified" in note


def test_st002_stale_build_falls_back_to_free_port():
    """旧构建（资产指纹不同）不能复用：改用空闲备选端口并注入 PLAYWRIGHT_BASE_URL。"""
    current_markers = {"/ui-next/assets/index-NEW999.js"}
    served = '<script src="/ui-next/assets/index-OLD111.js"></script>'   # 旧 dist
    port, note, env = run_gates.resolve_preview_port(
        is_busy=lambda p: p == 4173,
        fetch=lambda: served,
        markers=current_markers,
        fallback_ports=(4273, 4274))
    assert port == 4273 and env == "http://127.0.0.1:4273/ui-next/"
    assert "旧构建" in note


def test_st002_foreign_service_or_unprobeable_falls_back():
    """外来服务/探测失败同样走备选端口。"""
    port, note, env = run_gates.resolve_preview_port(
        is_busy=lambda p: p in (4173, 4273),
        fetch=lambda: "<html>some other app</html>",
        markers={"/ui-next/assets/index-X.js"},
        fallback_ports=(4273, 4274))
    assert port == 4274 and env == "http://127.0.0.1:4274/ui-next/"
    # 探测完全失败（空响应）
    port2, _note2, env2 = run_gates.resolve_preview_port(
        is_busy=lambda p: p == 4173,
        fetch=lambda: "",
        markers={"/ui-next/assets/index-X.js"},
        fallback_ports=(4273,))
    assert port2 == 4273 and env2 is not None


def test_st002_all_fallback_ports_busy_reports_failure():
    port, note, env = run_gates.resolve_preview_port(
        is_busy=lambda p: True,
        fetch=lambda: "whatever",
        markers={"/ui-next/assets/index-X.js"},
        fallback_ports=(4273, 4274))
    assert port is None and env is None and "no-free-preview-port" in note


def test_st002_port_competition_picks_next_free():
    busy_set = {4173, 4273, 4274, 4275}
    port, note, env = run_gates.resolve_preview_port(
        is_busy=lambda p: p in busy_set,
        fetch=lambda: "foreign",
        markers={"/ui-next/assets/index-X.js"},
        fallback_ports=(4273, 4274, 4275, 4276))
    assert port == 4276 and env == "http://127.0.0.1:4276/ui-next/"


def test_st002_expected_build_markers_from_real_dist():
    markers = run_gates.expected_build_markers(ROOT / "frontend" / "dist" / "index.html")
    assert markers, "frontend/dist/index.html 应解析出 assets 指纹"
    assert all(m.startswith("assets/") or "/assets/" in m for m in markers)


# ---------------------------------------------------------------- ST-001：Oracle 非空过滤


@pytest.fixture()
def stats_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.models import QCFeedback, Base as AppBase

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    QCFeedback.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _add_feedback(session, text, count=1, dept_id=1):
    from app.models import QCFeedback
    for _ in range(count):
        session.add(QCFeedback(push_log_id=1, dept_id=dept_id, severity="medium",
                               status="pending", feedback_text=text, created_by=1))
    session.commit()


def test_st001_sqlite_filters_null_and_empty_keeps_order_and_limit(stats_session):
    from app.services.feedback_stats import FeedbackStatsService
    svc = FeedbackStatsService(stats_session)
    _add_feedback(stats_session, "入院记录超时", count=3)
    _add_feedback(stats_session, "缺首程", count=2)
    _add_feedback(stats_session, "缺手术记录", count=1)
    _add_feedback(stats_session, "", count=5)          # 空串不得计入
    _add_feedback(stats_session, None, count=7)        # NULL 不得计入

    rows = svc.get_top_issues(limit=10)
    assert [r["issue"] for r in rows] == ["入院记录超时", "缺首程", "缺手术记录"]
    assert [r["count"] for r in rows] == [3, 2, 1]
    assert svc.get_top_issues(limit=2) == [
        {"issue": "入院记录超时", "count": 3},
        {"issue": "缺首程", "count": 2},
    ]
    # dept 过滤路径同语义
    rows_d2 = svc.get_top_issues(limit=10, dept_id=2)
    assert rows_d2 == []


def test_st001_oracle_dialect_sql_has_no_empty_string_compare():
    """Oracle 方言编译结果禁止出现 != ''/<> ''（恒 NULL 语义），必须走 LENGTH。"""
    from sqlalchemy import func, select
    from sqlalchemy.dialects import oracle
    from app.models import QCFeedback

    count_col = func.count(QCFeedback.id).label("count")
    stmt = (
        select(QCFeedback.feedback_text, count_col)
        .where(QCFeedback.feedback_text.isnot(None),
               func.length(QCFeedback.feedback_text) > 0)
        .group_by(QCFeedback.feedback_text)
        .order_by(count_col.desc())
        .limit(10)
    )
    sql = str(stmt.compile(dialect=oracle.dialect()))
    assert "LENGTH" in sql.upper()
    for bad in ("!= ''", "<> ''", "!=''", "<>''"):
        assert bad not in sql, f"Oracle 非空过滤仍使用空串比较: {bad}"


def test_st001_service_query_compiles_oracle_dialect_safely(stats_session):
    """服务实际构造的查询语句在 Oracle 方言下编译不含空串比较。"""
    from sqlalchemy.dialects import oracle
    from app.services.feedback_stats import FeedbackStatsService

    captured = {}

    class _CapturingSession:
        def query(self, *entities):
            from sqlalchemy.orm import Query
            q = stats_session.query(*entities)
            captured["statement"] = None
            # 包装以捕获最终编译前的语句：filter/group/order/limit 全链路后编译
            return _ChainCapture(q, captured)

    class _ChainCapture:
        def __init__(self, q, captured):
            self._q = q
            self._captured = captured

        def filter(self, *a, **k):
            return _ChainCapture(self._q.filter(*a, **k), self._captured)

        def group_by(self, *a, **k):
            return _ChainCapture(self._q.group_by(*a, **k), self._captured)

        def order_by(self, *a, **k):
            return _ChainCapture(self._q.order_by(*a, **k), self._captured)

        def limit(self, *a, **k):
            final = self._q.limit(*a, **k)
            self._captured["statement"] = final.statement
            return final

        def all(self):
            return self._q.all()

    svc = FeedbackStatsService(_CapturingSession())
    assert svc.get_top_issues(limit=5) == []
    sql = str(captured["statement"].compile(dialect=oracle.dialect()))
    assert "LENGTH" in sql.upper()
    for bad in ("!= ''", "<> ''", "!=''", "<>''"):
        assert bad not in sql


def test_st001_uses_length_not_string_compare_in_source():
    """源码级防回退：get_top_issues 内不得再出现 `!= ""` 过滤。"""
    src = (ROOT / "app" / "services" / "feedback_stats.py").read_text(encoding="utf-8")
    start = src.index("def get_top_issues")
    end = src.index("def ", start + 10)
    body = src[start:end]
    assert "length(" in body
    assert '!= ""' not in body and '!= ""' not in body.replace(" ", "")


# ---------------------------------------------------------------- ST-005：调度空 body 兼容


def _scheduler_client(monkeypatch, tmp_path, initial: dict):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import config as config_router_module
    from app import database as database_module
    from app import auth as auth_module

    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(initial, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr(config_router_module, "load_config",
                        lambda: json.loads(cfg_file.read_text(encoding="utf-8")))
    monkeypatch.setattr(config_router_module, "update_section",
                        lambda section, data: _save(cfg_file, section, data))
    monkeypatch.setattr(config_router_module, "update_scheduler",
                        lambda enabled, cron, run_mode, job_id=None:
                        {"applied": True, "message": "ok"})

    app = FastAPI()
    app.include_router(config_router_module.router, prefix="/api/config")

    class _FakeUser:
        id = 1
        role_id = 1
        username = "admin"

    app.dependency_overrides[auth_module.get_current_user] = lambda: _FakeUser()
    app.dependency_overrides[database_module.get_db] = lambda: _DummyDb()
    return TestClient(app), lambda: json.loads(cfg_file.read_text(encoding="utf-8"))


def _save(cfg_file, section, data):
    cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    cfg[section] = data
    cfg_file.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg[section]


class _DummyDb:
    def query(self, _model):
        return self

    def filter(self, *_a, **_k):
        return self

    def first(self):
        return SimpleNamespace(name="admin")


ST005_INITIAL = {
    "scheduler_daily": {"enabled": True, "cron": "10 10 * * *",
                        "audit_run_mode": "daily_increment",
                        "audit_type_codes": ["progress_vs_nursing"]},
    "scheduler_discharge": {"enabled": False, "cron": "30 11 * * *",
                            "audit_run_mode": "discharge_final",
                            "audit_type_codes": ["progress_vs_nursing"]},
}


def test_st005_scheduler_daily_empty_body_200_and_zero_change(monkeypatch, tmp_path):
    client, load = _scheduler_client(monkeypatch, tmp_path, ST005_INITIAL)
    before = load()["scheduler_daily"]
    r = client.post("/api/config/scheduler-daily", json={})
    assert r.status_code == 200
    after = load()["scheduler_daily"]
    assert after == before, "空 body 保存后磁盘配置必须零改动（已裁定语义，不改 422）"


def test_st005_scheduler_discharge_empty_body_200_and_zero_change(monkeypatch, tmp_path):
    client, load = _scheduler_client(monkeypatch, tmp_path, ST005_INITIAL)
    before = load()["scheduler_discharge"]
    r = client.post("/api/config/scheduler-discharge", json={})
    assert r.status_code == 200
    assert load()["scheduler_discharge"] == before


def test_st005_partial_save_preserves_existing_values(monkeypatch, tmp_path):
    client, load = _scheduler_client(monkeypatch, tmp_path, ST005_INITIAL)
    r = client.post("/api/config/scheduler-daily", json={"enabled": False})
    assert r.status_code == 200
    section = load()["scheduler_daily"]
    assert section["enabled"] is False
    assert section["cron"] == "10 10 * * *"          # 未提交字段保留原值
    assert section["audit_run_mode"] == "daily_increment"


def test_st005_legacy_scheduler_empty_body_still_422(monkeypatch, tmp_path):
    """legacy scheduler 节无编程期字段赋值 → 空 body 保持 422（现有零改动语义整体不回退）。"""
    client, load = _scheduler_client(monkeypatch, tmp_path, ST005_INITIAL)
    r = client.post("/api/config/scheduler", json={})
    assert r.status_code == 422
    assert "scheduler" not in load() or load().get("scheduler") is None


# ---------------------------------------------------------------- OBS-1：demo 凭据隔离


def test_obs1_demo_seed_not_called_by_startup(monkeypatch, tmp_path):
    """app.main 组装不触碰 demo seed：demo 用户只经 demo_env 显式创建。"""
    import app.main as main_module
    src = Path(main_module.__file__).read_text(encoding="utf-8")
    for banned in ("demo_support.seed", "seed_database", "DEMO_PASSWORD"):
        assert banned not in src, f"app.main 不得引用 demo seed（{banned}）"
    db_src = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
    assert "demo_support" not in db_src


def test_obs1_demo_password_absent_from_static_frontend():
    """前端静态资产不落 demo 凭据明文（凭据只在 demo_env 输出通道展示）。"""
    hits = []
    for pattern in ("static/templates/*.html", "static/scripts/**/*.js",
                    "frontend/src/**/*.ts", "frontend/src/**/*.vue"):
        for path in ROOT.glob(pattern):
            try:
                if "Demo-12Dept" in path.read_text(encoding="utf-8", errors="ignore"):
                    hits.append(str(path))
            except OSError:
                continue
    assert not hits, f"demo 口令泄漏到前端资产: {hits}"


def test_obs1_demo_env_prints_login_only_via_explicit_command():
    src = (ROOT / "scripts" / "demo_env.py").read_text(encoding="utf-8")
    assert "DEMO_PASSWORD" in src and "login" in src   # 凭据出口=demo_env 显式输出
