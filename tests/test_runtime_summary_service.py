"""Tests for runtime_summary_service — Phase 2.5 hardening.

All tests use hand-crafted config dicts; no real config.json, database,
or network access.
"""

from __future__ import annotations

from copy import deepcopy

from app.services.runtime_summary_service import (
    build_runtime_summary,
    _deep_scan_for_secrets,
    _source_uses_sql,
)


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
                "sort_order": 10,
                "sources": {"primary": {"type": "sql", "required": True, "query_sql": "SELECT ... FROM ..."}},
                "payload": {"builder": "generic_multi_source"},
                "dify": {
                    "base_url": "http://dify-audit/v1",
                    "api_key_enc": "at-key",
                    "workflow_input_variable": "mr_txt",
                },
                "response": {"dimension_path": "$.dimensions", "conclusion_path": "$.overall_conclusion"},
                "display": {"blocks": []},
                "group_key": ["patient_id", "visit_number"],
            },
            {
                "code": "jyjc_vs_bcnursing",
                "name": "检验检查 vs 病程护理",
                "enabled": True,
                "default_for_schedule": True,
                "sources": {
                    "lab": {"type": "sql", "required": True, "query_sql": "SELECT ..."},
                    "exam": {"type": "sql", "required": True, "query_sql": "SELECT ..."},
                    "progress": {"type": "sql", "required": True, "query_sql": "SELECT ..."},
                    "nursing": {"type": "sql", "required": True, "query_sql": "SELECT ..."},
                },
                "payload": {"builder": "lab_exam_structured_progress_nursing"},
            },
            {
                "code": "syssvsscbc",
                "name": "病案首页手术 vs 首次病程",
                "enabled": True,
                "default_for_schedule": True,
                "sources": {"frontpage": {"type": "sql", "required": True, "query_sql": "SELECT ..."}, "first_progress": {"type": "sql", "required": True, "query_sql": "SELECT ..."}},
                "payload": {"builder": "frontpage_surgery_first_progress"},
            },
            {
                "code": "orders_vs_progress",
                "name": "医嘱 vs 病程",
                "enabled": False,
                "default_for_schedule": False,
                "sources": {"orders": {"type": "sql", "required": True, "query_sql": "SELECT ..."}, "progress": {"type": "sql", "required": True, "query_sql": "SELECT ..."}},
                "payload": {"builder": "orders_progress_stub"},
            },
        ],
    }


# ---- top-level structure ----------------------------------------------------


class TestTopLevelStructure:
    def test_has_all_top_level_keys(self):
        result = build_runtime_summary(_base_config())
        assert "run_modes" in result
        assert "schedulers" in result
        assert "dept_scopes" in result
        assert "audit_types" in result
        assert "warnings" in result
        assert "meta" in result

    def test_meta_fields(self):
        result = build_runtime_summary(_base_config())
        meta = result["meta"]
        assert meta["readonly"] is True
        assert meta["secrets_masked"] is True
        assert meta["sql_included"] is False
        assert meta["config_shape"] == "legacy-compatible"


# ---- run_modes ---------------------------------------------------------------


class TestRunModes:
    def test_contains_four_modes(self):
        result = build_runtime_summary(_base_config())
        modes = result["run_modes"]
        assert "daily_increment" in modes
        assert "discharge_final" in modes
        assert "manual" in modes
        assert "precheck" in modes

    def test_precheck_is_readonly(self):
        result = build_runtime_summary(_base_config())
        precheck = result["run_modes"]["precheck"]
        assert precheck["calls_dify"] is False
        assert precheck["writes_push_log"] is False
        assert precheck["writes_scheduler_history"] is False
        assert precheck["triggers_relay_alert"] is False

    def test_daily_increment_flags(self):
        result = build_runtime_summary(_base_config())
        daily = result["run_modes"]["daily_increment"]
        assert daily["calls_dify"] is True
        assert daily["writes_push_log"] is True


# ---- schedulers --------------------------------------------------------------


class TestSchedulers:
    def test_preserves_empty_audit_type_codes(self):
        cfg = _base_config()
        cfg["scheduler_daily"]["audit_type_codes"] = []
        result = build_runtime_summary(cfg)
        assert result["schedulers"]["scheduler_daily"]["audit_type_codes"] == []

    def test_preserves_empty_discharge_audit_type_codes(self):
        cfg = _base_config()
        cfg["scheduler_discharge"]["audit_type_codes"] = []
        result = build_runtime_summary(cfg)
        assert result["schedulers"]["scheduler_discharge"]["audit_type_codes"] == []

    def test_scheduler_run_mode(self):
        result = build_runtime_summary(_base_config())
        assert result["schedulers"]["scheduler_daily"]["run_mode"] == "daily_increment"
        assert result["schedulers"]["scheduler_discharge"]["run_mode"] == "discharge_final"


# ---- dept_scopes -------------------------------------------------------------


class TestDeptScopes:
    def test_preserves_empty_dept_filter(self):
        cfg = _base_config()
        cfg["scheduler_daily"]["dept_filter"] = []
        result = build_runtime_summary(cfg)
        assert result["dept_scopes"]["daily_increment"]["dept_codes"] == []

    def test_has_four_scopes(self):
        result = build_runtime_summary(_base_config())
        scopes = result["dept_scopes"]
        assert "daily_increment" in scopes
        assert "discharge_final" in scopes
        assert "manual_default" in scopes
        assert "patient_census" in scopes


# ---- audit_types -------------------------------------------------------------


class TestAuditTypes:
    def test_includes_enabled_and_disabled(self):
        result = build_runtime_summary(_base_config())
        codes = [at["code"] for at in result["audit_types"]]
        assert "progress_vs_nursing" in codes
        assert "orders_vs_progress" in codes

    def test_omits_query_sql(self):
        result = build_runtime_summary(_base_config())
        for at in result["audit_types"]:
            def _has_key(obj, key):
                if isinstance(obj, dict):
                    if key in obj:
                        return True
                    for v in obj.values():
                        if _has_key(v, key):
                            return True
                elif isinstance(obj, list):
                    for item in obj:
                        if _has_key(item, key):
                            return True
                return False
            assert not _has_key(at, "query_sql"), f"query_sql found in audit type: {at['code']}"

    def test_omits_field_mapping(self):
        result = build_runtime_summary(_base_config())
        for at in result["audit_types"]:
            def _has_key(obj, key):
                if isinstance(obj, dict):
                    if key in obj:
                        return True
                    for v in obj.values():
                        if _has_key(v, key):
                            return True
                elif isinstance(obj, list):
                    for item in obj:
                        if _has_key(item, key):
                            return True
                return False
            assert not _has_key(at, "field_mapping"), f"field_mapping found in audit type: {at['code']}"

    def test_has_builder_and_source_keys(self):
        result = build_runtime_summary(_base_config())
        at = next(a for a in result["audit_types"] if a["code"] == "progress_vs_nursing")
        assert at["builder"] == "generic_multi_source"
        assert "primary" in at["source_keys"]

    def test_multi_source_audit_type(self):
        result = build_runtime_summary(_base_config())
        at = next(a for a in result["audit_types"] if a["code"] == "jyjc_vs_bcnursing")
        assert set(at["source_keys"]) == {"lab", "exam", "progress", "nursing"}
        assert set(at["required_source_keys"]) == {"lab", "exam", "progress", "nursing"}

    def test_disabled_audit_type_still_listed(self):
        result = build_runtime_summary(_base_config())
        at = next(a for a in result["audit_types"] if a["code"] == "orders_vs_progress")
        assert at["enabled"] is False

    def test_omits_secret_fields(self):
        cfg = _base_config()
        cfg["audit_types"][0]["dify"]["api_key"] = "plain-secret"
        cfg["dify"]["api_key"] = "global-plain"
        result = build_runtime_summary(cfg)
        at = next(a for a in result["audit_types"] if a["code"] == "progress_vs_nursing")
        secret_keys = {"api_key", "api_key_enc", "password", "password_enc", "secret_key", "secret_key_enc"}
        def _find_secrets(obj, depth=0):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in secret_keys:
                        return k
                    found = _find_secrets(v, depth + 1)
                    if found:
                        return found
            elif isinstance(obj, list):
                for item in obj:
                    found = _find_secrets(item, depth + 1)
                    if found:
                        return found
            return None
        assert _find_secrets(at) is None, f"Found secret key: {_find_secrets(at)}"
        dt = at["dify_target"]
        assert "api_key" not in dt
        assert "api_key_enc" not in dt
        assert dt["has_api_key"] is True

    def test_flags(self):
        result = build_runtime_summary(_base_config())
        at = next(a for a in result["audit_types"] if a["code"] == "progress_vs_nursing")
        assert at["flags"]["uses_sql"] is True
        assert at["flags"]["has_sensitive_secret"] is True
        assert at["flags"]["has_display_config"] is True


# ---- sources summary (Phase 2.5) --------------------------------------------


class TestSourcesSummary:
    def test_sources_summary_exists(self):
        result = build_runtime_summary(_base_config())
        at = next(a for a in result["audit_types"] if a["code"] == "jyjc_vs_bcnursing")
        assert "sources" in at
        assert isinstance(at["sources"], list)
        assert len(at["sources"]) == 4

    def test_sources_summary_omits_query_sql(self):
        result = build_runtime_summary(_base_config())
        at = next(a for a in result["audit_types"] if a["code"] == "progress_vs_nursing")
        for src in at["sources"]:
            assert "query_sql" not in src, f"query_sql key found in source: {src['key']}"

    def test_sources_summary_omits_field_mapping(self):
        result = build_runtime_summary(_base_config())
        at = next(a for a in result["audit_types"] if a["code"] == "progress_vs_nursing")
        for src in at["sources"]:
            flat = str(src)
            assert "field_mapping" not in flat

    def test_sources_summary_fields(self):
        result = build_runtime_summary(_base_config())
        at = next(a for a in result["audit_types"] if a["code"] == "progress_vs_nursing")
        src = at["sources"][0]
        assert src["key"] == "primary"
        assert src["type"] == "sql"
        assert src["required"] is True
        assert src["has_query_sql"] is True


# ---- uses_sql precision (Phase 2.5) -----------------------------------------


class TestUsesSql:
    def test_uses_sql_true_for_sql_source(self):
        result = build_runtime_summary(_base_config())
        at = next(a for a in result["audit_types"] if a["code"] == "progress_vs_nursing")
        assert at["flags"]["uses_sql"] is True

    def test_uses_sql_false_for_non_sql_source(self):
        cfg = _base_config()
        cfg["audit_types"].append({
            "code": "test_json_source",
            "name": "JSON Only",
            "enabled": False,
            "sources": {"api": {"type": "http", "required": True}},
            "payload": {"builder": "stub"},
        })
        result = build_runtime_summary(cfg)
        at = next(a for a in result["audit_types"] if a["code"] == "test_json_source")
        assert at["flags"]["uses_sql"] is False

    def test_source_uses_sql_helper(self):
        assert _source_uses_sql({"type": "sql"}) is True
        assert _source_uses_sql({"query_sql": "SELECT 1"}) is True
        assert _source_uses_sql({"type": "http"}) is False
        assert _source_uses_sql({}) is False


# ---- warning paths (Phase 2.5) ----------------------------------------------


class TestWarningPaths:
    def test_warning_paths_are_dot_notation(self):
        cfg = _base_config()
        cfg["scheduler_daily"]["audit_type_codes"] = []
        cfg["scheduler_daily"]["cron"] = ""
        result = build_runtime_summary(cfg)
        for w in result["warnings"]:
            path = w.get("path", "")
            assert "[" not in path, f"warning path contains brackets: {path}"
            assert " / " not in path, f"warning path contains slash: {path}"

    def test_dept_mismatch_has_related_path(self):
        cfg = _base_config()
        cfg["scheduler_daily"]["dept_filter"] = ["020103"]
        cfg["scheduler_discharge"]["dept_filter"] = ["030201"]
        result = build_runtime_summary(cfg)
        mismatch = [w for w in result["warnings"] if w["code"] == "dept_filter_mismatch"]
        assert len(mismatch) == 1
        assert mismatch[0]["path"] == "scheduler_daily.dept_filter"
        assert mismatch[0].get("related_path") == "scheduler_discharge.dept_filter"

    def test_dify_base_url_empty_has_related_path(self):
        cfg = _base_config()
        cfg["dify"]["base_url"] = ""
        cfg["audit_types"][0].pop("dify", None)
        result = build_runtime_summary(cfg)
        dify_warn = [w for w in result["warnings"] if w["code"] == "dify_base_url_empty"]
        assert len(dify_warn) >= 1
        assert dify_warn[0].get("related_path") == "dify.base_url"

    def test_workflow_input_variable_warning_path_per_type(self):
        cfg = _base_config()
        cfg["audit_types"][0]["dify"]["workflow_input_variable"] = "custom_input"
        result = build_runtime_summary(cfg)
        wiv_warn = [w for w in result["warnings"] if w["code"] == "workflow_input_variable_not_default"]
        assert len(wiv_warn) >= 1
        at_w = [w for w in wiv_warn if "progress_vs_nursing" in w.get("path", "")]
        assert len(at_w) == 1
        assert at_w[0]["path"] == "audit_types.progress_vs_nursing.dify.workflow_input_variable"

    def test_workflow_input_variable_warning_path_global(self):
        cfg = _base_config()
        # Remove any per-type setting, rely on global
        for at in cfg["audit_types"]:
            at.pop("dify", None)
        cfg["dify"]["workflow_input_variable"] = "global_input"
        result = build_runtime_summary(cfg)
        wiv_warn = [w for w in result["warnings"] if w["code"] == "workflow_input_variable_not_default"]
        assert len(wiv_warn) >= 1
        # all should point to dify.workflow_input_variable since no per-type override
        for w in wiv_warn:
            assert w["path"] == "dify.workflow_input_variable"


# ---- dify target in audit_types ---------------------------------------------


class TestDifyTarget:
    def test_audit_type_has_dify_target(self):
        result = build_runtime_summary(_base_config())
        at = next(a for a in result["audit_types"] if a["code"] == "progress_vs_nursing")
        assert "dify_target" in at
        assert at["dify_target"]["target_source"] == "audit_type"
        assert at["dify_target"]["has_api_key"] is True

    def test_no_secrets_in_dify_target(self):
        result = build_runtime_summary(_base_config())
        for at in result["audit_types"]:
            dt = at.get("dify_target", {})
            assert "api_key" not in dt
            assert "api_key_enc" not in dt


# ---- warnings ----------------------------------------------------------------


class TestWarnings:
    def test_empty_audit_type_codes_info(self):
        cfg = _base_config()
        cfg["scheduler_daily"]["audit_type_codes"] = []
        result = build_runtime_summary(cfg)
        codes = [w["code"] for w in result["warnings"]]
        assert "scheduler_daily_empty_audit_type_codes" in codes

    def test_empty_discharge_audit_type_codes_warning(self):
        cfg = _base_config()
        cfg["scheduler_discharge"]["audit_type_codes"] = []
        result = build_runtime_summary(cfg)
        codes = [w["code"] for w in result["warnings"]]
        assert "scheduler_discharge_empty_audit_type_codes" in codes

    def test_invalid_scheduler_audit_type_error(self):
        cfg = _base_config()
        cfg["scheduler_daily"]["audit_type_codes"] = ["nonexistent_type"]
        result = build_runtime_summary(cfg)
        codes = [w["code"] for w in result["warnings"]]
        assert "scheduler_daily_invalid_audit_type" in codes

    def test_disabled_audit_type_in_scheduler_warning(self):
        cfg = _base_config()
        cfg["scheduler_daily"]["audit_type_codes"] = ["orders_vs_progress"]
        result = build_runtime_summary(cfg)
        codes = [w["code"] for w in result["warnings"]]
        assert "scheduler_daily_disabled_audit_type" in codes

    def test_enabled_scheduler_without_cron_warning(self):
        cfg = _base_config()
        cfg["scheduler_daily"]["cron"] = ""
        result = build_runtime_summary(cfg)
        codes = [w["code"] for w in result["warnings"]]
        assert "scheduler_daily_enabled_without_cron" in codes

    def test_enabled_discharge_without_cron_warning(self):
        cfg = _base_config()
        cfg["scheduler_discharge"]["cron"] = ""
        result = build_runtime_summary(cfg)
        codes = [w["code"] for w in result["warnings"]]
        assert "scheduler_discharge_enabled_without_cron" in codes

    def test_empty_dept_filter_info(self):
        cfg = _base_config()
        cfg["scheduler_daily"]["dept_filter"] = []
        result = build_runtime_summary(cfg)
        codes = [w["code"] for w in result["warnings"]]
        assert "dept_filter_empty_daily" in codes

    def test_dept_filter_mismatch_info(self):
        cfg = _base_config()
        cfg["scheduler_daily"]["dept_filter"] = ["020103"]
        cfg["scheduler_discharge"]["dept_filter"] = ["030201"]
        result = build_runtime_summary(cfg)
        codes = [w["code"] for w in result["warnings"]]
        assert "dept_filter_mismatch" in codes

    def test_audit_type_missing_builder(self):
        cfg = _base_config()
        cfg["audit_types"].append({
            "code": "test_no_builder",
            "name": "Test",
            "enabled": True,
            "sources": {"src": {"type": "sql", "query_sql": "SELECT 1"}},
            "payload": {},
        })
        result = build_runtime_summary(cfg)
        codes = [w["code"] for w in result["warnings"]]
        assert "audit_type_missing_builder" in codes

    def test_audit_type_missing_sources(self):
        cfg = _base_config()
        cfg["audit_types"].append({
            "code": "test_no_sources",
            "name": "Test",
            "enabled": True,
            "sources": {},
            "payload": {"builder": "stub"},
        })
        result = build_runtime_summary(cfg)
        codes = [w["code"] for w in result["warnings"]]
        assert "audit_type_missing_sources" in codes

    def test_source_missing_sql(self):
        cfg = _base_config()
        cfg["audit_types"].append({
            "code": "test_no_sql",
            "name": "Test",
            "enabled": True,
            "sources": {"src": {"type": "sql", "required": True}},
            "payload": {"builder": "stub"},
        })
        result = build_runtime_summary(cfg)
        codes = [w["code"] for w in result["warnings"]]
        assert "audit_type_source_missing_sql" in codes

    def test_dify_base_url_missing(self):
        cfg = _base_config()
        cfg["dify"]["base_url"] = ""
        result = build_runtime_summary(cfg)
        codes = [w["code"] for w in result["warnings"]]
        assert "dify_base_url_empty" in codes

    def test_workflow_input_variable_not_mr_txt(self):
        cfg = _base_config()
        cfg["dify"]["workflow_input_variable"] = "custom_input"
        result = build_runtime_summary(cfg)
        codes = [w["code"] for w in result["warnings"]]
        assert "workflow_input_variable_not_default" in codes


# ---- no mutation -------------------------------------------------------------


class TestImmutability:
    def test_build_runtime_summary_does_not_mutate_config(self):
        cfg = _base_config()
        original = deepcopy(cfg)
        build_runtime_summary(cfg)
        assert cfg == original


# ---- no secrets anywhere -----------------------------------------------------


class TestNoSecrets:
    def test_no_secret_fields_anywhere(self):
        cfg = _base_config()
        cfg["dify"]["api_key"] = "plain-key"
        result = build_runtime_summary(cfg)
        leaked = _deep_scan_for_secrets(result)
        assert leaked == [], f"Unexpected secret fields found: {leaked}"

    def test_deep_scan_utility(self):
        nested = {"a": {"b": {"api_key": "secret"}}}
        assert "api_key" in _deep_scan_for_secrets(nested)

        arr = [{"safe": "ok"}, {"api_key_enc": "enc"}]
        assert "api_key_enc" in _deep_scan_for_secrets(arr)

        clean = {"run_modes": {"daily": {"calls_dify": True}}}
        assert _deep_scan_for_secrets(clean) == []


# ---- edge cases --------------------------------------------------------------


class TestEdgeCases:
    def test_empty_config(self):
        result = build_runtime_summary({})
        assert "run_modes" in result
        assert result["audit_types"] == []

    def test_no_scheduler_discharge(self):
        cfg = _base_config()
        del cfg["scheduler_discharge"]
        result = build_runtime_summary(cfg)
        assert "scheduler_discharge" in result["schedulers"]

    def test_no_audit_types(self):
        cfg = _base_config()
        cfg["audit_types"] = []
        result = build_runtime_summary(cfg)
        assert result["audit_types"] == []
