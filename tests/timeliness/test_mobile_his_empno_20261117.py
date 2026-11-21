"""白屏修复（APP.mount）与 HIS.SYS_EMPLOYEE 工号直登虚拟身份测试（2026-11-17）。

覆盖：mount 源码断言 / verify_token his_empno 分支 / get_current_user 虚拟身份 /
HIS lookup 命中与拒绝 / 直登签发 JWT+Cookie / 科室可见性隔离 / me 虚拟返回 /
常规 empno 应用库账号优先于 HIS 直登。
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app import auth as auth_module
from app.routers import mobile_timeliness as mt
from tests.timeliness.test_mobile_timeliness_20261116 import env  # noqa: F401


@pytest.fixture(autouse=True)
def _offline_patient_names(monkeypatch):
    monkeypatch.setenv("MOBILE_TIMELINESS_EMPNO_LOGIN", "true")
    """离线单测零连库：姓名补齐层直接降级为空 map。"""
    monkeypatch.setattr(mt.timeliness, "_patient_name_map", lambda pairs: {})


def client_as(app, user) -> TestClient:
    app.dependency_overrides[auth_module.get_current_user] = lambda: user
    return TestClient(app)


# ---- 白屏修复：mount 源码断言 ----


def test_h5_js_mounts_vue_app():
    js = (pathlib.Path(__file__).resolve().parents[2]
          / "static" / "scripts" / "mobile" / "timeliness_h5.js").read_text("utf-8")
    assert "APP.mount('#app')" in js or 'APP.mount("#app")' in js
    # mount 必须在 detectBase().then 之前（先挂载再探测，否则 v-cloak 永留）
    assert js.index("APP.mount('#app')") < js.index("detectBase().then")


def test_html_cache_param_bumped_for_mount_fix():
    html = (pathlib.Path(__file__).resolve().parents[2]
            / "static" / "templates" / "mobile" / "timeliness_h5.html").read_text("utf-8")
    assert "timeliness_h5.js?v=20261118b" in html


def test_h5_js_spin_forever_guards():
    """2026-11-17 转圈修复守卫：loadMe 非 2xx reject + apiFetch 空 token 不发
    Authorization + 启动 8s 兜底置 ready。"""
    js = (pathlib.Path(__file__).resolve().parents[2]
          / "static" / "scripts" / "mobile" / "timeliness_h5.js").read_text("utf-8")
    assert "if (!res.ok)" in js and "Promise.reject(res)" in js          # loadMe 失败进启动链
    assert "if (token) headers['Authorization']" in js                   # 空 token 不发 Bearer
    assert "8000" in js and "state.ready = true" in js                   # 8s 兜底
    assert "AbortController" in js                                       # ping 3s 超时
    # /me 走 apiFetch 且失败 reject（不再静默 resolve）
    assert "apiFetch('/me')" in js


# ---- verify_token：his_empno 分支 ----


def _make_his_token(empno="90001", name="测试医师", dept_code="040112", dept_name="耳鼻喉一科"):
    now = datetime.utcnow()
    payload = {
        "sub": f"his_empno:{empno}",
        "username": empno,
        "full_name": name,
        "dept_code": dept_code,
        "dept_name": dept_name,
        "exp": now + timedelta(hours=8),
        "iat": now,
    }
    return pyjwt.encode(payload, auth_module.JWT_SECRET_KEY, algorithm=auth_module.JWT_ALGORITHM)


def test_verify_token_parses_his_empno_sub():
    data = auth_module.verify_token(_make_his_token())
    assert data["is_his_empno"] is True
    assert data["his_empno"] == "90001"
    assert data["his_dept_code"] == "040112"
    assert data["his_dept_name"] == "耳鼻喉一科"
    assert data["user_id"] == 0


def test_get_current_user_constructs_his_virtual_user(env):
    db, users, app = env
    token = _make_his_token()
    client = TestClient(app)  # 不覆盖 get_current_user：让 his_empno token 走真实校验
    client.headers.update({"Authorization": f"Bearer {token}"})
    resp = client.get("/api/mobile/timeliness/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["role"] == "his_employee"
    assert body["user"]["role_label"] == "临床员工（HIS 工号直登）"
    assert body["user"]["full_name"] == "测试医师"
    assert body["user"]["dept_name"] == "耳鼻喉一科"
    assert body["capabilities"]["can_approve"] is False
    assert body["capabilities"]["can_exempt"] is False


# ---- HIS lookup：命中与拒绝（mock 连接） ----


class _FakeCur:
    def __init__(self, row):
        self._row = row
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchone(self):
        return self._row

    def fetchall(self):
        return [self._row] if self._row else []

    def close(self):
        pass


class _FakeConn:
    def __init__(self, row):
        self.cur = _FakeCur(row)

    def cursor(self):
        return self.cur

    def close(self):
        pass


def test_his_lookup_returns_employee_when_valid(monkeypatch):
    from app.timeliness import his_oracle_reader

    row = ("90001", "测试医师", "040112", "耳鼻喉一科")
    monkeypatch.setattr(his_oracle_reader, "_get_connection", lambda: _FakeConn(row))
    result = mt._his_employee_lookup("90001")
    assert result == {
        "empno": "90001", "name": "测试医师",
        "dept_code": "040112", "dept_name": "耳鼻喉一科",
    }


def test_his_lookup_rejects_missing_or_no_dept(monkeypatch):
    from app.timeliness import his_oracle_reader

    monkeypatch.setattr(his_oracle_reader, "_get_connection", lambda: _FakeConn(None))
    assert mt._his_employee_lookup("ghost999") is None

    monkeypatch.setattr(his_oracle_reader, "_get_connection",
                        lambda: _FakeConn(("90002", "测试医师", "", "")))
    assert mt._his_employee_lookup("90002") is None


def test_his_lookup_disabled_by_env(monkeypatch):
    monkeypatch.setenv("MOBILE_TIMELINESS_HIS_EMPNO_LOGIN", "false")
    assert mt._his_employee_lookup("90001") is None


# ---- 直登：应用库未命中 → HIS 签发 JWT+Cookie ----


def test_empno_login_falls_back_to_his_and_issues_token(monkeypatch, env):
    from app.timeliness import his_oracle_reader

    row = ("90001", "测试医师", "040112", "耳鼻喉一科")
    monkeypatch.setattr(his_oracle_reader, "_get_connection", lambda: _FakeConn(row))
    _, users, app = env
    client = client_as(app, users["admin"])
    resp = client.post("/api/mobile/timeliness/login/empno", json={"empno": "90001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["his_employee"] is True
    assert body["user"]["full_name"] == "测试医师"
    assert body["user"]["role"] == "his_employee"
    assert body["access_token"]
    assert "med_audit_token" in resp.headers.get("set-cookie", "")

    # 签发的 his_empno token 可直接用于鉴权接口，且科室可见性限定 040112
    # 清除前面 client_as 设置的 get_current_user override（同 app 共享），
    # 让 his_empno token 走真实校验与科室可见性
    app.dependency_overrides.pop(auth_module.get_current_user, None)
    fresh = TestClient(app)
    fresh.headers.update({"Authorization": f"Bearer {body['access_token']}"})
    events = fresh.get("/api/mobile/timeliness/events?status=ACTIVE_RISK")
    assert events.status_code == 200
    payload = events.json()
    assert payload["total"] >= 1
    assert {i["dept_code"] for i in payload["items"]} == {"040112"}

    approvals = fresh.get("/api/mobile/timeliness/approvals?status_tab=all")
    assert approvals.status_code == 200
    assert {i["dept_code"] for i in approvals.json()["items"]} == {"040112"}


def test_empno_login_unknown_and_no_his_match_returns_401(monkeypatch, env):
    from app.timeliness import his_oracle_reader

    monkeypatch.setattr(his_oracle_reader, "_get_connection", lambda: _FakeConn(None))
    _, users, app = env
    client = client_as(app, users["admin"])
    resp = client.post("/api/mobile/timeliness/login/empno", json={"empno": "ghost777"})
    assert resp.status_code == 401


def test_empno_login_prefers_app_account_over_his(env):
    """应用库已有账号时走常规 empno 链路（不触发 HIS 直登）。"""
    _, users, app = env
    client = client_as(app, users["admin"])
    resp = client.post("/api/mobile/timeliness/login/empno", json={"empno": "mob_scoped"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["username"] == "mob_scoped"
    assert "his_employee" not in body


# ---- 虚拟身份写操作天然 403（role_id=None） ----


def test_his_virtual_cannot_approve_or_exempt(env):
    _, users, app = env
    token = _make_his_token()
    client = TestClient(app)  # 不覆盖：虚拟身份 role_id=None → 写操作 403
    client.headers.update({"Authorization": f"Bearer {token}"})
    resp = client.post("/api/mobile/timeliness/approvals/1/approve", json={"dry_run": True})
    assert resp.status_code == 403
    resp2 = client.post("/api/mobile/timeliness/events/1/exempt",
                        json={"exempt_reason": "测试"})
    assert resp2.status_code == 403
