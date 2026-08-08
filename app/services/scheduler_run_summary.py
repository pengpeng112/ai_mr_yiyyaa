"""调度运行完整性汇总（003 工作包 A，方案 B：API 派生，无父 run 表）。"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy.orm import Session

from app.models import AuditDimensionResult, PushLog, QCRecordAlertLog, SchedulerHistory
from app.services.qc_status_semantics import is_qc_usable, is_transport_success

_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(password|passwd|pwd)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(jdbc:|oracle\+|postgres(ql)?://)\S+"),
    re.compile(r"(?i)\b(SELECT|INSERT|UPDATE|DELETE|WITH)\b[\s\S]{0,400}"),
]


def sanitize_error_summary(message: Any, *, max_len: int = 240) -> str:
    """错误摘要脱敏：去掉口令、连接串、长 SQL；不输出患者标识与病历正文。"""
    text = str(message or "").strip()
    if not text:
        return ""
    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub("[redacted]", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _as_code(value: Any) -> str:
    return str(value or "").strip()


def derive_overall_run_status(
    *,
    configured_codes: Sequence[str],
    type_statuses: Mapping[str, str],
    lock_running: bool = False,
) -> str:
    """
    completed: 配置类型全部有终态且无 failed
    partial: 任一类型 failed 或缺少终态，但仍有其他类型终态
    failed: 配置类型均 failed，或全部缺失且有失败信号
    running: 锁占用且结果不完整
    unknown: 无法判定
    """
    codes = [_as_code(c) for c in configured_codes if _as_code(c)]
    if not codes:
        if lock_running:
            return "running"
        if type_statuses:
            if any(s == "failed" for s in type_statuses.values()):
                return "partial" if any(s == "completed" for s in type_statuses.values()) else "failed"
            return "completed" if type_statuses else "unknown"
        return "unknown"

    missing = [c for c in codes if c not in type_statuses]
    failed = [c for c in codes if type_statuses.get(c) == "failed"]
    completed = [c for c in codes if type_statuses.get(c) == "completed"]
    terminal = [c for c in codes if c in type_statuses]

    if lock_running and (missing or failed):
        return "running"
    if failed and len(failed) == len(codes) and not missing:
        return "failed"
    if failed or missing:
        if completed or (terminal and len(terminal) < len(codes)):
            return "partial"
        if failed and not completed:
            return "failed" if not missing else "partial"
        return "partial"
    return "completed"


def _pick_latest_history_per_type(
    rows: Sequence[SchedulerHistory],
) -> dict[str, SchedulerHistory]:
    latest: dict[str, SchedulerHistory] = {}
    for row in rows:
        code = _as_code(getattr(row, "audit_type_code", ""))
        if not code or code.startswith("__"):
            continue
        prev = latest.get(code)
        if prev is None:
            latest[code] = row
            continue
        prev_rt = getattr(prev, "run_time", None) or datetime.min
        cur_rt = getattr(row, "run_time", None) or datetime.min
        if cur_rt >= prev_rt:
            latest[code] = row
    return latest


def _history_rows_for_mode_window(
    history_rows: Sequence[SchedulerHistory],
    mode_push_rows: Sequence[PushLog],
    other_mode_push_rows: Sequence[PushLog],
    *,
    window_minutes: int = 60,
) -> tuple[list[SchedulerHistory], str]:
    """用带 run_mode 的 PushLog 时间窗保守归属无 run_mode 的历史。

    SchedulerHistory 目前没有 run_mode。没有本模式锚点或两种模式窗口重叠时，
    宁可返回 unavailable/ambiguous，也不能把另一模式历史误判为本模式。
    """
    anchors = [getattr(row, "push_time", None) for row in mode_push_rows]
    anchors = [value for value in anchors if isinstance(value, datetime)]
    if not anchors:
        return [], "unavailable_no_mode_push_anchor"

    margin = timedelta(minutes=max(int(window_minutes or 0), 1))
    start = min(anchors) - margin
    end = max(anchors) + margin

    other_anchors = [getattr(row, "push_time", None) for row in other_mode_push_rows]
    other_anchors = [value for value in other_anchors if isinstance(value, datetime)]
    if other_anchors:
        other_start = min(other_anchors) - margin
        other_end = max(other_anchors) + margin
        if start <= other_end and other_start <= end:
            return [], "ambiguous_overlapping_mode_windows"

    selected = []
    for row in history_rows:
        run_time = getattr(row, "run_time", None)
        if isinstance(run_time, datetime) and start <= run_time <= end:
            selected.append(row)
    if not selected:
        return [], "unavailable_no_history_in_mode_window"
    return selected, "push_time_window"


def _history_rows_for_mode(
    history_rows: Sequence[SchedulerHistory],
    mode: str,
    mode_push_rows: Sequence[PushLog],
    other_mode_push_rows: Sequence[PushLog],
) -> tuple[list[SchedulerHistory], str]:
    explicit = [
        row for row in history_rows
        if _as_code(getattr(row, "audit_run_mode", "")) == mode
    ]
    if explicit:
        return explicit, "scheduler_history_run_mode"
    legacy = [
        row for row in history_rows
        if not _as_code(getattr(row, "audit_run_mode", ""))
    ]
    return _history_rows_for_mode_window(
        legacy,
        mode_push_rows,
        other_mode_push_rows,
        window_minutes=20,
    )


def _count_push_stats(logs: Sequence[PushLog]) -> dict[str, Any]:
    status_c: Counter = Counter()
    parse_c: Counter = Counter()
    skip_c: Counter = Counter()
    transport = 0
    usable = 0
    high = 0
    for log in logs:
        st = _as_code(getattr(log, "status", ""))
        ps = _as_code(getattr(log, "parse_status", ""))
        status_c[st or "(empty)"] += 1
        parse_c[ps or "(empty)"] += 1
        sk = _as_code(getattr(log, "skip_reason", ""))
        if sk:
            skip_c[sk] += 1
        if is_transport_success(st):
            transport += 1
        if is_qc_usable(st, ps):
            usable += 1
        if _as_code(getattr(log, "severity", "")).lower() == "high":
            high += 1
    return {
        "push_log_count": len(logs),
        "status": dict(status_c),
        "parse_status": dict(parse_c),
        "skip_reason": dict(skip_c),
        "transport_success": transport,
        "parse_success": int(parse_c.get("success", 0)),
        "parse_fallback": int(parse_c.get("fallback", 0)),
        "parse_failed": int(parse_c.get("failed", 0)),
        "qc_usable": usable,
        "high": high,
    }


def _count_alerts(db: Session, push_log_ids: Sequence[int]) -> dict[str, int]:
    if not push_log_ids:
        return {
            "pending": 0,
            "sending": 0,
            "success": 0,
            "failed": 0,
            "dept_filtered": 0,
            "suppressed": 0,
            "total": 0,
        }
    rows = (
        db.query(QCRecordAlertLog.status)
        .filter(QCRecordAlertLog.push_log_id.in_(list(push_log_ids)))
        .all()
    )
    counter: Counter = Counter()
    for (status,) in rows:
        counter[_as_code(status) or "(empty)"] += 1
    return {
        "pending": int(counter.get("pending", 0)),
        "sending": int(counter.get("sending", 0)),
        "success": int(counter.get("success", 0)),
        "failed": int(counter.get("failed", 0)),
        "dept_filtered": int(counter.get("dept_filtered", 0)),
        "suppressed": int(counter.get("suppressed", 0)),
        "total": int(sum(counter.values())),
    }


def build_scheduler_run_summary(
    db: Session,
    *,
    query_date: str,
    audit_run_mode: str,
    configured_codes: Sequence[str] | None = None,
    lock_running: bool = False,
    window_hours: int = 36,
) -> dict[str, Any]:
    """按 query_date + 配置类型集合派生一次调度完整性摘要。"""
    mode = _as_code(audit_run_mode) or "daily_increment"
    qdate = _as_code(query_date)
    codes = [_as_code(c) for c in (configured_codes or []) if _as_code(c)]
    codes = list(dict.fromkeys(codes))

    history_q = db.query(SchedulerHistory).filter(
        SchedulerHistory.query_date == qdate,
        SchedulerHistory.trigger_type == "auto",
    )
    all_history_rows = history_q.order_by(SchedulerHistory.run_time.desc()).all()

    all_push_rows = db.query(PushLog).filter(PushLog.query_date == qdate).all()
    push_rows = [row for row in all_push_rows if _as_code(getattr(row, "audit_run_mode", "")) == mode]
    other_push_rows = [row for row in all_push_rows if _as_code(getattr(row, "audit_run_mode", "")) not in {"", mode}]
    history_rows, history_attribution = _history_rows_for_mode(
        all_history_rows,
        mode,
        push_rows,
        other_push_rows,
    )
    latest_by_type = _pick_latest_history_per_type(history_rows)

    # 若未显式传入配置，则用 history 中出现过的类型（仍标记 incomplete 风险）
    config_source = "request"
    if not codes:
        codes = sorted(latest_by_type.keys())
        config_source = "history_inferred"

    type_statuses = {code: _as_code(getattr(row, "status", "")) for code, row in latest_by_type.items()}
    overall = (
        derive_overall_run_status(
            configured_codes=codes,
            type_statuses={c: type_statuses[c] for c in codes if c in type_statuses},
            lock_running=lock_running,
        )
        if history_attribution in {"scheduler_history_run_mode", "push_time_window"}
        else ("running" if lock_running else "unknown")
    )
    incomplete = overall in {"partial", "failed", "running", "unknown"} and bool(codes)

    # PushLog 按类型聚合（限定 run_mode）
    logs_by_type: dict[str, list[PushLog]] = defaultdict(list)
    for log in push_rows:
        logs_by_type[_as_code(getattr(log, "audit_type_code", "")) or "(empty)"].append(log)

    types_out = []
    for code in codes:
        hist = latest_by_type.get(code)
        logs = logs_by_type.get(code, [])
        push_stats = _count_push_stats(logs)
        alert_stats = _count_alerts(db, [int(x.id) for x in logs if getattr(x, "id", None) is not None])
        hist_status = _as_code(getattr(hist, "status", "")) if hist else ""
        candidate_total = int(getattr(hist, "total_records", 0) or 0) if hist else 0
        type_level_failure = bool(hist) and hist_status == "failed" and push_stats["push_log_count"] == 0
        types_out.append(
            {
                "audit_type_code": code,
                "history_present": hist is not None,
                "history_status": hist_status or None,
                "history_run_time": hist.run_time.strftime("%Y-%m-%d %H:%M:%S") if hist and hist.run_time else None,
                "candidate_total": candidate_total,
                "history_success_count": int(getattr(hist, "success_count", 0) or 0) if hist else 0,
                "history_failed_count": int(getattr(hist, "failed_count", 0) or 0) if hist else 0,
                "history_duration_seconds": int(getattr(hist, "duration_seconds", 0) or 0) if hist else 0,
                "history_error_code": _as_code(getattr(hist, "error_code", "")) if hist else "",
                "history_error_msg": sanitize_error_summary(getattr(hist, "error_msg", "")) if hist else "",
                "type_level_failure_before_pushlog": type_level_failure,
                **push_stats,
                "alerts": alert_stats,
                "high_dimensions": _count_high_dimensions(db, [int(x.id) for x in logs if getattr(x, "id", None)]),
            }
        )

    missing_terminal = [c for c in codes if c not in latest_by_type]
    type_level_failures = [
        t["audit_type_code"] for t in types_out if t.get("type_level_failure_before_pushlog")
    ]

    banner = None
    if incomplete:
        reasons = []
        if type_level_failures:
            reasons.append("类型级失败(无 PushLog): " + ", ".join(type_level_failures))
        if missing_terminal:
            reasons.append("缺少终态: " + ", ".join(missing_terminal))
        failed_types = [c for c in codes if type_statuses.get(c) == "failed"]
        if failed_types and not type_level_failures:
            reasons.append("历史 failed: " + ", ".join(failed_types))
        banner = {
            "level": "danger" if overall in {"failed", "partial"} else "warning",
            "title": "本次运行不完整",
            "message": "；".join(reasons) if reasons else f"汇总状态={overall}",
            "hint": "请勿仅以 PushLog failed=0 判断整体成功",
        }

    return {
        "query_date": qdate,
        "audit_run_mode": mode,
        "configured_codes": codes,
        "config_source": config_source,
        "history_attribution": history_attribution,
        "overall_status": overall,
        "incomplete": incomplete,
        "banner": banner,
        "missing_terminal_types": missing_terminal,
        "type_level_failures": type_level_failures,
        "types": types_out,
        "totals": {
            "configured_count": len(codes),
            "history_present_count": sum(1 for t in types_out if t["history_present"]),
            "push_log_count": sum(t["push_log_count"] for t in types_out),
            "transport_success": sum(t["transport_success"] for t in types_out),
            "qc_usable": sum(t["qc_usable"] for t in types_out),
            "parse_failed": sum(t["parse_failed"] for t in types_out),
            "high": sum(t["high"] for t in types_out),
        },
        "notes": [
            "qc_usable = status==success AND parse_status==success",
            "type-level load failures appear as SchedulerHistory failed with zero PushLog",
            "run_mode uses SchedulerHistory.audit_run_mode; legacy rows fall back to PushLog time-window attribution",
            f"history_mode_attribution={history_attribution}",
            f"window_hours={window_hours}",
        ],
    }


def _count_high_dimensions(db: Session, push_log_ids: Sequence[int]) -> int:
    if not push_log_ids:
        return 0
    return int(
        db.query(AuditDimensionResult)
        .filter(
            AuditDimensionResult.push_log_id.in_(list(push_log_ids)),
            AuditDimensionResult.severity == "high",
        )
        .count()
        or 0
    )


def attach_history_item_flags(item: Mapping[str, Any]) -> dict[str, Any]:
    """增强单条 SchedulerHistory 展示字段。"""
    out = dict(item)
    status = _as_code(item.get("status"))
    total = int(item.get("total_records") or 0)
    failed = int(item.get("failed_count") or 0)
    out["type_level_failure_before_pushlog"] = status == "failed" and total == 0
    out["looks_successful_but_zero_candidates"] = status == "completed" and total == 0
    # 明确：PushLog failed=0 不能证明类型成功
    out["cannot_infer_from_pushlog_failed_zero"] = True
    out["failed_count"] = failed
    return out
