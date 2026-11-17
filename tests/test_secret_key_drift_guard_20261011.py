"""W7：启动期密钥金丝雀。坏密文必须拒绝启动，消息含 SECRET_KEY_DRIFT，且不回显密文。"""
import pytest
from cryptography.fernet import Fernet

from app.config import encrypt_value, validate_runtime_config

_DRIFT_TEXT = "SECRET_KEY 与密文不匹配（疑似密钥漂移），拒绝启动"


def _bad_token() -> str:
    """另一把密钥发出的令牌，模拟 SECRET_KEY 漂移。明文仅为合成标记。"""
    return Fernet(Fernet.generate_key()).encrypt(b"w7-synthetic").decode()


def test_bad_ciphertext_refuses_startup_without_echoing_token():
    token = _bad_token()
    with pytest.raises(RuntimeError) as exc_info:
        validate_runtime_config({"oracle": {"password_enc": token}})
    message = str(exc_info.value)
    assert "SECRET_KEY_DRIFT" in message
    assert _DRIFT_TEXT in message
    assert token not in message
    assert exc_info.value.__cause__ is None


def test_good_ciphertext_passes_startup_check():
    token = encrypt_value("w7-canary")
    warnings = validate_runtime_config({"dify": {"api_key_enc": token}})
    assert isinstance(warnings, list)


def test_no_ciphertext_skips_startup_check():
    warnings = validate_runtime_config({"data_source": {"type": "oracle"}})
    assert isinstance(warnings, list)
    warnings = validate_runtime_config(
        {"oracle": {"password_enc": ""}, "dify": {"api_key_enc": "   "}}
    )
    assert isinstance(warnings, list)
