# -*- coding: utf-8 -*-
"""预检服务独立配置：JSON 加载/校验/默认值 + Fernet 凭据加密（独立实现）。

与 Med-Audit 主服务完全隔离：
- 不 import 主服务任何模块，不共享其 SECRET_KEY；
- 密钥来源：环境变量 PREARCHIVE_SECRET_KEY 优先，否则 config.security.secret_key；
- 加密值带 ``enc:v1:`` 前缀，明文一律不允许出现在配置文件中（占位符除外）。

命令行用法（生成密钥 / 加密口令）::

    python -m prearchive.config genkey
    python -m prearchive.config encrypt <fernet_key> <明文>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken

ENC_PREFIX = "enc:v1:"

DEFAULTS: dict = {
    "service": {
        "name": "prearchive-service",
        "poll_interval_seconds": 300,       # 轮询间隔（默认 5 分钟，D3）
        "batch_limit": 100,                 # 单轮最多处理的新完成病历数
        "lookback_seconds": 86400,          # 水位回看窗（复检：完成时间在窗内更新可被重新发现）
        # 触发锚点模式（031 T2-1）：finished=完成时间（默认，029 K1 证实 177 副本全 NULL
        # 生产暂不可用）；discharge=出院时间（177 实测 99% 有值，语义退化兜底）；
        # blws_status=v_blws.modify_date 文书状态聚合（视图重，029 K5 全表聚合 120s 超时，
        # 生产不可用仅联调）。新模式必须显式配置才生效，默认保持 finished 行为不变。
        "anchor_mode": "finished",
        "state_file": "data/state.json",    # 断点续跑水位 + 检查键去重表（相对 prearchive_service/）
        "lock_file": "data/poller.lock",    # 防重入锁文件
        "heartbeat_file": "data/heartbeat.json",
        "heartbeat_max_age_seconds": 900,   # 心跳超过该秒数视为停跳（外部探测口径）
    },
    "rules": {
        "rules_file": "rules/example_rules.json",
        # T8-4 系统推送类独立通道（多文件合并；不写真实规则，等用户 W10 清单）
        "extra_rules_files": ["rules/system_push_rules.json"],
    },
    "push": {
        "enabled": False,                   # 一期默认关；影子运行期保持 false（P1-6）
        "base_url": "<RELAY_BASE_URL_PLACEHOLDER>",
        "endpoint": "/qc-record-alert",
        "secret_key_enc": "<ENC_SECRET_PLACEHOLDER>",
        "timeout_seconds": 10,
        "severity_levels": ["medium", "high"],   # 低于该级别的结果不推送
    },
    "receiver": {
        # 完成医生优先，管床医师兜底（D1/A4）；映射函数运行时注入（P0-6 基线后实现）
        "fallback_order": ["first_finished_doctor", "attending_doctor"],
    },
    "api": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8600,
        "shared_token": "<SHARED_TOKEN_PLACEHOLDER>",   # 鉴权头 X-Precheck-Token（A19）
        "require_dept_binding": True,                    # 患者归属科室校验（防冒用，最小实现）
    },
    "logging": {
        "level": "INFO",
        "file": "logs/prearchive.log",
    },
    # 四源连接：全部占位符，不含任何真实 IP/账号/口令（凭据边界见 028 §1.4）
    "sources": {
        "jhemr": {
            "type": "postgresql",        # Vastbase 兼容协议
            "enabled": False,
            "host": "<JHEMR_HOST_PLACEHOLDER>",
            "port": 5432,
            "database": "<JHEMR_DB_PLACEHOLDER>",
            "user": "<JHEMR_USER_PLACEHOLDER>",
            "password_enc": "<ENC_PASSWORD_PLACEHOLDER>",
            "sslmode": "",
        },
        "his": {
            "type": "oracle",
            "enabled": False,
            "host": "<HIS_HOST_PLACEHOLDER>",
            "port": 1521,
            "service_name": "<HIS_SERVICE_PLACEHOLDER>",
            "user": "<HIS_USER_PLACEHOLDER>",
            "password_enc": "<ENC_PASSWORD_PLACEHOLDER>",
        },
        "sm": {
            "type": "oracle",
            "enabled": False,
            "host": "<SM_HOST_PLACEHOLDER>",
            "port": 1521,
            "service_name": "<SM_SERVICE_PLACEHOLDER>",
            "user": "<SM_USER_PLACEHOLDER>",
            "password_enc": "<ENC_PASSWORD_PLACEHOLDER>",
        },
        "lis": {
            "type": "mssql",             # pyodbc 只在本服务出现（R11/A7）
            "enabled": False,
            "odbc_driver": "<ODBC_DRIVER_PLACEHOLDER>",
            "host": "<LIS_HOST_PLACEHOLDER>",
            "port": 1433,
            "database": "<LIS_DB_PLACEHOLDER>",
            "user": "<LIS_USER_PLACEHOLDER>",
            "password_enc": "<ENC_PASSWORD_PLACEHOLDER>",
        },
        # 无纸化 CDMS 第五源（031 T2-7）：规则目录/聚合金标准元数据——不是患者文书源，
        # 禁止接入 PatientContextBuilder.documents（R15）；默认 disabled，凭据占位
        "paperless": {
            "type": "oracle",
            "enabled": False,
            "host": "<PAPERLESS_HOST_PLACEHOLDER>",
            "port": 1521,
            "service_name": "<PAPERLESS_SERVICE_PLACEHOLDER>",
            "user": "<PAPERLESS_USER_PLACEHOLDER>",
            "password_enc": "<ENC_PASSWORD_PLACEHOLDER>",
        },
        # T8-2 新七源（031 §10 全源矩阵）：全部默认 disabled、DSN/凭据占位、
        # fixture 驱动本地可跑；BLOCKED 源不伪造实测结果（骨架+TODO）
        "pacs": {
            "type": "mysql",              # GE gecris（连接器实测 REPORTNAME=文本/时间列=varchar）
            "enabled": False,
            "host": "<PACS_HOST_PLACEHOLDER>",
            "port": 3306,
            "database": "<PACS_DB_PLACEHOLDER>",
            "user": "<PACS_USER_PLACEHOLDER>",
            "password_enc": "<ENC_PASSWORD_PLACEHOLDER>",
        },
        "es": {                            # 内镜+超声双视图合并一源标签 es_itf
            "type": "mssql",
            "enabled": False,
            "odbc_driver": "<ODBC_DRIVER_PLACEHOLDER>",
            "host": "<ES_HOST_PLACEHOLDER>",
            "port": 1433,
            "database": "AnyImage",        # 连接器默认库是 MedcareUS，须显式指定 AnyImage
            "user": "<ES_USER_PLACEHOLDER>",
            "password_enc": "<ENC_PASSWORD_PLACEHOLDER>",
        },
        "bl": {                            # 病理 BLOCKED：平台连接器缺 sqlserver 驱动
            "type": "mssql",
            "enabled": False,
            "odbc_driver": "<ODBC_DRIVER_PLACEHOLDER>",
            "host": "<BL_HOST_PLACEHOLDER>",
            "port": 1433,
            "database": "pitaya",
            "user": "<BL_USER_PLACEHOLDER>",
            "password_enc": "<ENC_PASSWORD_PLACEHOLDER>",
        },
        "xt": {                            # 血透（未登记平台）
            "type": "postgresql",
            "enabled": False,
            "host": "<XT_HOST_PLACEHOLDER>",
            "port": 5432,
            "database": "dialysis",
            "user": "<XT_USER_PLACEHOLDER>",
            "password_enc": "<ENC_PASSWORD_PLACEHOLDER>",
            "sslmode": "",
        },
        "xd": {                            # 心电 BLOCKED：实例两库均无 ITF 对象，对接信息用户后期提供
            "type": "mssql",               # 登记口径 sqlserver；真实库型待用户提供（031 §10）
            "enabled": False,
            "odbc_driver": "<ODBC_DRIVER_PLACEHOLDER>",
            "host": "<XD_HOST_PLACEHOLDER>",
            "port": 1433,
            "database": "<XD_DB_PLACEHOLDER>",
            "user": "<XD_USER_PLACEHOLDER>",
            "password_enc": "<ENC_PASSWORD_PLACEHOLDER>",
        },
        "dcn": {                           # 电测听（未登记平台）
            "type": "postgresql",
            "enabled": False,
            "host": "<DCN_HOST_PLACEHOLDER>",
            "port": 15432,
            "database": "report",
            "user": "<DCN_USER_PLACEHOLDER>",
            "password_enc": "<ENC_PASSWORD_PLACEHOLDER>",
            "sslmode": "",
        },
        "qgj": {                           # 气管镜（未登记平台）
            "type": "postgresql",
            "enabled": False,
            "host": "<QGJ_HOST_PLACEHOLDER>",
            "port": 5432,
            "database": "<QGJ_DB_PLACEHOLDER>",
            "user": "<QGJ_USER_PLACEHOLDER>",
            "password_enc": "<ENC_PASSWORD_PLACEHOLDER>",
            "sslmode": "",
        },
        # T8-3 基本信息视图（HIS@10.10.10.14 his 库）——未登记平台 BLOCKED；
        # 用途：VW_user_info 工号映射 / VW_dept_dict 科室规范化 / 出院患者交叉校验
        "his_base": {
            "type": "oracle",
            "enabled": False,
            "host": "<HIS_BASE_HOST_PLACEHOLDER>",
            "port": 1521,
            "service_name": "<HIS_BASE_SERVICE_PLACEHOLDER>",
            "user": "<HIS_BASE_USER_PLACEHOLDER>",
            "password_enc": "<ENC_PASSWORD_PLACEHOLDER>",
        },
    },
    # 结果库（应用侧独立库；本地原型/测试用 sqlite，生产 Oracle 走 sql/ DDL 手工建表）
    "result_store": {
        "type": "sqlite",
        "sqlite_path": "data/prearchive_result.db",
        "oracle_dsn": "<RESULT_ORACLE_DSN_PLACEHOLDER>",
        "oracle_user": "<RESULT_USER_PLACEHOLDER>",
        "oracle_password_enc": "<ENC_PASSWORD_PLACEHOLDER>",
    },
}


class ConfigError(Exception):
    """配置结构/凭据错误。"""


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | os.PathLike) -> dict:
    """加载 JSON 配置并与默认值深合并；结构异常抛 ConfigError。"""
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"config file not found: {config_path}")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config file is not valid JSON: {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be an object: {config_path}")
    return validate_config(_deep_merge(DEFAULTS, raw))


def validate_config(config: dict) -> dict:
    """轻量结构校验（类型/取值），失败抛 ConfigError。不触网、不读密文之外的东西。"""
    service = config.get("service") or {}
    interval = service.get("poll_interval_seconds")
    if not isinstance(interval, (int, float)) or interval <= 0:
        raise ConfigError("service.poll_interval_seconds must be a positive number")
    limit = service.get("batch_limit")
    if not isinstance(limit, int) or limit <= 0:
        raise ConfigError("service.batch_limit must be a positive int")
    anchor_mode = str(service.get("anchor_mode") or "finished")
    if anchor_mode not in ("finished", "discharge", "blws_status", "paperless_rpa"):
        raise ConfigError(
            "service.anchor_mode must be one of "
            "finished/discharge/blws_status/paperless_rpa, "
            f"got {anchor_mode!r}")
    state_backend = str(service.get("state_backend") or "json")
    if state_backend not in ("json", "db"):
        raise ConfigError(f"service.state_backend must be json/db, got {state_backend!r}")
    sources = config.get("sources") or {}
    # mysql 仅 PACS（gecris）使用：pymysql 生产开通再装（本地 fixture 免驱动，T8-2）
    _KNOWN_SOURCE_TYPES = ("postgresql", "oracle", "mssql", "mysql")
    for name in ("jhemr", "his", "sm", "lis", "paperless",
                 "pacs", "es", "bl", "xt", "xd", "dcn", "qgj", "his_base"):
        if name not in sources:
            raise ConfigError(f"sources.{name} missing")
        src_type = sources[name].get("type")
        if src_type not in _KNOWN_SOURCE_TYPES:
            raise ConfigError(
                f"sources.{name}.type must be one of {_KNOWN_SOURCE_TYPES}, "
                f"got {src_type!r}")
    severity_levels = (config.get("push") or {}).get("severity_levels") or []
    if not isinstance(severity_levels, list):
        raise ConfigError("push.severity_levels must be a list")
    return config


def get_fernet(config: dict) -> Fernet:
    """从环境变量或配置取密钥构造 Fernet（独立于主服务 SECRET_KEY）。"""
    key = os.environ.get("PREARCHIVE_SECRET_KEY", "").strip()
    if not key:
        key = str(((config.get("security") or {}).get("secret_key")) or "").strip()
    if not key or key.startswith("<"):
        raise ConfigError(
            "Fernet key missing: set PREARCHIVE_SECRET_KEY or config.security.secret_key "
            "(generate via: python -m prearchive.config genkey)"
        )
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:  # ValueError 等无效密钥
        raise ConfigError(f"invalid Fernet key: {exc}") from exc


def encrypt_value(fernet: Fernet, plaintext: str) -> str:
    """加密为 enc:v1:<token> 形式（配置文件内只允许该形式或占位符）。"""
    if not isinstance(plaintext, str) or plaintext == "":
        raise ConfigError("plaintext to encrypt must be a non-empty string")
    token = fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
    return ENC_PREFIX + token


def decrypt_value(fernet: Fernet, value: str) -> str:
    """解密 enc:v1:<token>；已是明文形式的旧值直接返回（迁移宽容）。"""
    if not isinstance(value, str) or value == "":
        return ""
    if value.startswith("<") and value.endswith(">"):
        raise ConfigError("credential is still a placeholder, configure real encrypted value first")
    if not value.startswith(ENC_PREFIX):
        return value
    try:
        return fernet.decrypt(value[len(ENC_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ConfigError(
            "cannot decrypt credential: wrong PREARCHIVE_SECRET_KEY or corrupted token"
        ) from exc


def resolve_source_password(config: dict, fernet: Fernet, source_name: str) -> str:
    sources = config.get("sources") or {}
    if source_name not in sources:
        raise ConfigError(f"unknown source: {source_name}")
    return decrypt_value(fernet, str(sources[source_name].get("password_enc") or ""))


def resolve_result_store_password(config: dict, fernet: Fernet) -> str:
    """Oracle 结果库口令（T2-3）；占位符直接 ConfigError（fail-fast，不回落 sqlite）。"""
    store = config.get("result_store") or {}
    return decrypt_value(fernet, str(store.get("oracle_password_enc") or ""))


def resolve_push_secret(config: dict, fernet: Fernet) -> str:
    return decrypt_value(fernet, str((config.get("push") or {}).get("secret_key_enc") or ""))


def resolve_base_dir(config_path: str | os.PathLike) -> Path:
    """相对路径（state/日志/规则文件）统一以 prearchive_service/ 目录为基准。"""
    return Path(config_path).resolve().parent


def resolve_path(base_dir: Path, configured: str) -> Path:
    p = Path(configured)
    return p if p.is_absolute() else (base_dir / p)


def _cli(argv: list) -> int:
    if len(argv) >= 2 and argv[1] == "genkey":
        print(Fernet.generate_key().decode("ascii"))
        return 0
    if len(argv) >= 4 and argv[1] == "encrypt":
        fernet = Fernet(argv[2].encode("utf-8"))
        print(encrypt_value(fernet, argv[3]))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli(sys.argv))
