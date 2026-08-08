"""006: Dify 节点池 resolver 与合并契约测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import encrypt_value
from app.services.bulk_push_executor import BulkPushExecutor
from app.services.config_parser import ConfigParser
from app.services.push_executor import PushConfig


def _cfg_with_targets(targets, **pool_kwargs):
    dify = {
        "base_url": "http://global-dify/v1",
        "api_key_enc": encrypt_value("global-key"),
        "workflow_input_variable": "mr_txt",
        "workflow_output_key": "aa",
        "user_identifier": "med-audit-system",
        "timeout_seconds": 90,
        "extra_inputs": {},
        "target_strategy": pool_kwargs.get("target_strategy", "round_robin"),
        "circuit_breaker_failures": pool_kwargs.get("circuit_breaker_failures", 3),
        "circuit_breaker_seconds": pool_kwargs.get("circuit_breaker_seconds", 60),
        "targets": targets,
    }
    return {"dify": dify}


def _audit_type(code="progress_vs_nursing", output_key="hcjg", mr_type="病程与护理核查"):
    return SimpleNamespace(
        code=code,
        name=code,
        dify=SimpleNamespace(
            model_dump=lambda: {
                "base_url": "http://audit-type-dify/v1",
                "api_key_enc": encrypt_value("audit-key"),
                "workflow_input_variable": "mr_txt",
                "workflow_output_key": output_key,
                "user_identifier": "med-audit-system",
                "timeout_seconds": 120,
                "extra_inputs": {"mr_type": mr_type},
                "full_debug_log": False,
            }
        ),
        payload={"builder": "generic_multi_source"},
    )


def test_resolve_empty_targets_uses_serial_base():
    config = _cfg_with_targets([])
    pool = ConfigParser.resolve_dify_target_pool(config, _audit_type())
    assert pool["use_bulk"] is False
    assert pool["targets"] == []
    assert pool["pool_unavailable"] is False
    assert pool["base_config"]["workflow_output_key"] == "hcjg"
    assert pool["base_config"]["extra_inputs"]["mr_type"] == "病程与护理核查"


def test_resolve_two_targets_uses_bulk_and_strategy():
    targets = [
        {
            "name": "a",
            "base_url": "http://dify-a/v1",
            "api_key_enc": encrypt_value("k1"),
            "timeout_seconds": 30,
            "weight": 1,
            "enabled": True,
        },
        {
            "name": "b",
            "base_url": "http://dify-b/v1",
            "api_key_enc": encrypt_value("k2"),
            "timeout_seconds": 40,
            "weight": 2,
            "enabled": True,
        },
    ]
    config = _cfg_with_targets(targets, target_strategy="weighted_random", circuit_breaker_seconds=90)
    pool = ConfigParser.resolve_dify_target_pool(config, _audit_type())
    assert pool["use_bulk"] is True
    assert pool["enabled_target_count"] == 2
    assert pool["strategy"] == "weighted_random"
    assert pool["circuit_breaker_seconds"] == 90
    assert all("api_key" in t and "api_key_enc" not in t for t in pool["targets"])


def test_target_does_not_override_mr_type_or_io_vars():
    targets = [
        {
            "name": "a",
            "base_url": "http://dify-a/v1",
            "api_key_enc": encrypt_value("k1"),
            "timeout_seconds": 30,
            "weight": 1,
            "enabled": True,
            # 恶意字段：不得进入端点覆盖
            "workflow_output_key": "should_not_apply",
            "workflow_input_variable": "should_not_apply",
            "extra_inputs": {"mr_type": "hacked"},
        }
    ]
    config = _cfg_with_targets(targets)
    audit = _audit_type(output_key="hcjg", mr_type="入院与首次病程核查")
    pool = ConfigParser.resolve_dify_target_pool(config, audit)
    base = pool["base_config"]
    assert base["workflow_output_key"] == "hcjg"
    assert base["workflow_input_variable"] == "mr_txt"
    assert base["extra_inputs"]["mr_type"] == "入院与首次病程核查"

    executor = BulkPushExecutor(
        dify_config=base,
        dify_targets=pool["targets"],
        target_strategy=pool["strategy"],
    )
    # 选中节点后配置仍保留 base 的 input/output
    picked = executor._pick_target()
    assert picked.config["workflow_output_key"] == "hcjg"
    assert picked.config["workflow_input_variable"] == "mr_txt"
    assert picked.config["extra_inputs"]["mr_type"] == "入院与首次病程核查"
    assert picked.config["base_url"].startswith("http://dify-a")
    assert picked.config["api_key"] == "k1"


def test_single_patient_only_one_target_call(monkeypatch):
    targets = [
        {
            "name": "a",
            "base_url": "http://dify-a/v1",
            "api_key": "k1",
            "timeout_seconds": 30,
            "weight": 1,
            "enabled": True,
        },
        {
            "name": "b",
            "base_url": "http://dify-b/v1",
            "api_key": "k2",
            "timeout_seconds": 30,
            "weight": 1,
            "enabled": True,
        },
    ]
    executor = BulkPushExecutor(
        dify_config={
            "base_url": "http://default/v1",
            "api_key": "default",
            "workflow_input_variable": "mr_txt",
            "workflow_output_key": "aa",
            "timeout_seconds": 30,
        },
        dify_targets=targets,
        target_strategy="round_robin",
        empty_retry_max=0,
    )
    calls = []

    def _fake_push(dify_input, cfg, patient_id, **kwargs):
        calls.append((patient_id, cfg.get("name") or cfg.get("base_url"), cfg.get("base_url")))
        return {
            "status": "success",
            "result": {"aa": '{"version":"2.0","dimensions":[],"overall_conclusion":"ok"}'},
            "parsed_output": {"parse_success": False},
            "workflow_run_id": "wr",
            "elapsed_ms": 1,
            "inconsistency": False,
            "severity": "",
            "risk_score": 0,
        }

    monkeypatch.setattr("app.services.bulk_push_executor.push_to_dify", _fake_push)
    # 避免真实落库路径：直接测 empty_retry 单次选择
    result = executor._push_with_empty_retry("payload", "p001")
    assert result["status"] == "success"
    assert len(calls) == 1


def test_configured_enabled_but_no_usable_key_is_pool_unavailable():
    targets = [
        {
            "name": "broken",
            "base_url": "http://dify-a/v1",
            "api_key_enc": "not-a-valid-fernet-token",
            "timeout_seconds": 30,
            "weight": 1,
            "enabled": True,
        }
    ]
    config = _cfg_with_targets(targets)
    pool = ConfigParser.resolve_dify_target_pool(config, None)
    assert pool["configured_enabled_count"] == 1
    assert pool["enabled_target_count"] == 0
    assert pool["pool_unavailable"] is True
    assert pool["error_code"] == "dify_target_pool_unavailable"
    assert pool["use_bulk"] is False


def test_endpoint_only_overlay_strips_io_fields():
    overlay = ConfigParser.endpoint_only_target_overlay(
        {
            "name": "a",
            "base_url": "http://x/v1",
            "api_key": "k",
            "workflow_output_key": "aa",
            "extra_inputs": {"mr_type": "x"},
            "weight": 2,
        }
    )
    assert "workflow_output_key" not in overlay
    assert "extra_inputs" not in overlay
    assert overlay["name"] == "a"
    assert overlay["weight"] == 2
