"""
Runtime Summary Service — Phase 2.5 read-only config aggregation (hardened).

Provides `build_runtime_summary(config: dict) -> dict` that aggregates
run modes, schedulers, dept scopes, audit types, Dify targets, and
warnings into a single JSON-safe read-only summary.

Constraints:
- No DB access, no network calls, no file writes.
- No secrets (api_key, api_key_enc, password, password_enc, secret_key, secret_key_enc).
- No SQL body (query_sql is stripped).
- No mutation of the input config.

Phase 2.5 hardening:
- Uses `resolve_audit_type_config()` for consistent resolver alignment.
- Precise `uses_sql` flag (checks source type/query_sql, not just keys).
- Safe `sources` summary array (no query_sql, no field_mapping).
- Warning paths unified to dot notation; dual-path uses `related_path`.
- Workflow input variable warnings distinguish per-type vs global source.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.runtime_config_resolver import (
    resolve_run_mode_config,
    resolve_scheduler_config,
    resolve_dept_scope,
    resolve_audit_type_config,
    resolve_dify_target,
)

_SECRET_KEY_PATTERNS = (
    "api_key", "api_key_enc",
    "password", "password_enc",
    "secret_key", "secret_key_enc",
)


def _deep_scan_for_secrets(obj: Any) -> list[str]:
    """Recursively check for secret fields. Returns list of found paths."""
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _SECRET_KEY_PATTERNS:
                found.append(k)
            found.extend(_deep_scan_for_secrets(v))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_deep_scan_for_secrets(item))
    return found


# ---- run modes ---------------------------------------------------------------


def _build_run_modes(config: dict[str, Any]) -> dict[str, Any]:
    modes: dict[str, Any] = {}
    for mode_key in ("daily_increment", "discharge_final", "manual", "precheck"):
        modes[mode_key] = resolve_run_mode_config(config, mode_key)
    return modes


# ---- schedulers --------------------------------------------------------------


def _build_schedulers(config: dict[str, Any]) -> dict[str, Any]:
    schedulers: dict[str, Any] = {}
    for key in ("scheduler_daily", "scheduler_discharge"):
        schedulers[key] = resolve_scheduler_config(config, key)
    return schedulers


# ---- dept scopes -------------------------------------------------------------


def _build_dept_scopes(config: dict[str, Any]) -> dict[str, Any]:
    scopes: dict[str, Any] = {}
    for name in ("daily_increment", "discharge_final", "manual_default", "patient_census"):
        scopes[name] = resolve_dept_scope(config, name)
    return scopes


# ---- audit types -------------------------------------------------------------


def _source_uses_sql(source: dict[str, Any] | None) -> bool:
    """Check whether a single source entry uses SQL."""
    if not isinstance(source, dict):
        return False
    return source.get("type") == "sql" or bool(source.get("query_sql"))


def _build_safe_sources_summary(sources: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a safe source summary: no query_sql, no field_mapping."""
    result: list[dict[str, Any]] = []
    for src_key, src_val in (sources or {}).items():
        if not isinstance(src_val, dict):
            continue
        result.append({
            "key": src_key,
            "type": str(src_val.get("type") or ""),
            "backend": str(src_val.get("backend") or "default"),
            "required": bool(src_val.get("required", True)),
            "has_query_sql": bool(src_val.get("query_sql")),
        })
    return result


def _build_audit_type_summary(at: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Build a safe audit-type summary with no SQL and no secrets.

    *at* is expected to come from resolve_audit_type_config() (deepcopy).
    """
    code = str(at.get("code") or "").strip()
    if not code:
        return {}

    sources: dict[str, Any] = at.get("sources", {}) or {}
    source_keys = list(sources.keys())
    required_source_keys = [k for k, v in sources.items() if isinstance(v, dict) and v.get("required", True)]
    payload = at.get("payload", {}) or {}
    response = at.get("response", {}) or {}

    # Dify target summary via resolver (already secrets-safe)
    try:
        dify_target = resolve_dify_target(config, code)
    except ValueError:
        dify_target = {"audit_type_code": code, "target_source": "unknown", "base_url": "", "workflow_input_variable": "", "has_api_key": False}

    # Flags
    uses_sql = any(_source_uses_sql(v) for v in sources.values())
    has_sensitive_secret = False
    raw_dify = at.get("dify", {}) or {}
    if raw_dify.get("api_key_enc") or raw_dify.get("api_key"):
        has_sensitive_secret = True
    has_display_config = bool(at.get("display"))

    # Clean response section — only include JSONPath keys, not raw values
    safe_response: dict[str, Any] = {}
    for k in ("parse_strategy", "dimension_path", "conclusion_path", "severity_path", "risk_score_path", "inconsistency_path"):
        if k in response:
            safe_response[k] = response[k]

    return {
        "code": code,
        "name": str(at.get("name") or ""),
        "enabled": bool(at.get("enabled", True)),
        "default_for_schedule": bool(at.get("default_for_schedule", False)),
        "sort_order": at.get("sort_order", 100),
        "builder": str(payload.get("builder") or ""),
        "source_keys": source_keys,
        "required_source_keys": required_source_keys,
        "sources": _build_safe_sources_summary(sources),
        "group_key": [str(k) for k in (at.get("group_key") or [])] or ["patient_id", "visit_number"],
        "dify_target": dify_target,
        "response": safe_response,
        "display_paths": list(at.get("display", {}).keys()) if at.get("display") else [],
        "flags": {
            "uses_sql": uses_sql,
            "has_sensitive_secret": has_sensitive_secret,
            "has_display_config": has_display_config,
        },
    }


def _build_audit_types(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Iterate audit_types via resolve_audit_type_config() for consistency."""
    raw_types = config.get("audit_types", []) or []
    result: list[dict[str, Any]] = []
    for raw in raw_types:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or "").strip()
        if not code:
            continue
        try:
            at = resolve_audit_type_config(config, code)
            summary = _build_audit_type_summary(at, config)
            if summary:
                result.append(summary)
        except ValueError:
            continue
    return result


# ---- warnings ----------------------------------------------------------------


def _build_warnings(config: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []

    # Collect valid audit type codes
    raw_types = config.get("audit_types", []) or []
    all_audit_codes: set[str] = set()
    for at in raw_types:
        if isinstance(at, dict):
            code = str(at.get("code") or "").strip()
            if code:
                all_audit_codes.add(code)

    code_by_enabled: dict[str, bool] = {}
    for at in raw_types:
        if isinstance(at, dict):
            code = str(at.get("code") or "").strip()
            if code:
                code_by_enabled[code] = bool(at.get("enabled", True))

    # --- scheduler daily ---
    sched_daily = config.get("scheduler_daily", {}) or {}
    daily_codes = list(sched_daily.get("audit_type_codes") or [])
    daily_enabled = bool(sched_daily.get("enabled", False))
    daily_cron = str(sched_daily.get("cron") or "")

    if not daily_codes:
        warnings.append({
            "level": "info",
            "code": "scheduler_daily_empty_audit_type_codes",
            "message": "scheduler_daily.audit_type_codes is empty; scheduler will use default_for_schedule audit types.",
            "path": "scheduler_daily.audit_type_codes",
        })

    if daily_enabled and not daily_cron:
        warnings.append({
            "level": "warning",
            "code": "scheduler_daily_enabled_without_cron",
            "message": "scheduler_daily.enabled=true but cron is empty.",
            "path": "scheduler_daily.cron",
        })

    for code in daily_codes:
        if code not in all_audit_codes:
            warnings.append({
                "level": "error",
                "code": "scheduler_daily_invalid_audit_type",
                "message": f"scheduler_daily references unknown audit type: {code}.",
                "path": "scheduler_daily.audit_type_codes",
            })
        elif not code_by_enabled.get(code, False):
            warnings.append({
                "level": "warning",
                "code": "scheduler_daily_disabled_audit_type",
                "message": f"scheduler_daily references disabled audit type: {code}.",
                "path": "scheduler_daily.audit_type_codes",
            })

    # --- scheduler discharge ---
    sched_discharge = config.get("scheduler_discharge", {}) or {}
    discharge_codes = list(sched_discharge.get("audit_type_codes") or [])
    discharge_enabled = bool(sched_discharge.get("enabled", False))
    discharge_cron = str(sched_discharge.get("cron") or "")

    if not discharge_codes:
        warnings.append({
            "level": "warning",
            "code": "scheduler_discharge_empty_audit_type_codes",
            "message": "scheduler_discharge.audit_type_codes is empty; may fallback to safe default.",
            "path": "scheduler_discharge.audit_type_codes",
        })

    if discharge_enabled and not discharge_cron:
        warnings.append({
            "level": "warning",
            "code": "scheduler_discharge_enabled_without_cron",
            "message": "scheduler_discharge.enabled=true but cron is empty.",
            "path": "scheduler_discharge.cron",
        })

    for code in discharge_codes:
        if code not in all_audit_codes:
            warnings.append({
                "level": "error",
                "code": "scheduler_discharge_invalid_audit_type",
                "message": f"scheduler_discharge references unknown audit type: {code}.",
                "path": "scheduler_discharge.audit_type_codes",
            })
        elif not code_by_enabled.get(code, False):
            warnings.append({
                "level": "warning",
                "code": "scheduler_discharge_disabled_audit_type",
                "message": f"scheduler_discharge references disabled audit type: {code}.",
                "path": "scheduler_discharge.audit_type_codes",
            })

    # --- dept filter ---
    daily_dept = list(sched_daily.get("dept_filter") or [])
    discharge_dept = list(sched_discharge.get("dept_filter") or [])

    if not daily_dept:
        warnings.append({
            "level": "info",
            "code": "dept_filter_empty_daily",
            "message": "scheduler_daily.dept_filter is empty; semantics determined by execution chain.",
            "path": "scheduler_daily.dept_filter",
        })

    if not discharge_dept:
        warnings.append({
            "level": "info",
            "code": "dept_filter_empty_discharge",
            "message": "scheduler_discharge.dept_filter is empty; semantics determined by execution chain.",
            "path": "scheduler_discharge.dept_filter",
        })

    if daily_dept and discharge_dept and daily_dept != discharge_dept:
        warnings.append({
            "level": "info",
            "code": "dept_filter_mismatch",
            "message": "scheduler_daily and scheduler_discharge use different dept_filter values.",
            "path": "scheduler_daily.dept_filter",
            "related_path": "scheduler_discharge.dept_filter",
        })

    # --- audit type structural checks ---
    for at in raw_types:
        if not isinstance(at, dict):
            continue
        code = str(at.get("code") or "").strip()
        if not code:
            continue
        enabled = bool(at.get("enabled", True))

        payload = at.get("payload", {}) or {}
        builder = str(payload.get("builder") or "").strip()
        if enabled and not builder:
            warnings.append({
                "level": "warning",
                "code": "audit_type_missing_builder",
                "message": f"Audit type '{code}' is enabled but has no payload.builder.",
                "path": f"audit_types.{code}.payload.builder",
            })

        sources = at.get("sources", {}) or {}
        if enabled and not sources:
            warnings.append({
                "level": "error",
                "code": "audit_type_missing_sources",
                "message": f"Audit type '{code}' is enabled but has no sources.",
                "path": f"audit_types.{code}.sources",
            })

        for src_key, src_val in (sources or {}).items():
            if not isinstance(src_val, dict):
                continue
            if not src_val.get("query_sql"):
                warnings.append({
                    "level": "warning",
                    "code": "audit_type_source_missing_sql",
                    "message": f"Audit type '{code}' source '{src_key}' has no query_sql.",
                    "path": f"audit_types.{code}.sources.{src_key}.query_sql",
                })

    # --- Dify base_url ---
    global_dify = config.get("dify", {}) or {}
    global_base_url = str(global_dify.get("base_url") or "").strip()

    for at in raw_types:
        if not isinstance(at, dict):
            continue
        code = str(at.get("code") or "").strip()
        if not code:
            continue
        enabled = bool(at.get("enabled", True))
        if not enabled:
            continue
        at_dify = at.get("dify", {}) or {}
        at_url = str(at_dify.get("base_url") or "").strip()
        effective_url = at_url or global_base_url
        if not effective_url:
            warning: dict[str, Any] = {
                "level": "warning",
                "code": "dify_base_url_empty",
                "message": f"Audit type '{code}' has no Dify base_url (neither per-type nor global).",
                "path": f"audit_types.{code}.dify.base_url",
                "related_path": "dify.base_url",
            }
            warnings.append(warning)

        wiv = str(at_dify.get("workflow_input_variable") or global_dify.get("workflow_input_variable", "mr_txt"))
        if wiv != "mr_txt":
            # distinguish source: per-type override vs global
            if at_dify.get("workflow_input_variable"):
                wiv_path = f"audit_types.{code}.dify.workflow_input_variable"
            else:
                wiv_path = "dify.workflow_input_variable"
            warnings.append({
                "level": "info",
                "code": "workflow_input_variable_not_default",
                "message": f"Audit type '{code}' workflow_input_variable is '{wiv}' (default is 'mr_txt').",
                "path": wiv_path,
            })

    return warnings


# ---- main public API ---------------------------------------------------------


def build_runtime_summary(config: dict[str, Any]) -> dict[str, Any]:
    """Build a read-only runtime summary dict from the given config.

    Returns:
        dict with keys: run_modes, schedulers, dept_scopes, audit_types,
        warnings, meta.

        - run_modes:        resolved run mode metadata
        - schedulers:       resolved scheduler config (no expansion)
        - dept_scopes:      resolved dept scopes
        - audit_types:      safe audit type summaries (no SQL, no secrets)
        - warnings:         list of config warnings (info/warning/error)
        - meta:             read-only metadata
    """
    result: dict[str, Any] = {
        "run_modes": _build_run_modes(config),
        "schedulers": _build_schedulers(config),
        "dept_scopes": _build_dept_scopes(config),
        "audit_types": _build_audit_types(config),
        "warnings": _build_warnings(config),
        "meta": {
            "readonly": True,
            "secrets_masked": True,
            "sql_included": False,
            "config_shape": "legacy-compatible",
        },
    }

    # Sanity check: recursively verify no secrets leaked (fail-closed)
    leaked = _deep_scan_for_secrets(result)
    if leaked:
        raise RuntimeError(f"runtime summary contains sensitive fields: {leaked}")

    return result
