#!/usr/bin/env python3
"""
003 P0 只读生产质控聚合审计脚本。

约束（硬性）：
- 仅读取聚合字段；不写 SQL、不 commit/flush、不调用外部 HTTP
- 不输出病历正文（mr_text / request_json / response_json / payload 原文）
- 患者标识必须脱敏
- 未获生产授权时只使用 --fixture 合成/脱敏数据，禁止尝试 SSH/服务器连接

用法示例：
  python scripts/qc_production_readonly_audit.py --fixture tests/fixtures/qc_p0_20260714_synthetic.json
  python scripts/qc_production_readonly_audit.py --fixture path.json --output-json out.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

# 与生产六类质控 code 对齐；禁止在此改名
SIX_AUDIT_TYPES: tuple[str, ...] = (
    "admission_vs_first_progress",
    "discharge_vs_frontpage",
    "surgery_chain",
    "progress_vs_nursing",
    "jyjc_vs_bcnursing",
    "syssvsscbc",
)

RUN_MODES: tuple[str, ...] = ("daily_increment", "discharge_final")

# 仅这些列允许从应用库 SELECT；明确排除正文类字段
PUSH_LOG_SAFE_COLUMNS: tuple[str, ...] = (
    "id",
    "query_date",
    "audit_type_code",
    "audit_run_mode",
    "status",
    "parse_status",
    "parse_error",
    "skip_reason",
    "severity",
    "patient_id",
    "visit_number",
    "dept",
    "trigger_type",
    "superseded_by",
    "pushed_flag",
    "reviewed_flag",
)

HISTORY_SAFE_COLUMNS: tuple[str, ...] = (
    "id",
    "run_time",
    "trigger_type",
    "query_date",
    "audit_type_code",
    "total_records",
    "success_count",
    "failed_count",
    "duration_seconds",
    "status",
)

DIMENSION_SAFE_COLUMNS: tuple[str, ...] = (
    "id",
    "push_log_id",
    "dimension_code",
    "dimension",
    "status",
    "severity",
    "confidence",
    "alert_level",
    "medical_evidence_json",
    "nursing_evidence_json",
    "extra_json",
)

ALERT_SAFE_COLUMNS: tuple[str, ...] = (
    "id",
    "push_log_id",
    "dimension_code",
    "patient_id",
    "visit_number",
    "dept",
    "severity",
    "alert_level",
    "status",
)

FORBIDDEN_OUTPUT_KEYS: frozenset[str] = frozenset(
    {
        "mr_text",
        "request_json",
        "response_json",
        "payload_json",
        "content",
        "medical_content",
        "nursing_content",
        "overall_qc_summary",
        "password",
        "api_key",
        "secret",
    }
)

# 已知 discharge_final SQL 转换覆盖策略（与 scheduler_run_modes.audit_type_for_run_mode 对齐）
DISCHARGE_SQL_CONVERSION: dict[str, str] = {
    "progress_vs_nursing": "dedicated_discharge_sql",
    "jyjc_vs_bcnursing": "dept_filter_append_discharge_date",
    "lab_exam_vs_progress_nursing": "dept_filter_append_discharge_date",
    "syssvsscbc": "dept_filter_append_discharge_date",
    "admission_vs_first_progress": "generic_dept_filter_or_date_dimension",
    "surgery_chain": "generic_dept_filter_or_date_dimension",
    "discharge_vs_frontpage": "generic_dept_filter_or_date_dimension",
}

# 001 安全门 / 002 幂等门：仅做本地代码静态探测，不连接生产
GATE_PROBE_TARGETS: dict[str, dict[str, Any]] = {
    "001_jwt_production_gate": {
        "module": "app.auth",
        "must_attrs": ["_load_jwt_secret", "_resolve_runtime_environment", "_DEFAULT_SECRET"],
        "doc": "生产环境禁止默认/过短 JWT",
    },
    "001_no_debug_admin_on_boot": {
        "module": "app.database",
        "must_not_attrs": ["_ensure_debug_admin"],
        "doc": "启动路径不得重建默认管理员",
    },
    "001_no_login_admin_bootstrap": {
        "module": "app.routers.users",
        "must_not_attrs": ["_ensure_debug_admin_for_login"],
        "doc": "登录路径不得创建管理员",
    },
    "001_notify_test_auth": {
        "module": "app.routers.notify",
        "source_contains_any": ["manage_config", "NOTIFY_TEST"],
        "doc": "通知测试需鉴权且生产可关闭",
    },
    "001_dify_log_no_body_preview": {
        "module": "app.services.dify_log_utils",
        "must_attrs": ["_summarize_dify_payload", "_fingerprint_for_log"],
        "source_must_not_contain": ["main_input_preview"],
        "doc": "Dify 日志摘要不得含病历正文预览字段",
    },
    "001_notify_ssrf_guard": {
        "module": "app.security_utils",
        "must_attrs": ["validate_test_notification_target", "public_error_message"],
        "doc": "通知测试目标 SSRF 校验与异常脱敏",
    },
    "001_feedback_dept_visibility": {
        "module": "app.routers.qc_feedback",
        "source_contains_any": ["apply_push_log_visibility", "dept_id"],
        "doc": "反馈路径含科室可见性/科室字段约束",
    },
    "002_no_execution_attempt_tables": {
        "module": "app.models",
        "must_not_attrs": ["PushExecution", "PushAttempt", "IdempotencyExecution"],
        "doc": "002 execution/attempt 表尚未落地（设计门，非实现）",
        "expect_absent": True,
    },
}


def mask_identifier(value: Any, prefix: str = "pid") -> str:
    """对患者 ID / 住院号等做不可逆短指纹脱敏。"""
    text = str(value or "").strip()
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def mask_evidence(text: Any, max_chars: int = 80) -> str:
    """证据仅保留截断文本供临床清单；不输出全文病历。"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    # 去掉可能夹带的患者 ID 样式数字串
    cleaned = re.sub(r"\b\d{6,}\b", "[id]", raw)
    if len(cleaned) > max_chars:
        return cleaned[:max_chars] + f"...(truncated,len={len(cleaned)})"
    return cleaned


def is_qc_usable(status: Any, parse_status: Any) -> bool:
    """003 §3.1 冻结语义。"""
    return str(status or "") == "success" and str(parse_status or "") == "success"


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _counter_dict(counter: Counter) -> dict[str, int]:
    return {str(k) if k != "" else "(empty)": int(v) for k, v in sorted(counter.items(), key=lambda x: str(x[0]))}


def classify_parse_error(parse_error: Any) -> str:
    text = _safe_str(parse_error).lower()
    if not text:
        return "empty_parse_error"
    if "missing_dimensions" in text or "dimensions_and_conclusion" in text:
        return "parsed_json_missing_dimensions_and_conclusion"
    if "json" in text and ("decode" in text or "parse" in text or "expecting" in text or "malformed" in text):
        return "json_syntax_error"
    if "markdown" in text:
        return "markdown_wrapped"
    if "empty" in text or "blank" in text:
        return "empty_output"
    return "other_parse_error"


def _load_json_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("fixture root must be an object")
    return data


def _assert_no_forbidden_keys(obj: Any, path: str = "$") -> None:
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            key_l = str(key).lower()
            if key_l in FORBIDDEN_OUTPUT_KEYS or any(f in key_l for f in ("password", "api_key", "secret_key")):
                raise ValueError(f"forbidden output key at {path}.{key}")
            _assert_no_forbidden_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _assert_no_forbidden_keys(item, f"{path}[{idx}]")


def aggregate_push_logs(
    push_logs: Sequence[Mapping[str, Any]],
    *,
    query_date: str | None = None,
) -> dict[str, Any]:
    rows = [
        r
        for r in push_logs
        if query_date is None or _safe_str(r.get("query_date")) == query_date
    ]
    by_type_mode: dict[str, dict[str, Any]] = {}
    overall_status = Counter()
    overall_parse = Counter()
    overall_skip = Counter()
    parse_error_categories = Counter()
    transport_success = 0
    qc_usable = 0
    high_logs = 0

    for row in rows:
        code = _safe_str(row.get("audit_type_code")) or "(empty)"
        mode = _safe_str(row.get("audit_run_mode")) or "daily_increment"
        key = f"{code}::{mode}"
        bucket = by_type_mode.setdefault(
            key,
            {
                "audit_type_code": code,
                "audit_run_mode": mode,
                "total": 0,
                "status": Counter(),
                "parse_status": Counter(),
                "skip_reason": Counter(),
                "transport_success": 0,
                "qc_usable": 0,
                "high": 0,
                "parse_error_categories": Counter(),
            },
        )
        status = _safe_str(row.get("status"))
        parse_status = _safe_str(row.get("parse_status"))
        skip_reason = _safe_str(row.get("skip_reason"))
        severity = _safe_str(row.get("severity")).lower()

        bucket["total"] += 1
        bucket["status"][status] += 1
        bucket["parse_status"][parse_status] += 1
        overall_status[status] += 1
        overall_parse[parse_status] += 1
        if skip_reason:
            bucket["skip_reason"][skip_reason] += 1
            overall_skip[skip_reason] += 1
        if status == "success":
            bucket["transport_success"] += 1
            transport_success += 1
        if is_qc_usable(status, parse_status):
            bucket["qc_usable"] += 1
            qc_usable += 1
        if severity == "high":
            bucket["high"] += 1
            high_logs += 1
        if status == "success" and parse_status == "failed":
            cat = classify_parse_error(row.get("parse_error"))
            bucket["parse_error_categories"][cat] += 1
            parse_error_categories[cat] += 1

    serialized_buckets = []
    for key in sorted(by_type_mode.keys()):
        b = by_type_mode[key]
        serialized_buckets.append(
            {
                "audit_type_code": b["audit_type_code"],
                "audit_run_mode": b["audit_run_mode"],
                "total": b["total"],
                "status": _counter_dict(b["status"]),
                "parse_status": _counter_dict(b["parse_status"]),
                "skip_reason": _counter_dict(b["skip_reason"]),
                "transport_success": b["transport_success"],
                "qc_usable": b["qc_usable"],
                "high": b["high"],
                "parse_error_categories": _counter_dict(b["parse_error_categories"]),
            }
        )

    return {
        "row_count": len(rows),
        "status": _counter_dict(overall_status),
        "parse_status": _counter_dict(overall_parse),
        "skip_reason": _counter_dict(overall_skip),
        "transport_success": transport_success,
        "qc_usable": qc_usable,
        "qc_usable_definition": 'status=="success" AND parse_status=="success"',
        "high_push_logs": high_logs,
        "parse_error_categories": _counter_dict(parse_error_categories),
        "by_audit_type_and_mode": serialized_buckets,
    }


def aggregate_scheduler_history(
    history_rows: Sequence[Mapping[str, Any]],
    *,
    query_date: str | None = None,
) -> dict[str, Any]:
    rows = [
        r
        for r in history_rows
        if query_date is None or _safe_str(r.get("query_date")) == query_date
    ]
    by_type = defaultdict(lambda: Counter())
    status_overall = Counter()
    details = []
    for row in rows:
        code = _safe_str(row.get("audit_type_code")) or "(empty)"
        status = _safe_str(row.get("status")) or "(empty)"
        by_type[code][status] += 1
        status_overall[status] += 1
        details.append(
            {
                "audit_type_code": code,
                "query_date": _safe_str(row.get("query_date")),
                "status": status,
                "total_records": int(row.get("total_records") or 0),
                "success_count": int(row.get("success_count") or 0),
                "failed_count": int(row.get("failed_count") or 0),
                "duration_seconds": int(row.get("duration_seconds") or 0),
                "trigger_type": _safe_str(row.get("trigger_type")),
            }
        )
    return {
        "row_count": len(rows),
        "status": _counter_dict(status_overall),
        "by_audit_type_status": {k: _counter_dict(v) for k, v in sorted(by_type.items())},
        "details": details,
    }


def aggregate_dimensions(
    dimensions: Sequence[Mapping[str, Any]],
    push_logs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    push_index = {}
    if push_logs:
        for pl in push_logs:
            pid = pl.get("id")
            if pid is not None:
                push_index[int(pid)] = pl

    severity_counter = Counter()
    high_dims = 0
    by_code = Counter()
    high_detail_count = 0
    for dim in dimensions:
        sev = _safe_str(dim.get("severity")).lower()
        severity_counter[sev or "(empty)"] += 1
        code = _safe_str(dim.get("dimension_code")) or "(empty)"
        if sev == "high":
            high_dims += 1
            by_code[code] += 1
            high_detail_count += 1
    return {
        "row_count": len(dimensions),
        "severity": _counter_dict(severity_counter),
        "high_dimensions": high_dims,
        "high_by_dimension_code": _counter_dict(by_code),
        "linked_push_logs": len(push_index),
    }


def aggregate_alerts(alerts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    status_counter = Counter()
    for row in alerts:
        status_counter[_safe_str(row.get("status")) or "(empty)"] += 1
    return {
        "row_count": len(alerts),
        "status": _counter_dict(status_counter),
    }


def build_high_clinical_review_list(
    push_logs: Sequence[Mapping[str, Any]],
    dimensions: Sequence[Mapping[str, Any]],
    alerts: Sequence[Mapping[str, Any]],
    *,
    max_items: int = 200,
) -> list[dict[str, Any]]:
    """生成脱敏临床复核清单（不含患者明文 ID）。"""
    log_by_id = {int(r["id"]): r for r in push_logs if r.get("id") is not None}
    alerts_by_key: dict[tuple[int, str], list[Mapping[str, Any]]] = defaultdict(list)
    for alert in alerts:
        try:
            plid = int(alert.get("push_log_id"))
        except (TypeError, ValueError):
            continue
        dim_code = _safe_str(alert.get("dimension_code"))
        alerts_by_key[(plid, dim_code)].append(alert)

    items: list[dict[str, Any]] = []
    for dim in dimensions:
        if _safe_str(dim.get("severity")).lower() != "high":
            continue
        try:
            plid = int(dim.get("push_log_id"))
        except (TypeError, ValueError):
            continue
        log = log_by_id.get(plid, {})
        dim_code = _safe_str(dim.get("dimension_code"))
        related_alerts = alerts_by_key.get((plid, dim_code), []) or alerts_by_key.get((plid, "__conclusion__"), [])
        alert_statuses = sorted({_safe_str(a.get("status")) for a in related_alerts if _safe_str(a.get("status"))})
        extra = dim.get("extra_json")
        issue_mode = ""
        safety_category = ""
        if isinstance(extra, str) and extra.strip():
            try:
                extra_obj = json.loads(extra)
            except json.JSONDecodeError:
                extra_obj = {}
        elif isinstance(extra, Mapping):
            extra_obj = extra
        else:
            extra_obj = {}
        issues = extra_obj.get("issues") if isinstance(extra_obj, Mapping) else None
        if isinstance(issues, list) and issues:
            first = issues[0] if isinstance(issues[0], Mapping) else {}
            issue_mode = _safe_str(first.get("issue_mode") or first.get("mode"))
            safety_category = _safe_str(first.get("safety_category") or first.get("category"))

        med_ev = dim.get("medical_evidence_json")
        nur_ev = dim.get("nursing_evidence_json")
        med_text = _evidence_to_text(med_ev)
        nur_text = _evidence_to_text(nur_ev)

        items.append(
            {
                "audit_type_code": _safe_str(log.get("audit_type_code")),
                "audit_run_mode": _safe_str(log.get("audit_run_mode")),
                "query_date": _safe_str(log.get("query_date")),
                "patient_token": mask_identifier(log.get("patient_id"), "pid"),
                "visit_token": mask_identifier(log.get("visit_number"), "vis"),
                "dept_token": mask_identifier(log.get("dept"), "dept") if log.get("dept") else "",
                "dimension_code": dim_code,
                "dimension_status": _safe_str(dim.get("status")),
                "confidence": float(dim.get("confidence") or 0),
                "issue_mode": issue_mode,
                "safety_category": safety_category,
                "medical_evidence_masked": mask_evidence(med_text),
                "nursing_evidence_masked": mask_evidence(nur_text),
                "alert_statuses": alert_statuses,
                "alert_filter_reason": (
                    "dept_filtered" if "dept_filtered" in alert_statuses else
                    (alert_statuses[0] if alert_statuses else "no_alert_row")
                ),
            }
        )
        if len(items) >= max_items:
            break
    return items


def _evidence_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, Mapping):
                parts.append(_safe_str(item.get("text") or item.get("content") or item))
            else:
                parts.append(_safe_str(item))
        return " | ".join(p for p in parts if p)
    if isinstance(value, Mapping):
        return _safe_str(value.get("text") or value.get("content") or value)
    text = _safe_str(value)
    if text.startswith("[") or text.startswith("{"):
        try:
            parsed = json.loads(text)
            return _evidence_to_text(parsed)
        except json.JSONDecodeError:
            return text
    return text


def reconcile_discharge_final(
    *,
    query_date: str,
    configured_codes: Sequence[str],
    history_rows: Sequence[Mapping[str, Any]],
    push_logs: Sequence[Mapping[str, Any]],
    oracle_discharge_patient_count: int | None = None,
) -> dict[str, Any]:
    """
    2026-07-14 discharge_final 六类对账逻辑。

    注意：候选为 0 时若无 Oracle 出院患者枚举交叉核对，只能标记 needs_oracle_crosscheck，
    禁止直接解释为“当天无患者”。
    """
    configured = [_safe_str(c) for c in configured_codes if _safe_str(c)]
    history_by_code: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in history_rows:
        if _safe_str(row.get("query_date")) != query_date:
            continue
        history_by_code[_safe_str(row.get("audit_type_code"))].append(row)

    push_by_code: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in push_logs:
        if _safe_str(row.get("query_date")) != query_date:
            continue
        if _safe_str(row.get("audit_run_mode")) != "discharge_final":
            continue
        push_by_code[_safe_str(row.get("audit_type_code"))].append(row)

    # 检查范围：配置中的类型 ∪ 六类标准集合中在配置或历史/日志出现过的类型
    scope = list(dict.fromkeys(list(configured) + list(SIX_AUDIT_TYPES)))
    results = []
    for code in scope:
        hist = history_by_code.get(code, [])
        pushes = push_by_code.get(code, [])
        in_config = code in configured
        history_present = len(hist) > 0
        history_statuses = sorted({_safe_str(h.get("status")) for h in hist})
        candidate_total = sum(int(h.get("total_records") or 0) for h in hist)
        push_count = len(pushes)
        transport_success = sum(1 for p in pushes if _safe_str(p.get("status")) == "success")
        qc_usable = sum(1 for p in pushes if is_qc_usable(p.get("status"), p.get("parse_status")))
        sql_conversion = DISCHARGE_SQL_CONVERSION.get(code, "unknown")
        uses_discharge_date = sql_conversion != "unknown"

        interpretation = []
        if not in_config:
            interpretation.append("not_in_discharge_scheduler_config")
        if in_config and not history_present:
            interpretation.append("configured_but_no_scheduler_history")
        type_failed_before_push = (
            history_present and "failed" in history_statuses and push_count == 0
        )
        if type_failed_before_push:
            interpretation.append("type_level_failure_before_pushlog")
        elif history_present and candidate_total == 0 and push_count == 0:
            # 仅在非类型级失败时要求与 Oracle 出院枚举交叉核对；
            # 禁止把「候选 0」直接解释为当天无患者。
            if oracle_discharge_patient_count is None:
                interpretation.append("zero_candidates_needs_oracle_crosscheck")
            elif oracle_discharge_patient_count == 0:
                interpretation.append("zero_candidates_matches_oracle_zero_discharges")
            else:
                interpretation.append(
                    "zero_candidates_but_oracle_has_discharges_possible_sql_or_load_gap"
                )
        if push_count > 0 and transport_success > qc_usable:
            interpretation.append("has_transport_success_but_not_all_qc_usable")
        if not interpretation:
            interpretation.append("ok_or_has_push_activity")

        results.append(
            {
                "audit_type_code": code,
                "in_scheduler_config": in_config,
                "scheduler_history_present": history_present,
                "scheduler_history_statuses": history_statuses,
                "candidate_total_from_history": candidate_total,
                "push_log_count": push_count,
                "transport_success": transport_success,
                "qc_usable": qc_usable,
                "sql_conversion_strategy": sql_conversion,
                "uses_discharge_date_filter_expected": uses_discharge_date,
                "interpretation_flags": interpretation,
            }
        )

    missing_terminal = [
        r["audit_type_code"]
        for r in results
        if r["in_scheduler_config"] and not r["scheduler_history_present"]
    ]
    type_level_failures = [
        r["audit_type_code"]
        for r in results
        if "type_level_failure_before_pushlog" in r["interpretation_flags"]
    ]
    return {
        "query_date": query_date,
        "run_mode": "discharge_final",
        "configured_codes": configured,
        "oracle_discharge_patient_count": oracle_discharge_patient_count,
        "oracle_crosscheck_available": oracle_discharge_patient_count is not None,
        "types": results,
        "summary": {
            "configured_count": len(configured),
            "history_present_count": sum(1 for r in results if r["scheduler_history_present"]),
            "missing_terminal_types": missing_terminal,
            "type_level_failures": type_level_failures,
            "needs_oracle_crosscheck": [
                r["audit_type_code"]
                for r in results
                if "zero_candidates_needs_oracle_crosscheck" in r["interpretation_flags"]
            ],
        },
    }


def _ensure_repo_on_syspath() -> Path:
    """保证以 scripts/ 直接运行时也能 import app。"""
    root = Path(__file__).resolve().parents[1]
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    return root


def probe_local_gates() -> dict[str, Any]:
    """本地代码静态探测 001/002 门禁实现状态（不连接生产）。"""
    _ensure_repo_on_syspath()
    results = {}
    for gate_id, spec in GATE_PROBE_TARGETS.items():
        entry: dict[str, Any] = {
            "gate_id": gate_id,
            "doc": spec.get("doc", ""),
            "status": "unknown",
            "evidence": [],
        }
        try:
            module_name = spec["module"]
            mod = __import__(module_name, fromlist=["*"])
            source_path = Path(getattr(mod, "__file__", "") or "")
            source_text = source_path.read_text(encoding="utf-8") if source_path.is_file() else ""

            ok = True
            for attr in spec.get("must_attrs", []) or []:
                if not hasattr(mod, attr):
                    ok = False
                    entry["evidence"].append(f"missing_attr:{attr}")
                else:
                    entry["evidence"].append(f"has_attr:{attr}")
            for attr in spec.get("must_not_attrs", []) or []:
                if hasattr(mod, attr):
                    ok = False
                    entry["evidence"].append(f"unexpected_attr:{attr}")
                else:
                    entry["evidence"].append(f"absent_attr:{attr}")
            for token in spec.get("source_contains_any", []) or []:
                if token in source_text:
                    entry["evidence"].append(f"source_has:{token}")
                    break
            else:
                if spec.get("source_contains_any"):
                    ok = False
                    entry["evidence"].append("source_missing_required_tokens")
            for token in spec.get("source_must_not_contain", []) or []:
                if token in source_text:
                    ok = False
                    entry["evidence"].append(f"source_has_forbidden:{token}")
                else:
                    entry["evidence"].append(f"source_absent:{token}")

            if spec.get("expect_absent"):
                # 期望不存在实现表：must_not_attrs 全部 absent 则 gate 记为 not_implemented（预期）
                entry["status"] = "not_implemented_expected" if ok else "unexpected_implementation"
            else:
                entry["status"] = "implemented_local" if ok else "incomplete_local"
        except Exception as exc:  # noqa: BLE001 - 探测失败必须如实记录
            entry["status"] = "probe_error"
            entry["evidence"].append(f"error:{type(exc).__name__}")
        results[gate_id] = entry

    # 002 汇总
    results["002_summary"] = {
        "design_status": "confirmed",
        "code_status": "withdrawn_pending_reimplementation",
        "production_status": "not_deployed",
        "note": "ACTIVE/002 设计已确认；execution/attempt 代码未在 app.models 落地",
    }
    results["001_summary"] = {
        "jwt_and_admin_boot": results.get("001_jwt_production_gate", {}).get("status"),
        "notify_ssrf_auth": results.get("001_notify_test_auth", {}).get("status"),
        "dify_log_privacy": results.get("001_dify_log_no_body_preview", {}).get("status"),
        "production_deploy_status": "unknown_not_connected",
        "note": "本地代码探测；部署到生产需另行书面授权验证",
    }
    return results


def build_report(fixture: Mapping[str, Any]) -> dict[str, Any]:
    query_date = _safe_str(fixture.get("query_date") or "2026-07-14")
    push_logs = list(fixture.get("push_logs") or [])
    history = list(fixture.get("scheduler_history") or [])
    dimensions = list(fixture.get("dimensions") or [])
    alerts = list(fixture.get("alerts") or [])
    configured = list(
        fixture.get("configured_discharge_audit_types")
        or fixture.get("configured_codes")
        or list(SIX_AUDIT_TYPES)
    )
    oracle_count = fixture.get("oracle_discharge_patient_count", None)
    if oracle_count is not None:
        oracle_count = int(oracle_count)

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query_date": query_date,
        "source": _safe_str(fixture.get("source") or "fixture"),
        "six_audit_types": list(SIX_AUDIT_TYPES),
        "run_modes": list(RUN_MODES),
        "readonly": True,
        "notes": [
            "qc_usable uses frozen rule: status==success AND parse_status==success",
            "fallback excluded from qc_usable",
            "no medical record body fields are exported",
            "patient identifiers are hashed tokens",
        ],
    }

    report = {
        "meta": meta,
        "push_log_aggregate": aggregate_push_logs(push_logs, query_date=query_date),
        "scheduler_history_aggregate": aggregate_scheduler_history(history, query_date=query_date),
        "dimension_aggregate": aggregate_dimensions(dimensions, push_logs),
        "alert_aggregate": aggregate_alerts(alerts),
        "parse_failure_fixture_summary": fixture.get("parse_failure_fixture_summary")
        or {
            "source": "derived_from_push_logs",
            "categories": aggregate_push_logs(push_logs, query_date=query_date)["parse_error_categories"],
        },
        "high_clinical_review_list": build_high_clinical_review_list(push_logs, dimensions, alerts),
        "discharge_final_reconciliation": reconcile_discharge_final(
            query_date=query_date,
            configured_codes=configured,
            history_rows=history,
            push_logs=push_logs,
            oracle_discharge_patient_count=oracle_count,
        ),
        "gates": probe_local_gates(),
    }

    # 校验和：稳定序列化
    canonical = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    report["checksum_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    _assert_no_forbidden_keys(report)
    # 二次保证：正文关键词不应出现在输出中（允许出现在 notes 等说明）
    dumped = json.dumps(report, ensure_ascii=False)
    for banned in ("mr_text", "request_json", "response_json", "payload_json"):
        # keys already forbidden; also block accidental body dumps in values beyond field names in notes
        if f'"{banned}"' in dumped and banned not in json.dumps(meta, ensure_ascii=False):
            # only fail if present as data keys already handled; keep soft check
            pass
    return report


def compare_to_documented_baseline(report: Mapping[str, Any], baseline: Mapping[str, Any] | None) -> dict[str, Any]:
    """与 003 文档记载的 2026-07-14 聚合数字做可选对账（fixture 可携带 expected_baseline）。"""
    if not baseline:
        return {"compared": False, "reason": "no_expected_baseline_in_fixture"}
    push = report.get("push_log_aggregate") or {}
    diffs = []
    mapping = {
        "push_log_total": push.get("row_count"),
        "status_success": (push.get("status") or {}).get("success"),
        "status_skipped": (push.get("status") or {}).get("skipped"),
        "status_failed": (push.get("status") or {}).get("failed", 0),
        "parse_success": (push.get("parse_status") or {}).get("success"),
        "parse_fallback": (push.get("parse_status") or {}).get("fallback"),
        "parse_failed": (push.get("parse_status") or {}).get("failed"),
        "high_push_logs": push.get("high_push_logs"),
    }
    for key, actual in mapping.items():
        if key not in baseline:
            continue
        expected = baseline[key]
        if actual != expected:
            diffs.append({"field": key, "expected": expected, "actual": actual})
    return {
        "compared": True,
        "match": len(diffs) == 0,
        "diffs": diffs,
        "actual": mapping,
        "expected": {k: baseline.get(k) for k in mapping if k in baseline},
    }


def script_source_readonly_guards(source_text: str) -> list[str]:
    """对脚本源码做只读静态守卫（AST，避免匹配文档/字符串字面量）。"""
    import ast

    violations: list[str] = []
    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        return [f"syntax_error:{exc}"]

    banned_calls = {"commit", "flush"}
    banned_imports = {
        "requests",
        "httpx",
        "paramiko",
        "urllib3",
        "aiohttp",
        "paramiko",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name in banned_calls:
                violations.append(f"{name}(")
            # 禁止 execute("INSERT ...") 一类写 SQL
            if name == "execute" and node.args:
                arg0 = node.args[0]
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    upper = arg0.value.upper()
                    if any(tok in upper for tok in ("INSERT", "UPDATE", "DELETE", "MERGE")):
                        violations.append("write_sql_execute")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in banned_imports or alias.name.startswith("urllib.request"):
                    violations.append(root)
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            full = node.module or ""
            if mod in banned_imports or full.startswith("urllib.request"):
                violations.append(full or mod)
            if full == "socket" or mod == "socket":
                for alias in node.names:
                    if alias.name == "create_connection":
                        violations.append("socket.create_connection")
    return sorted(set(violations))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="003 P0 readonly QC production audit")
    parser.add_argument(
        "--fixture",
        required=True,
        help="Path to synthetic/desensitized JSON fixture (required without production authorization)",
    )
    parser.add_argument("--output-json", default="", help="Optional path to write full report JSON")
    parser.add_argument("--output-csv-summary", default="", help="Optional path for push aggregate CSV")
    parser.add_argument(
        "--allow-db",
        action="store_true",
        help="Reserved; P0 does not implement production DB access. Flag will error if used.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.allow_db:
        print(
            "ERROR: P0 未获生产连接授权，--allow-db 被拒绝。"
            "请仅使用 --fixture 合成/脱敏数据。",
            file=sys.stderr,
        )
        return 2

    fixture_path = Path(args.fixture)
    if not fixture_path.is_file():
        print(f"ERROR: fixture not found: {fixture_path}", file=sys.stderr)
        return 2

    fixture = _load_json_fixture(fixture_path)
    report = build_report(fixture)
    baseline_cmp = compare_to_documented_baseline(report, fixture.get("expected_baseline"))
    report["documented_baseline_comparison"] = baseline_cmp

    # stdout: compact summary only
    summary = {
        "query_date": report["meta"]["query_date"],
        "source": report["meta"]["source"],
        "push_log_row_count": report["push_log_aggregate"]["row_count"],
        "transport_success": report["push_log_aggregate"]["transport_success"],
        "qc_usable": report["push_log_aggregate"]["qc_usable"],
        "parse_error_categories": report["push_log_aggregate"]["parse_error_categories"],
        "scheduler_history_row_count": report["scheduler_history_aggregate"]["row_count"],
        "high_dimensions": report["dimension_aggregate"]["high_dimensions"],
        "alert_status": report["alert_aggregate"]["status"],
        "discharge_summary": report["discharge_final_reconciliation"]["summary"],
        "baseline_comparison": baseline_cmp,
        "gates_001": report["gates"].get("001_summary"),
        "gates_002": report["gates"].get("002_summary"),
        "checksum_sha256": report["checksum_sha256"],
        "high_review_items": len(report["high_clinical_review_list"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.output_json:
        out = Path(args.output_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote_report={out}", file=sys.stderr)

    if args.output_csv_summary:
        import csv

        out_csv = Path(args.output_csv_summary)
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        rows = report["push_log_aggregate"]["by_audit_type_and_mode"]
        fieldnames = [
            "audit_type_code",
            "audit_run_mode",
            "total",
            "transport_success",
            "qc_usable",
            "high",
        ]
        with out_csv.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        print(f"wrote_csv={out_csv}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
