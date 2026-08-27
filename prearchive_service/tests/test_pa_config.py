# -*- coding: utf-8 -*-
"""配置模块单测：加载/默认合并/Fernet 加解密/凭据解析。"""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from prearchive.config import (
    ConfigError,
    DEFAULTS,
    decrypt_value,
    encrypt_value,
    get_fernet,
    load_config,
    validate_config,
)

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.json"


def test_example_config_loads_and_merges_defaults():
    config = load_config(EXAMPLE)
    assert config["service"]["poll_interval_seconds"] == 300
    assert config["service"]["batch_limit"] == 100
    assert config["sources"]["lis"]["type"] == "mssql"
    # 占位符不能通过密钥校验
    with pytest.raises(ConfigError):
        get_fernet(config)


def test_example_config_has_no_real_credentials():
    text = EXAMPLE.read_text(encoding="utf-8")
    for key in ("password_enc", "secret_key_enc", "shared_token", "host"):
        pass
    # 所有凭据/地址字段都应为 <...> 占位符
    import json

    data = json.loads(text)
    sources = data["sources"]
    for name, src in sources.items():
        assert str(src["host"]).startswith("<"), f"{name}.host 必须占位"
        assert str(src["password_enc"]).startswith("<"), f"{name}.password_enc 必须占位"
    assert data["api"]["shared_token"].startswith("<")


def test_validate_config_rejects_bad_interval():
    bad = {"service": {"poll_interval_seconds": 0}}
    with pytest.raises(ConfigError):
        validate_config(bad)
    bad2 = {"service": {"poll_interval_seconds": 30, "batch_limit": -1}}
    with pytest.raises(ConfigError):
        validate_config(bad2)


def test_validate_config_rejects_unknown_source_type():
    bad = {"service": {"poll_interval_seconds": 60, "batch_limit": 10},
           "sources": {name: {"type": "mysql"} for name in ("jhemr", "his", "sm", "lis")}}
    with pytest.raises(ConfigError):
        validate_config(bad)


def test_missing_config_file():
    with pytest.raises(ConfigError):
        load_config("no/such/file.json")


def test_fernet_roundtrip():
    key = Fernet.generate_key().decode("ascii")
    fernet = Fernet(key)
    token = encrypt_value(fernet, "s3cret-口令")
    assert token.startswith("enc:v1:")
    assert "s3cret" not in token
    assert decrypt_value(fernet, token) == "s3cret-口令"


def test_fernet_wrong_key_rejected():
    token = encrypt_value(Fernet(Fernet.generate_key()), "secret")
    other = Fernet(Fernet.generate_key())
    with pytest.raises(ConfigError):
        decrypt_value(other, token)


def test_decrypt_placeholder_rejected():
    fernet = Fernet(Fernet.generate_key())
    with pytest.raises(ConfigError):
        decrypt_value(fernet, "<ENC_PASSWORD_PLACEHOLDER>")


def test_get_fernet_env_override(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("PREARCHIVE_SECRET_KEY", key)
    fernet = get_fernet({"security": {"secret_key": "ignored"}})
    assert encrypt_value(fernet, "x").startswith("enc:v1:")
