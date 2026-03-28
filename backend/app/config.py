"""
配置读取模块 —— 环境变量 + config.json + SQLite
"""
import os
import json
import base64
import logging
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

CONFIG_DIR = os.getenv("CONFIG_DIR", "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DATA_DIR = os.getenv("DATA_DIR", "data")
DB_PATH = os.path.join(DATA_DIR, "med_audit.db")
LOG_DIR = os.getenv("LOG_DIR", "logs")

# ---- 加密工具 ----
_SECRET_KEY = os.getenv("SECRET_KEY", "default-dev-key-change-in-prod")


def _get_fernet() -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"med-audit-salt-v1",
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(_SECRET_KEY.encode()))
    return Fernet(key)


def encrypt_value(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_value(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()


def mask_secret(value: str, show: int = 4) -> str:
    if not value or len(value) <= show:
        return "****"
    return value[:show] + "*" * (len(value) - show)


# ---- JSON 配置文件读写 ----
_DEFAULT_CONFIG = {
    "oracle": {
        "host": "10.255.255.20",
        "port": 1521,
        "service_name": "orcl",
        "username": "",
        "password_enc": "",
    },
    "dify": {
        "base_url": "http://10.255.255.10/v1",
        "api_key_enc": "",
        "workflow_input_variable": "mr_txt",
        "workflow_output_key": "aa",
        "user_identifier": "med-audit-system",
        "timeout_seconds": 90,
        "extra_inputs": {},
    },
    "departments": {
        "mode": "include",  # include | exclude
        "list": [],
    },
    "scheduler": {
        "enabled": True,
        "cron": "0 6 * * *",  # 每天早上6:00
    },
    "push": {
        "interval_ms": 500,
        "max_retry": 3,
        "batch_size": 50,
    },
    "notify": {
        "channels": [],  # list of {type, enabled, config}
    },
    "sql": {
        "main_query": (
            "SELECT\n"
            "    a.患者ID, a.次数, a.住院号, a.患者姓名, a.性别, a.出生日期, a.入院日期,\n"
            "    a.BED_NO AS 床号, a.入院诊断, a.入院病情,\n"
            "    a.护理级别 AS 医嘱护理级别, a.所在科室名称, a.管床医生,\n"
            "    b.病历标题时间, b.病历名称, b.创建人 AS 病历创建人, b.病历内容,\n"
            "    c.护理记录时间, c.护理单类型, c.记录人 AS 护理记录人,\n"
            "    c.体温, c.心率脉搏, c.呼吸, c.血压, c.血氧饱和度, c.血糖, c.意识神志,\n"
            "    c.氧疗_鼻导管, c.氧疗_面罩,\n"
            "    c.入量_名称, c.入量_途径, c.入量_量, c.出量_名称, c.出量_量, c.尿量,\n"
            "    c.皮肤情况, c.刀口情况, c.管道护理, c.高危风险,\n"
            "    c.病情观察及护理措施, c.护士签名\n"
            "FROM jhemr.v_zybr a\n"
            "LEFT JOIN jhemr.v_bcjl b ON a.患者ID = b.患者ID AND a.次数 = b.次数\n"
            "LEFT JOIN ydhl.v_hljl c ON c.患者ID = b.患者ID || '_' || b.次数\n"
            "    AND TO_CHAR(b.病历标题时间, 'yyyy-mm-dd') = TO_CHAR(c.护理记录时间, 'yyyy-mm-dd')\n"
            "WHERE {dept_filter}\n"
            "  AND TO_CHAR(b.病历标题时间, 'yyyy-mm-dd') = :query_date\n"
            "ORDER BY a.患者ID, a.次数, b.病历标题时间, c.护理记录时间"
        ),
        "dept_column": "所在科室名称",
    },
}


def _ensure_dirs():
    for d in (CONFIG_DIR, DATA_DIR, LOG_DIR):
        Path(d).mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    _ensure_dirs()
    if not os.path.exists(CONFIG_FILE):
        save_config(_DEFAULT_CONFIG)
        return _DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict):
    _ensure_dirs()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def update_section(section: str, data: dict):
    cfg = load_config()
    cfg[section] = data
    save_config(cfg)
    return cfg[section]
