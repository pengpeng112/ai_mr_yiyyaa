"""
Bulk manual push executor for high-volume push.

Scope:
- Used only by /api/push/manual path.
- Keeps existing PushExecutor unchanged for other menus and scheduler.
"""

from __future__ import annotations

import copy
import logging
import random
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from app.database import SessionLocal
from app.dify_pusher import push_to_dify
from app.notifier import send_notification
from app.services.push_executor import PushConfig, PushExecutor, PushResult, _safe_json_dumps, with_audit_type_mr_type
from app.services.record_identity import get_bundle_source_key

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
        logger.info(
            "[audit.dify] bulk_start workers=%s targets=%s strategy=%s circuit_breaker=%s/%ss",
            worker_count,
            len(self._targets),
            self.target_strategy,
            self.circuit_breaker_failures,
            self.circuit_breaker_seconds,
        )

        records_iter = iter(grouped_records.items())
        futures: Dict[Any, str] = {}
        cancelled = False
        pool = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="bulk-push")

        def _submit_next() -> bool:
            if stop_check and stop_check():
                return False
            try:
                patient_id, patient_records = next(records_iter)
            except StopIteration:
                return False
            if stop_check is None:
                future = pool.submit(self._process_single, patient_id, patient_records, push_config)
            else:
                future = pool.submit(self._process_single, patient_id, patient_records, push_config, stop_check)
            futures[future] = patient_id
            return True

        try:
            for _ in range(worker_count):
                if not _submit_next():
                    break

            while futures:
                if stop_check and stop_check():
                    cancelled = True
                    logger.info("[bulk_push] cancel signal received, stop submitting new patients")
                    for pending in futures:
                        pending.cancel()
                    break

                done, _ = wait(futures.keys(), timeout=1, return_when=FIRST_COMPLETED)
                if not done:
                    continue

                for future in done:
                    patient_id = futures.pop(future)
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
                        result.skipped += 1
                    else:
                        result.failed += 1

                    if on_item_done:
                        try:
                            on_item_done(status)
                        except Exception:
                            logger.debug("on_item_done callback failed", exc_info=True)

                    if not (stop_check and stop_check()):
                        _submit_next()
        finally:
            pool.shutdown(wait=not cancelled, cancel_futures=True)

        result.duration_seconds = time.time() - start_time
        logger.info(
            "[bulk_push] done total=%s success=%s failed=%s duration=%.2fs",
            result.total,
            result.success,
            result.failed,
            result.duration_seconds,
        )
        metrics = self.get_target_metrics()
        selected_total = sum(int((item.get("selected") or 0)) for item in metrics.values())
        qps = (selected_total / result.duration_seconds) if result.duration_seconds > 0 else 0.0
        logger.info(
            "[audit.dify] bulk_done selected=%s qps=%.2f metrics=%s",
            selected_total,
            qps,
            metrics,
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
        stop_check: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if hasattr(patient_records, "group_values"):
            real_patient_id = str(patient_records.group_values.get("patient_id", "") or patient_id)
        else:
            real_patient_id = patient_id.split("_")[0] if "_" in patient_id else patient_id
        # 检查点1：任务入口，尚未建立 DB 连接
        if stop_check and stop_check():
            return {
                "patient_id": real_patient_id,
                "status": "skipped",
                "inconsistency": False,
                "severity": "",
                "workflow_run_id": "",
                "elapsed_ms": 0,
                "error": "cancelled by user",
                "skip_reason": "cancelled",
            }

        base_executor = PushExecutor(self._targets[0].config, self.notify_config, self.field_mapping)

        # ── 阶段1：前置检查（短生命周期 DB 会话，完成后立即释放） ──
        db = SessionLocal()
        try:
            bundle, payload, mr_text, _, visit_number, bundle_records = base_executor._build_payload_and_mr_text(
                patient_id, patient_records, push_config,
            )
            audit_type = push_config.audit_type

            surgery_reason, surgery_msg = base_executor._get_surgery_chain_skip_reason(audit_type, bundle)
            if surgery_reason:
                db.add(base_executor._create_skipped_push_log(
                    patient_id=patient_id, patient_records=patient_records,
                    push_config=push_config, skip_reason=surgery_reason, skip_message=surgery_msg,
                ))
                db.commit()
                return {
                    "patient_id": real_patient_id, "status": "skipped",
                    "inconsistency": False, "severity": "",
                    "workflow_run_id": "", "elapsed_ms": 0,
                    "error": surgery_msg, "skip_reason": surgery_reason,
                }

            source_record_key = get_bundle_source_key(bundle, audit_type, push_config.audit_run_mode) if audit_type else ""

            skip_reason, skip_message = base_executor._get_skip_reason(
                db,
                real_patient_id,
                visit_number,
                push_config.audit_type_code,
                source_record_key,
                push_config.audit_run_mode,
            )
            if skip_reason:
                db.add(base_executor._create_skipped_push_log(
                    patient_id=patient_id, patient_records=patient_records,
                    push_config=push_config, skip_reason=skip_reason, skip_message=skip_message,
                ))
                db.commit()
                return {
                    "patient_id": real_patient_id, "status": "skipped",
                    "inconsistency": False, "severity": "",
                    "workflow_run_id": "", "elapsed_ms": 0,
                    "error": skip_message, "skip_reason": skip_reason,
                }

            lab_exam_skip = base_executor._get_empty_lab_exam_skip_reason(payload)
            if lab_exam_skip:
                db.add(base_executor._create_skipped_push_log(
                    patient_id=patient_id, patient_records=patient_records,
                    push_config=push_config, skip_reason="empty_lab_exam", skip_message=lab_exam_skip,
                ))
                db.commit()
                return {
                    "patient_id": real_patient_id, "status": "skipped",
                    "inconsistency": False, "severity": "",
                    "workflow_run_id": "", "elapsed_ms": 0,
                    "error": lab_exam_skip, "skip_reason": "empty_lab_exam",
                }
        except Exception as exc:
            db.rollback()
            logger.error("bulk push pre-check failed: patient_id=%s err=%s", patient_id, exc, exc_info=True)
            return {
                "patient_id": patient_id, "status": "error",
                "inconsistency": False, "severity": "",
                "workflow_run_id": "", "elapsed_ms": 0, "error": str(exc),
            }
        finally:
            db.close()

        # ── 阶段2：Dify 调用（不持有任何 DB 连接） ──
        dify_input = mr_text or _safe_json_dumps(payload)
        if stop_check and stop_check():
            return {
                "patient_id": real_patient_id, "status": "skipped",
                "inconsistency": False, "severity": "",
                "workflow_run_id": "", "elapsed_ms": 0,
                "error": "cancelled by user", "skip_reason": "cancelled",
            }

        audit_type = push_config.audit_type
        response_cfg = (audit_type.response or {}) if audit_type else {}
        dify_result = self._push_with_empty_retry(
            dify_input, real_patient_id,
            audit_type=audit_type,
            response_paths=response_cfg,
            parse_strategy=str(response_cfg.get("parse_strategy") or "hybrid"),
            stop_check=stop_check,
        )
        if stop_check and stop_check():
            return {
                "patient_id": real_patient_id, "status": "skipped",
                "inconsistency": False, "severity": "",
                "workflow_run_id": "", "elapsed_ms": 0,
                "error": "cancelled by user", "skip_reason": "cancelled",
            }

        # ── 阶段3：结果写入（新 DB 会话） ──
        db = SessionLocal()
        try:
            base_executor._enforce_authoritative_patient_fields(
                dify_result=dify_result, payload=payload,
                patient_records=bundle_records, query_date=push_config.query_date,
                patient_id=real_patient_id,
            )

            payload_for_log = copy.deepcopy(payload)
            payload_for_log["_bulk_push_meta"] = {
                "target_name": dify_result.get("_target_name", ""),
                "empty_retry_count": int(dify_result.get("_empty_retry_count", 0)),
            }

            log = base_executor._create_push_log(
                patient_id=patient_id, patient_records=patient_records,
                dify_result=dify_result, payload=payload_for_log,
                mr_text=mr_text, push_config=push_config,
            )
            db.add(log)
            db.flush()
            if str(response_cfg.get("parse_strategy") or "hybrid") in {"hybrid", "dimensions_only"}:
                base_executor._save_audit_results(db, log.id, dify_result, str(push_config.audit_type_code or ""))
            db.flush()  # 确保维度/结论记录可见，供 relay 查询

            from app.services.push_log_supersede import ensure_supersede
            ensure_supersede(db, log)

            # 高危问题推送到前置机（只 enqueue，dispatch 在 commit 后执行）
            try:
                from app.services.relay_alert_service import RelayAlertService
                from app.config import load_config as _load_cfg
                _relay_svc = RelayAlertService(db, _load_cfg())
                _relay_svc.enqueue_high_severity_alerts(log.id)
            except Exception as _relay_exc:
                logger.error("relay_alert enqueue failed: patient_id=%s err=%s", real_patient_id, _relay_exc, exc_info=True)

            if dify_result.get("inconsistency") and push_config.notify_enabled:
                try:
                    send_notification(real_patient_id, dify_result, self.notify_config)
                except Exception as _exc:
                    logger.error("send notification failed: patient_id=%s err=%s", real_patient_id, _exc, exc_info=True)

            db.commit()

            # 主事务提交后，发送本次记录的待推送前置机告警
            try:
                from app.services.relay_alert_service import RelayAlertService as _RAS
                from app.config import load_config as _lcfg
                _relay_svc = _RAS(db, _lcfg())
                _relay_result = _relay_svc.dispatch_pending(push_log_ids=[log.id])
                if _relay_result.get("sent") or _relay_result.get("failed"):
                    logger.info("relay_alert dispatch: %s", _relay_result)
            except Exception as _relay_exc:
                logger.error("relay_alert dispatch failed: %s", _relay_exc, exc_info=True)

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
            logger.error("bulk push db write failed: patient_id=%s err=%s", patient_id, exc, exc_info=True)
            return {
                "patient_id": patient_id, "status": "error",
                "inconsistency": False, "severity": "",
                "workflow_run_id": "", "elapsed_ms": 0, "error": str(exc),
            }
        finally:
            db.close()

    def _push_with_empty_retry(
        self,
        dify_input: Any,
        patient_id: str,
        audit_type: Any = None,
        response_paths: Optional[Dict[str, Any]] = None,
        parse_strategy: str = "hybrid",
        stop_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        last_result: Dict[str, Any] = {}
        empty_retry_count = 0
        for attempt in range(self.empty_retry_max + 1):
            # 检查取消信号：每次重试循环开头
            if stop_check and stop_check():
                logger.info("[bulk_push] empty retry cancelled: patient_id=%s attempt=%s", patient_id, attempt)
                return {
                    "status": "failed",
                    "error": "cancelled by user during empty retry",
                    "_empty_retry_count": empty_retry_count,
                    "_target_name": last_result.get("_target_name", ""),
                }
            target = self._pick_target()
            logger.info(
                "[audit.dify] target_picked patient_id=%s attempt=%s target=%s strategy=%s",
                patient_id,
                attempt,
                target.name,
                self.target_strategy,
            )
            push_kwargs: Dict[str, Any] = {}
            if response_paths:
                push_kwargs["response_paths"] = response_paths
            if parse_strategy != "hybrid":
                push_kwargs["parse_strategy"] = parse_strategy
            try:
                target_config = with_audit_type_mr_type(target.config, audit_type)
                result = push_to_dify(
                    dify_input,
                    target_config,
                    patient_id,
                    **push_kwargs,
                )
            except TypeError as exc:
                error_text = str(exc)
                if push_kwargs and "unexpected keyword argument" in error_text:
                    result = push_to_dify(dify_input, target_config, patient_id)
                else:
                    raise
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
                # 检查取消信号：sleep 结束后
                if stop_check and stop_check():
                    logger.info("[bulk_push] empty retry cancelled after sleep: patient_id=%s attempt=%s", patient_id, attempt)
                    return {
                        "status": "failed",
                        "error": "cancelled by user during empty retry",
                        "_empty_retry_count": empty_retry_count,
                        "_target_name": last_result.get("_target_name", ""),
                    }

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

        def _sanitize_target(base_cfg: Dict[str, Any], target_cfg: Dict[str, Any]) -> Dict[str, Any]:
            cfg = dict(base_cfg or {})
            cfg["base_url"] = str(target_cfg.get("base_url") or cfg.get("base_url") or "").strip()
            cfg["api_key"] = str(target_cfg.get("api_key") or cfg.get("api_key") or "").strip()
            cfg["name"] = str(target_cfg.get("name") or cfg.get("name") or "")
            cfg["weight"] = int(target_cfg.get("weight", cfg.get("weight", 1)) or 1)
            cfg["enabled"] = bool(target_cfg.get("enabled", cfg.get("enabled", True)))
            cfg["timeout_seconds"] = int(target_cfg.get("timeout_seconds") or cfg.get("timeout_seconds", 90))
            return cfg

        for idx, item in enumerate(source):
            cfg = _sanitize_target(dify_config, dict(item or {}))
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
        unique_identities = {
            (str(t.config.get("base_url") or "").strip(), str(t.config.get("api_key") or "").strip())
            for t in targets if str(t.config.get("base_url") or "").strip()
        }
        if len(targets) >= 2 and len(unique_identities) <= 1:
            logger.warning(
                "[bulk_push] multiple targets configured but (base_url, api_key) are identical: target_count=%s",
                len(targets),
            )
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
