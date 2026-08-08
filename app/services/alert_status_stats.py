"""告警状态账实统计（003 工作包 E 可观测性）。"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditDimensionResult, PushLog, QCRecordAlertLog


def build_alert_status_report(
    db: Session,
    *,
    query_date: str | None = None,
    audit_run_mode: str | None = None,
) -> dict[str, Any]:
    push_filters = []
    if query_date:
        push_filters.append(PushLog.query_date == query_date)
    if audit_run_mode:
        push_filters.append(PushLog.audit_run_mode == audit_run_mode)

    usable_filters = [PushLog.status == "success", PushLog.parse_status == "success"]
    high_eligible_logs = int(
        db.query(PushLog.id)
        .filter(*push_filters, *usable_filters, PushLog.severity == "high")
        .count()
        or 0
    )
    high_eligible_dims = int(
        db.query(AuditDimensionResult.id)
        .join(PushLog, PushLog.id == AuditDimensionResult.push_log_id)
        .filter(*push_filters, *usable_filters, AuditDimensionResult.severity == "high")
        .count()
        or 0
    )

    alert_q = db.query(QCRecordAlertLog.status, QCRecordAlertLog.dept)
    if push_filters:
        alert_q = alert_q.join(PushLog, PushLog.id == QCRecordAlertLog.push_log_id).filter(*push_filters)
    alert_rows = alert_q.all()

    status_c: Counter = Counter()
    empty_dept = 0
    for status, dept in alert_rows:
        status_c[str(status or "(empty)")] += 1
        if not str(dept or "").strip():
            empty_dept += 1

    return {
        "query_date": query_date,
        "audit_run_mode": audit_run_mode,
        "high_eligible_push_logs": high_eligible_logs,
        "high_eligible_dimensions": high_eligible_dims,
        "alerts_created": len(alert_rows),
        "alert_status": dict(status_c),
        "empty_dept_alert_rows": empty_dept,
        "notes": [
            "dept_filtered 表示科室白名单过滤，不是发送成功",
            "high_eligible 仅统计 qc_usable 记录",
            "真实企业微信外发需单独批准；本接口只读",
        ],
    }
