"""病历时效提醒器（T7；主设计文档 §8.3 层级三 / §14.3 调整 3 / §15 T7）。

在**不改变现有高危告警行为**的前提下，为时效事件提供提醒发送能力：

- 复用通用签名发送层 ``app.services.relay_client.send_signed_relay``（与
  RelayAlertService 同一套 HMAC-SHA256 契约，企微中继通道，§8.3）；
- **幂等去重**：同一 ``event_uid`` + 同一通知类型（notify_type）只处理一次；
  去重以 ``tl_action_log`` 留痕为准（LOG_ONLY 记 ``DRY_RUN``、真实发送记
  ``EXECUTED``，二者均计入去重），``mode='BLOCKED'``（缺中继配置被拦，未留有效
  通知）不计入——补齐配置后可重试；
- **所有通知动作先写 ``tl_action_log``**：先落库再发送，HTTP 结果事后回填 result；
- ``timeliness.notify_mode``：``LOG_ONLY``（默认）/ ``SEND``；配置项
  ``timeliness.relay_contract_confirmed`` 不为 ``True`` 之前（D6：中继新消息类型
  契约未确认），即使设为 ``SEND`` 也强制按 LOG_ONLY 执行，绝不发真实 HTTP。

配置键（均可选，缺省安全）：
- ``timeliness.notify_mode``：LOG_ONLY / SEND（默认 LOG_ONLY）；
- ``timeliness.relay_contract_confirmed``：bool，默认 false（D6 闸门）；
- ``timeliness.relay_endpoint``：时效消息端点（默认 ``/timeliness-alert``，
  以 D6 契约最终约定为准）；
- 中继地址与密钥复用 ``relay_alert`` 段（base_url / secret_key / secret_key_enc）。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.services.relay_client import send_signed_relay
from app.timeliness.models import TLActionLog, TLEvent

logger = logging.getLogger(__name__)

LOG_ONLY = "LOG_ONLY"
SEND = "SEND"
NOTIFY_MODES = (LOG_ONLY, SEND)

# 常用通知类型（不封闭集合：允许后续扩展，仅校验非空与长度）。
NOTIFY_TYPE_WARN = "WARN"
NOTIFY_TYPE_OVERDUE = "OVERDUE"

DEFAULT_RELAY_ENDPOINT = "/timeliness-alert"
DEFAULT_TIMEOUT_SECONDS = 10


class TimelinessNotifierError(ValueError):
    """提醒器入参或配置非法。"""


def resolve_notify_mode(config: dict | None) -> tuple[str, str]:
    """解析生效模式：返回 (生效模式, 强制降级原因)。

    - 未配置 / 非法值 → LOG_ONLY（默认）；
    - notify_mode=SEND 但 relay_contract_confirmed 不为 True → 强制 LOG_ONLY
      （原因注明 D6），绝不发真实 HTTP；
    - SEND 生效前提：notify_mode=SEND 且 relay_contract_confirmed=True。
    """
    section = (config or {}).get("timeliness") or {}
    if not isinstance(section, dict):
        return LOG_ONLY, ""
    requested = str(section.get("notify_mode") or LOG_ONLY).strip().upper()
    if requested not in NOTIFY_MODES:
        logger.warning("[timeliness] 非法 notify_mode=%r，按默认 LOG_ONLY 处理", requested)
        return LOG_ONLY, ""
    if requested == SEND and section.get("relay_contract_confirmed") is not True:
        return (
            LOG_ONLY,
            "forced LOG_ONLY: notify_mode=SEND but relay_contract_confirmed is not true (D6 pending)",
        )
    return requested, ""


def _resolve_relay_secret(config: dict) -> str:
    """复用 relay_alert 段密钥：明文 secret_key 优先，其次 secret_key_enc 解密。"""
    relay_cfg = (config or {}).get("relay_alert") or {}
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
        logger.warning("[timeliness] relay_alert.secret_key_enc 解密失败，提醒发送不可用")
        return ""


def _dump_params(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class TimelinessNotifier:
    """时效事件提醒器：去重 → 先写 tl_action_log → 按模式记录或发送。"""

    def __init__(
        self,
        db: Session,
        config: dict | None,
        *,
        sender: Callable[..., Any] | None = None,
        now_fn: Callable[[], datetime] = datetime.now,
    ):
        self.db = db
        self.config = config or {}
        self._sender = sender or send_signed_relay
        self._now = now_fn
        section = self.config.get("timeliness") or {}
        self.endpoint = str(section.get("relay_endpoint") or DEFAULT_RELAY_ENDPOINT).strip()
        relay_cfg = self.config.get("relay_alert") or {}
        self.base_url = str(relay_cfg.get("base_url") or "").rstrip("/")
        self.timeout = int(relay_cfg.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
        self.secret = _resolve_relay_secret(self.config)

    # ---- 内部工具 ----

    def _find_event(self, event_uid: str) -> TLEvent:
        event = self.db.query(TLEvent).filter(TLEvent.event_uid == event_uid).first()
        if event is None:
            raise TimelinessNotifierError(f"event not found: {event_uid}")
        return event

    def _already_notified(self, event_id: int, notify_type: str) -> TLActionLog | None:
        """同一事件 + 同一通知类型已有非 BLOCKED 留痕 → 视为已处理（幂等去重）。"""
        return (
            self.db.query(TLActionLog)
            .filter(
                TLActionLog.event_id == event_id,
                TLActionLog.action_type == "NOTIFY",
                TLActionLog.target == notify_type,
                TLActionLog.mode != "BLOCKED",
            )
            .first()
        )

    def _default_payload(self, event: TLEvent, notify_type: str) -> dict:
        return {
            "msg_type": "timeliness_notify",
            "notify_type": notify_type,
            "event_uid": event.event_uid,
            "rule_code": event.rule_code,
            "patient_id": event.patient_id,
            "visit_id": event.visit_id,
            "dept_code": event.dept_code,
            "deadline": event.deadline.isoformat() if event.deadline else None,
            "status": event.status,
            "source": "timeliness",
        }

    # ---- 主入口 ----

    def notify_event(
        self,
        *,
        event_uid: str,
        notify_type: str,
        payload: dict | None = None,
        operator: str = "system",
    ) -> dict[str, Any]:
        """对单个事件发一次提醒（同 event_uid + notify_type 幂等）。

        返回 dict：handled / sent / mode / action_log_id / reason 等字段；
        去重命中与配置闸门不抛异常，事件不存在或 notify_type 非法抛
        TimelinessNotifierError。
        """
        text = str(notify_type or "").strip()
        if not text or len(text) > 32:
            raise TimelinessNotifierError(f"notify_type 非法: {notify_type!r}")
        event = self._find_event(event_uid)

        existed = self._already_notified(event.id, text)
        if existed is not None:
            return {
                "handled": False,
                "sent": False,
                "reason": "duplicate: event_uid + notify_type already notified",
                "action_log_id": existed.id,
            }

        effective_mode, forced_reason = resolve_notify_mode(self.config)
        body = dict(payload) if payload else self._default_payload(event, text)
        log = TLActionLog(
            event_id=event.id,
            action_type="NOTIFY",
            mode="EXECUTED",
            target=text,
            operator=operator,
            created_at=self._now(),
            params_json=_dump_params(body),
        )
        if effective_mode == LOG_ONLY:
            # 默认/强制降级路径：只留痕（DRY_RUN），绝不发 HTTP（D6 未确认前 SEND 同样落此分支）。
            log.mode = "DRY_RUN"
            log.result = forced_reason or f"{LOG_ONLY}: notification recorded without sending"
            self.db.add(log)
            self.db.commit()
            return {
                "handled": True,
                "sent": False,
                "mode": LOG_ONLY,
                "forced": bool(forced_reason),
                "action_log_id": log.id,
                "reason": forced_reason,
            }

        # SEND 生效：先落 tl_action_log（持久留痕先于外呼），再发送并回填结果。
        # 缺中继地址/密钥属配置闸门：写 BLOCKED（不计入去重，补齐后可重试），不外呼。
        url = f"{self.base_url}{self.endpoint}"
        if not self.base_url or not self.secret:
            log.mode = "BLOCKED"
            log.result = "blocked: relay_alert base_url/secret not configured"
            self.db.add(log)
            self.db.commit()
            return {
                "handled": False,
                "sent": False,
                "mode": SEND,
                "action_log_id": log.id,
                "reason": "blocked: relay base_url/secret not configured",
            }
        log.result = "sending"
        self.db.add(log)
        self.db.commit()
        isolated_mode = os.getenv("TEST_ISOLATED_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
        if isolated_mode:
            from app.services.isolated_mode import assert_loopback_url

            assert_loopback_url(url, "Timeliness notify")
        try:
            resp = self._sender(url, body, self.secret, timeout=self.timeout, isolated_mode=isolated_mode)
            status_code = int(getattr(resp, "status_code", 0) or 0)
            if 0 < status_code < 300:
                log.result = f"sent: HTTP {status_code}"
                self.db.commit()
                return {"handled": True, "sent": True, "mode": SEND, "action_log_id": log.id, "reason": ""}
            log.result = f"failed: HTTP {status_code}"
            self.db.commit()
            return {
                "handled": True,
                "sent": False,
                "mode": SEND,
                "action_log_id": log.id,
                "reason": f"HTTP {status_code}",
            }
        except Exception as exc:
            log.result = f"failed: {type(exc).__name__}"
            self.db.commit()
            logger.warning("[timeliness] notify send error event=%s type=%s: %s", event_uid, text, type(exc).__name__)
            return {
                "handled": True,
                "sent": False,
                "mode": SEND,
                "action_log_id": log.id,
                "reason": f"error_type={type(exc).__name__}",
            }
