"""Tests for runtime_config_resolver — Phase 1 read-only config interpretation.

All tests use hand-crafted config dicts; no real config.json or database
access.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.runtime_config_resolver import (
    resolve_run_mode_config,
    resolve_scheduler_config,
    resolve_dept_scope,
    resolve_audit_type_config,
    resolve_dify_target,
)


# ---- shared test fixtures ---------------------------------------------------


def _base_config() -> dict:
    return {
        "data_source": {"type": "oracle"},
        "scheduler": {"enabled": True, "cron": "0 6 * * *"},
        "scheduler_daily": {
            "enabled": True,
            "cron": "0 10 * * *",
            "schedule_mode": "daily",
            "daily_time": "10:00",
            "audit_run_mode": "daily_increment",
            "audit_type_codes": ["progress_vs_nursing"],
            "dept_filter": ["020103"],
        },
        "scheduler_discharge": {
            "enabled": True,
            "cron": "13 14 * * *",
            "schedule_mode": "daily",
            "daily_time": "14:13",
            "audit_run_mode": "discharge_final",
            "audit_type_codes": [
                "progress_vs_nursing",
                "jyjc_vs_bcnursing",
                "syssvsscbc",
            ],
            "dept_filter": ["020103"],
        },
        "dify": {
            "base_url": "http://10.255.255.10/v1",
            "api_key_enc": "encrypted-key",
            "workflow_input_variable": "mr_txt",
        },
        "audit_types": [
            {
                "code": "progress_vs_nursing",
                "name": "病程 vs 护理",
                "enabled": True,
                "default_for_schedule": True,
                "sources": {"primary": {"type": "sql", "required": True}},
                "payload": {"builder": "generic_multi_source"},
                "dify": {
                    "base_url": "http://dify-audit/v1",
                    "api_key_enc": "at-key",
                    "workflow_input_variable": "mr_txt",
                },
            },
            {
                "code": "jyjc_vs_bcnursing",
                "name": "检验检查 vs 病程护理(多源)",
                "enabled": True,
                "default_for_schedule": True,
                "sources": {
                    "lab": {"type": "sql", "required": True},
                    "exam": {"type": "sql", "required": True},
                    "progress": {"type": "sql", "required": True},
                    "nursing": {"type": "sql", "required": True},
                },
                "payload": {"builder": "lab_exam_structured_progress_nursing"},
            },
            {
                "code": "syssvsscbc",
                "name": "病案首页手术 vs 首次病程",
                "enabled": True,
                "default_for_schedule": True,
                "sources": {"frontpage": {"type": "sql", "required": True}, "first_progress": {"type": "sql", "required": True}},
                "payload": {"builder": "frontpage_surgery_first_progress"},
            },
            {
                "code": "orders_vs_progress",
                "name": "医嘱 vs 病程",
                "enabled": False,
                "default_for_schedule": False,
                "sources": {"orders": {"type": "sql", "required": True}, "progress": {"type": "sql", "required": True}},
                "payload": {"builder": "orders_progress_stub"},
            },
        ],
    }


# ---- resolve_run_mode_config -------------------------------------------------


class TestResolveRunModeConfig:
    def test_daily_increment(self):
        cfg = _base_config()
        result = resolve_run_mode_config(cfg, "daily_increment")
        assert result["run_mode"] == "daily_increment"
        assert result["calls_dify"] is True
        assert result["writes_push_log"] is True
        assert result["writes_scheduler_history"] is True
        assert result["triggers_relay_alert"] is True
        assert result["source_record_key_namespace"] is None
        assert result["dept_scope"] == "daily_increment"

    def test_discharge_final_namespace(self):
        cfg = _base_config()
        result = resolve_run_mode_config(cfg, "discharge_final")
        assert result["source_record_key_namespace"] == "mode::discharge_final"

    def test_precheck_is_readonly(self):
        cfg = _base_config()
        result = resolve_run_mode_config(cfg, "precheck")
        assert result["calls_dify"] is False
        assert result["writes_push_log"] is False
        assert result["writes_scheduler_history"] is False
        assert result["triggers_relay_alert"] is False

    def test_unknown_run_mode_raises(self):
        cfg = _base_config()
        with pytest.raises(ValueError, match="Unknown run_mode"):
            resolve_run_mode_config(cfg, "nonexistent")

    def test_result_is_new_dict(self):
        cfg = _base_config()
        result = resolve_run_mode_config(cfg, "discharge_final")
        result["calls_dify"] = None
        r2 = resolve_run_mode_config(cfg, "discharge_final")
        assert r2["calls_dify"] is True


# ---- resolve_scheduler_config ------------------------------------------------


class TestResolveSchedulerConfig:
    def test_daily_scheduler(self):
        cfg = _base_config()
        result = resolve_scheduler_config(cfg, "scheduler_daily")
        assert result["scheduler_key"] == "scheduler_daily"
        assert result["enabled"] is True
        assert result["run_mode"] == "daily_increment"
        assert result["dept_scope"] == "daily_increment"
        assert result["audit_type_codes"] == ["progress_vs_nursing"]
        assert result["dept_filter"] == ["020103"]

    def test_discharge_scheduler(self):
        cfg = _base_config()
        result = resolve_scheduler_config(cfg, "scheduler_discharge")
        assert result["scheduler_key"] == "scheduler_discharge"
        assert result["run_mode"] == "discharge_final"
        assert result["dept_scope"] == "discharge_final"

    def test_empty_audit_type_codes_not_expanded(self):
        cfg = _base_config()
        cfg["scheduler_daily"]["audit_type_codes"] = []
        result = resolve_scheduler_config(cfg, "scheduler_daily")
        assert result["audit_type_codes"] == []

    def test_dept_filter_empty_preserved(self):
        cfg = _base_config()
        cfg["scheduler_discharge"]["dept_filter"] = []
        result = resolve_scheduler_config(cfg, "scheduler_discharge")
        assert result["dept_filter"] == []

    def test_dept_filter_none_normalized(self):
        cfg = _base_config()
        del cfg["scheduler_daily"]["dept_filter"]
        result = resolve_scheduler_config(cfg, "scheduler_daily")
        assert result["dept_filter"] == []

    def test_unknown_scheduler_raises(self):
        cfg = _base_config()
        with pytest.raises(ValueError, match="Unknown scheduler_key"):
            resolve_scheduler_config(cfg, "scheduler_fake")

    def test_result_does_not_mutate_config(self):
        cfg = _base_config()
        original = deepcopy(cfg)
        resolve_scheduler_config(cfg, "scheduler_daily")
        assert cfg == original

    def test_run_mode_falls_back_to_default(self):
        cfg = _base_config()
        del cfg["scheduler_daily"]["audit_run_mode"]
        result = resolve_scheduler_config(cfg, "scheduler_daily")
        assert result["run_mode"] == "daily_increment"


# ---- resolve_dept_scope -----------------------------------------------------


class TestResolveDeptScope:
    def test_from_legacy_daily(self):
        cfg = _base_config()
        result = resolve_dept_scope(cfg, "daily_increment")
        assert result["scope_name"] == "daily_increment"
        assert result["dept_codes"] == ["020103"]
        assert result["field_semantics"] == "current_dept"

    def test_from_legacy_discharge(self):
        cfg = _base_config()
        result = resolve_dept_scope(cfg, "discharge_final")
        assert result["scope_name"] == "discharge_final"
        assert result["dept_codes"] == ["020103"]
        assert result["field_semantics"] == "discharge_dept"

    def test_empty_dept_filter_preserved(self):
        cfg = _base_config()
        cfg["scheduler_daily"]["dept_filter"] = []
        result = resolve_dept_scope(cfg, "daily_increment")
        assert result["dept_codes"] == []

    def test_prefers_new_dept_scopes(self):
        cfg = _base_config()
        cfg["dept_scopes"] = {
            "daily_increment": {
                "dept_codes": ["030101"],
                "field_semantics": "custom_dept",
            }
        }
        result = resolve_dept_scope(cfg, "daily_increment")
        assert result["dept_codes"] == ["030101"]
        assert result["field_semantics"] == "custom_dept"

    def test_override_takes_precedence(self):
        cfg = _base_config()
        result = resolve_dept_scope(cfg, "discharge_final", override=["040201"])
        assert result["dept_codes"] == ["040201"]

    def test_patient_census_extra_fields(self):
        cfg = _base_config()
        result = resolve_dept_scope(cfg, "patient_census")
        assert result["masking_required"] is True
        assert result["max_limit"] == 500

    def test_unknown_scope_raises(self):
        cfg = _base_config()
        with pytest.raises(ValueError, match="Unknown dept_scope"):
            resolve_dept_scope(cfg, "fake_scope")

    def test_does_not_mutate_config(self):
        cfg = _base_config()
        original = deepcopy(cfg)
        resolve_dept_scope(cfg, "daily_increment")
        assert cfg == original


# ---- resolve_audit_type_config -----------------------------------------------


class TestResolveAuditTypeConfig:
    def test_found_active_type(self):
        cfg = _base_config()
        result = resolve_audit_type_config(cfg, "progress_vs_nursing")
        assert result["code"] == "progress_vs_nursing"
        assert result["name"] == "病程 vs 护理"
        assert result["enabled"] is True

    def test_disabled_type_returned_without_error(self):
        cfg = _base_config()
        result = resolve_audit_type_config(cfg, "orders_vs_progress")
        assert result["code"] == "orders_vs_progress"
        assert result["enabled"] is False

    def test_multi_source_audit_type(self):
        cfg = _base_config()
        result = resolve_audit_type_config(cfg, "jyjc_vs_bcnursing")
        sources = result.get("sources", {})
        assert "lab" in sources
        assert "exam" in sources
        assert "progress" in sources
        assert "nursing" in sources

    def test_unknown_audit_type_raises(self):
        cfg = _base_config()
        with pytest.raises(ValueError, match="Unknown audit_type"):
            resolve_audit_type_config(cfg, "not_exists")

    def test_no_discharge_suffix_types(self):
        cfg = _base_config()
        with pytest.raises(ValueError, match="Unknown audit_type"):
            resolve_audit_type_config(cfg, "progress_vs_nursing_discharge")

    def test_result_is_deep_copy(self):
        cfg = _base_config()
        result = resolve_audit_type_config(cfg, "progress_vs_nursing")
        result["enabled"] = False
        original = resolve_audit_type_config(cfg, "progress_vs_nursing")
        assert original["enabled"] is True

    def test_does_not_mutate_config(self):
        cfg = _base_config()
        original = deepcopy(cfg)
        resolve_audit_type_config(cfg, "progress_vs_nursing")
        assert cfg == original


# ---- resolve_dify_target ----------------------------------------------------


class TestResolveDifyTarget:
    def test_audit_type_level_target(self):
        cfg = _base_config()
        result = resolve_dify_target(cfg, "progress_vs_nursing")
        assert result["target_source"] == "audit_type"
        assert result["base_url"] == "http://dify-audit/v1"
        assert result["has_api_key"] is True
        assert result["workflow_input_variable"] == "mr_txt"

    def test_global_fallback(self):
        cfg = _base_config()
        # jy jc_vs_bcnursing has no per-audit-type dify section
        result = resolve_dify_target(cfg, "jyjc_vs_bcnursing")
        assert result["target_source"] == "global"
        assert result["base_url"] == "http://10.255.255.10/v1"
        assert result["has_api_key"] is True

    def test_no_plaintext_api_key(self):
        cfg = _base_config()
        result = resolve_dify_target(cfg, "progress_vs_nursing")
        assert "api_key" not in result
        assert "api_key_enc" not in result

    def test_no_api_key_when_missing(self):
        cfg = _base_config()
        cfg["dify"].pop("api_key_enc", None)
        cfg["dify"]["api_key"] = None
        result = resolve_dify_target(cfg, "jyjc_vs_bcnursing")
        assert result["has_api_key"] is False
