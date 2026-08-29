# -*- coding: utf-8 -*-
"""触发轮询：finished_date_time 增量 + 检查键去重 + 水位持久化 + 防重入锁。

- 检查键 (patient_id, visit_id, finished_date_time)：同一患者完成时间更新 =
  新检查键 → 重新预检（A1 复检闭环）；
- 水位回看窗 lookback_seconds：完成时间在窗内更新的患者也能被重新发现
  （否则其他患者更晚的完成时间会把水位推高，漏掉早回写的复检）；
- 去重表 per (patient_id, visit_id) 记录已处理的 finished_date_time，
  老于等于已处理值的一律跳过；
- RunLock 文件锁防重入（含陈旧锁检测：持锁进程已死则接管）；
- 每处理一例即落盘状态（断点续跑）。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .collectors import JhemrCollector, PatientContextBuilder
from .context import FinishedVisit
from .engine import RuleEngine
from .pusher import WeComPusher
from .store import ResultRepository

logger = logging.getLogger("prearchive.trigger")


# ---------------------------------------------------------------------------
# 水位与检查键状态（JSON 文件持久化）
# ---------------------------------------------------------------------------
class StateStore:
    """state.json：{watermark, last_processed: {"pid|vid": finished_iso}, iterations}"""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {"watermark": None, "last_processed": {}, "iterations": 0}

    def save(self, state: dict) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent),
                                                prefix=".state_", suffix=".tmp")
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(state, handle, ensure_ascii=False)
                os.replace(tmp_name, str(self.path))
            except Exception:
                logger.exception("[state] save failed (keep last good state)")

    @staticmethod
    def key_of(visit: FinishedVisit) -> str:
        return f"{visit.patient_id}|{visit.visit_id}"


# ---------------------------------------------------------------------------
# 防重入锁（文件锁 + PID + 陈旧检测）
# ---------------------------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)   # Windows: 无特权信号探测存活；不存在则 ProcessLookupError/OSError
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


class RunLock:
    def __init__(self, path):
        self.path = Path(path)
        self._held = False

    def acquire(self) -> bool:
        if self._held:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                record = self._read()
                pid = int(record.get("pid") or 0)
                if pid != os.getpid() and _pid_alive(pid):
                    return False        # 别的进程在跑：本轮回跳过（防重入）
                self._release_file()    # 陈旧锁：接管
            fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent),
                                            prefix=".lock_", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"pid": os.getpid(), "ts": datetime.now().isoformat()},
                          handle)
            os.replace(tmp_name, str(self.path))
            self._held = True
            return True
        except Exception:
            logger.exception("[lock] acquire failed; treat as not held (fail-open)")
            return False

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _release_file(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except Exception:
            pass

    def release(self) -> None:
        if self._held:
            self._release_file()
            self._held = False

    @property
    def held(self) -> bool:
        return self._held


# ---------------------------------------------------------------------------
# 单例处理器：采集 → 判定 → 存储 → 推送
# ---------------------------------------------------------------------------
class PrecheckProcessor:
    def __init__(self, context_builder: PatientContextBuilder, engine: RuleEngine,
                 repository: ResultRepository, pusher: WeComPusher):
        self.context_builder = context_builder
        self.engine = engine
        self.repository = repository
        self.pusher = pusher

    def process(self, visit: FinishedVisit,
                check_time: Optional[datetime] = None):
        """处理一次完成事件；任何异常向上抛由轮询层记录（不中断批次内其他患者）。

        check_time 缺省=轮询发现时刻（now）：min_hours_after_event 时间窗以真实
        判定时点衡量，而非锚点时间本身（否则窗口永不过期/永不触发）。
        """
        if check_time is None:
            check_time = datetime.now()
        ctx = self.context_builder.build(visit, check_time=check_time)
        output = self.engine.evaluate(ctx)

        receiver = None
        try:
            receiver = self.pusher.resolver.resolve(ctx)
        except Exception:
            receiver = None

        row = self.repository.upsert_result(
            patient_id=visit.patient_id,
            visit_id=visit.visit_id,
            finished_date_time=visit.finished_date_time,
            problems=output.problems,
            rule_version=output.rule_version,
            dept_code=ctx.dept_code,
            dept_name=ctx.dept_name,
            patient_name=ctx.patient_name,
            receiver=receiver,
        )

        # 推送判定交给 pusher（零问题/影子模式/低于阈值都会返回 skipped 并落状态）
        outcome = self.pusher.push_result(row, ctx)
        self.repository.set_push_status(row.id, "wecom", outcome["status"],
                                        outcome.get("detail", ""))
        return row


# ---------------------------------------------------------------------------
# 轮询器
# ---------------------------------------------------------------------------
@dataclass
class PollStats:
    fetched: int = 0
    processed: int = 0
    skipped_seen: int = 0
    lock_skipped: bool = False
    watermark: Optional[str] = None
    errors: list = field(default_factory=list)


class TriggerPoller:
    def __init__(self, jhemr_collector: JhemrCollector, processor: PrecheckProcessor,
                 state_store: StateStore, lock: RunLock, heartbeat=None,
                 interval_seconds: float = 300, batch_limit: int = 100,
                 lookback_seconds: int = 86400,
                 anchor_mode: str = "finished",
                 clock=time.time):
        self.jhemr = jhemr_collector
        self.processor = processor
        self.state_store = state_store
        self.lock = lock
        self.heartbeat = heartbeat
        self.interval_seconds = float(interval_seconds)
        self.batch_limit = int(batch_limit)
        self.lookback = timedelta(seconds=int(lookback_seconds))
        self.anchor_mode = str(anchor_mode or "finished")   # T2-1：默认 finished 行为不变
        self.clock = clock

    # -- 查询边界：水位回看窗内的完成记录（复检发现靠窗，不靠严格 > watermark）
    def _since_bound(self, watermark: Optional[str]) -> Optional[datetime]:
        if not watermark:
            return None
        try:
            base = datetime.fromisoformat(str(watermark))
        except ValueError:
            return None
        return base - self.lookback

    def _seen_finished(self, last_processed: dict, visit: FinishedVisit):
        """检查键去重：该 (pid,vid) 已处理过 >= 本次完成时间 → 已见过。"""
        seen_iso = last_processed.get(StateStore.key_of(visit))
        if not seen_iso:
            return False
        try:
            seen = datetime.fromisoformat(seen_iso)
        except ValueError:
            return False
        return visit.finished_date_time <= seen

    def _collect_new_visits(self, watermark, last_processed: dict) -> tuple:
        """分页扫描回看窗，收集未处理过的新检查键（limit 只计入新键）。

        返回 (new_visits, fetched_total, skipped_seen, errors)。
        窗口内旧键（已处理）重复出现时不算批次额度，否则旧键会占满 limit
        卡死水位推进；翻页用游标 + examined 集合防重复。
        """
        new_visits: list = []
        examined: set = set()
        cursor = self._since_bound(watermark)
        page_size = max(self.batch_limit, 1)
        fetched_total = 0
        skipped_seen = 0
        for _ in range(50):   # 翻页安全阀
            try:
                visits = self.jhemr.fetch_anchor_visits(cursor, page_size,
                                                       self.anchor_mode)
            except Exception as exc:  # noqa: BLE001
                return new_visits, fetched_total, skipped_seen, \
                    [f"fetch_finished_visits: {exc}"]
            fetched_total += len(visits)
            if not visits:
                break
            for visit in visits:
                key = (StateStore.key_of(visit),
                       visit.finished_date_time.isoformat())
                if key in examined:
                    continue
                examined.add(key)
                if self._seen_finished(last_processed, visit):
                    skipped_seen += 1
                    continue
                new_visits.append(visit)
                if len(new_visits) >= self.batch_limit:
                    return new_visits, fetched_total, skipped_seen, []
            if len(visits) < page_size:
                break   # 窗口取尽
            # 游标回退 1s：容忍同秒多行跨页（examined 集合防重复）
            cursor = visits[-1].finished_date_time - timedelta(seconds=1)
        return new_visits, fetched_total, skipped_seen, []

    def poll_once(self) -> PollStats:
        stats = PollStats()
        if not self.lock.acquire():
            stats.lock_skipped = True   # 防重入：上一轮还在跑
            return stats
        try:
            state = self.state_store.load()
            watermark = state.get("watermark")
            last_processed = dict(state.get("last_processed") or {})
            iterations = int(state.get("iterations") or 0)

            visits, fetched_total, skipped_seen, fetch_errors = \
                self._collect_new_visits(watermark, last_processed)
            stats.fetched = fetched_total
            stats.skipped_seen = skipped_seen
            stats.errors.extend(fetch_errors)
            if fetch_errors:
                logger.exception("[poll] fetch failed")

            for visit in visits:
                key = StateStore.key_of(visit)
                try:
                    self.processor.process(visit)
                    stats.processed += 1
                    iterations += 1
                except Exception as exc:  # noqa: BLE001 —— 单患者失败不毒化批次
                    stats.errors.append(f"{key}: {exc}")
                    logger.exception("[poll] process failed: %s", key)
                    continue

                last_processed[key] = visit.finished_date_time.isoformat()
                if watermark is None or visit.finished_date_time.isoformat() > str(watermark):
                    watermark = visit.finished_date_time.isoformat()
                # 断点续跑：逐例落盘
                self.state_store.save({
                    "watermark": watermark,
                    "last_processed": last_processed,
                    "iterations": iterations,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                })

            self.state_store.save({
                "watermark": watermark,
                "last_processed": last_processed,
                "iterations": iterations,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
            stats.watermark = watermark

            if self.heartbeat is not None:
                self.heartbeat.write({
                    "watermark": watermark,
                    "processed_total": iterations,
                    "interval_seconds": self.interval_seconds,
                })
            return stats
        finally:
            self.lock.release()

    def run_forever(self, stop_event: Optional[threading.Event] = None) -> None:
        """常驻轮询（服务线程入口）；stop_event 置位即退出。"""
        stop = stop_event or threading.Event()
        while not stop.is_set():
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001 —— 轮询主循环永不因单轮异常退出
                logger.exception("[poll] unexpected error in loop iteration")
            self._sleep(stop)

    def _sleep(self, stop: threading.Event) -> None:
        # 分片睡眠：退出信号秒级响应
        deadline = self.clock() + self.interval_seconds
        while not stop.is_set():
            remaining = deadline - self.clock()
            if remaining <= 0:
                return
            stop.wait(min(remaining, 1.0))
