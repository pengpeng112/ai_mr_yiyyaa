"""
Runtime configuration resolver — Phase 1 read-only interpretation layer.

Provides standardized, immutable interpretation of the existing config dict
without importing business modules or modifying the config in-place.

Phase 1 constraint: This module is NOT imported by any existing business code.
Only tests may import it.  It operates on plain dicts returned by
app.config.load_config().
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


# ---- run-mode metadata (phase 1: descriptive only, do not replace existing logic) ----

_RUN_MODE_DEFAULTS: dict[str, dict[str, Any]] = {
    "daily_increment": {
        "calls_dify": True,
        "writes_push_log": True,
        "writes_scheduler_history": True,
        "triggers_relay_alert": True,
        "source_record_key_namespace": None,
        "default_query_date": "today",
        "dept_scope": "daily_increment",
    },
    "discharge_final": {
        "calls_dify": True,
        "writes_push_log": True,
        "writes_scheduler_history": True,
        "triggers_relay_alert": True,
        "source_record_key_namespace": "mode::discharge_final",
        "default_query_date": "yesterday",
        "dept_scope": "discharge_final",
    },
    "manual": {
        "calls_dify": True,
        "writes_push_log": True,
        "writes_scheduler_history": False,
        "triggers_relay_alert": True,
        "source_record_key_namespace": "manual",
        "default_query_date": "request",
        "dept_scope": "manual_default",
    },
    "precheck": {
        "calls_dify": False,
        "writes_push_log": False,
        "writes_scheduler_history": False,
        "triggers_relay_alert": False,
        "source_record_key_namespace": None,
        "default_query_date": "request",
        "dept_scope": "patient_census",
    },
}

_VALID_RUN_MODES = frozenset(_RUN_MODE_DEFAULTS.keys())


# ---- dept-scope defaults ----

_DEPT_SCOPE_DEFAULTS: dict[str, dict[str, Any]] = {
    "daily_increment": {
        "field_semantics": "current_dept",
        "date_basis": "record_date",
        "allow_override": True,
        "dept_codes": [],
    },
    "discharge_final": {
        "field_semantics": "discharge_dept",
        "date_basis": "discharge_date",
        "allow_override": True,
        "dept_codes": [],
    },
    "manual_default": {
        "field_semantics": "request_defined",
        "date_basis": "request_defined",
        "allow_override": True,
        "dept_codes": [],
    },
    "patient_census": {
        "field_semantics": "mode_defined",
        "date_basis": "request_defined",
        "allow_override": True,
        "dept_codes": [],
        "masking_required": True,
        "max_limit": 500,
    },
}

_VALID_DEPT_SCOPES = frozenset(_DEPT_SCOPE_DEFAULTS.keys())


# ---- public API ---------------------------------------------------------------


def resolve_run_mode_config(config: dict[str, Any], run_mode: str) -> dict[str, Any]:
    """Return standardized metadata for a run mode.

    The returned dict is a new object; the caller cannot mutate the original
    config through it.

    Raises:
        ValueError: Unknown *run_mode*.
    """
    mode = str(run_mode or "").strip()
    if mode not in _VALID_RUN_MODES:
        raise ValueError(f"Unknown run_mode: {mode}")
    return {"run_mode": mode, **deepcopy(_RUN_MODE_DEFAULTS[mode])}


def resolve_scheduler_config(
    config: dict[str, Any], scheduler_key: str
) -> dict[str, Any]:
    """Resolve scheduler configuration from the existing config dict.

    - ``audit_type_codes`` is returned **as-is** (never auto-expanded).
    - ``dept_filter`` is returned **as-is** (empty list is preserved
      verbatim; ``None`` is normalized to ``[]``).

    Raises:
        ValueError: Unknown *scheduler_key*.
    """
    key = str(scheduler_key or "").strip()
    if key not in ("scheduler_daily", "scheduler_discharge"):
        raise ValueError(f"Unknown scheduler_key: {key}")

    sched = config.get(key, {}) or {}

    run_mode = str(
        sched.get("audit_run_mode")
        or ("discharge_final" if key == "scheduler_discharge" else "daily_increment")
    )

    raw_dept = sched.get("dept_filter")
    dept_filter: list[str] = list(raw_dept) if raw_dept is not None else []

    dept_scope = (
        "discharge_final" if key == "scheduler_discharge" else "daily_increment"
    )

    return {
        "scheduler_key": key,
        "enabled": bool(sched.get("enabled", False)),
        "run_mode": run_mode,
        "schedule_mode": str(sched.get("schedule_mode") or "daily"),
        "cron": str(sched.get("cron") or ""),
        "daily_time": str(sched.get("daily_time") or ""),
        "interval_value": sched.get("interval_value", 10),
        "interval_unit": str(sched.get("interval_unit") or "minutes"),
        "audit_type_codes": list(sched.get("audit_type_codes") or []),
        "dept_filter": dept_filter,
        "dept_scope": dept_scope,
    }


def resolve_dept_scope(
    config: dict[str, Any],
    scope_name: str,
    override: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve a named department scope.

    Precedence:
    1. If ``override`` is given it becomes the effective ``dept_codes``.
    2. Otherwise, if ``config["dept_scopes"][scope_name]`` exists **and**
       contains ``dept_codes``, that value is used.
    3. Otherwise, the resolver falls back to the legacy scheduler sections
       (``scheduler_daily.dept_filter`` / ``scheduler_discharge.dept_filter``).
    4. As a last resort the scope-default empty list ``[]`` is returned.

    An empty ``dept_filter`` in the legacy config is preserved verbatim
    (``[]``) — the resolver does **not** decide whether that means
    “all departments” or “not configured”.

    Raises:
        ValueError: Unknown *scope_name*.
    """
    name = str(scope_name or "").strip()
    if name not in _VALID_DEPT_SCOPES:
        raise ValueError(f"Unknown dept_scope: {name}")

    result = deepcopy(_DEPT_SCOPE_DEFAULTS[name])

    # 1. new dept_scopes section
    new_section = config.get("dept_scopes", {}) or {}
    if isinstance(new_section, dict) and name in new_section:
        scope_data = new_section[name]
        if isinstance(scope_data, dict):
            for k in result:
                if k in scope_data:
                    result[k] = deepcopy(scope_data[k])
    else:
        # 2. legacy scheduler fallback
        if name == "daily_increment":
            legacy = config.get("scheduler_daily", {}) or {}
            df = legacy.get("dept_filter")
            if df is not None:
                result["dept_codes"] = list(df)
        elif name == "discharge_final":
            legacy = config.get("scheduler_discharge", {}) or {}
            df = legacy.get("dept_filter")
            if df is not None:
                result["dept_codes"] = list(df)

    # 3. explicit override
    if override is not None:
        result["dept_codes"] = list(override)

    result["scope_name"] = name
    return result


def resolve_audit_type_config(
    config: dict[str, Any], audit_type_code: str
) -> dict[str, Any]:
    """Look up a single audit-type configuration entry.

    Returns a **deep copy** so the caller cannot accidentally mutate the
    original config.  Missing optional keys are defaulted to keep the
    returned shape predictable (``code``, ``enabled``).

    Raises:
        ValueError: *audit_type_code* not found in ``config["audit_types"]``.
    """
    code = str(audit_type_code or "").strip()
    types = config.get("audit_types", []) or []
    for at in types:
        if isinstance(at, dict) and str(at.get("code") or "").strip() == code:
            result = deepcopy(at)
            result.setdefault("code", code)
            result.setdefault("enabled", False)
            return result
    raise ValueError(f"Unknown audit_type: {code}")


def resolve_dify_target(
    config: dict[str, Any], audit_type_code: str
) -> dict[str, Any]:
    """Return the effective Dify target for a given audit type.

    Prefers the audit-type-level Dify section; falls back to the global
    ``dify`` section.  **Never** returns plain-text api_key / api_key_enc.

    Returns:
        dict with keys: ``audit_type_code``, ``target_source``,
        ``base_url``, ``workflow_input_variable``, ``has_api_key``.
    """
    code = str(audit_type_code or "").strip()
    at = resolve_audit_type_config(config, code)
    at_dify = at.get("dify", {}) or {}
    global_dify = config.get("dify", {}) or {}

    at_url = str(at_dify.get("base_url") or "").strip()
    at_key = bool(at_dify.get("api_key_enc") or at_dify.get("api_key"))

    if at_url or at_key:
        return {
            "audit_type_code": code,
            "target_source": "audit_type",
            "base_url": at_url or str(global_dify.get("base_url") or ""),
            "workflow_input_variable": str(
                at_dify.get("workflow_input_variable")
                or global_dify.get("workflow_input_variable", "mr_txt")
            ),
            "has_api_key": at_key,
        }

    return {
        "audit_type_code": code,
        "target_source": "global",
        "base_url": str(global_dify.get("base_url") or ""),
        "workflow_input_variable": str(
            global_dify.get("workflow_input_variable", "mr_txt")
        ),
        "has_api_key": bool(
            global_dify.get("api_key_enc") or global_dify.get("api_key")
        ),
    }
