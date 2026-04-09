"""
配置管理路由 —— /api/config
"""
import re
import logging

from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel
from typing import Optional, Any, List
from sqlalchemy.orm import Session

from app.schemas import (
    OracleConfig, OracleConfigResponse, OracleFieldMapping,
    PostgreSQLConfig, PostgreSQLConfigResponse, DataSourceConfig,
    DifyConfig, DifyConfigResponse, DifyTargetSave, DifyTargetsResponse,
    DeptConfig, SchedulerConfig, PushSettings,
    NotifyConfig, PrivacyMaskingConfig, MessageResponse,
)
from app.config import (
    load_config, save_config, update_section, encrypt_value, decrypt_value, mask_secret,
    normalize_dify_base_url, validate_postgresql_query_sql,
    validate_oracle_instant_client_dir,
)
from app.oracle_client import test_oracle_connection, fetch_department_list, reset_oracle_pool
from app.postgresql_client import test_pg_connection, fetch_pg_department_list, get_pg_connection
from app.dify_pusher import test_dify_connection, push_to_dify
from app.scheduler import update_scheduler, validate_cron_expression
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Role
from app.permissions import require_permission

_logger = logging.getLogger(__name__)
_audit_logger = logging.getLogger("audit.config")

# ---- SQL 安全校验 ----
_DANGEROUS_SQL_KEYWORDS = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|EXEC|CREATE|GRANT|REVOKE|MERGE)\b",
    re.IGNORECASE,
)


def _validate_sql_readonly(sql: str) -> None:
    """校验 SQL 仅允许 SELECT 语句"""
    stripped = sql.strip().rstrip(";；/").strip()
    if "；" in stripped:
        raise HTTPException(status_code=400, detail="SQL 中包含中文分号，请改为英文标点")
    if not stripped.upper().startswith("SELECT"):
        raise HTTPException(status_code=400, detail="仅允许 SELECT 查询语句")
    match = _DANGEROUS_SQL_KEYWORDS.search(stripped)
    if match:
        raise HTTPException(
            status_code=400,
            detail=f"SQL 中包含禁止的关键字: {match.group()}",
        )


def _require_manage_config(current_user: User = Depends(require_permission("manage_config"))):
    """要求配置管理权限（admin 自动放行）。"""
    return current_user


class DifyDebugRequest(BaseModel):
    mr_txt: str = ""
    payload_json: Optional[Any] = None
    user: str = "debug-user"
    response_mode: str = "blocking"
    workflow_input_variable: Optional[str] = None
    workflow_output_key: Optional[str] = None
    extra_inputs: Optional[dict] = None


router = APIRouter()


# ---- 数据源类型 ----
@router.get("/data-source", response_model=DataSourceConfig, summary="获取当前数据源类型")
def get_data_source(_user: User = Depends(get_current_user)):
    cfg = load_config().get("data_source", {})
    return DataSourceConfig(type=cfg.get("type", "oracle"))


@router.post("/data-source", response_model=MessageResponse, summary="保存当前数据源类型")
def save_data_source(body: DataSourceConfig, current_user: User = Depends(_require_manage_config)):
    update_section("data_source", body.model_dump())
    _audit_logger.info("[AUDIT] 用户=%s id=%s 修改数据源类型为 %s", current_user.username, current_user.id, body.type)
    return MessageResponse(message="数据源类型已保存")


# ---- Oracle ----
@router.get("/oracle", response_model=OracleConfigResponse, summary="获取 Oracle 配置")
def get_oracle_config(_user: User = Depends(_require_manage_config)):
    cfg = load_config().get("oracle", {})
    pwd = ""
    try:
        pwd = decrypt_value(cfg.get("password_enc", ""))
    except Exception:
        pass
    fallback_direct_raw = cfg.get("pool_fallback_direct", False)
    if isinstance(fallback_direct_raw, bool):
        fallback_direct = fallback_direct_raw
    else:
        fallback_direct = str(fallback_direct_raw).strip().lower() in {"1", "true", "yes", "y", "on"}

    return OracleConfigResponse(
        host=cfg.get("host", ""),
        port=cfg.get("port", 1521),
        service_name=cfg.get("service_name", ""),
        username=cfg.get("username", ""),
        password_masked=mask_secret(pwd),
        instant_client_dir=cfg.get("instant_client_dir", ""),
        query_sql=cfg.get("query_sql", ""),
        dept_sql=cfg.get("dept_sql", ""),
        field_mapping=OracleFieldMapping(**cfg.get("field_mapping", {})) if cfg.get("field_mapping") else None,
        pool_min=int(cfg.get("pool_min", 1) or 1),
        pool_max=int(cfg.get("pool_max", 8) or 8),
        pool_increment=int(cfg.get("pool_increment", 1) or 1),
        pool_timeout_seconds=int(cfg.get("pool_timeout_seconds", 60) or 60),
        acquire_timeout_seconds=int(cfg.get("acquire_timeout_seconds", 15) or 15),
        pool_fallback_direct=fallback_direct,
    )


@router.post("/oracle", response_model=MessageResponse, summary="保存 Oracle 配置")
def save_oracle_config(body: OracleConfig, current_user: User = Depends(_require_manage_config)):
    current = load_config().get("oracle", {})
    instant_client_dir = validate_oracle_instant_client_dir(body.instant_client_dir, require_exists=False)
    query_sql = (body.query_sql or "").strip().rstrip(";；/").strip()
    dept_sql = (body.dept_sql or "").strip().rstrip(";；/").strip()
    if query_sql:
        _validate_sql_readonly(query_sql)
    if dept_sql:
        _validate_sql_readonly(dept_sql)
    data = {
        "host": body.host,
        "port": body.port,
        "service_name": body.service_name,
        "username": body.username,
        "password_enc": encrypt_value(body.password) if body.password else current.get("password_enc", ""),
        "instant_client_dir": instant_client_dir,
        "query_sql": query_sql,
        "dept_sql": dept_sql,
        "field_mapping": body.field_mapping.model_dump() if body.field_mapping else {},
        "pool_min": body.pool_min,
        "pool_max": body.pool_max,
        "pool_increment": body.pool_increment,
        "pool_timeout_seconds": body.pool_timeout_seconds,
        "acquire_timeout_seconds": body.acquire_timeout_seconds,
        "pool_fallback_direct": body.pool_fallback_direct,
    }
    update_section("oracle", data)
    reset_oracle_pool()
    _audit_logger.info("[AUDIT] 用户=%s id=%s 修改 Oracle 配置 host=%s service=%s", current_user.username, current_user.id, body.host, body.service_name)
    return MessageResponse(message="Oracle 配置已保存")


@router.post("/oracle/test", summary="测试 Oracle 连接")
def test_oracle(_user: User = Depends(_require_manage_config)):
    cfg = load_config().get("oracle", {})
    try:
        cfg["password"] = decrypt_value(cfg.get("password_enc", ""))
    except Exception:
        cfg["password"] = ""
    return test_oracle_connection(cfg)


@router.post("/oracle/query", summary="Oracle SQL 查询测试")
def oracle_query_test(body: dict, _user: User = Depends(_require_manage_config)):
    from app.oracle_client import get_oracle_connection

    cfg = load_config().get("oracle", {}).copy()
    try:
        cfg["password"] = decrypt_value(cfg.get("password_enc", ""))
    except Exception:
        cfg["password"] = ""
    if body.get("instant_client_dir"):
        cfg["instant_client_dir"] = body["instant_client_dir"]

    sql = body.get("sql", "").strip()
    limit = min(int(body.get("limit", 20)), 200)
    params = body.get("params", {})

    if not sql:
        raise HTTPException(status_code=400, detail="SQL 不能为空")
    _validate_sql_readonly(sql)

    import time
    start = time.time()
    conn = None
    cursor = None
    try:
        conn = get_oracle_connection(cfg)
        cursor = conn.cursor()
        cursor.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchmany(limit)
        elapsed = int((time.time() - start) * 1000)
        data = [dict(zip(columns, [str(v) if v is not None else "" for v in row])) for row in rows]
        return {
            "status": "success",
            "columns": columns,
            "rows": data,
            "row_count": len(data),
            "elapsed_ms": elapsed,
        }
    except HTTPException:
        raise
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        _logger.error(f"Oracle 查询测试失败: {e}")
        return {
            "status": "error",
            "message": "查询执行失败，请检查 SQL 语句和连接配置",
            "elapsed_ms": elapsed,
        }
    finally:
        if cursor:
            try: cursor.close()
            except Exception: pass
        if conn:
            try: conn.close()
            except Exception: pass


# ---- PostgreSQL ----
@router.get("/postgresql", response_model=PostgreSQLConfigResponse, summary="获取 PostgreSQL 配置")
def get_postgresql_config(_user: User = Depends(_require_manage_config)):
    cfg = load_config().get("postgresql", {})
    pwd = ""
    try:
        pwd = decrypt_value(cfg.get("password_enc", ""))
    except Exception:
        pass
    return PostgreSQLConfigResponse(
        host=cfg.get("host", "localhost"),
        port=cfg.get("port", 5432),
        database=cfg.get("database", ""),
        username=cfg.get("username", ""),
        password_masked=mask_secret(pwd),
        query_sql=cfg.get("query_sql", ""),
        dept_sql=cfg.get("dept_sql", ""),
        field_mapping=OracleFieldMapping(**cfg.get("field_mapping", {})) if cfg.get("field_mapping") else None,
    )


@router.post("/postgresql", response_model=MessageResponse, summary="保存 PostgreSQL 配置")
def save_postgresql_config(body: PostgreSQLConfig, current_user: User = Depends(_require_manage_config)):
    current = load_config().get("postgresql", {})
    validate_postgresql_query_sql(body.query_sql)
    data = {
        "host": body.host,
        "port": body.port,
        "database": body.database,
        "username": body.username,
        "password_enc": encrypt_value(body.password) if body.password else current.get("password_enc", ""),
        "query_sql": body.query_sql,
        "dept_sql": body.dept_sql,
        "field_mapping": body.field_mapping.model_dump() if body.field_mapping else {},
    }
    update_section("postgresql", data)
    _audit_logger.info("[AUDIT] 用户=%s id=%s 修改 PostgreSQL 配置 host=%s db=%s", current_user.username, current_user.id, body.host, body.database)
    return MessageResponse(message="PostgreSQL 配置已保存")


@router.post("/postgresql/test", summary="测试 PostgreSQL 连接")
def test_postgresql(_user: User = Depends(_require_manage_config)):
    cfg = load_config().get("postgresql", {})
    try:
        cfg["password"] = decrypt_value(cfg.get("password_enc", ""))
    except Exception:
        cfg["password"] = ""
    return test_pg_connection(cfg)


@router.post("/postgresql/query", summary="PostgreSQL SQL 查询测试")
def postgresql_query_test(body: dict, _user: User = Depends(_require_manage_config)):
    cfg = load_config().get("postgresql", {}).copy()
    try:
        cfg["password"] = decrypt_value(cfg.get("password_enc", ""))
    except Exception:
        cfg["password"] = ""

    sql = body.get("sql", "").strip()
    limit = min(int(body.get("limit", 20)), 200)

    if not sql:
        raise HTTPException(status_code=400, detail="SQL 不能为空")
    _validate_sql_readonly(sql)

    import time
    import psycopg2.extras

    start = time.time()
    conn = None
    cursor = None
    try:
        conn = get_pg_connection(cfg)
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(sql)
        rows = cursor.fetchmany(limit)
        columns = [desc[0] for desc in cursor.description]
        elapsed = int((time.time() - start) * 1000)
        data = [{k: (str(v) if v is not None else "") for k, v in dict(row).items()} for row in rows]
        return {
            "status": "success",
            "columns": columns,
            "rows": data,
            "row_count": len(data),
            "elapsed_ms": elapsed,
        }
    except HTTPException:
        raise
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        _logger.error(f"PostgreSQL 查询测试失败: {e}")
        return {
            "status": "error",
            "message": "查询执行失败，请检查 SQL 语句和连接配置",
            "elapsed_ms": elapsed,
        }
    finally:
        if cursor:
            try: cursor.close()
            except Exception: pass
        if conn:
            try: conn.close()
            except Exception: pass


# ---- Dify ----
@router.get("/dify", response_model=DifyConfigResponse, summary="获取 Dify 配置")
def get_dify_config(_user: User = Depends(_require_manage_config)):
    cfg = load_config().get("dify", {})
    key = ""
    try:
        key = decrypt_value(cfg.get("api_key_enc", ""))
    except Exception:
        pass
    return DifyConfigResponse(
        base_url=cfg.get("base_url", ""),
        api_key_masked=mask_secret(key),
        workflow_input_variable=cfg.get("workflow_input_variable", "mr_txt"),
        workflow_output_key=cfg.get("workflow_output_key", "aa"),
        user_identifier=cfg.get("user_identifier", ""),
        timeout_seconds=cfg.get("timeout_seconds", 90),
        extra_inputs=cfg.get("extra_inputs", {}),
    )


@router.post("/dify", response_model=MessageResponse, summary="保存 Dify 配置")
def save_dify_config(body: DifyConfig, current_user: User = Depends(_require_manage_config)):
    current = load_config().get("dify", {})
    api_key = (body.api_key or "").strip()
    if api_key.lower().startswith("bearer "):
        api_key = api_key[7:].strip()
    base_url = normalize_dify_base_url(body.base_url)
    data = {
        "base_url": base_url,
        "api_key_enc": encrypt_value(api_key) if api_key else current.get("api_key_enc", ""),
        "workflow_input_variable": body.workflow_input_variable,
        "workflow_output_key": body.workflow_output_key,
        "user_identifier": body.user_identifier,
        "timeout_seconds": body.timeout_seconds,
        "extra_inputs": body.extra_inputs,
        "targets": current.get("targets", []),
    }
    update_section("dify", data)
    _audit_logger.info("[AUDIT] 用户=%s id=%s 修改 Dify 配置 base_url=%s input=%s output=%s", current_user.username, current_user.id, base_url, body.workflow_input_variable, body.workflow_output_key)
    return MessageResponse(message="Dify 配置已保存")


@router.get("/dify/targets", response_model=DifyTargetsResponse, summary="获取持久化 Dify 目标节点列表")
def get_dify_targets(_user: User = Depends(_require_manage_config)):
    """返回已持久化的 Dify 多节点列表，包含明文 api_key（用于自动回填）。"""
    cfg = load_config().get("dify", {})
    raw_targets = cfg.get("targets", []) or []
    result = []
    for t in raw_targets:
        t_copy = dict(t)
        api_key_plain = ""
        try:
            api_key_plain = decrypt_value(t_copy.get("api_key_enc", ""))
        except Exception:
            pass
        t_copy["api_key"] = api_key_plain
        t_copy["api_key_masked"] = mask_secret(api_key_plain)
        t_copy.pop("api_key_enc", None)
        result.append(t_copy)
    return DifyTargetsResponse(targets=result)


@router.post("/dify/targets", response_model=MessageResponse, summary="保存持久化 Dify 目标节点列表")
def save_dify_targets(body: List[dict] = Body(...), current_user: User = Depends(_require_manage_config)):
    """接收目标节点列表，加密存储 api_key，写入 config.json。"""
    if not isinstance(body, list):
        raise HTTPException(status_code=422, detail="body must be a list of target objects")
    if len(body) > 10:
        raise HTTPException(status_code=422, detail="最多只能配置 10 个 Dify 目标节点")

    current_cfg = load_config().get("dify", {})
    existing_targets = current_cfg.get("targets", []) or []
    existing_enc_map = {}
    for t in existing_targets:
        name = t.get("name", "")
        if name and t.get("api_key_enc"):
            existing_enc_map[name] = t["api_key_enc"]

    saved_targets = []
    for item in body:
        try:
            t = DifyTargetSave(**item) if isinstance(item, dict) else DifyTargetSave(**item.model_dump())
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"目标节点数据格式错误: {e}")
        base_url_normalized = normalize_dify_base_url(t.base_url)
        api_key = (t.api_key or "").strip()
        if api_key.lower().startswith("bearer "):
            api_key = api_key[7:].strip()
        # 若 api_key 为空（前端未修改已脱敏字段），则保留原有加密值
        if api_key:
            api_key_enc = encrypt_value(api_key)
        else:
            api_key_enc = existing_enc_map.get(t.name, "")
        saved_targets.append({
            "name": t.name,
            "base_url": base_url_normalized,
            "api_key_enc": api_key_enc,
            "workflow_input_variable": t.workflow_input_variable,
            "workflow_output_key": t.workflow_output_key,
            "user_identifier": t.user_identifier,
            "timeout_seconds": t.timeout_seconds,
            "weight": t.weight,
            "enabled": t.enabled,
        })

    # 保留 dify section 其他字段，只更新 targets
    full_cfg = load_config()
    dify_section = full_cfg.get("dify", {})
    dify_section["targets"] = saved_targets
    full_cfg["dify"] = dify_section
    save_config(full_cfg)
    _audit_logger.info("[AUDIT] 用户=%s id=%s 保存 Dify targets，共 %s 个节点", current_user.username, current_user.id, len(saved_targets))
    return MessageResponse(message=f"已保存 {len(saved_targets)} 个 Dify 目标节点")


@router.post("/dify/test", summary="测试 Dify 连接")
def test_dify(_user: User = Depends(_require_manage_config)):
    cfg = load_config().get("dify", {})
    try:
        key = decrypt_value(cfg.get("api_key_enc", ""))
        if key.lower().startswith("bearer "):
            key = key[7:].strip()
        cfg["api_key"] = key
    except Exception:
        cfg["api_key"] = ""
    return test_dify_connection(cfg)


@router.post("/dify/debug", summary="Dify 直接调试（使用自定义入参）")
def debug_dify(body: DifyDebugRequest, _user: User = Depends(_require_manage_config)):
    cfg = load_config().get("dify", {}).copy()
    try:
        key = decrypt_value(cfg.get("api_key_enc", ""))
        if key.lower().startswith("bearer "):
            key = key[7:].strip()
        cfg["api_key"] = key
    except Exception:
        cfg["api_key"] = ""

    if body.workflow_input_variable:
        cfg["workflow_input_variable"] = body.workflow_input_variable
    if body.workflow_output_key:
        cfg["workflow_output_key"] = body.workflow_output_key
    if body.user:
        cfg["user_identifier"] = body.user

    if body.extra_inputs:
        existing = cfg.get("extra_inputs") or {}
        cfg["extra_inputs"] = {**existing, **body.extra_inputs}

    payload_input = body.payload_json if body.payload_json is not None else body.mr_txt
    return push_to_dify(payload_input, cfg, body.user)


# ---- 科室 ----
@router.get("/departments", response_model=DeptConfig, summary="获取科室配置")
def get_departments(_user: User = Depends(get_current_user)):
    cfg = load_config().get("departments", {})
    return DeptConfig(**cfg)


@router.post("/departments", response_model=MessageResponse, summary="保存科室配置")
def save_departments(body: DeptConfig, current_user: User = Depends(_require_manage_config)):
    update_section("departments", body.model_dump())
    _audit_logger.info("[AUDIT] 用户=%s id=%s 修改科室配置 mode=%s size=%s", current_user.username, current_user.id, body.mode, len(body.list or []))
    return MessageResponse(message="科室配置已保存")


@router.get("/departments/list", summary="按当前数据源动态查询科室列表")
def list_departments_by_data_source(_user: User = Depends(get_current_user)):
    cfg_all = load_config()
    data_source = (cfg_all.get("data_source", {}) or {}).get("type", "oracle")

    try:
        if data_source == "postgresql":
            cfg = cfg_all.get("postgresql", {}).copy()
            cfg["password"] = decrypt_value(cfg.get("password_enc", "")) if cfg.get("password_enc") else ""
            depts = fetch_pg_department_list(cfg)
        else:
            cfg = cfg_all.get("oracle", {}).copy()
            cfg["password"] = decrypt_value(cfg.get("password_enc", "")) if cfg.get("password_enc") else ""
            depts = fetch_department_list(cfg)
        return {"departments": depts}
    except HTTPException:
        raise
    except Exception as e:
        _logger.error(f"查询科室列表失败: {e}")
        raise HTTPException(status_code=500, detail="查询科室列表失败，请检查数据库连接配置")


# ---- 定时规则 ----
@router.get("/scheduler", response_model=SchedulerConfig, summary="获取定时任务配置")
def get_scheduler_config(_user: User = Depends(_require_manage_config)):
    cfg = load_config().get("scheduler", {})
    cfg.setdefault("schedule_mode", "daily")
    cfg.setdefault("daily_time", "06:00")
    cfg.setdefault("interval_value", 10)
    cfg.setdefault("interval_unit", "minutes")
    cfg.setdefault("cron", "0 6 * * *")
    return SchedulerConfig(**cfg)


def _resolve_scheduler_cron(body: SchedulerConfig) -> str:
    if body.schedule_mode == "every_n_minutes":
        return f"*/{int(body.interval_value)} * * * *"
    if body.schedule_mode == "every_n_hours":
        return f"0 */{int(body.interval_value)} * * *"
    if body.schedule_mode == "daily":
        hour, minute = body.daily_time.split(":")
        return f"{int(minute)} {int(hour)} * * *"
    return body.cron


@router.post("/scheduler", response_model=MessageResponse, summary="保存定时任务配置")
def save_scheduler_config(body: SchedulerConfig, current_user: User = Depends(_require_manage_config)):
    resolved_cron = _resolve_scheduler_cron(body)
    valid, message = validate_cron_expression(resolved_cron)
    if not valid:
        raise HTTPException(status_code=400, detail=message)

    payload = body.model_dump()
    payload["cron"] = resolved_cron

    apply_result = update_scheduler(body.enabled, resolved_cron)
    update_section("scheduler", payload)

    if isinstance(apply_result, dict) and not apply_result.get("applied"):
        _audit_logger.info("[AUDIT] 用户=%s id=%s 修改调度配置 enabled=%s cron=%s (未即时生效: %s)", current_user.username, current_user.id, body.enabled, resolved_cron, apply_result.get("message", ""))
        return MessageResponse(
            message=f"定时任务配置已保存，但当前未生效: {apply_result.get('message', '')}",
            success=False,
            data=apply_result,
        )
    _audit_logger.info("[AUDIT] 用户=%s id=%s 修改调度配置 enabled=%s cron=%s", current_user.username, current_user.id, body.enabled, resolved_cron)
    return MessageResponse(message="定时任务配置已保存", data=apply_result if isinstance(apply_result, dict) else None)


# ---- 推送设置 ----
@router.get("/push", response_model=PushSettings, summary="获取推送参数")
def get_push_settings(_user: User = Depends(_require_manage_config)):
    cfg = load_config().get("push", {})
    return PushSettings(**cfg)


@router.post("/push", response_model=MessageResponse, summary="保存推送参数")
def save_push_settings(body: PushSettings, current_user: User = Depends(_require_manage_config)):
    update_section("push", body.model_dump())
    _audit_logger.info("[AUDIT] 用户=%s id=%s 修改推送参数 interval_ms=%s max_retry=%s batch_size=%s", current_user.username, current_user.id, body.interval_ms, body.max_retry, body.batch_size)
    return MessageResponse(message="推送参数已保存")


# ---- 隐私脱敏配置 ----
@router.get("/privacy-masking", response_model=PrivacyMaskingConfig, summary="获取隐私脱敏配置")
def get_privacy_masking_config(_user: User = Depends(_require_manage_config)):
    cfg = load_config().get("privacy_masking", {})
    return PrivacyMaskingConfig(**cfg)


@router.post("/privacy-masking", response_model=MessageResponse, summary="保存隐私脱敏配置")
def save_privacy_masking_config(body: PrivacyMaskingConfig, current_user: User = Depends(_require_manage_config)):
    update_section("privacy_masking", body.model_dump())
    _audit_logger.info(
        "[AUDIT] 用户=%s id=%s 修改隐私脱敏配置 enabled=%s name=%s id_card=%s address=%s phone=%s",
        current_user.username,
        current_user.id,
        body.enabled,
        body.mask_name,
        body.mask_id_card,
        body.mask_address,
        body.mask_phone,
    )
    return MessageResponse(message="隐私脱敏配置已保存")


# ---- 通知配置 ----
@router.get("/notify", response_model=NotifyConfig, summary="获取通知渠道配置")
def get_notify_config(_user: User = Depends(_require_manage_config)):
    cfg = load_config().get("notify", {})
    return NotifyConfig(**cfg)


@router.post("/notify", response_model=MessageResponse, summary="保存通知渠道配置")
def save_notify_config(body: NotifyConfig, current_user: User = Depends(_require_manage_config)):
    update_section("notify", body.model_dump())
    _audit_logger.info("[AUDIT] 用户=%s id=%s 修改通知配置 channels=%s", current_user.username, current_user.id, len(body.channels or []))
    return MessageResponse(message="通知配置已保存")
