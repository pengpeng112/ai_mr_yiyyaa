"""异步推送执行器 —— 统一进度回调、取消检查、单条事务。"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List

from app.services.push_executor import PushConfig, PushExecutor, PushResult

logger = logging.getLogger(__name__)


class AsyncCallbackPushExecutor(PushExecutor):
    """支持进度回调和取消检查的异步推送执行器。

    保持与 PushExecutor 相同的构造函数和 _push_single_record 方法，
    重写 execute() 以支持：
    - 每条记录 begin_nested() 事务隔离
    - 单条失败不污染整批
    - 进度回调 on_item_done(status)
    - 取消检查 stop_check() -> bool
    """

    def __init__(
        self,
        dify_config: Dict[str, Any],
        notify_config: Dict[str, Any] = None,
        field_mapping: Dict[str, str] = None,
        on_item_done: Callable[[str], None] = None,
        stop_check: Callable[[], bool] = None,
        cancel_log_prefix: str = "async",
    ):
        super().__init__(dify_config, notify_config, field_mapping)
        self._on_item_done = on_item_done
        self._stop_check = stop_check
        self._cancel_log_prefix = cancel_log_prefix

    def execute(self, db, grouped_records, push_config: PushConfig) -> PushResult:
        start_time = time.time()
        result = PushResult(total=len(grouped_records))
        try:
            for patient_id, patient_records in grouped_records.items():
                if self._stop_check and self._stop_check():
                    logger.info(
                        "%s push cancelled: processed=%s/%s",
                        self._cancel_log_prefix,
                        result.success + result.failed,
                        result.total,
                    )
                    break
                try:
                    with db.begin_nested():
                        single_result = self._push_single_record(db, patient_id, patient_records, push_config)
                    result.results.append(single_result)
                    status = str(single_result.get("status", "failed"))
                    if status == "success":
                        result.success += 1
                    elif status == "skipped":
                        result.skipped += 1
                    else:
                        result.failed += 1
                    if self._on_item_done:
                        self._on_item_done(status)
                    time.sleep(push_config.interval_ms / 1000)
                except Exception as exc:
                    logger.error(
                        "%s push single patient failed: patient_id=%s err=%s",
                        self._cancel_log_prefix,
                        patient_id,
                        exc,
                        exc_info=True,
                    )
                    result.failed += 1
                    result.results.append({"patient_id": patient_id, "status": "error", "error": str(exc)})
                    if self._on_item_done:
                        self._on_item_done("failed")
            db.commit()
        except Exception:
            db.rollback()
            raise
        result.duration_seconds = time.time() - start_time
        return result
