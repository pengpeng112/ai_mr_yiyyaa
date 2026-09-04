# -*- coding: utf-8 -*-
"""医保插件测试（039 T5 / §12.1 Insurance）。"""

import pytest

from prearchive.insurance import InsuranceContext
from prearchive.insurance.deterministic import DeterministicCodingPlugin
from prearchive.insurance.noop import NoopInsurancePlugin
from prearchive.insurance.opendrg_adapter import OpenDRGAdapter, build_insurance_plugin


def test_noop_returns_disabled():
    plugin = NoopInsurancePlugin()
    assert plugin.validate_configuration() == []
    result = plugin.evaluate(InsuranceContext())
    assert result.status == "disabled"
    assert result.plugin_code == "noop"


def test_deterministic_missing_principal_diagnosis():
    plugin = DeterministicCodingPlugin()
    ctx = InsuranceContext(patient_id="P1", visit_number="1")
    result = plugin.evaluate(ctx)
    assert result.status == "warn"
    codes = [d["code"] for d in result.diagnostics]
    assert "principal_diagnosis_missing" in codes


def test_deterministic_format_and_duplicates():
    plugin = DeterministicCodingPlugin()
    ctx = InsuranceContext(
        principal_diagnosis="J18.9",
        secondary_diagnoses=["E11", "E11", "I10"],
        principal_surgery="",
        secondary_surgeries=["47.09"],
    )
    result = plugin.evaluate(ctx)
    codes = [d["code"] for d in result.diagnostics]
    assert "principal_surgery_missing" in codes
    assert "duplicate_codes" in codes
    assert result.status == "warn"


def test_deterministic_pass_when_clean():
    plugin = DeterministicCodingPlugin()
    ctx = InsuranceContext(principal_diagnosis="J18.9",
                           secondary_diagnoses=["I10"],
                           principal_surgery="47.09")
    result = plugin.evaluate(ctx)
    assert result.status == "pass"
    assert result.diagnostics == []


def test_deterministic_missing_fields_unknown():
    plugin = DeterministicCodingPlugin()
    result = plugin.evaluate(InsuranceContext(
        principal_diagnosis="J18.9",
        missing_fields=["birth_weight_grams"]))
    assert result.status == "unknown"


def test_deterministic_invalid_regex_config_reported():
    plugin = DeterministicCodingPlugin({"icd_pattern": "([bad"})
    problems = plugin.validate_configuration()
    assert problems and problems[0]["level"] == "error"


def test_opendrg_blocked_without_license():
    adapter = OpenDRGAdapter({"enabled": True, "license_verified": False})
    problems = adapter.validate_configuration()
    assert any(p["level"] == "error" and "license" in p["message"] for p in problems)
    result = adapter.evaluate(InsuranceContext())
    assert result.status == "unknown"
    assert any(d["code"] == "opendrg_blocked" for d in result.diagnostics)


def test_opendrg_disabled_by_default():
    adapter = OpenDRGAdapter({})
    assert adapter.evaluate(InsuranceContext()).status == "disabled"


def test_build_plugin_defaults_noop_and_fail_open():
    assert isinstance(build_insurance_plugin({}), NoopInsurancePlugin)
    assert isinstance(build_insurance_plugin({"insurance_qc": {"enabled": False}}),
                      NoopInsurancePlugin)
    deterministic = build_insurance_plugin({
        "insurance_qc": {"enabled": True, "plugin": "deterministic"}})
    assert isinstance(deterministic, DeterministicCodingPlugin)
    assert deterministic.evaluate(InsuranceContext()).plugin_code == "deterministic"


def test_config_validation_forces_disabled_without_year():
    """insurance_qc.enabled=true 但年度未配置 → 配置校验强制视为关闭。"""
    from prearchive.config import ConfigError, validate_config
    config = {
        "service": {"poll_interval_seconds": 300, "batch_limit": 10},
        "sources": {name: {"type": "oracle"} for name in (
            "jhemr", "his", "sm", "lis", "paperless", "pacs", "es", "bl",
            "xt", "xd", "dcn", "qgj", "his_base")},
        "rule_registry": {"mode": "file"},
        "result_delivery": {"enabled": False},
        "insurance_qc": {"enabled": True, "plugin": "deterministic",
                         "ruleset_year": ""},
    }
    validated = validate_config(config)
    assert validated["insurance_qc"]["enabled"] is False

    config["insurance_qc"]["plugin"] = "opendrg"
    config["insurance_qc"]["ruleset_year"] = "2026"
    config["insurance_qc"]["opendrg"] = {"license_verified": False}
    with pytest.raises(ConfigError, match="license_verified"):
        validate_config(config)
