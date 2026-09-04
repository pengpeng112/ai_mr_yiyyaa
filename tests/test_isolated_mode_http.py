"""IsolatedModeError → HTTP 400 契约测试（037 RP-C / P-003）。

覆盖：隔离门禁拒绝必须以 400 + 原始英文原因返回，不得落入
generic_exception_handler 变成 500 INTERNAL_ERROR。
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.services.isolated_mode import IsolatedModeError


def _build_app() -> FastAPI:
    """与 app.main 相同的 handler 注册方式构建最小应用。"""
    app = FastAPI()

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": f"HTTP_{exc.status_code}", "message": exc.detail},
        )

    @app.exception_handler(IsolatedModeError)
    async def isolated_mode_exception_handler(_request: Request, exc: IsolatedModeError):
        return JSONResponse(
            status_code=400,
            content={"code": "HTTP_400", "message": str(exc)},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(_request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"code": "INTERNAL_ERROR", "message": "internal error"},
        )

    @app.get("/raise-isolated")
    async def raise_isolated():
        raise IsolatedModeError("isolated mode requires data_source.type=fixture")

    @app.get("/raise-runtime")
    async def raise_runtime():
        raise RuntimeError("plain runtime failure")

    return app


def test_isolated_mode_error_maps_to_400_with_original_message():
    client = TestClient(_build_app(), raise_server_exceptions=False)
    r = client.get("/raise-isolated")
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "HTTP_400"
    assert "isolated mode requires data_source.type=fixture" in body["message"]
    assert "INTERNAL_ERROR" not in str(body)


def test_other_runtime_errors_still_500():
    """未捕获的普通异常仍走 500，不得被隔离 handler 误吃。"""
    client = TestClient(_build_app(), raise_server_exceptions=False)
    r = client.get("/raise-runtime")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL_ERROR"


def test_main_app_registers_isolated_mode_handler():
    """主应用必须注册 IsolatedModeError 专用 handler（防误删回归锚）。"""
    from app.main import app as main_app

    assert IsolatedModeError in main_app.exception_handlers
