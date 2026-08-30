# -*- coding: utf-8 -*-
"""企微推送模块（独立实现，走 relay 签名协议）。

纪律（028 §4.4 / R5 / A8）：
- 单患者单次合并一条：一个 result 的全部问题合成一条消息；
- 同一 result_id 双通道去重：push_wecom_status / push_agent_status 每通道至多 sent 一次；
- 严重度降噪：只推 severity 达到配置级别的问题；无符合项则整体跳过；
- 一期影子运行 push.enabled=false，全部记 skipped。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Optional, Protocol

from . import signing
from .context import PatientContext
from .models import PUSH_FAILED, PUSH_SENT, PUSH_SKIPPED, PrearchiveResult
from .receivers import DefaultReceiverResolver, Receiver

logger = logging.getLogger("prearchive.pusher")

SEVERITY_LEVEL_ORDER = {"low": 1, "medium": 2, "high": 3}


class HttpSender(Protocol):
    def send(self, url: str, body: bytes, headers: dict, timeout: float) -> tuple:
        """返回 (status_code, response_text)。"""


class UrllibSender:
    """标准库实现（不引入 requests 依赖；生产可替换为连接池实现）。"""

    def send(self, url: str, body: bytes, headers: dict, timeout: float) -> tuple:
        import urllib.error
        import urllib.request

        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace") if exc.fp else str(exc)


def build_push_payload(result: PrearchiveResult, ctx: PatientContext,
                       receiver: Receiver,
                       dept_normalizer=None) -> dict:
    """构造最小化文案的合并消息（不带病历原文，R10）。

    dept_normalizer（可选，T8-3）：提供 normalize_name(name)->str 的规范化器
    （HisBaseDeptNormalizer）；传入时科室名按 VW_dept_dict 标准名输出推送文案。
    """
    problems = []
    for problem in result.problems():
        problems.append({
            "rule_id": problem.get("rule_id"),
            "name": problem.get("name"),
            "severity": problem.get("severity"),
            "message": problem.get("message"),
        })
    dept_name = ctx.dept_name
    if dept_normalizer is not None and dept_name:
        try:
            dept_name = dept_normalizer.normalize_name(dept_name)
        except Exception:   # noqa: BLE001 —— 规范化失败不阻断推送
            pass
    return {
        "event": "prearchive_check_issue",
        "doctor_id": receiver.doctor_id,
        "doctor_name": receiver.doctor_name,
        "receiver_user_id": receiver.user_id,
        "receiver_fallback": receiver.is_fallback,
        "patient_id": ctx.patient_id,
        "visit_id": ctx.visit_id,
        "patient_name": ctx.patient_name,
        "dept_code": ctx.dept_code,
        "dept_name": dept_name,
        "finished_date_time": result.finished_date_time.isoformat(timespec="seconds")
        if result.finished_date_time else None,
        "result_id": result.id,
        "problem_count": result.problem_count,
        "problems": problems,
        "occurred_at": datetime.now().isoformat(timespec="seconds"),
        "source": "prearchive-service",
    }


class WeComPusher:
    """结果 → 合并签名消息 → 发送 → 状态回写。"""

    def __init__(self, push_config: dict, secret_provider: Callable[[], str],
                 sender: HttpSender, resolver: Optional[DefaultReceiverResolver] = None,
                 severity_levels: Optional[list] = None,
                 clock: Callable[[], datetime] = datetime.now,
                 dept_normalizer=None):
        self.config = push_config or {}
        self.enabled = bool(self.config.get("enabled"))
        self.base_url = str(self.config.get("base_url") or "").rstrip("/")
        self.endpoint = str(self.config.get("endpoint") or "/qc-record-alert")
        self.timeout = float(self.config.get("timeout_seconds") or 10)
        self._secret_provider = secret_provider
        self.sender = sender
        self.resolver = resolver or DefaultReceiverResolver()
        self.dept_normalizer = dept_normalizer   # T8-3：None=不规范化（默认现状）
        levels = severity_levels if severity_levels is not None \
            else (self.config.get("severity_levels") or ["medium", "high"])
        self.min_severity = min(
            (SEVERITY_LEVEL_ORDER.get(s, 2) for s in levels), default=2)

    def _problems_above_level(self, result: PrearchiveResult) -> list:
        return [p for p in result.problems()
                if SEVERITY_LEVEL_ORDER.get(p.get("severity"), 2) >= self.min_severity]

    def push_result(self, result: PrearchiveResult,
                    ctx: PatientContext) -> dict:
        """推送一次结果。返回 {status, detail, payload?}；不抛异常（fail-open）。"""
        if not self.enabled:
            return {"status": PUSH_SKIPPED, "detail": "push disabled (shadow mode)"}
        if result.push_wecom_status == PUSH_SENT:
            return {"status": PUSH_SENT, "detail": "already sent (dedup)",
                    "deduped": True}   # 同一 result_id 不再扰（R5）
        if result.problem_count <= 0:
            return {"status": PUSH_SKIPPED, "detail": "no problems"}

        notable = self._problems_above_level(result)
        if not notable:
            return {"status": PUSH_SKIPPED, "detail": "below severity threshold"}

        receiver = None
        try:
            receiver = self.resolver.resolve(ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[push] receiver resolve failed: %s", exc)
        if receiver is None:
            return {"status": PUSH_SKIPPED, "detail": "no receiver resolved"}

        url = self.base_url + self.endpoint
        if not self.base_url or self.base_url.startswith("<"):
            return {"status": PUSH_FAILED, "detail": "relay base_url not configured"}

        try:
            payload = build_push_payload(result, ctx, receiver,
                                         dept_normalizer=self.dept_normalizer)
            body, headers = signing.build_signed_request(
                payload, self._secret_provider())
            status_code, text = self.sender.send(url, body, headers, self.timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[push] send failed for result %s: %s", result.id, exc)
            return {"status": PUSH_FAILED, "detail": f"{type(exc).__name__}: {exc}"}

        if 200 <= int(status_code) < 300:
            return {"status": PUSH_SENT, "detail": f"HTTP {status_code}",
                    "payload": payload}
        return {"status": PUSH_FAILED,
                "detail": f"HTTP {status_code}: {str(text)[:200]}"}
