"""企微 OAuth 回调直签发（2026-11-17 安全增强）测试。

覆盖：未配置凭据 302 裸回 / relay 换 userid 成功 → 应用库账号直签 Cookie（Location
不含 empno 凭证）/ userid 无应用库账号但 HIS 有效 → his_empno 虚拟 Cookie（/me
role=his_employee、写 403）/ 双未命中 302 且无 Cookie / Cookie 直通 /me 可用。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth as auth_module
from app.routers import mobile_timeliness as mt
from tests.timeliness.test_mobile_timeliness_20261116 import env  # noqa: F401


@pytest.fixture(autouse=True)
def _offline_patient_names(monkeypatch):
    monkeypatch.setattr(mt.timeliness, "_patient_name_map", lambda pairs: {})


class _FakeHisConn:
    def __init__(self, row):
        self._row = row

    def cursor(self):
        cur = self

        class _Cur:
            def execute(self, sql, params=None):
                pass

            def fetchone(self):
                return cur._row

            def close(self):
                pass

        return _Cur()

    def close(self):
        pass


def _patch_relay_userid(monkeypatch, userid: str):
    monkeypatch.setattr(mt, "_wecom_oauth_config", lambda: ("ww-test", "test-secret", "1000033"))
    monkeypatch.setattr(mt, "_wecom_relay_config",
                        lambda: ("https://relay.example/wecom", "relay-key"))
    monkeypatch.setattr(mt, "_wecom_relay_exchange",
                        lambda code, corpid, secret, agentid, url, key: userid)


def test_oauth_without_credentials_redirects_bare(env, monkeypatch):
    monkeypatch.setattr(mt, "_wecom_oauth_config", lambda: ("", "", ""))
    _, _, app = env
    client = TestClient(app)
    resp = client.get("/mobile/qc/timeliness/oauth/wecom/callback", params={"code": "x"},
                      follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/mobile/qc/timeliness"
    assert "set-cookie" not in {k.lower() for k in resp.headers}


def test_oauth_app_account_issues_cookie_without_empno_in_url(env, monkeypatch):
    _patch_relay_userid(monkeypatch, "mob_admin")
    _, users, app = env
    client = TestClient(app)
    resp = client.get("/mobile/qc/timeliness/oauth/wecom/callback",
                      params={"code": "real-code", "state": "empno"}, follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location == "/mobile/qc/timeliness"
    assert "empno" not in location  # 凭证不留 URL
    assert "med_audit_token" in resp.headers.get("set-cookie", "")

    # Cookie 直通 /me（Bearer 缺省回落 Cookie）
    authed = TestClient(app)
    authed.cookies.set("med_audit_token", resp.cookies.get("med_audit_token"))
    me = authed.get("/api/mobile/timeliness/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "mob_admin"


def test_oauth_his_employee_issues_virtual_cookie(env, monkeypatch):
    row = ("90001", "测试医师", "040112", "耳鼻喉一科")
    monkeypatch.setattr("app.timeliness.his_oracle_reader._get_connection",
                        lambda: _FakeHisConn(row))
    _patch_relay_userid(monkeypatch, "90001")  # 应用库无此账号 → HIS 直登
    _, users, app = env
    client = TestClient(app)
    resp = client.get("/mobile/qc/timeliness/oauth/wecom/callback",
                      params={"code": "c2"}, follow_redirects=False)
    assert resp.status_code == 302
    assert "med_audit_token" in resp.headers.get("set-cookie", "")

    authed = TestClient(app)
    authed.cookies.set("med_audit_token", resp.cookies.get("med_audit_token"))
    me = authed.get("/api/mobile/timeliness/me")
    assert me.status_code == 200
    assert me.json()["user"]["role"] == "his_employee"
    assert me.json()["user"]["dept_name"] == "耳鼻喉一科"

    # 虚拟身份写操作天然 403（role_id=None）
    approve = authed.post("/api/mobile/timeliness/approvals/1/approve", json={"dry_run": True})
    assert approve.status_code == 403


def test_oauth_unknown_userid_redirects_without_cookie(env, monkeypatch):
    from app.timeliness import his_oracle_reader

    monkeypatch.setattr(his_oracle_reader, "_get_connection", lambda: _FakeHisConn(None))
    _patch_relay_userid(monkeypatch, "ghost999")
    _, _, app = env
    client = TestClient(app)
    resp = client.get("/mobile/qc/timeliness/oauth/wecom/callback",
                      params={"code": "c3"}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/mobile/qc/timeliness"
    assert "set-cookie" not in {k.lower() for k in resp.headers}


# ---- IP 全局限流 ----


def test_ip_global_rate_limit_blocks_flood(env):
    mt.reset_ip_login_rate_limit()
    try:
        for _ in range(60):
            mt.check_ip_login_rate_limit("global")
        with pytest.raises(Exception) as exc:
            mt.check_ip_login_rate_limit("global")
        assert "429" in str(getattr(exc.value, "status_code", "")) or exc.value.status_code == 429
    finally:
        mt.reset_ip_login_rate_limit()
