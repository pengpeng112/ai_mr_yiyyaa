"""通用提醒通道抽象（T10；主设计文档 §15 T10）。

目标：让「病历时效（TIMELINESS）/ 规则内涵（RULE）/ Dify AI 质控（AI）」三类结果
走同一提醒出口；本期只做接口与本地实现，不接生产（零外发）。

接口契约：

- ``Reminder``：统一提醒载体——``source``（TIMELINESS/RULE/AI）、``patient_id``、
  ``visit_id``、``file_unique_id``、``severity``、``title``、``detail``、``dedupe_key``
  （幂等去重键，调用方保证稳定：TIMELINESS=tl_event.event_uid，AI=``{push_log_id}:{dimension_code}``）；
- ``ReminderChannel.send(reminder) -> ChannelResult``：所有通道的留痕先于外发
  （写 ``tl_action_log``，与 T7 notifier 同一约定）；``ChannelResult.mode`` 取值
  DRY_RUN / EXECUTED / BLOCKED / SKIPPED / UNAVAILABLE。

实现类（本期）：

- ``WeComChannel``：企微卡片出口。复用 T7 ``resolve_notify_mode`` 的 D6 闸门
  （``relay_contract_confirmed`` 非 True 一律 LOG_ONLY 零 HTTP）；留痕自管于
  ``tl_action_log``（event_id 可空）——因为 RULE/AI 源没有 ``tl_event`` 行，
  T7 notifier 的 ``event_uid`` 绑定不适用；TIMELINESS 源且事件存在时挂
  ``event_id`` 增强关联。去重键 = ``WECOM/{source}/{dedupe_key}``（非 BLOCKED
  留痕已存在即视为已通知）。
- ``JhemrMonitorChannel``：JHEMR 监控行出口——**只用于 TIMELINESS 源**，调用
  T8 ``JhemrWriter.insert_monitor_row``（D3 答复前该方法直接抛 NotImplementedError，
  本通道捕获后返回 ``mode='UNAVAILABLE'``，不留痕不连库）。
- ``JhemrRectificationChannel``：构造即抛 ``ChannelDisabled``（勘误 E7：整改通道
  不做提醒出口，实验性禁用）。
- ``JhemrFileVerifyChannel``：**按任务书只写设计不写代码**（见
  ``review/timeliness/T10_channel_design.md`` §FILEVERIFY，D10 待批）。

AI 结果接入点：``build_reminders_from_ai_results(db, ...)`` **只读**查询
``PushLog``/``AuditDimensionResult`` 高危维度生成 ``Reminder`` 列表——不修改
Dify 链路、不改这两张表结构（验收红线）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from sqlalchemy.orm import Session

from app.services.relay_client import send_signed_relay
from app.timeliness.models import TLActionLog
from app.timeliness.notifier import resolve_notify_mode

SOURCES = ("TIMELINESS", "RULE", "AI")

DEFAULT_RELAY_ENDPOINT = "/timeliness-alert"


class ChannelDisabled(RuntimeError):
    """通道被勘误/决策禁用（E7：整改通道不作为提醒出口）。"""


@dataclass(frozen=True)
class Reminder:
    """统一提醒载体（§15 T10 接口字段，逐字对齐任务书）。"""

    source: str
    patient_id: str
    visit_id: str
    file_unique_id: str | None
    severity: str
    title: str
    detail: str
    dedupe_key: str

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f"reminder.source 非法: {self.source!r}（允许 {', '.join(SOURCES)}）")
        if not str(self.patient_id or "").strip():
            raise ValueError("reminder.patient_id 不能为空")
        if not str(self.dedupe_key or "").strip():
            raise ValueError("reminder.dedupe_key 不能为空（幂等去重键）")

    def payload(self) -> dict[str, Any]:
        """发送报文（无 PHI 扩展字段：不含患者姓名等，仅标识与内容摘要）。"""
        return {
            "msg_type": "quality_reminder",
            "source": self.source,
            "patient_id": self.patient_id,
            "visit_id": self.visit_id,
            "file_unique_id": self.file_unique_id,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ChannelResult:
    """通道发送结果（mode：DRY_RUN/EXECUTED/BLOCKED/SKIPPED/UNAVAILABLE）。"""

    channel: str
    handled: bool
    sent: bool
    mode: str
    reason: str = ""
    action_log_id: int | None = None
    reference: str | None = None


def _dump_params(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class ReminderChannel:
    """通道基类：子类实现 ``_deliver``；基类负责入参校验与统一异常兜底。"""

    name: str = "base"
    supported_sources: tuple[str, ...] = SOURCES

    def send(self, reminder: Reminder) -> ChannelResult:
        if reminder.source not in self.supported_sources:
            return ChannelResult(
                channel=self.name, handled=False, sent=False, mode="SKIPPED",
                reason=f"source {reminder.source} not supported by {self.name}",
            )
        try:
            return self._deliver(reminder)
        except ChannelDisabled:
            raise
        except Exception as exc:  # 通道故障不中断批量分发
            return ChannelResult(
                channel=self.name, handled=False, sent=False, mode="BLOCKED",
                reason=f"error_type={type(exc).__name__}",
            )

    def _deliver(self, reminder: Reminder) -> ChannelResult:  # pragma: no cover - 接口
        raise NotImplementedError


class WeComChannel(ReminderChannel):
    """企微卡片出口（复用 T7 D6 闸门；LOG_ONLY 默认零 HTTP）。

    留痕自管于 tl_action_log（event_id 可空）：RULE/AI 源无 tl_event 行，
    T7 notifier 的 event_uid 绑定不适用；去重键 = WECOM/{source}/{dedupe_key}。
    """

    name = "wecom"

    def __init__(self, db: Session, config: dict | None):
        self.db = db
        self.config = config or {}
        relay_cfg = self.config.get("relay_alert") or {}
        section = self.config.get("timeliness") or {}
        self.base_url = str(relay_cfg.get("base_url") or "").rstrip("/")
        self.endpoint = str(section.get("relay_endpoint") or DEFAULT_RELAY_ENDPOINT).strip()
        self.timeout = int(relay_cfg.get("timeout_seconds") or 10)
        self.secret = _resolve_secret(relay_cfg)

    def _dedupe_target(self, reminder: Reminder) -> str:
        return f"WECOM/{reminder.source}/{reminder.dedupe_key}"[:200]

    def _find_existing(self, target: str) -> TLActionLog | None:
        return (
            self.db.query(TLActionLog)
            .filter(
                TLActionLog.action_type == "NOTIFY",
                TLActionLog.target == target,
                TLActionLog.mode != "BLOCKED",
            )
            .first()
        )

    def _event_id_for(self, reminder: Reminder) -> int | None:
        from app.timeliness.models import TLEvent

        if reminder.source != "TIMELINESS":
            return None
        event = (
            self.db.query(TLEvent)
            .filter(TLEvent.event_uid == reminder.dedupe_key)
            .first()
        )
        return event.id if event else None

    def _deliver(self, reminder: Reminder) -> ChannelResult:
        target = self._dedupe_target(reminder)
        existed = self._find_existing(target)
        if existed is not None:
            return ChannelResult(
                channel=self.name, handled=False, sent=False, mode="SKIPPED",
                reason="duplicate: dedupe_key already notified",
                action_log_id=existed.id, reference=target,
            )

        effective_mode, forced_reason = resolve_notify_mode(self.config)
        body = reminder.payload()
        log = TLActionLog(
            action_type="NOTIFY",
            mode="EXECUTED",
            target=target,
            operator="reminder_channel",
            created_at=_now(),
            params_json=_dump_params(body),
            event_id=self._event_id_for(reminder),
        )
        if effective_mode == "LOG_ONLY":
            log.mode = "DRY_RUN"
            log.result = forced_reason or "LOG_ONLY: reminder recorded without sending"
            self.db.add(log)
            self.db.commit()
            return ChannelResult(channel=self.name, handled=True, sent=False,
                                 mode="DRY_RUN", reason=forced_reason,
                                 action_log_id=log.id, reference=target)

        # SEND 生效（relay_contract_confirmed=True）：先留痕再外呼，回填结果。
        url = f"{self.base_url}{self.endpoint}"
        if not self.base_url or not self.secret:
            log.mode = "BLOCKED"
            log.result = "blocked: relay_alert base_url/secret not configured"
            self.db.add(log)
            self.db.commit()
            return ChannelResult(channel=self.name, handled=False, sent=False,
                                 mode="BLOCKED", reason="relay not configured",
                                 action_log_id=log.id, reference=target)
        log.result = "sending"
        self.db.add(log)
        self.db.commit()
        try:
            resp = send_signed_relay(url, body, self.secret, timeout=self.timeout)
            status_code = int(getattr(resp, "status_code", 0) or 0)
            if 0 < status_code < 300:
                log.result = f"sent: HTTP {status_code}"
                self.db.commit()
                return ChannelResult(channel=self.name, handled=True, sent=True,
                                     mode="EXECUTED", action_log_id=log.id, reference=target)
            log.result = f"failed: HTTP {status_code}"
            self.db.commit()
            return ChannelResult(channel=self.name, handled=True, sent=False,
                                 mode="EXECUTED", reason=f"HTTP {status_code}",
                                 action_log_id=log.id, reference=target)
        except Exception as exc:
            log.result = f"failed: {type(exc).__name__}"
            self.db.commit()
            return ChannelResult(channel=self.name, handled=True, sent=False,
                                 mode="EXECUTED", reason=f"error_type={type(exc).__name__}",
                                 action_log_id=log.id, reference=target)


class JhemrMonitorChannel(ReminderChannel):
    """JHEMR 监控行出口——只用于 TIMELINESS 源；底层=T8 writer 模板 A。

    D3 答复前 ``insert_monitor_row`` 直接抛 NotImplementedError（T8 交付口径），
    本通道捕获后返回 ``mode='UNAVAILABLE'``（不连库、不留痕——writer 未做任何动作）。
    """

    name = "jhemr_monitor"
    supported_sources = ("TIMELINESS",)

    def __init__(self, writer: Any):
        self._writer = writer

    def _deliver(self, reminder: Reminder) -> ChannelResult:
        try:
            outcome = self._writer.insert_monitor_row(reminder=reminder)
        except NotImplementedError as exc:
            return ChannelResult(channel=self.name, handled=False, sent=False,
                                 mode="UNAVAILABLE", reason=str(exc))
        mode = str((outcome or {}).get("mode") or "BLOCKED")
        return ChannelResult(
            channel=self.name,
            handled=bool((outcome or {}).get("handled")),
            sent=bool((outcome or {}).get("executed")),
            mode=mode,
            reason=str((outcome or {}).get("reason") or ""),
            reference=(outcome or {}).get("action_log_id"),
        )


class JhemrRectificationChannel:
    """整改通道：勘误 E7 明确不作为提醒出口——构造即禁用（experimental）。"""

    experimental = True

    def __init__(self, *args: Any, **kwargs: Any):
        raise ChannelDisabled(
            "JhemrRectificationChannel is disabled (勘误 E7)：整改通道不做提醒出口"
        )


def _resolve_secret(relay_cfg: dict) -> str:
    plain = str(relay_cfg.get("secret_key") or "").strip()
    if plain:
        return plain
    enc = str(relay_cfg.get("secret_key_enc") or "").strip()
    if not enc:
        return ""
    try:
        from app.config import decrypt_value

        return decrypt_value(enc)
    except Exception:
        return ""


def _now():
    from datetime import datetime

    return datetime.now()


def dispatch_reminder(
    reminder: Reminder,
    channels: Sequence[ReminderChannel],
) -> list[ChannelResult]:
    """把一条 reminder 分发给多个通道（单通道故障不中断整批）。"""
    return [channel.send(reminder) for channel in channels]


def build_reminders_from_ai_results(
    db: Session,
    *,
    severity_levels: Iterable[str] = ("high",),
    limit: int = 200,
) -> list[Reminder]:
    """AI 结果接入点：**只读**查询高危维度生成 reminder（不改表、不改 Dify 链路）。

    - 来源：``AuditDimensionResult`` join ``PushLog``（取患者/住院次标识）；
    - 过滤：``severity`` 在 severity_levels 内（默认仅 high）；
    - 去重键：``{push_log_id}:{dimension_code}``（stable，同维度同推送不重发）；
    - 标题：维度名 + 质控类型；正文：issue_summary/rationale 摘要（截断 500）。
    """
    from app.models import AuditDimensionResult, PushLog

    levels = [str(level).strip().lower() for level in severity_levels if str(level).strip()]
    if not levels:
        return []
    rows = (
        db.query(AuditDimensionResult, PushLog)
        .join(PushLog, AuditDimensionResult.push_log_id == PushLog.id)
        .filter(AuditDimensionResult.severity.in_(levels))
        .order_by(AuditDimensionResult.id.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    reminders: list[Reminder] = []
    for dim, push in rows:
        detail = str(getattr(dim, "issue_summary", "") or getattr(dim, "explanation", "") or "").strip()
        reminders.append(
            Reminder(
                source="AI",
                patient_id=str(push.patient_id or "").strip(),
                visit_id=str(push.visit_number or "").strip(),
                file_unique_id=None,
                severity=str(dim.severity or "").strip().lower(),
                title=f"{dim.dimension or dim.dimension_code or '质控维度'}（{push.audit_type_code or ''}）",
                detail=detail[:500],
                dedupe_key=f"{dim.push_log_id}:{dim.dimension_code}",
            )
        )
    return [reminder for reminder in reminders if reminder.patient_id and reminder.visit_id]
