"""事件状态机（病历时效质控 T3）。

取值与 app/timeliness/models.py 的 EVENT_STATUSES 保持一致（本模块不得
引入 sqlalchemy 依赖，状态常量各自声明、由测试保证同步）。

状态语义（主设计文档 §15 T3 第 4 条）：
- 未完成且 now < deadline - warn          → PENDING
- 未完成且进入预警窗（deadline-warn ≤ now ≤ deadline）→ WARNING
- 未完成且 now > deadline                  → OVERDUE
- 审批日志 flag=1（已申请解锁）            → APPLYING
- 审批日志 flag=2（审批通过）              → APPROVED
- 完成时间 ≤ deadline                      → COMPLETED_ON_TIME（终态）
- 完成时间 > deadline                      → COMPLETED_LATE（终态）
- 出院/删除/转出导致不再适用               → CANCELLED（终态）
- 豁免                                     → EXEMPT（终态）

转换表为常量字典；非法转换抛 IllegalStatusTransition。终态
（COMPLETED_*、CANCELLED、EXEMPT）无出边，不再改变。
APPLYING 允许回退到时钟态（PENDING/WARNING/OVERDUE）：申请记录随扫描窗口
变化可能暂时缺位，时钟态是随时可重算的派生态；APPROVED 是已成立的审批
决定，只有完成/取消/豁免能终结它。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.timeliness.engine.deadline import to_datetime

PENDING = "PENDING"
WARNING = "WARNING"
OVERDUE = "OVERDUE"
APPLYING = "APPLYING"
APPROVED = "APPROVED"
COMPLETED_ON_TIME = "COMPLETED_ON_TIME"
COMPLETED_LATE = "COMPLETED_LATE"
CANCELLED = "CANCELLED"
EXEMPT = "EXEMPT"

EVENT_STATUSES = (
    PENDING,
    WARNING,
    OVERDUE,
    APPLYING,
    APPROVED,
    COMPLETED_ON_TIME,
    COMPLETED_LATE,
    CANCELLED,
    EXEMPT,
)

TERMINAL_STATUSES = frozenset({COMPLETED_ON_TIME, COMPLETED_LATE, CANCELLED, EXEMPT})

# 状态转换表：from → 允许的 to 集合（终态无出边）。
# 2026-11-14 P0 修复：WARNING/OVERDUE 允许回退 PENDING、OVERDUE 允许回退
# WARNING——排台顺延（SM.SCHEDULED_DATE_TIME 改期）或管理员放宽 limit_minutes
# 时 deadline 后移，时钟派生态重算出更早状态属合法回退（与 APPLYING 同理：
# 时钟态随时可重算；终态与 APPROVED 保护不变）。回退 PENDING 时扫描层同步
# 清空 warn_sent_at（见 scanner._persist_results），确保重新临期可再发预警。
STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    PENDING: frozenset(
        {WARNING, OVERDUE, APPLYING, APPROVED, COMPLETED_ON_TIME, COMPLETED_LATE, CANCELLED, EXEMPT}
    ),
    WARNING: frozenset(
        {PENDING, OVERDUE, APPLYING, APPROVED, COMPLETED_ON_TIME, COMPLETED_LATE, CANCELLED, EXEMPT}
    ),
    OVERDUE: frozenset(
        {PENDING, WARNING, APPLYING, APPROVED, COMPLETED_ON_TIME, COMPLETED_LATE, CANCELLED, EXEMPT}
    ),
    APPLYING: frozenset(
        {PENDING, WARNING, OVERDUE, APPROVED, COMPLETED_ON_TIME, COMPLETED_LATE, CANCELLED, EXEMPT}
    ),
    APPROVED: frozenset({COMPLETED_ON_TIME, COMPLETED_LATE, CANCELLED, EXEMPT}),
    COMPLETED_ON_TIME: frozenset(),
    COMPLETED_LATE: frozenset(),
    CANCELLED: frozenset(),
    EXEMPT: frozenset(),
}


class IllegalStatusTransition(ValueError):
    """非法状态转换（不在 STATUS_TRANSITIONS 表内）。"""


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def transition(from_status: str, to_status: str, *, reason: str = "") -> str:
    """校验一次状态转换并返回目标状态。

    - from == to 视为无变化，直接返回（扫描重算会反复得到同一状态）；
    - 不在转换表内的转换抛 IllegalStatusTransition；
    - 未知状态（不在 EVENT_STATUSES 内）同样抛错。
    """
    if from_status not in EVENT_STATUSES:
        raise IllegalStatusTransition(f"未知状态: {from_status!r}")
    if to_status not in EVENT_STATUSES:
        raise IllegalStatusTransition(f"未知状态: {to_status!r}")
    if from_status == to_status:
        return from_status
    if to_status not in STATUS_TRANSITIONS[from_status]:
        raise IllegalStatusTransition(
            f"非法状态转换: {from_status} -> {to_status}" + (f"（{reason}）" if reason else "")
        )
    return to_status


def normalize_approval_flag(flag: Any) -> str | None:
    """规整审批标志：1/‘1’→'1'（申请中），2/'2'→'2'（通过），其余/空→None（不参与判定）。"""
    if flag is None:
        return None
    text = str(flag).strip()
    if not text:
        return None
    try:
        number = str(int(text))
    except ValueError:
        return None
    if number == "1":
        return "1"
    if number == "2":
        return "2"
    return None


def derive_status(
    *,
    now: Any,
    deadline: Any,
    warn_before_minutes: int | None = None,
    completed_at: Any = None,
    cancelled: bool = False,
    exempt: bool = False,
    approval_flag: Any = None,
    previous_status: str | None = None,
) -> str:
    """根据事实推导目标状态（纯函数，不读取转换表以外的任何外部信息）。

    优先级（高→低）：完成 > 取消 > 豁免 > 审批 > 时钟（预警/超时/未到期）。
    previous_status=APPROVED 且无完成/取消/豁免时保持 APPROVED（审批决定不因
    申请日志滑出扫描窗口而失效）；终态由调用方先行保护，本函数不重复处理。
    """
    completed = to_datetime(completed_at)
    dl = to_datetime(deadline)

    if completed is not None:
        if dl is None or completed <= dl:
            return COMPLETED_ON_TIME
        return COMPLETED_LATE
    if cancelled:
        return CANCELLED
    if exempt:
        return EXEMPT
    if previous_status == APPROVED:
        return APPROVED

    flag = normalize_approval_flag(approval_flag)
    if flag == "2":
        return APPROVED
    if flag == "1":
        return APPLYING

    if dl is None:
        return PENDING
    current = to_datetime(now)
    if current is None:
        raise ValueError("now 不能为空")
    if current > dl:
        return OVERDUE
    if warn_before_minutes:
        if isinstance(warn_before_minutes, bool) or not isinstance(warn_before_minutes, int) or warn_before_minutes < 0:
            raise ValueError(f"warn_before_minutes 须为非负整数或 None: {warn_before_minutes!r}")
        warn_at = dl - timedelta(minutes=warn_before_minutes)
        if current >= warn_at:
            return WARNING
    return PENDING
