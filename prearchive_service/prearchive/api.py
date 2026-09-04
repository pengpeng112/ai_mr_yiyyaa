# -*- coding: utf-8 -*-
"""只读 API（A19 最小鉴权实现）：

- GET /healthz                      —— 服务心跳/水位/存活状态（外部探测停跳，R13）
- GET /api/precheck/{pid}/{vid}     —— 最新（current）预检问题清单
    鉴权：header X-Precheck-Token = 配置共享密钥；
          query  doctor_id + dept_code 必填（工号+科室，A19）；
          require_dept_binding=true 时校验患者归属科室（防冒用）。

只读：本服务 API 不提供任何写操作。
"""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import FastAPI, HTTPException, Request

from .store import ResultRepository

TOKEN_HEADER = "X-Precheck-Token"


def create_app(config: dict, repository: ResultRepository,
               heartbeat, watermark_provider: Optional[Callable[[], object]] = None,
               poller=None, rule_center: Optional[dict] = None) -> FastAPI:
    application = FastAPI(
        title="Prearchive Check Service",
        description="归档前病历预检服务（028 一期原型）——独立于 Med-Audit 主服务",
        version="0.1.0",
        docs_url="/docs",
    )
    api_config = (config or {}).get("api") or {}
    shared_token = str(api_config.get("shared_token") or "")
    require_dept_binding = bool(api_config.get("require_dept_binding", True))
    heartbeat_max_age = int(((config or {}).get("service") or {})
                            .get("heartbeat_max_age_seconds", 900))

    # 039 规则中心管理 API（可选挂载：rule_center 缺失或 admin_api 未配置时健康
    # 检查/患者查询不受影响）
    if rule_center is not None:
        admin_cfg = (config or {}).get("admin_api") or {}
        if bool(admin_cfg.get("enabled", True)):
            from .admin_api import create_admin_router
            application.include_router(create_admin_router(
                config,
                rule_center["repository"],
                rule_center["service"],
            ))

    def _check_token(request: Request) -> None:
        if not shared_token or shared_token.startswith("<"):
            raise HTTPException(status_code=503, detail="api token not configured")
        provided = request.headers.get(TOKEN_HEADER, "")
        if provided != shared_token:
            raise HTTPException(status_code=401, detail="invalid or missing token")

    @application.get("/healthz", summary="健康与心跳探测")
    def healthz():
        record = heartbeat.read() if heartbeat is not None else None
        alive = heartbeat.is_alive(heartbeat_max_age) if heartbeat is not None else False
        payload = {
            "status": "ok" if alive else "degraded",
            "heartbeat": record,
            "heartbeat_alive": alive,
            "heartbeat_max_age_seconds": heartbeat_max_age,
        }
        if watermark_provider is not None:
            try:
                payload["watermark"] = watermark_provider()
            except Exception as exc:  # noqa: BLE001
                payload["watermark"] = f"error: {exc}"
        if poller is not None:
            payload["poll_interval_seconds"] = poller.interval_seconds
            payload["lock_held"] = poller.lock.held
        return payload

    @application.get("/api/precheck/{patient_id}/{visit_id}",
                     summary="查询患者最新预检问题清单（工号+科室鉴权）")
    def get_precheck(patient_id: str, visit_id: str, request: Request,
                     doctor_id: str = "", dept_code: str = ""):
        _check_token(request)
        if not doctor_id.strip() or not dept_code.strip():
            raise HTTPException(
                status_code=400,
                detail="doctor_id and dept_code are required (A19)")
        row = repository.get_current(patient_id, visit_id)
        if row is None:
            raise HTTPException(status_code=404, detail="no precheck result for patient")
        if require_dept_binding:
            if row.dept_code and dept_code and row.dept_code != dept_code:
                raise HTTPException(
                    status_code=403,
                    detail="patient not in requested dept")
        data = row.to_public_dict()
        data["queried_by_doctor_id"] = doctor_id
        return data

    return application
