"""
病历时效质控配置与异常（T1）。

- 配置段：config.json 的 `timeliness`（模板已含默认骨架，enabled 默认 false）；
- 只读账号固定 `aizk_user`（D2 决策，见主设计文档 §18.1/§18.2）；
- 口令来源：环境变量 TIMELINESS_JHEMR_PASSWORD 优先，其次 config.json 的
  `password_enc`（用 app.config.decrypt_value 做 Fernet 解密）；两者都缺 → 未配置；
- 严禁在代码、配置、测试、文档、日志中写入真实口令明文。
"""
from __future__ import annotations

import os

from cryptography.fernet import InvalidToken

from app.config import decrypt_value, load_config

# D2：电子病历只读账号固定，禁止在配置中改用其他账号（§18.6 T1）。
READONLY_USERNAME_FIXED = "aizk_user"

# 口令环境变量名（部署时由用户注入，不落任何文件）。
PASSWORD_ENV_VAR = "TIMELINESS_JHEMR_PASSWORD"


class TimelinessError(RuntimeError):
    """病历时效质控模块基础异常。"""


class TimelinessNotConfigured(TimelinessError):
    """timeliness 配置段缺失、未启用或关键项（host/口令）未配置。"""


class TimelinessPermissionMissing(TimelinessError):
    """只读账号对某表缺少 SELECT 权限（SQLSTATE 42501）。

    属性 table_name 为完整限定表名（如 jhemr.jhmr_file_index）。
    处置约定（§18.6 T1）：扫描任务记录失败并列入缺权限表清单，不得换账号。
    """

    def __init__(self, table_name: str):
        super().__init__(
            f"只读账号 {READONLY_USERNAME_FIXED} 缺少表 {table_name} 的 SELECT 权限"
            "（D2：不得换账号，请按主设计文档 §18.2 申请授权）"
        )
        self.table_name = table_name


def get_timeliness_section(config: dict | None = None) -> dict:
    """读取并校验 timeliness 配置段；缺失或未启用抛 TimelinessNotConfigured。

    config 传 None 时读取应用配置（load_config()）。
    """
    cfg = config if config is not None else load_config()
    section = (cfg or {}).get("timeliness")
    if not isinstance(section, dict) or not section.get("enabled"):
        raise TimelinessNotConfigured(
            "config.json 缺少 timeliness 配置段，或该段 enabled 未设为 true"
        )
    return section


def resolve_jhemr_readonly(section: dict | None = None) -> dict:
    """校验 timeliness.jhemr_readonly 并解析连接参数（口令已解密）。

    返回 dict 含 host/port/database/username/password/statement_timeout_ms/
    connect_timeout_seconds/sslmode。password 仅在内存中传递，严禁写入日志。
    """
    if section is None:
        section = get_timeliness_section()
    readonly = section.get("jhemr_readonly") or {}
    if not isinstance(readonly, dict):
        raise TimelinessNotConfigured("timeliness.jhemr_readonly 配置段类型错误")

    host = str(readonly.get("host") or "").strip()
    if not host:
        raise TimelinessNotConfigured("timeliness.jhemr_readonly.host 未配置")
    database = str(readonly.get("database") or "").strip() or "jhemr"

    username = str(readonly.get("username") or "").strip()
    if username and username != READONLY_USERNAME_FIXED:
        raise TimelinessNotConfigured(
            f"D2：只读账号固定为 {READONLY_USERNAME_FIXED}，禁止改用其他账号（配置值为 {username!r}）"
        )

    password = os.environ.get(PASSWORD_ENV_VAR, "").strip()
    if not password:
        token = str(readonly.get("password_enc") or "").strip()
        if token:
            try:
                password = decrypt_value(token)
            except InvalidToken:
                raise RuntimeError(
                    "timeliness.jhemr_readonly.password_enc 解密失败"
                    "（SECRET_KEY 与密文不匹配，疑似密钥漂移），拒绝回退明文"
                ) from None
    if not password:
        raise TimelinessNotConfigured(
            f"JHEMR 只读口令未配置：请设置环境变量 {PASSWORD_ENV_VAR}"
            "，或在 config.json 的 timeliness.jhemr_readonly.password_enc 填入 Fernet 密文"
        )

    return {
        "host": host,
        "port": int(readonly.get("port") or 5432),
        "database": database,
        "username": READONLY_USERNAME_FIXED,
        "password": password,
        "statement_timeout_ms": int(readonly.get("statement_timeout_ms") or 60000),
        "connect_timeout_seconds": int(readonly.get("connect_timeout_seconds") or 10),
        "sslmode": str(readonly.get("sslmode") or "").strip(),
    }
