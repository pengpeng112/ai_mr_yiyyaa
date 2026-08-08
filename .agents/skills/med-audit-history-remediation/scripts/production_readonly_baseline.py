"""生产应用库阶段 0 基线；只输出聚合统计，不输出患者标识或病历内容。

覆盖：
- 顶层/维度层 high/red 并集
- 证据字段路径盘点（evidence 数组空但 content/extra 有内容）
- 形式门槛 formally_qualified / formally_unqualified（从库行还原 dim 后跑 _qualified_high_risk_issue）
- 可选语义 shadow 候选降级计数（不改库、不输出原文）
- push_time 范围（Oracle 友好）与 query_date 范围
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# 允许从技能目录直接执行，无需调用者额外设置 PYTHONPATH。
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import func, or_

from app.database import SessionLocal
from app.models import AuditDimensionResult, PushLog, QCRecordAlertLog
from app.services.dify_schema_parser import (
    _high_risk_rejection_reasons,
    _qualified_high_risk_issue,
)


SIX_CODES = {
    "admission_vs_first_progress", "discharge_vs_frontpage", "surgery_chain",
    "progress_vs_nursing", "jyjc_vs_bcnursing", "syssvsscbc",
}


def _empty(value) -> bool:
    return value is None or not str(value).strip()


def _loads(raw: Any, fallback: Any):
    if raw in (None, ""):
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


def _patient_info(raw: str) -> dict:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    info = data.get("patient_info", {}) if isinstance(data, dict) else {}
    return info if isinstance(info, dict) else {}


def _chunks(values: set[int], size: int = 900):
    ordered = sorted(values)
    for start in range(0, len(ordered), size):
        yield ordered[start:start + size]


def _evidence_from_extra(extra: dict[str, Any], side: str) -> list[str]:
    """从结构化 issues 或 mapper 保留的 legacy 扩展恢复一侧证据。"""
    issue_key = "evidence_a" if side == "medical" else "evidence_b"
    values = []
    issues = extra.get("issues") if isinstance(extra.get("issues"), list) else []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        value = issue.get(issue_key)
        if isinstance(value, list):
            values.extend(str(item).strip() for item in value if str(item or "").strip())
        elif str(value or "").strip():
            values.append(str(value).strip())
    if values:
        return values
    legacy = extra.get(f"{side}_evidence_legacy")
    if isinstance(legacy, list):
        return [str(item).strip() for item in legacy if str(item or "").strip()]
    return [str(legacy).strip()] if str(legacy or "").strip() else []


def _evidence_list_from_row(
    evidence_json: Any, content: Any, extra: dict[str, Any], side: str
) -> list[str]:
    """按数组列、content、extra 的顺序恢复门槛用证据。"""
    arr = _loads(evidence_json, [])
    if isinstance(arr, list) and any(str(x or "").strip() for x in arr):
        return [str(x) for x in arr if str(x or "").strip()]
    text = str(content or "").strip()
    return [text] if text else _evidence_from_extra(extra, side)


def _dim_dict_from_orm(row: AuditDimensionResult) -> dict[str, Any]:
    extra = _loads(getattr(row, "extra_json", None), {})
    if not isinstance(extra, dict):
        extra = {}
    return {
        "dimension_code": getattr(row, "dimension_code", "") or "",
        "dimension": getattr(row, "dimension", "") or "",
        "status": getattr(row, "status", "") or "",
        "severity": (getattr(row, "severity", "") or "").lower(),
        "alert_level": (getattr(row, "alert_level", "") or "").lower(),
        "confidence": float(getattr(row, "confidence", 0) or 0),
        "medical_evidence": _evidence_list_from_row(
            getattr(row, "medical_evidence_json", None),
            getattr(row, "medical_content", None),
            extra,
            "medical",
        ),
        "nursing_evidence": _evidence_list_from_row(
            getattr(row, "nursing_evidence_json", None),
            getattr(row, "nursing_content", None),
            extra,
            "nursing",
        ),
        "medical_content": getattr(row, "medical_content", "") or "",
        "nursing_content": getattr(row, "nursing_content", "") or "",
        "extra": extra,
    }


def _json_array_empty(raw: Any) -> bool:
    data = _loads(raw, [])
    if not isinstance(data, list):
        return True
    return not any(str(x or "").strip() for x in data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Med-Audit production read-only baseline")
    parser.add_argument("--apply", action="store_true", help="始终拒绝；本脚本无写入能力")
    parser.add_argument("--skip-request-json", action="store_true", help="跳过慢速 CLOB 扫描，仅取应用库快速基线")
    parser.add_argument(
        "--skip-formal-gate",
        action="store_true",
        help="跳过形式门槛重算（仅计数与证据路径盘点）",
    )
    parser.add_argument(
        "--include-semantic-shadow",
        action="store_true",
        help="对 formally_qualified 再跑 semantic shadow 聚合（仍只读）",
    )
    args = parser.parse_args()
    if args.apply:
        parser.error("阶段 0 脚本禁止 --apply")

    db = SessionLocal()
    try:
        top_filter = or_(func.lower(PushLog.severity) == "high", func.lower(PushLog.alert_level) == "red")
        dim_filter = or_(
            func.lower(AuditDimensionResult.severity) == "high",
            func.lower(AuditDimensionResult.alert_level) == "red",
        )
        top_ids = {row[0] for row in db.query(PushLog.id).filter(top_filter).all()}
        dim_ids = {
            row[0]
            for row in db.query(AuditDimensionResult.push_log_id).filter(dim_filter).distinct().all()
        }
        union_ids = top_ids | dim_ids

        code_counts = Counter()
        parse_counts = Counter()
        reviewed_counts = Counter()
        date_values: list[str] = []
        push_time_values: list[str] = []
        log_code_by_id: dict[int, str] = {}

        for id_batch in _chunks(union_ids):
            for row_id, code, parse_status, reviewed, query_date, push_time in db.query(
                PushLog.id,
                PushLog.audit_type_code,
                PushLog.parse_status,
                PushLog.reviewed_flag,
                PushLog.query_date,
                PushLog.push_time,
            ).filter(PushLog.id.in_(id_batch)).all():
                code_s = str(code or "<empty>")
                code_counts[code_s] += 1
                parse_counts[str(parse_status or "<empty>")] += 1
                reviewed_counts[str(reviewed or 0)] += 1
                log_code_by_id[int(row_id)] = str(code or "")
                if query_date:
                    date_values.append(str(query_date))
                if push_time:
                    push_time_values.append(str(push_time))

        alert_counts = Counter()
        for id_batch in _chunks(union_ids):
            alert_counts.update(
                str(status or "<empty>")
                for (status,) in db.query(QCRecordAlertLog.status)
                .filter(QCRecordAlertLog.push_log_id.in_(id_batch)).all()
            )

        # ---- 证据路径 + 形式门槛（仅 high/red 维度）----
        evidence_path = Counter()
        formal = Counter()
        rejection = Counter()
        safety_cat = Counter()
        dim_by_type = Counter()
        semantic_shadow = Counter()
        high_dim_total = 0

        high_dims = db.query(AuditDimensionResult).filter(dim_filter).all()
        for dim_row in high_dims:
            high_dim_total += 1
            pl_id = int(getattr(dim_row, "push_log_id", 0) or 0)
            audit_code = log_code_by_id.get(pl_id, "")
            if not audit_code:
                # 维度在 union 外的顶层非 high 日志上极少见；补查一次
                audit_code = (
                    db.query(PushLog.audit_type_code)
                    .filter(PushLog.id == pl_id)
                    .scalar()
                ) or ""
                audit_code = str(audit_code)
            dim_by_type[audit_code or "<empty>"] += 1

            med_ev_empty = _json_array_empty(getattr(dim_row, "medical_evidence_json", None))
            nur_ev_empty = _json_array_empty(getattr(dim_row, "nursing_evidence_json", None))
            med_content = not _empty(getattr(dim_row, "medical_content", None))
            nur_content = not _empty(getattr(dim_row, "nursing_content", None))
            extra = _loads(getattr(dim_row, "extra_json", None), {})
            issues = extra.get("issues") if isinstance(extra, dict) else None
            has_issues = isinstance(issues, list) and any(isinstance(i, dict) for i in issues)

            if med_ev_empty and nur_ev_empty:
                evidence_path["both_evidence_json_empty"] += 1
            if med_ev_empty and med_content:
                evidence_path["med_evidence_empty_but_content"] += 1
            if nur_ev_empty and nur_content:
                evidence_path["nur_evidence_empty_but_content"] += 1
            if has_issues:
                evidence_path["extra_has_issues"] += 1
            else:
                evidence_path["extra_missing_issues"] += 1

            if isinstance(issues, list):
                for issue in issues:
                    if not isinstance(issue, dict):
                        continue
                    cat = str(issue.get("safety_category") or "<empty>")
                    safety_cat[cat] += 1
                    if issue.get("evidence_a") not in (None, "", []):
                        evidence_path["issues_with_evidence_a"] += 1
                    if issue.get("evidence_b") not in (None, "", []):
                        evidence_path["issues_with_evidence_b"] += 1

            if args.skip_formal_gate:
                continue

            dim_dict = _dim_dict_from_orm(dim_row)
            is_high_like = (
                str(dim_dict.get("severity") or "").lower() == "high"
                or str(dim_dict.get("alert_level") or "").lower() == "red"
            )
            if not is_high_like:
                continue

            qualified = _qualified_high_risk_issue(dim_dict, audit_code)
            if qualified is not None:
                formal["formally_qualified"] += 1
                formal[f"qualified__{audit_code or 'empty'}"] += 1
                if args.include_semantic_shadow:
                    try:
                        from app.services.high_risk_semantic_shadow import (
                            evaluate_semantic_high_risk_dim,
                        )
                        shadow = evaluate_semantic_high_risk_dim(dim_dict, audit_code)
                        if shadow.get("should_demote"):
                            semantic_shadow["shadow_should_demote"] += 1
                            for r in shadow.get("reasons") or []:
                                semantic_shadow[f"reason__{r}"] += 1
                        else:
                            semantic_shadow["shadow_keep_candidate"] += 1
                    except Exception as exc:  # noqa: BLE001 — 基线脚本容错
                        semantic_shadow[f"shadow_error__{type(exc).__name__}"] += 1
            else:
                formal["formally_unqualified"] += 1
                formal[f"unqualified__{audit_code or 'empty'}"] += 1
                for reason in _high_risk_rejection_reasons(dim_dict, audit_code):
                    rejection[reason] += 1

        dept = Counter({
            "pushlog_total": db.query(func.count(PushLog.id)).scalar() or 0,
            "pushlog_dept_missing": db.query(func.count(PushLog.id)).filter(
                or_(PushLog.dept.is_(None), PushLog.dept == "")
            ).scalar() or 0,
        })
        json_invalid = 0
        json_rows = [] if args.skip_request_json else db.query(PushLog.request_json).yield_per(500)
        for (raw,) in json_rows:
            info = _patient_info(raw)
            if raw and not info:
                try:
                    json.loads(raw)
                except (TypeError, ValueError):
                    json_invalid += 1
            if _empty(info.get("inpatient_dept_name")):
                dept["inpatient_dept_name_missing"] += 1
            if _empty(info.get("discharge_dept_name")):
                dept["discharge_dept_name_missing"] += 1
            if _empty(info.get("discharge_dept_code")):
                dept["discharge_dept_code_missing"] += 1

        report = {
            "readonly": True,
            "scope": "application_db_only",
            "notes": [
                "formally_qualified 仅表示通过后端复合门槛，不等于临床 keep_high",
                "evidence_json 为空在非 legacy 类型上为常见落库行为，证据多在 content/extra",
                "dept_filtered 不是发送成功",
            ],
            "high": {
                "top_level_pushlogs": len(top_ids),
                "dimension_level_pushlogs": len(dim_ids),
                "union_pushlogs": len(union_ids),
                "high_red_dimensions": high_dim_total,
                "six_type_union": sum(v for k, v in code_counts.items() if k in SIX_CODES),
                "query_date_min": min(date_values) if date_values else "",
                "query_date_max": max(date_values) if date_values else "",
                "push_time_min": min(push_time_values) if push_time_values else "",
                "push_time_max": max(push_time_values) if push_time_values else "",
                "by_audit_type": dict(sorted(code_counts.items())),
                "dimensions_by_audit_type": dict(sorted(dim_by_type.items())),
                "by_parse_status": dict(sorted(parse_counts.items())),
                "by_reviewed_flag": dict(sorted(reviewed_counts.items())),
                "alert_status": dict(sorted(alert_counts.items())),
            },
            "evidence_path": dict(sorted(evidence_path.items())),
            "formal_gate": {
                "skipped": bool(args.skip_formal_gate),
                "counts": dict(sorted(formal.items())),
                "rejection_reasons": dict(sorted(rejection.items())),
                "safety_category_on_issues": dict(sorted(safety_cat.items())),
            },
            "semantic_shadow": {
                "enabled": bool(args.include_semantic_shadow),
                "counts": dict(sorted(semantic_shadow.items())),
            },
            "department_missing": dict(sorted(dept.items())),
            "request_json_scan_skipped": args.skip_request_json,
            "request_json_invalid": json_invalid,
            "pending_separate_checks": [
                "V_QYBR patient_id+visit_number duplicate-key aggregate",
                "V_QYBR match/no-match/ambiguous/conflict dry-run",
                "clinical keep_high requires prompt rules + human approval beyond formal_gate",
            ],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
