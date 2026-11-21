"""企微 OAuth 免登回调（自建应用主页 code→userid→302 H5）后端测试（2026-11-17）。

覆盖：缺 code 回退 / 未配置凭据回退（零外呼）/ code→userid 建账命中 302 带 empno /
userid 未绑定回退 / 停用账号回退 / 企微链路异常回退 / Location 恒为本站路径。
"""
from __future__ import annotations

import pytest

import app.routers.mobile_timeliness as mt
from tests.timeliness.test_mobile_timeliness_20261116 import env  # noqa: F401

CALLBACK = "/mobile/qc/timeliness/oauth/wecom/callback"


def _client(app) -> object:
    from fastapi.testclient import TestClient

    return TestClient(app)


def _oauth_env(monkeypatch) -> None:
    monkeypatch.setenv("WECOM_CORPID", "ww-test-corp")
    monkeypatch.setenv("WECOM_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("WECOM_AGENTID", "1000002")
    monkeypatch.setattr(mt, "_wecom_access_token", lambda corpid, secret: "fake-token")


# ---- 回退类（不允许任何外呼） ----


def test_missing_code_falls_back_to_h5(monkeypatch, env):
    monkeypatch.delenv("WECOM_CORPID", raising=False)
    client = _client(env[2])
    resp = client.get(CALLBACK, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/mobile/qc/timeliness"


def test_missing_code_with_config_still_falls_back(monkeypatch, env):
    _oauth_env(monkeypatch)
    client = _client(env[2])
    resp = client.get(CALLBACK, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/mobile/qc/timeliness"


def test_unconfigured_env_falls_back_without_call(monkeypatch, env):
    monkeypatch.delenv("WECOM_CORPID", raising=False)
    monkeypatch.delenv("WECOM_SECRET", raising=False)

    def _boom(*a, **k):  # 若发生外呼即失败
        raise AssertionError("unexpected outbound call")

    monkeypatch.setattr(mt.requests, "get", _boom)
    client = _client(env[2])
    resp = client.get(CALLBACK + "?code=abc", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/mobile/qc/timeliness"


# ---- 命中类 ----


def test_code_resolves_bound_user_issues_cookie_without_empno(monkeypatch, env):
    # 2026-11-17 安全增强（直签发）：身份确认后本端点直接 Set-Cookie，
    # Location 为干净 H5（凭证不留 URL，旧 ?empno= 302 方式废弃）。
    _oauth_env(monkeypatch)

    class _R:
        def json(self):
            return {"userid": "mob_admin"}

    monkeypatch.setattr(mt.requests, "get", lambda *a, **k: _R())
    client = _client(env[2])
    resp = client.get(CALLBACK + "?code=realcode", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/mobile/qc/timeliness"
    assert "med_audit_token" in resp.headers.get("set-cookie", "")


# ---- 回退类（身份解析后） ----


def test_unbound_userid_falls_back(monkeypatch, env):
    _oauth_env(monkeypatch)

    class _R:
        def json(self):
            return {"userid": "ghost99999"}

    monkeypatch.setattr(mt.requests, "get", lambda *a, **k: _R())
    client = _client(env[2])
    resp = client.get(CALLBACK + "?code=realcode", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/mobile/qc/timeliness"


def test_inactive_user_falls_back(monkeypatch, env):
    db, _users, app = env
    from app.models import User

    ghost = db.query(User).filter(User.username == "mob_viewer").one()
    ghost.is_active = False
    db.commit()
    _oauth_env(monkeypatch)

    class _R:
        def json(self):
            return {"userid": "mob_viewer"}

    monkeypatch.setattr(mt.requests, "get", lambda *a, **k: _R())
    client = _client(app)
    resp = client.get(CALLBACK + "?code=realcode", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/mobile/qc/timeliness"


def test_wecom_api_error_falls_back(monkeypatch, env):
    _oauth_env(monkeypatch)

    def _raise(*a, **k):
        raise RuntimeError("egress blocked")

    monkeypatch.setattr(mt.requests, "get", _raise)
    client = _client(env[2])
    resp = client.get(CALLBACK + "?code=realcode", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/mobile/qc/timeliness"


# ---- relay 代换通道（84 无公网出口的默认通道） ----


def _relay_env(monkeypatch):
    _oauth_env(monkeypatch)
    monkeypatch.setattr(mt, "_wecom_relay_config",
                        lambda: ("http://10.20.1.153:3000", "relay-hmac-key-not-for-production"))


def test_relay_exchange_success_redirects_with_empno(monkeypatch, env):
    _relay_env(monkeypatch)
    seen = {}

    class _R:
        ok = True

        def json(self):
            return {"ok": True, "userid": "mob_admin"}

    def _post(url, data, headers, timeout):
        seen["url"] = url
        seen["headers"] = headers
        return _R()

    monkeypatch.setattr(mt.requests, "post", _post)
    client = _client(env[2])
    resp = client.get(CALLBACK + "?code=realcode", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/mobile/qc/timeliness"
    assert "med_audit_token" in resp.headers.get("set-cookie", "")  # 直签发
    assert seen["url"].endswith("/wecom-oauth/exchange")
    assert seen["headers"].get("X-Relay-Signature")
    assert seen["headers"].get("X-Relay-Timestamp")


def test_relay_exchange_rejected_falls_back(monkeypatch, env):
    _relay_env(monkeypatch)

    class _R:
        ok = False

        def json(self):
            return {}

    monkeypatch.setattr(mt.requests, "post", lambda *a, **k: _R())
    client = _client(env[2])
    resp = client.get(CALLBACK + "?code=realcode", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/mobile/qc/timeliness"


# ---- 防御 ----


def test_redirect_target_is_fixed_site_relative_path():
    """回调只允许 302 到本站固定 H5 路径（源码断言，防开放跳转回归）。"""
    import inspect
    import pathlib

    src = pathlib.Path(inspect.getfile(mt)).read_text(encoding="utf-8")
    assert 'h5 = "/mobile/qc/timeliness"' in src
    # 2026-11-17 直签发增强：Location 恒为干净固定路径（不再拼接 ?empno= 凭证），
    # 身份凭证只经 HttpOnly Cookie 下发。
    assert 'f"{h5}?empno={userid}"' not in src
    assert 'redirect.set_cookie(' in src
    assert 'redirect.headers["Cache-Control"] = "no-store"' in src
