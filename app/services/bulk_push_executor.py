"""
Bulk manual push executor for high-volume push.

Scope:
- Used only by /api/push/manual path.
- Keeps existing PushExecutor unchanged for other menus and scheduler.
"""

from __future__ import annotations

import copy
import json
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from app.database import SessionLocal
from app.dify_pusher import push_to_dify
from app.notifier import send_notification
from app.services.payload_builder import build_dify_mr_text, build_dify_payload
from app.services.push_executor import PushConfig, PushExecutor, PushResult

logger = logging.getLogger(__name__)


@dataclass
class _TargetState:
    name: str
    config: Dict[str, Any]
    weight: int = 1
    consecutive_failures: int = 0
    cool_down_until: float = 0.0


class BulkPushExecutor:
    """Parallel executor for manual bulk push."""

    def __init__(
        self,
        dify_config: Dict[str, Any],
        notify_config: Dict[str, Any] | None = None,
        field_mapping: Dict[str, str] | None = None,
        dify_targets: Optional[List[Dict[str, Any]]] = None,
        max_workers: int = 4,
        empty_retry_max: int = 0,
        empty_retry_backoff_ms: int = 1000,
        target_strategy: str = "round_robin",
        circuit_breaker_failures: int = 3,
        circuit_breaker_seconds: int = 30,
    ):
        self.notify_config = notify_config or {}
        self.field_mapping = field_mapping or {}
        self.max_workers = max(1, int(max_workers))
        self.empty_retry_max = max(0, int(empty_retry_max))
        self.empty_retry_backoff_ms = max(0, int(empty_retry_backoff_ms))
        self.target_strategy = str(target_strategy or "round_robin")
        self.circuit_breaker_failures = max(1, int(circuit_breaker_failures))
        self.circuit_breaker_seconds = max(1, int(circuit_breaker_seconds))

        self._lock = threading.RLock()
        self._targets: List[_TargetState] = self._build_targets(dify_config, dify_targets)
        self._rr_ring = self._build_rr_ring(self._targets)
        self._rr_pos = 0
        self._target_metrics: Dict[str, Dict[str, int]] = {
            t.name: {"selected": 0, "success": 0, "failed": 0, "empty": 0}
            for t in self._targets
        }

    def execute(
        self,
        grouped_records: Dict[str, List[Dict[str, Any]]],
        push_config: PushConfig,
        on_item_done: Optional[Callable[[str], None]] = None,
        stop_check: Optional[Callable[[], bool]] = None,
    ) -> PushResult:
        start_time = time.time()
        result = PushResult(total=len(grouped_records))
        if not grouped_records:
            return result

        worker_count = min(self.max_workers, max(1, len(grouped_records)))
        logger.info(
            "[bulk_push] start total=%s workers=%s targets=%s empty_retry_max=%s strategy=%s",
            len(grouped_records),
            worker_count,
            len(self._targets),
            self.empty_retry_max,
            self.target_strategy,
        )

        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="bulk-push") as pool:
            futures = {
                pool.submit(self._process_single, patient_id, patient_records, push_config): patient_id
                for patient_id, patient_records in grouped_records.items()
            }
            for future in as_completed(futures):
                # 检查取消信号
                if stop_check and stop_check():
                    logger.info("[bulk_push] cancel signal received, shutting down remaining futures")
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                patient_id = futures[future]
                try:
                    single = future.result()
                except Exception as exc:
                    logger.error("bulk push future failed: patient_id=%s err=%s", patient_id, exc, exc_info=True)
                    single = {
                        "patient_id": patient_id,
                        "status": "error",
                        "inconsistency": False,
                        "severity": "",
                        "workflow_run_id": "",
                        "elapsed_ms": 0,
                        "error": str(exc),
                    }

                result.results.append(single)
                status = str(single.get("status", "failed"))
                if status == "success":
                    result.success += 1
                elif status == "skipped":
                    pass
                else:
                    result.failed += 1

                if on_item_done:
                    try:
                        on_item_done(status)
                    except Exception:
                        logger.debug("on_item_done callback failed", exc_info=True)

        result.duration_seconds = time.time() - start_time
        logger.info(
            "[bulk_push] done total=%s success=%s failed=%s duration=%.2fs",
            result.total,
            result.success,
            result.failed,
            result.duration_seconds,
        )
        return result

    def get_target_metrics(self) -> Dict[str, Dict[str, int]]:
        with self._lock:
            return copy.deepcopy(self._target_metrics)

    def _process_single(
        self,
        patient_id: str,
        patient_records: List[Dict[str, Any]],
        push_config: PushConfig,
    ) -> Dict[str, Any]:
        db = SessionLocal()
        base_executor = PushExecutor(self._targets[0].config, self.notify_config, self.field_mapping)
        try:
            payload = build_dify_payload(patient_records, self.field_mapping, push_config.query_date)
            mr_text = build_dify_mr_text(patient_records, self.field_mapping, push_config.query_date)
            real_patient_id = patient_id.split("_")[0] if "_" in patient_id else patient_id
            visit_number = str(patient_records[0].get(self.field_mapping.get("visit_number", "次数"), "") or "")

            skip_reason, skip_message = base_executor._get_skip_reason(db, real_patient_id, visit_number)
            if skip_reason:
                return {
                    "patient_id": real_patient_id,
                    "status": "skipped",
                    "inconsistency": False,
                    "severity": "",
                    "workflow_run_id": "",
                    "elapsed_ms": 0,
                    "error": skip_message,
                    "skip_reason": skip_reason,
                }

            dify_input = mr_text or json.dumps(payload, ensure_ascii=False)
            dify_result = self._push_with_empty_retry(dify_input, real_patient_id)
            base_executor._enforce_authoritative_patient_fields(
                dify_result=dify_result,
                payload=payload,
                patient_records=patient_records,
                query_date=push_config.query_date,
                patient_id=real_patient_id,
            )

            payload_for_log = copy.deepcopy(payload)
            payload_for_log["_bulk_push_meta"] = {
                "target_name": dify_result.get("_target_name", ""),
                "empty_retry_count": int(dify_result.get("_empty_retry_count", 0)),
            }

            log = base_executor._create_push_log(
                patient_id=patient_id,
                patient_records=patient_records,
                dify_result=dify_result,
                payload=payload_for_log,
                mr_text=mr_text,
                push_config=push_config,
            )
            db.add(log)
            db.flush()
            base_executor._save_audit_results(db, log.id, dify_result)

            if dify_result.get("inconsistency") and push_config.notify_enabled:
                try:
                    send_notification(real_patient_id, dify_result, self.notify_config)
                except Exception as exc:
                    logger.error("send notification failed: patient_id=%s err=%s", real_patient_id, exc, exc_info=True)

            db.commit()
            return {
                "patient_id": real_patient_id,
                "status": dify_result.get("status", "failed"),
                "inconsistency": dify_result.get("inconsistency", False),
                "severity": dify_result.get("severity", ""),
                "workflow_run_id": dify_result.get("workflow_run_id", ""),
                "elapsed_ms": dify_result.get("elapsed_ms", 0),
                "target_name": dify_result.get("_target_name", ""),
                "empty_retry_count": int(dify_result.get("_empty_retry_count", 0)),
            }
        except Exception as exc:
            db.rollback()
            logger.error("bulk push single failed: patient_id=%s err=%s", patient_id, exc, exc_info=True)
            return {
                "patient_id": patient_id,
                "status": "error",
                "inconsistency": False,
                "severity": "",
                "workflow_run_id": "",
                "elapsed_ms": 0,
                "error": str(exc),
            }
        finally:
            db.close()

    def _push_with_empty_retry(self, dify_input: Any, patient_id: str) -> Dict[str, Any]:
        last_result: Dict[str, Any] = {}
        empty_retry_count = 0
        for attempt in range(self.empty_retry_max + 1):
            target = self._pick_target()
            result = push_to_dify(dify_input, target.config, patient_id)
            result["_target_name"] = target.name

            if result.get("status") != "success":
                self._record_target_result(target.name, success=False, empty=False)
                result["_empty_retry_count"] = empty_retry_count
                return result

            output_key = str(target.config.get("workflow_output_key", "aa") or "aa")
            if not self._is_empty_success_result(result, output_key):
                self._record_target_result(target.name, success=True, empty=False)
                result["_empty_retry_count"] = empty_retry_count
                return result

            empty_retry_count += 1
            last_result = result
            self._record_target_result(target.name, success=False, empty=True)
            if attempt < self.empty_retry_max:
                sleep_ms = self.empty_retry_backoff_ms * (attempt + 1)
                time.sleep(max(0, sleep_ms) / 1000.0)

        final_result = dict(last_result) if last_result else {}
        final_result.update(
            {
                "status": "failed",
                "error": f"empty dify output after retries={self.empty_retry_max}",
                "inconsistency": False,
                "severity": "",
                "risk_score": 0,
                "_empty_retry_count": empty_retry_count,
            }
        )
        return final_result

    @staticmethod
    def _is_empty_success_result(dify_result: Dict[str, Any], output_key: str) -> bool:
        outputs = dify_result.get("result")
        if not isinstance(outputs, dict):
            return True
        if output_key not in outputs:
            return len(outputs) == 0
        value = outputs.get(output_key)
        if value is None:
            return True
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized in {"", "{}", "[]", "null", "none"}
        if isinstance(value, (list, dict)):
            return len(value) == 0
        return False

    def _build_targets(
        self,
        dify_config: Dict[str, Any],
        dify_targets: Optional[List[Dict[str, Any]]],
    ) -> List[_TargetState]:
        targets: List[_TargetState] = []
        source = dify_targets or [dify_config]
        for idx, item in enumerate(source):
            cfg = dict(item or {})
            if not cfg:
                continue
            enabled = bool(cfg.get("enabled", True))
            if not enabled:
                continue
            name = str(cfg.get("name") or f"target-{idx + 1}")
            weight = int(cfg.get("weight", 1) or 1)
            targets.append(_TargetState(name=name, config=cfg, weight=max(1, weight)))
        if not targets:
            raise ValueError("No enabled dify target configured")
        return targets

    @staticmethod
    def _build_rr_ring(targets: List[_TargetState]) -> List[int]:
        ring: List[int] = []
        for idx, target in enumerate(targets):
            ring.extend([idx] * max(1, int(target.weight)))
        return ring or [0]

    def _pick_target(self) -> _TargetState:
        with self._lock:
            now = time.time()
            available = [t for t in self._targets if t.cool_down_until <= now]
            pool = available if available else self._targets
            if self.target_strategy == "weighted_random":
                weights = [max(1, int(t.weight)) for t in pool]
                picked = random.choices(pool, weights=weights, k=1)[0]
                self._target_metrics[picked.name]["selected"] += 1
                return picked

            # round_robin (weighted via rr ring)
            if len(pool) != len(self._targets):
                # if partial availability, switch to simple rr on available pool
                target = pool[self._rr_pos % len(pool)]
                self._rr_pos += 1
                self._target_metrics[target.name]["selected"] += 1
                return target

            ring_idx = self._rr_ring[self._rr_pos % len(self._rr_ring)]
            self._rr_pos += 1
            target = self._targets[ring_idx]
            self._target_metrics[target.name]["selected"] += 1
            return target

    def _record_target_result(self, target_name: str, success: bool, empty: bool) -> None:
        with self._lock:
            target = next((t for t in self._targets if t.name == target_name), None)
            if target is None:
                return
            if success:
                self._target_metrics[target.name]["success"] += 1
                target.consecutive_failures = 0
                target.cool_down_until = 0.0
                return
            self._target_metrics[target.name]["failed"] += 1
            if empty:
                self._target_metrics[target.name]["empty"] += 1
            target.consecutive_failures += 1
            if target.consecutive_failures >= self.circuit_breaker_failures:
                target.cool_down_until = time.time() + self.circuit_breaker_seconds
                logger.warning(
                    "[bulk_push] target open-circuit: name=%s failures=%s empty=%s cooldown=%ss",
                    target.name,
                    target.consecutive_failures,
                    empty,
                    self.circuit_breaker_seconds,
                )
