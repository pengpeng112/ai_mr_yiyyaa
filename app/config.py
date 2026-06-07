"""
配置读取模块 —— 环境变量 + config.json + SQLite
"""
# pyright: reportMissingImports=false, reportMissingTypeArgument=false, reportAttributeAccessIssue=false
import os
import json
import base64
import copy
import logging
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

CONFIG_DIR = os.getenv("CONFIG_DIR", "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
CONFIG_TEMPLATE_PATH = os.getenv("CONFIG_TEMPLATE_PATH", os.path.join(CONFIG_DIR, "config.json.template"))
CONFIG_BACKUP_DIR = os.path.join(CONFIG_DIR, "backups")
DATA_DIR = os.getenv("DATA_DIR", "data")
DB_PATH = os.path.join(DATA_DIR, "med_audit.db")
LOG_DIR = os.getenv("LOG_DIR", "logs")
APP_DB_TYPE = os.getenv("APP_DB_TYPE", "sqlite").strip().lower() or "sqlite"
APP_ORACLE_HOST = os.getenv("APP_ORACLE_HOST", "")
APP_ORACLE_PORT = int(os.getenv("APP_ORACLE_PORT", "1521"))
APP_ORACLE_SERVICE_NAME = os.getenv("APP_ORACLE_SERVICE_NAME", "")
APP_ORACLE_USERNAME = os.getenv("APP_ORACLE_USERNAME", "")
APP_ORACLE_PASSWORD = os.getenv("APP_ORACLE_PASSWORD", "")


# ---- 加密工具 ----
def _validate_secret_key():
    """验证密钥配置，防止生产环境使用默认密钥"""
    secret_key = os.getenv("SECRET_KEY", "default-dev-key-change-in-prod")
    environment = os.getenv("ENVIRONMENT", "development")

    if environment == "production" and secret_key == "default-dev-key-change-in-prod":
        raise ValueError(
            "生产环境必须设置SECRET_KEY环境变量！"
            "请使用: export SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
        )

    if len(secret_key) < 32:
        logger.warning("SECRET_KEY长度不足32位，建议使用更长的密钥以增强安全性")

    return secret_key


_SECRET_KEY = _validate_secret_key()
_fernet_instance: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"med-audit-salt-v1",
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(_SECRET_KEY.encode()))
    _fernet_instance = Fernet(key)
    return _fernet_instance


def encrypt_value(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_value(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()


def mask_secret(value: str, show: int = 4) -> str:
    if not value or len(value) <= show:
        return "****"
    return value[:show] + "*" * (len(value) - show)


def normalize_dify_base_url(value: str) -> str:
    """标准化 Dify 基础地址，避免重复拼接 /workflows/run。"""
    base_url = (value or "").strip()
    if not base_url:
        raise ValueError("Dify base_url 不能为空")

    parsed = urlsplit(base_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Dify base_url 必须是完整地址，例如 https://api.dify.ai/v1")

    path = parsed.path.rstrip("/")
    if path.endswith("/workflows/run"):
        path = path[:-len("/workflows/run")]

    normalized = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    if not normalized:
        raise ValueError("Dify base_url 无效")
    return normalized


def validate_postgresql_query_sql(query_sql: str):
    """校验 PostgreSQL 查询 SQL，确保与当前执行器约定一致。"""
    sql = (query_sql or "").strip()
    if not sql:
        return

    sql_lower = sql.lower()
    if "{dept_filter}" not in sql:
        raise ValueError("PostgreSQL query_sql 必须包含 {dept_filter} 占位符")
    if "%s" not in sql:
        raise ValueError("PostgreSQL query_sql 必须包含 %s 日期参数占位符")
    if "select" not in sql_lower:
        raise ValueError("PostgreSQL query_sql 必须是 SELECT 查询")


def validate_oracle_instant_client_dir(path_value: str, require_exists: bool = False) -> str:
    """校验 Oracle Instant Client 路径。"""
    path_str = (path_value or "").strip()
    if not path_str:
        return ""

    client_path = Path(path_str)
    if require_exists and not client_path.exists():
        # 兼容工作树/目录名变化：优先尝试当前工程自带的 oracle-client 目录。
        bundled_path = Path(__file__).resolve().parent.parent / "oracle-client" / client_path.name
        if bundled_path.exists() and bundled_path.is_dir():
            logger.warning(f"Oracle Instant Client 目录不存在，已自动切换到当前工程目录: {bundled_path}")
            return str(bundled_path)

    if require_exists and not client_path.exists():
        raise ValueError(f"Oracle Instant Client 目录不存在: {path_str}")
    if require_exists and not client_path.is_dir():
        raise ValueError(f"Oracle Instant Client 路径不是目录: {path_str}")
    return path_str


def validate_runtime_config(cfg: dict) -> list[str]:
    """启动时做轻量配置自检，只返回告警，不阻塞服务启动。"""
    warnings = []

    try:
        dify_cfg = cfg.get("dify", {}) or {}
        if dify_cfg.get("base_url"):
            normalize_dify_base_url(dify_cfg.get("base_url", ""))
    except ValueError as exc:
        warnings.append(str(exc))

    try:
        pg_cfg = cfg.get("postgresql", {}) or {}
        validate_postgresql_query_sql(pg_cfg.get("query_sql", ""))
    except ValueError as exc:
        warnings.append(str(exc))

    try:
        oracle_cfg = cfg.get("oracle", {}) or {}
        validate_oracle_instant_client_dir(
            oracle_cfg.get("instant_client_dir", ""),
            require_exists=bool(oracle_cfg.get("instant_client_dir", "")),
        )
    except ValueError as exc:
        warnings.append(str(exc))

    return warnings


# ---- JSON 配置文件读写（线程安全） ----
_config_lock = threading.RLock()
_DEFAULT_QUERY_SQL = """SELECT
    a.患者ID, a.次数, a.住院号, a.患者姓名, a.性别, a.出生日期, a.入院日期,
    a.BED_NO AS 床号, a.入院诊断, a.入院病情,
    a.护理级别 AS 医嘱护理级别, a.所在科室名称, a.管床医生,
    b.病历标题时间 AS 病历文书_完成时间,
    b.病历名称 AS 病历文书_名称,
    b.创建人 AS 病历文书_签名医师,
    b.病历内容 AS 病历文书_内容,
    c.护理记录时间 AS 护理记录_创建时间,
    c.护理单类型 AS 护理记录_文书类型,
    c.病情观察及护理措施 AS 护理记录_内容,
    c.记录人 AS 护理记录_记录人,
    c.体温 AS 护理记录_体温,
    c.心率脉搏 AS 护理记录_心率脉搏,
    c.呼吸 AS 护理记录_呼吸,
    c.血压 AS 护理记录_血压,
    c.血氧饱和度 AS 护理记录_血氧饱和度,
    c.血糖 AS 护理记录_血糖,
    c.意识神志 AS 护理记录_意识神志,
    c.氧疗_鼻导管 AS 护理记录_氧疗_鼻导管,
    c.氧疗_面罩 AS 护理记录_氧疗_面罩,
    c.入量_名称 AS 护理记录_入量_名称,
    c.入量_途径 AS 护理记录_入量_途径,
    c.入量_量 AS 护理记录_入量_量,
    c.出量_名称 AS 护理记录_出量_名称,
    c.出量_量 AS 护理记录_出量_量,
    c.尿量 AS 护理记录_尿量,
    c.皮肤情况 AS 护理记录_皮肤情况,
    c.刀口情况 AS 护理记录_刀口情况,
    c.管道护理 AS 护理记录_管道护理,
    c.高危风险 AS 护理记录_高危风险,
    c.护士签名 AS 护理记录_护士签名
FROM jhemr.v_zybr a
LEFT JOIN jhemr.v_bcjl b ON a.患者ID = b.患者ID AND a.次数 = b.次数
LEFT JOIN ydhl.v_hljl c ON c.患者ID = b.患者ID || '_' || b.次数
    AND TO_CHAR(b.病历标题时间, 'yyyy-mm-dd') = TO_CHAR(c.护理记录时间, 'yyyy-mm-dd')
WHERE {dept_filter}
  AND TO_CHAR(b.病历标题时间, 'yyyy-mm-dd') = :query_date
ORDER BY a.患者ID, a.次数, b.病历标题时间, c.护理记录时间"""

_DEFAULT_DEPT_SQL = "SELECT DISTINCT 所在科室名称 FROM jhemr.v_zybr WHERE 所在科室名称 IS NOT NULL ORDER BY 所在科室名称"

_DEFAULT_CONFIG = {
    "data_source": {
        "type": "oracle"
    },
    "oracle": {
        "host": "10.255.255.20",
        "port": 1521,
        "service_name": "orcl",
        "username": "",
        "password_enc": "",
        "instant_client_dir": "",
        "query_sql": _DEFAULT_QUERY_SQL,
        "dept_sql": _DEFAULT_DEPT_SQL,
        "field_mapping": {
            "patient_id": "患者ID",
            "visit_number": "次数",
            "patient_name": "患者姓名",
            "dept": "所在科室名称",
            "admission_no": "住院号",
        },
        "extra_sources": {
            "medical_orders": {
                "enabled": False,
                "query_sql": "",
                "field_mapping": {
                    "patient_id": "患者ID",
                    "visit_number": "次数",
                    "order_time": "开嘱时间",
                    "order_type": "医嘱类型",
                    "order_content": "医嘱内容",
                    "doctor": "开嘱医生",
                    "order_status": "执行状态",
                },
            },
            "front_page": {
                "enabled": False,
                "query_sql": "",
                "field_mapping": {
                    "patient_id": "患者ID",
                    "visit_number": "次数",
                    "admission_diagnosis": "入院诊断",
                    "discharge_diagnosis": "出院主诊断",
                    "surgery_name": "手术名称",
                    "surgery_date": "手术日期",
                    "operation_doctor": "手术医生",
                },
            },
            "lab_exam_reports": {
                "enabled": False,
                "query_sql": "",
                "field_mapping": {
                    "patient_id": "患者ID",
                    "visit_number": "次数",
                    "report_time": "报告时间",
                    "report_type": "报告类型",
                    "item_name": "检查项目",
                    "result": "结果",
                    "reference_range": "参考范围",
                    "abnormal_flag": "异常标志",
                },
            },
        },
    },
    "postgresql": {
        "host": "localhost",
        "port": 5432,
        "database": "ai_hms_db",
        "username": "",
        "password_enc": "",
        "query_sql": "",
        "dept_sql": "",
        "field_mapping": {
            "patient_id": "患者ID",
            "visit_number": "次数",
            "patient_name": "患者姓名",
            "dept": "所在科室名称",
            "admission_no": "住院号",
        },
        "extra_sources": {
            "medical_orders": {
                "enabled": False,
                "query_sql": "",
                "field_mapping": {
                    "patient_id": "患者ID",
                    "visit_number": "次数",
                    "order_time": "开嘱时间",
                    "order_type": "医嘱类型",
                    "order_content": "医嘱内容",
                    "doctor": "开嘱医生",
                    "order_status": "执行状态",
                },
            },
            "front_page": {
                "enabled": False,
                "query_sql": "",
                "field_mapping": {
                    "patient_id": "患者ID",
                    "visit_number": "次数",
                    "admission_diagnosis": "入院诊断",
                    "discharge_diagnosis": "出院主诊断",
                    "surgery_name": "手术名称",
                    "surgery_date": "手术日期",
                    "operation_doctor": "手术医生",
                },
            },
            "lab_exam_reports": {
                "enabled": False,
                "query_sql": "",
                "field_mapping": {
                    "patient_id": "患者ID",
                    "visit_number": "次数",
                    "report_time": "报告时间",
                    "report_type": "报告类型",
                    "item_name": "检查项目",
                    "result": "结果",
                    "reference_range": "参考范围",
                    "abnormal_flag": "异常标志",
                },
            },
        },
    },
    "dify": {
        "base_url": "http://10.255.255.10/v1",
        "api_key_enc": "",
        "workflow_input_variable": "mr_txt",
        "workflow_output_key": "aa",
        "user_identifier": "med-audit-system",
        "timeout_seconds": 90,
        "extra_inputs": {},
        "full_debug_log": False,
        "targets": [],
    },
    "audit_types": [],
    "departments": {
        "mode": "include",
        "list": [],
    },
    "scheduler": {
        "enabled": False,
        "cron": "0 6 * * *",
        "schedule_mode": "daily",
        "daily_time": "06:00",
        "audit_run_mode": "daily_increment",
        "audit_type_codes": [],
        "dept_filter": [],
    },
    "scheduler_daily": {
        "enabled": False,
        "cron": "0 10 * * *",
        "schedule_mode": "daily",
        "daily_time": "10:00",
        "audit_run_mode": "daily_increment",
        "audit_type_codes": [],
        "dept_filter": [],
    },
    "scheduler_discharge": {
        "enabled": False,
        "cron": "0 11 * * *",
        "schedule_mode": "daily",
        "daily_time": "11:00",
        "audit_run_mode": "discharge_final",
        "audit_type_codes": ["progress_vs_nursing"],
        "dept_filter": [],
    },
    "push": {
        "interval_ms": 500,
        "max_retry": 3,
        "batch_size": 50,
    },
    "notify": {
        "channels": [],
    },
    "privacy_masking": {
        "enabled": False,
        "mask_name": True,
        "mask_id_card": True,
        "mask_address": True,
        "mask_phone": True,
    },
    "data_retention": {
        "enabled": True,
        "l1_log_meta_days": 90,
        "l2_audit_summary_days": 365,
        "l3_sensitive_content_days": 30,
        "cleanup_cron": "0 2 * * *",
        "cleanup_batch_size": 500,
    },
}


def _ensure_dirs():
    for d in (CONFIG_DIR, CONFIG_BACKUP_DIR, DATA_DIR, LOG_DIR):
        Path(d).mkdir(parents=True, exist_ok=True)


def _build_default_audit_type(cfg: dict) -> dict:
    data_source = ((cfg or {}).get("data_source", {}) or {}).get("type", "oracle")
    data_source_key = "postgresql" if data_source == "postgresql" else "oracle"
    source_cfg = ((cfg or {}).get(data_source_key, {}) or {})
    dify_cfg = ((cfg or {}).get("dify", {}) or {})
    source_field_mapping = copy.deepcopy(source_cfg.get("field_mapping", {}) or {})
    query_sql = str(source_cfg.get("query_sql") or "").strip()

    return {
        "code": "progress_vs_nursing",
        "name": "病程 vs 护理",
        "description": "病程记录与护理记录一致性核查",
        "enabled": True,
        "sort_order": 10,
        "default_for_schedule": True,
        "sources": {
            "primary": {
                "type": "sql",
                "query_sql": query_sql,
                "field_mapping": source_field_mapping,
                "required": True,
            }
        },
        "group_key": ["patient_id", "visit_number"],
        "payload": {
            "builder": "legacy_progress_nursing",
            "extra_fields": {},
        },
        "dify": {
            "base_url": str(dify_cfg.get("base_url") or ""),
            "api_key_enc": str(dify_cfg.get("api_key_enc") or ""),
            "workflow_input_variable": str(dify_cfg.get("workflow_input_variable") or "mr_txt"),
            "workflow_output_key": str(dify_cfg.get("workflow_output_key") or "aa"),
            "user_identifier": str(dify_cfg.get("user_identifier") or "med-audit-system"),
            "timeout_seconds": int(dify_cfg.get("timeout_seconds") or 90),
            "extra_inputs": copy.deepcopy(dify_cfg.get("extra_inputs", {}) or {}),
            "full_debug_log": bool(dify_cfg.get("full_debug_log", False)),
            "targets": copy.deepcopy(dify_cfg.get("targets", []) or []),
        },
        "response": {
            "parse_strategy": "hybrid",
            "dimension_path": "$.dimensions",
            "conclusion_path": "$.overall_conclusion",
            "severity_path": "$.severity",
            "risk_score_path": "$.risk_score",
            "inconsistency_path": "$.inconsistency",
        },
        "display": {
            "summary_blocks": [
                {"label": "总体结论", "path": "$.overall_conclusion", "type": "text_block"},
                {"label": "重点关注", "path": "$.focus_items", "type": "tag_list"},
                {"label": "风险分值", "path": "$.risk_score", "type": "severity_badge"},
            ],
            "detail_blocks": [
                {"label": "维度详情", "path": "$.dimensions", "type": "dimension_grid"},
                {"label": "原始 Dify 返回", "path": "$", "type": "raw_json", "collapsed": True},
            ],
        },
    }


def _ensure_default_audit_type(cfg: dict) -> dict:
    upgraded = copy.deepcopy(cfg or {})
    audit_types = upgraded.get("audit_types")
    if not isinstance(audit_types, list):
        audit_types = []
    has_seed = any(
        isinstance(item, dict) and str(item.get("code") or "").strip() == "progress_vs_nursing"
        for item in audit_types
    )
    if not has_seed:
        audit_types.insert(0, _build_default_audit_type(upgraded))
    upgraded["audit_types"] = audit_types
    return upgraded


def _upgrade_config(cfg: dict) -> tuple[dict, bool]:
    upgraded = copy.deepcopy(_DEFAULT_CONFIG)
    upgraded.update(copy.deepcopy(cfg or {}))

    for key in ("oracle", "postgresql", "dify", "departments", "scheduler", "scheduler_daily", "scheduler_discharge", "push", "notify", "privacy_masking", "data_retention"):
        merged = copy.deepcopy(_DEFAULT_CONFIG.get(key, {}))
        merged.update(copy.deepcopy((cfg or {}).get(key, {}) or {}))
        upgraded[key] = merged

    upgraded = _ensure_default_audit_type(upgraded)
    changed = upgraded != (cfg or {})
    return upgraded, changed


def _write_config_file(path: str, cfg: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _load_initial_config() -> dict:
    template_path = Path(CONFIG_TEMPLATE_PATH)

    if template_path.exists():
        with open(template_path, "r", encoding="utf-8") as f:
            template_cfg = json.load(f)
        initial, _ = _upgrade_config(template_cfg)
        logger.info("config.json 不存在，已基于模板初始化: %s", template_path)
        return initial

    initial = _ensure_default_audit_type(copy.deepcopy(_DEFAULT_CONFIG))
    logger.warning("配置模板不存在，已回退到内置默认配置: %s", template_path)
    return initial


def load_config() -> dict:
    _ensure_dirs()
    with _config_lock:
        if not os.path.exists(CONFIG_FILE):
            initial = _load_initial_config()
            _write_config_file(CONFIG_FILE, initial)
            return initial
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            current = json.load(f)
        upgraded, changed = _upgrade_config(current)
        if changed:
            _write_config_file(CONFIG_FILE, upgraded)
        return upgraded


def save_config(cfg: dict):
    _ensure_dirs()
    with _config_lock:
        upgraded, _ = _upgrade_config(cfg)
        if os.path.exists(CONFIG_FILE):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(CONFIG_BACKUP_DIR, f"config_{timestamp}.json")
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as src:
                    previous = json.load(src)
                _write_config_file(backup_file, previous)
            except Exception as exc:
                logger.warning("配置备份失败: %s", exc)
        _write_config_file(CONFIG_FILE, upgraded)


def update_section(section: str, data: dict):
    cfg = load_config()
    cfg[section] = data
    save_config(cfg)
    return cfg[section]
