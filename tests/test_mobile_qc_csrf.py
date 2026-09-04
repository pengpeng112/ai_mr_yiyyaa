"""移动端 H5 反馈 CSRF 豁免测试（037 RP-H / K-1）。

医生 H5 用 HMAC token 提交反馈时，浏览器残留的管理端 Cookie 不得触发 CSRF 403；
logout 强校验保持。前端 qc_detail.js 必须携带 X-Requested-With 双保险。
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import AUTH_COOKIE_NAME
from app.security_middleware import register_security_middleware

REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_app() -> FastAPI:
    app = FastAPI()
    register_security_middleware(app)

    @app.post("/api/mobile/qc-feedback")
    async def qc_feedback():
        return {"ok": True}

    @app.post("/api/users/logout")
    async def logout():
        return {"ok": True}

    return app


def test_t1_cookie_post_qc_feedback_without_header_not_csrf_blocked():
    client = TestClient(_build_app())
    client.cookies.set(AUTH_COOKIE_NAME, "stale-admin-cookie")
    r = client.post("/api/mobile/qc-feedback", json={"token": "hmac-token", "action": "ack"})
    assert r.status_code == 200, r.text
    assert "CSRF" not in str(r.json())


def test_t2_logout_still_requires_csrf_header():
    client = TestClient(_build_app())
    client.cookies.set(AUTH_COOKIE_NAME, "stale-admin-cookie")
    r = client.post("/api/users/logout")
    assert r.status_code == 403
    assert "CSRF" in r.json()["message"]


def test_t3_cookie_with_header_passes_middleware():
    client = TestClient(_build_app())
    client.cookies.set(AUTH_COOKIE_NAME, "stale-admin-cookie")
    r = client.post(
        "/api/mobile/qc-feedback",
        json={"token": "hmac-token"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert r.status_code == 200


def test_t4_no_cookie_post_passes_middleware():
    """无 Cookie 的移动端写请求天然放行，token 校验是路由的事。"""
    client = TestClient(_build_app())
    r = client.post("/api/mobile/qc-feedback", json={"token": "hmac-token"})
    assert r.status_code == 200


def test_t5_qc_detail_js_carries_csrf_header():
    """静态回归锚：qc_detail.js 的 fetch 必须带 X-Requested-With。"""
    js = (REPO_ROOT / "static" / "scripts" / "mobile" / "qc_detail.js").read_text(encoding="utf-8")
    assert "X-Requested-With" in js
