# -*- coding: utf-8 -*-
"""046 T6 结果→Outbox 自动接线（F03/F07 修复）。

- ResultEventEmitter：检查主链路（PrecheckProcessor.process 完成 run 后）自动
  落投递事件——不再依赖手工 enqueue/ reconcile 兜底调用；
- event_id 按**不可变结果身份**确定性生成（result_id+患者+就诊+完成时间）：
  同一结果重处理/补偿重放=同一事件（Outbox 唯一键幂等）；复检=新结果行=新事件；
- 治理（F07）在入队/补偿/发送全路径生效：总开关（result_delivery.enabled）、
  目标开关（destination.enabled）、试点科室（空=全部）、通知严重级、影子标记、
  零问题通知（默认开：让接收端能撤销旧缺陷，不能简单跳过）；
- 解决通知：本次 run 收敛的缺陷（fail→无）进入 envelope.resolutions（additive
  v1 扩展字段），接收端据此撤销旧缺陷；
- 崩溃窗口补偿：结果已提交但事件未落（进程崩溃）时，由 delivery worker 循环的
  bounded reconcile（recent_results 窗口）用同一确定性 event_id 补齐，唯一约束
  保证不重复。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .result_contract import (
    SEVERITY_ORDER,
    build_idempotency_key,
    serialize_result,
)
from .rule_repository import RuleRepository

logger = logging.getLogger("prearchive.delivery")


# ---------------------------------------------------------------------------
# 治理配置（F07）
# ---------------------------------------------------------------------------

@dataclass
class DeliveryGovernance:
    enabled: bool = False
    shadow: bool = False                    # 影子标记：事件带 shadow=true，接收端不触临床
    pilot_dept_codes: list = field(default_factory=list)   # 空=全部科室
    notify_severities: list = field(default_factory=lambda: ["low", "medium", "high"])
    zero_result_notify: bool = True         # 零问题结果也通知（撤销旧缺陷）
    reconcile_window: int = 200             # 崩溃窗口补偿的最近结果窗口

    def dept_allowed(self, dept_code: str) -> bool:
        return not self.pilot_dept_codes or dept_code in self.pilot_dept_codes

    def severity_allowed(self, highest_severity: str, problem_severities=None) -> bool:
        if not problem_severities:
            problem_severities = [highest_severity] if highest_severity else []
        return all(s in self.notify_severities for s in problem_severities) or \
            (highest_severity in self.notify_severities)


def load_delivery_governance(config: dict) -> DeliveryGovernance:
    delivery = (config or {}).get("result_delivery") or {}
    governance = ((config or {}).get("rule_registry") or {}).get("governance") or {}
    return DeliveryGovernance(
        enabled=bool(delivery.get("enabled")),
        shadow=bool(delivery.get("shadow")),
        pilot_dept_codes=list(governance.get("pilot_dept_codes") or []),
        notify_severities=list(governance.get("notify_severities")
                               or ["low", "medium", "high"]),
        zero_result_notify=bool(delivery.get("zero_result_notify", True)),
        reconcile_window=int(delivery.get("reconcile_window") or 200),
    )


# ---------------------------------------------------------------------------
# 确定性 event_id（与 outbox.reconcile_results 同一函数语义，保持收敛）
# ---------------------------------------------------------------------------

def result_event_id(result_id, patient_id: str, visit_id: str,
                    finished_at: Optional[datetime]) -> Optional[str]:
    """结果身份 → 稳定 event_id；finished_at 缺失返回 None（不可投递，记 missing）。"""
    if not finished_at:
        return None
    digest = hashlib.sha256(
        f"prearchive-result:{result_id}:{patient_id}:{visit_id}:"
        f"{finished_at.isoformat()}".encode("utf-8")).hexdigest()[:32]
    return f"res-{digest}"


# ---------------------------------------------------------------------------
# 发射器
# ---------------------------------------------------------------------------

class ResultEventEmitter:
    """检查主链路的自动入队入口（治理过滤→逐启停目标入队）。"""

    def __init__(self, rule_repository: RuleRepository,
                 governance: DeliveryGovernance):
        self.repository = rule_repository
        self.governance = governance

    def emit(self, *, run, result_row, problems: list, summary: dict,
             resolutions: Optional[list] = None,
             rule_version: str = "") -> list:
        """run 完成后调用；返回创建的 outbox 行摘要。trial 不投递。"""
        g = self.governance
        if not g.enabled:
            return []
        if getattr(run, "is_trial", 0):
            return []

        if not g.dept_allowed(run.dept_code or ""):
            logger.info("[emit] dept %s not in pilot scope; skip (run=%s)",
                        run.dept_code, run.id)
            return []

        highest = _highest_severity(problems)
        if problems and not g.severity_allowed(highest,
                                               [p.get("severity") for p in problems]):
            logger.info("[emit] severity gate blocked (highest=%s)", highest)
            return []
        if not problems and not g.zero_result_notify:
            # 零问题且关闭零通知：跳过（默认开——撤销旧缺陷依赖零问题事件）
            return []

        event_id = result_event_id(result_row.id, result_row.patient_id,
                                   result_row.visit_id,
                                   result_row.finished_date_time)
        if event_id is None:
            logger.warning("[emit] result %s lacks finished_at; not deliverable",
                           result_row.id)
            return []

        created = []
        for destination in self.repository.list_destinations():
            if not destination.enabled:
                continue
            envelope = serialize_result(
                result_id=result_row.id,
                patient_id=result_row.patient_id,
                visit_number=result_row.visit_id,
                dept_code=result_row.dept_code,
                trigger_mode=str(run.trigger_type),
                checked_at=run.checked_at or datetime.now(),
                problems=problems,
                rule_version=rule_version or result_row.rule_version,
                event_id=event_id,
                resolutions=resolutions or [],
                shadow=g.shadow,
                run_revision=run.run_revision,
                ruleset_revision=str(run.ruleset_revision or ""),
            )
            envelope.idempotency_key = build_idempotency_key(event_id,
                                                             destination.code)
            outbox = self.repository.enqueue_outbox(
                event_id=event_id, destination_code=destination.code,
                payload_json=envelope.model_dump_json(),
                idempotency_key=envelope.idempotency_key)
            created.append({"event_id": event_id,
                            "destination_code": destination.code,
                            "outbox_id": outbox.id, "status": outbox.status})
        if created:
            logger.info("[emit] run=%s → %d delivery events (%s)", run.id,
                        len(created), event_id)
        return created


def _highest_severity(problems: list) -> str:
    top = ""
    for problem in problems or []:
        if SEVERITY_ORDER.get(problem.get("severity"), 0) > SEVERITY_ORDER.get(top, 0):
            top = problem["severity"]
    return top


# ---------------------------------------------------------------------------
# 崩溃窗口补偿（bounded）
# ---------------------------------------------------------------------------

def reconcile_recent_results(rule_repository: RuleRepository,
                             result_repository, governance: DeliveryGovernance,
                             delivery_worker) -> dict:
    """delivery worker 循环内调用：最近 N 条结果 ←→ Outbox 对账补齐。

    同一确定性 event_id + (event, destination) 唯一约束 → 补偿幂等；发射器已
    正常入队的结果不会被重复补。只看最近 reconcile_window 条（bounded，不扫全量）。
    046 F07：补偿路径与正常入队执行同一治理（科室/严重级/零通知），不越权补发。
    """
    if not governance.enabled:
        return {"checked": 0, "enqueued": 0}
    recent = result_repository.recent_results(limit=governance.reconcile_window)
    eligible = []
    for result in recent:   # (id, pid, vid, dept_code, finished_at, problems_json, rule_version)
        dept_code = str(result[3] or "")
        problems = json.loads(result[5] or "[]")
        if not governance.dept_allowed(dept_code):
            continue
        if problems and not governance.severity_allowed(
                _highest_severity(problems),
                [p.get("severity") for p in problems]):
            continue
        if not problems and not governance.zero_result_notify:
            continue
        eligible.append(result)
    report = delivery_worker.reconcile_results(lambda: eligible)
    if report.get("enqueued"):
        logger.warning("[reconcile] crash-window backfill: %s events",
                       report["enqueued"])
    return report
