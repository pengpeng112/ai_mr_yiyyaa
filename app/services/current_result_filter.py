"""业务当前结果过滤器（ACTIVE/007 工作包 F / 009 P0-2）。

默认隐藏：
- 已被 supersede 的历史版本
- status=discarded 的审计占位
- contract_valid=0/false 的契约失败结果（不得作为业务当前结果）

历史 NULL contract_valid 兼容为可用；管理审计可 include_superseded=True 查看全量。
"""

from __future__ import annotations

from sqlalchemy import or_

from app.models import PushLog


def apply_current_result_filter(query, include_superseded: bool = False):
    """对 PushLog 查询应用"仅当前结果"过滤。

    Args:
        query: SQLAlchemy Query[PushLog]
        include_superseded: True 时不过滤（管理审计/替代链）
    """
    if include_superseded:
        return query
    return query.filter(
        PushLog.superseded_by.is_(None),
        PushLog.status != "discarded",
        # contract_valid: NULL=历史兼容通过；1/True=通过；0/False=不可见
        or_(PushLog.contract_valid.is_(None), PushLog.contract_valid == 1),
    )


def is_current_result(push_log) -> bool:
    """判断单条 PushLog 是否为业务当前结果。"""
    if getattr(push_log, "superseded_by", None) is not None:
        return False
    if str(getattr(push_log, "status", "") or "").strip() == "discarded":
        return False
    cv = getattr(push_log, "contract_valid", None)
    if cv is False or cv == 0:
        return False
    return True
