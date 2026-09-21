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
                 repository: ResultRepository, pusher: WeComPusher,
                 source_ready_gate_disabled: bool = False,
                 eval_store=None, trigger_type: str = "paperless_rpa",
                 catalog_provider=None, issue_service=None,
                 delivery_emitter=None):
        self.context_builder = context_builder
        self.engine = engine
        self.repository = repository
        self.pusher = pusher
        # T8-1：paperless_rpa 模式置 True（R5 水位门禁用）
        self.source_ready_gate_disabled = bool(source_ready_gate_disabled)
        self.last_reconciliation: dict = {}   # T8-1：RPTCOUNT 对账（仅告警）
        # 046 T2/F06：评估运行存储 + 触发类型 + 目录计数供给
        self.eval_store = eval_store
        self.trigger_type = trigger_type
        self.catalog_provider = catalog_provider
        # 046 T5：fail 评估 → 稳定缺陷实例（人工动作/复检收敛/接收端撤销的锚点）
        self.issue_service = issue_service
        # 046 T6/F03：run 完成后自动落投递事件（治理过滤→Outbox 入队）
        self.delivery_emitter = delivery_emitter

    def _rule_sources(self) -> dict:
        """规则 → 引用源（汇总 data_coverage 用）。"""
        sources = {}
        for rule in getattr(self.engine, "rules", []) or []:
            refs = set((rule.match or {}).get("sources") or [])
            trigger = rule.trigger or {}
            if trigger.get("patient_has") == "surgery":
                refs.add(str((trigger.get("evidence") or {}).get(
                    "surgery_evidence") or "sm_itf_entry"))
            elif trigger.get("patient_has") == "lab_order":
                refs.add("his_itf")
            sources[rule.rule_id] = sorted(refs)
        return sources

    def _summary_context(self) -> dict:
        catalog_count, mapped = 92, 0
        if self.catalog_provider is not None:
            try:
                provided = self.catalog_provider()
                catalog_count = int(provided.get("catalog_count", 92))
                mapped = int(provided.get("mapped_catalog_count", 0))
            except Exception:  # noqa: BLE001 —— 目录供给失败不阻断检查
                pass
        else:
            try:
                fids = {r.mark_item_fid for r in getattr(self.engine, "rules", [])
                        if r.mark_item_fid is not None}
                mapped = len(fids)
            except Exception:
                mapped = 0
        return {"catalog_count": catalog_count,
                "mapped_catalog_count": mapped,
                "rule_sources": self._rule_sources()}

    def process(self, visit: FinishedVisit,
                check_time: Optional[datetime] = None,
                trigger_type: Optional[str] = None,
                run_id: Optional[str] = None):
        """处理一次完成事件；任何异常向上抛由轮询层记录（不中断批次内其他患者）。

        check_time 缺省=轮询发现时刻（now）：min_hours_after_event 时间窗以真实
        判定时点衡量，而非锚点时间本身（否则窗口永不过期/永不触发）。
        046 T7：集成入口可透传 trigger_type（emr_submit/manual_recheck）与
        预创建 run_id（占位 run 由主链路接管，run_revision 已定）。
        """
        if check_time is None:
            check_time = datetime.now()
        ctx = self.context_builder.build(visit, check_time=check_time)
        if self.source_ready_gate_disabled:
            ctx.source_ready_gate_disabled = True
        output = self.engine.evaluate(ctx)

        # T8-1：RPTCOUNT 仅采集总量对账（多算/少算告警，不宣称护理缺项，R3）
        if getattr(visit, "rpt_count", 0):
            from .paperless_rpa import reconcile_report_count

            recon = reconcile_report_count(visit.rpt_count, len(ctx.documents))
            self.last_reconciliation = {
                "patient_id": visit.patient_id, "visit_id": visit.visit_id, **recon}
            if recon["status"] != "match":
                logger.warning("[rpa-reconcile] %s/%s %s", visit.patient_id,
                               visit.visit_id, recon)

        receiver = None
        try:
            receiver = self.pusher.resolver.resolve(ctx)
        except Exception:
            receiver = None

        # 046 T2/F06：RUN + RULE_EVAL + 汇总（eval_store 缺省=旧行为，仅 problems）
        run = None
        summary = None
        health = None
        if self.eval_store is not None:
            from .eval_store import build_summary, source_health
            summary_ctx = self._summary_context()
            health = source_health(ctx)
            ruleset_hash = ""
            try:
                import hashlib as _hash
                ruleset_hash = _hash.sha256(
                    str(output.rule_version).encode("utf-8")).hexdigest()[:16]
            except Exception:
                ruleset_hash = ""
            run = self.eval_store.start_run(
                patient_id=visit.patient_id,
                visit_number=ctx.visit_number or visit.visit_id,
                trigger_type=trigger_type or self.trigger_type,
                trigger_id=f"{visit.finished_date_time.isoformat()}",
                ruleset_revision=str(output.rule_version),
                ruleset_hash=ruleset_hash,
                dept_code=ctx.dept_code, dept_name=ctx.dept_name,
                run_id=run_id or "")
            self.eval_store.record_evals(run.id, output.evaluations)
            summary = build_summary(
                evaluations=output.evaluations,
                catalog_count=summary_ctx["catalog_count"],
                mapped_catalog_count=summary_ctx["mapped_catalog_count"],
                source_health_map=health,
                rule_sources=summary_ctx["rule_sources"])

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
            evaluations=output.evaluations,
            notices=output.notices,
            source_health=health,
            summary=summary,
        )

        if run is not None and summary is not None:
            has_source_error = any(
                v.get("status") == "error" for v in (health or {}).values())
            run_status = "partial" if has_source_error else "completed"
            # D-J1（050 §0.1-1 A 案）：物化先于 finish_run——run 一旦置
            # completed/partial，JHEMR GET 读到的 issues 必须已含本次 run 的
            # 物化结果。物化失败不得发布 completed：内联重试一次，仍败则降级
            # partial 并在 source_health 留 issues_materialization 诊断。
            # emit 仍用 finish 后的最新 run（envelope checked_at 依赖），只前移物化块。
            resolutions = []
            if self.issue_service is not None and not getattr(run, "is_trial", 0):
                materialized = None
                try:
                    materialized = self.issue_service.materialize_for_run(run.id)
                except Exception:  # noqa: BLE001 —— 物化失败不阻断检查主链路
                    logger.exception(
                        "[issues] materialize failed for run %s (retry once)",
                        run.id)
                    try:
                        materialized = self.issue_service.materialize_for_run(
                            run.id)
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "[issues] materialize retry failed for run %s; "
                            "downgrade run to partial", run.id)
                        run_status = "partial"
                        health = dict(health or {})
                        health["issues_materialization"] = {"status": "error"}
                if materialized is not None:
                    resolutions = [
                        {"issue_key": item["issue_key"],
                         "rule_id": item["rule_id"],
                         "event_instance_id": item.get("event_instance_id", ""),
                         "fid": item.get("fid")}
                        for item in materialized.get("resolved_issue_keys") or []
                    ]
            finished = self.eval_store.finish_run(
                run.id, run_status, summary, health or {}, result_id=row.id,
                checked_at=check_time, data_snapshot_at=check_time)
            if finished is not None:   # 用 finish 后的最新 run 状态（checked_at 等）
                run = finished
            # 046 T6/F03：run 完成+物化后自动入队投递事件（trial 在 emit 内跳过）；
            # 失败不阻断主链路，由 worker 循环的 reconcile 补偿（确定性 event_id 幂等）
            if self.delivery_emitter is not None:
                try:
                    self.delivery_emitter.emit(
                        run=run, result_row=row, problems=output.problems,
                        summary=summary, resolutions=resolutions,
                        rule_version=str(output.rule_version))
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "[delivery] emit failed for run %s (reconcile backfills)",
                        run.id)

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
                 paperless_rpa_collector=None,
                 clock=time.time):
        self.jhemr = jhemr_collector
        self.paperless_rpa = paperless_rpa_collector   # T8-1（anchor_mode=paperless_rpa）
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
                if self.anchor_mode == "paperless_rpa":
                    visits = self.paperless_rpa.fetch_anchor_visits(
                        cursor, page_size, self.anchor_mode)
                else:
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
