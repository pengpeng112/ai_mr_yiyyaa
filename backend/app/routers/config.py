"""
配置管理路由 —— /api/config
"""
from fastapi import APIRouter, HTTPException
from app.schemas import (
    OracleConfig, OracleConfigResponse,
    DifyConfig, DifyConfigResponse,
    DeptConfig, SchedulerConfig, PushSettings,
    NotifyConfig, MessageResponse,
)
from app.config import load_config, update_section, encrypt_value, decrypt_value, mask_secret
from app.oracle_client import test_oracle_connection, fetch_department_list
from app.dify_pusher import test_dify_connection
from app.scheduler import update_scheduler

router = APIRouter()


# ---- Oracle ----
@router.get("/oracle", response_model=OracleConfigResponse, summary="获取 Oracle 配置")
def get_oracle_config():
    cfg = load_config().get("oracle", {})
    pwd = ""
    try:
        pwd = decrypt_value(cfg.get("password_enc", ""))
    except Exception:
        pass
    return OracleConfigResponse(
        host=cfg.get("host", ""),
        port=cfg.get("port", 1521),
        service_name=cfg.get("service_name", ""),
        username=cfg.get("username", ""),
        password_masked=mask_secret(pwd),
    )


@router.post("/oracle", response_model=MessageResponse, summary="保存 Oracle 配置")
def save_oracle_config(body: OracleConfig):
    data = {
        "host": body.host,
        "port": body.port,
        "service_name": body.service_name,
        "username": body.username,
        "password_enc": encrypt_value(body.password) if body.password else "",
    }
    update_section("oracle", data)
    return MessageResponse(message="Oracle 配置已保存")


@router.post("/oracle/test", summary="测试 Oracle 连接")
def test_oracle():
    cfg = load_config().get("oracle", {})
    try:
        cfg["password"] = decrypt_value(cfg.get("password_enc", ""))
    except Exception:
        cfg["password"] = ""
    result = test_oracle_connection(cfg)
    return result


# ---- Dify ----
@router.get("/dify", response_model=DifyConfigResponse, summary="获取 Dify 配置")
def get_dify_config():
    cfg = load_config().get("dify", {})
    key = ""
    try:
        key = decrypt_value(cfg.get("api_key_enc", ""))
    except Exception:
        pass
    return DifyConfigResponse(
        base_url=cfg.get("base_url", ""),
        api_key_masked=mask_secret(key),
        workflow_input_variable=cfg.get("workflow_input_variable", "mr_text"),
        user_identifier=cfg.get("user_identifier", ""),
        timeout_seconds=cfg.get("timeout_seconds", 90),
    )


@router.post("/dify", response_model=MessageResponse, summary="保存 Dify 配置")
def save_dify_config(body: DifyConfig):
    data = {
        "base_url": body.base_url,
        "api_key_enc": encrypt_value(body.api_key) if body.api_key else "",
        "workflow_input_variable": body.workflow_input_variable,
        "user_identifier": body.user_identifier,
        "timeout_seconds": body.timeout_seconds,
    }
    update_section("dify", data)
    return MessageResponse(message="Dify 配置已保存")


@router.post("/dify/test", summary="测试 Dify 连接")
def test_dify():
    cfg = load_config().get("dify", {})
    try:
        cfg["api_key"] = decrypt_value(cfg.get("api_key_enc", ""))
    except Exception:
        cfg["api_key"] = ""
    result = test_dify_connection(cfg)
    return result


# ---- 科室 ----
@router.get("/departments", response_model=DeptConfig, summary="获取科室配置")
def get_departments():
    cfg = load_config().get("departments", {})
    return DeptConfig(**cfg)


@router.post("/departments", response_model=MessageResponse, summary="保存科室配置")
def save_departments(body: DeptConfig):
    update_section("departments", body.model_dump())
    return MessageResponse(message="科室配置已保存")


@router.get("/departments/list", summary="从 Oracle 动态查询科室列表")
def list_departments_from_oracle():
    cfg = load_config().get("oracle", {})
    try:
        cfg["password"] = decrypt_value(cfg.get("password_enc", ""))
    except Exception:
        cfg["password"] = ""
    try:
        depts = fetch_department_list(cfg)
        return {"departments": depts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---- 定时规则 ----
@router.get("/scheduler", response_model=SchedulerConfig, summary="获取定时任务配置")
def get_scheduler_config():
    cfg = load_config().get("scheduler", {})
    return SchedulerConfig(**cfg)


@router.post("/scheduler", response_model=MessageResponse, summary="保存定时任务配置")
def save_scheduler_config(body: SchedulerConfig):
    update_section("scheduler", body.model_dump())
    update_scheduler(body.enabled, body.cron)
    return MessageResponse(message="定时任务配置已保存")


# ---- 推送设置 ----
@router.get("/push", response_model=PushSettings, summary="获取推送参数")
def get_push_settings():
    cfg = load_config().get("push", {})
    return PushSettings(**cfg)


@router.post("/push", response_model=MessageResponse, summary="保存推送参数")
def save_push_settings(body: PushSettings):
    update_section("push", body.model_dump())
    return MessageResponse(message="推送参数已保存")


# ---- 通知配置 ----
@router.get("/notify", response_model=NotifyConfig, summary="获取通知渠道配置")
def get_notify_config():
    cfg = load_config().get("notify", {})
    return NotifyConfig(**cfg)


@router.post("/notify", response_model=MessageResponse, summary="保存通知渠道配置")
def save_notify_config(body: NotifyConfig):
    update_section("notify", body.model_dump())
    return MessageResponse(message="通知配置已保存")
