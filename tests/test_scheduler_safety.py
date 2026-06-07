"""Tests for scheduler safety: config resolution and empty audit type handling."""

from __future__ import annotations

import pytest

from app.scheduler import _resolve_scheduler_cfg, _resolve_audit_run_mode


class TestResolveAuditRunMode:
    def test_daily_default(self):
        assert _resolve_audit_run_mode({}) == "daily_increment"

    def test_explicit_daily(self):
        assert _resolve_audit_run_mode({"audit_run_mode": "daily_increment"}) == "daily_increment"

    def test_explicit_discharge(self):
        assert _resolve_audit_run_mode({"audit_run_mode": "discharge_final"}) == "discharge_final"

    def test_invalid_falls_back(self):
        assert _resolve_audit_run_mode({"audit_run_mode": "unknown"}) == "daily_increment"


class TestResolveSchedulerCfgDischarge:
    def test_discharge_with_config_returns_it(self):
        config = {
            "scheduler_discharge": {
                "enabled": True,
                "audit_run_mode": "discharge_final",
                "audit_type_codes": ["progress_vs_nursing", "jyjc_vs_bcnursing"],
                "dept_filter": ["020103"],
            }
        }
        result = _resolve_scheduler_cfg(config, "discharge_final")
        assert result["enabled"] is True
        assert result["audit_type_codes"] == ["progress_vs_nursing", "jyjc_vs_bcnursing"]
        assert result["dept_filter"] == ["020103"]

    def test_discharge_without_config_does_not_fallback_to_legacy(self):
        config = {
            "scheduler": {
                "enabled": True,
                "audit_run_mode": "daily_increment",
                "audit_type_codes": ["old_legacy_type"],
                "dept_filter": ["030101"],
            }
        }
        result = _resolve_scheduler_cfg(config, "discharge_final")
        assert result["audit_run_mode"] == "discharge_final"
        assert result["audit_type_codes"] == ["progress_vs_nursing"]
        assert result["dept_filter"] == []
        assert result.get("enabled") is False

    def test_discharge_safe_default_has_progress_vs_nursing(self):
        config = {}
        result = _resolve_scheduler_cfg(config, "discharge_final")
        assert result["audit_type_codes"] == ["progress_vs_nursing"]


class TestResolveSchedulerCfgDaily:
    def test_daily_with_config_returns_it(self):
        config = {
            "scheduler_daily": {
                "enabled": True,
                "audit_run_mode": "daily_increment",
                "audit_type_codes": ["progress_vs_nursing"],
                "dept_filter": ["020103"],
            }
        }
        result = _resolve_scheduler_cfg(config, "daily_increment")
        assert result["enabled"] is True
        assert result["audit_type_codes"] == ["progress_vs_nursing"]

    def test_daily_without_scheduler_daily_falls_back_to_legacy(self):
        config = {
            "scheduler": {
                "enabled": True,
                "cron": "0 6 * * *",
                "audit_type_codes": ["legacy_type"],
            }
        }
        result = _resolve_scheduler_cfg(config, "daily_increment")
        assert result["enabled"] is True
        assert result["audit_type_codes"] == ["legacy_type"]

    def test_daily_no_config_at_all_returns_empty(self):
        result = _resolve_scheduler_cfg({}, "daily_increment")
        assert result == {}
