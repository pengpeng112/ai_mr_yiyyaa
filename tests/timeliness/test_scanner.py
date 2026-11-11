"""T4：影子扫描器、调度注册与原生对账分类的本地假数据测试。

覆盖（主设计文档 §15 T4 / 用户任务书）：
- T1 fixture 列口径 + 假 Reader 跑完整扫描（启用规则逐条建台账、状态正确）；
- 重复扫描幂等：不重复建事件、无状态变化不写历史；
- 状态变化（OVERDUE→COMPLETED_LATE）写 tl_event_history；
- 锁被占用时跳过（tl_scan_run=SKIPPED，不建事件）；
- TimelinessPermissionMissing：error_text 记录缺权限表名并安全退出；
- 扫描软超时：记 FAILED 不重试；
- timeliness.enabled=false 时调度器不注册任务（含 scheduler.py 追加调用源码守卫）；
- 对账 classify_reconciliation 四类（含 R3 幽灵行）+ 两个补充清单 + 患者号脱敏。
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.timeliness.config import TimelinessPermissionMissing
from app.timeliness.models import TLEvent, TLEventHistory, TLRule, TLScanRun
from app.timeliness.rules_seed import seed_rules
from app.timeliness.scanner import (
    SCAN_JOB_ID,
    SCAN_LOCK_NAME,
    TimelinessScanner,
    register_timeliness_job,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
T1_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "jhemr_expected_columns.json"
RECONCILE_SCRIPT = REPO_ROOT / "scripts" / "timeliness" / "reconcile_native.py"

# 固定时钟：所有推导以 NOW 为准。
NOW = datetime(2026, 11, 10, 12, 0, 0)


def _clock(value: datetime = NOW):
    return lambda: value


# ---- 假 Reader（行结构按 T1 fixture 列口径构造） ----


class FakeReader:
    """内存假 Reader：分页取数按患者对过滤；可注入权限异常。"""

    def __init__(self, *, inpatients=None, discharges=None, operations=None, files=None,
                 consult_applies=None, limit_logs=None, permission_table: str = ""):
        self.inpatients = list(inpatients or [])
        self.discharges = list(discharges or [])
        self.operations = list(operations or [])
        self.files = list(files or [])
        self.consult_applies = list(consult_applies or [])
        self.limit_logs = list(limit_logs or [])
        self.permission_table = permission_table

    def _guard(self):
        if self.permission_table:
            raise TimelinessPermissionMissing(f"jhemr.{self.permission_table}")

    def list_inpatients(self):
        self._guard()
        return list(self.inpatients)

    def list_recent_discharges(self, days):
        self._guard()
        return list(self.discharges)

    @staticmethod
    def _by_pairs(rows, patient_visits):
        wanted = {(str(p[0]), str(p[1])) for p in patient_visits or ()}
        return [r for r in rows if (str(r.get("patient_id")), str(r.get("visit_id"))) in wanted]

    def list_files(self, patient_visits):
        self._guard()
        return self._by_pairs(self.files, patient_visits)

    def list_operations(self, patient_visits):
        self._guard()
        return self._by_pairs(self.operations, patient_visits)

    def list_consult_applies(self, since):
        self._guard()
        return list(self.consult_applies)

    def list_limit_logs(self, since):
        self._guard()
        return list(self.limit_logs)


class FakeLock:
    """可注入的进程内锁：默认可获取；hold=True 模拟被他方占用。"""

    def __init__(self, hold: bool = False):
        self.hold = hold
        self.released: list[str] = []

    def acquire(self):
        if self.hold:
            return False, "owner-other", "scheduler lock is running by owner-other"
        return True, "owner-me", "acquired"

    def release(self, owner_id):
        self.released.append(owner_id)


# ---- 公共 fixture ----


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    seed_rules(session)
    yield session
    session.close()


def _enable(db, *codes):
    for code in codes:
        rule = db.query(TLRule).filter(TLRule.rule_code == code).one()
        rule.enabled = True
    db.commit()


def _file(pid, vid, fid, mr_class, *, topic="", sign=None, created=None, delete_flag=0,
          monitor_code=None):
    return {
        "patient_id": pid, "visit_id": vid, "file_unique_id": fid, "mr_class": mr_class,
        "topic": topic, "monitor_code": monitor_code, "file_flag": "1" if sign else "T",
        "create_date_time": created or sign or NOW,
        "first_mr_sign_date_time": sign, "last_modify_date_time": sign or NOW,
        "topic_title_name": topic, "dept_code": "020307", "delete_flag": delete_flag,
    }


def _inpatient(pid, vid, admitted):
    return {"patient_id": pid, "visit_id": vid, "dept_code": "020307",
            "admission_date_time": admitted, "dept_discharge_from": None,
            "discharge_date_time": None}


def _discharge(pid, vid, discharged):
    return {"patient_id": pid, "visit_id": vid, "dept_discharge_from": "0201",
            "discharge_date_time": discharged}


def build_reader() -> FakeReader:
    """五名患者覆盖：PENDING/OVERDUE/按时完成/超时完成/出院完成/术后超时/老手术过滤。"""
    return FakeReader(
        inpatients=[
            _inpatient("PID0001", "1", datetime(2026, 11, 10, 6, 0)),     # 未到期
            _inpatient("PID0002", "1", datetime(2026, 11, 9, 6, 0)),      # 双双超时无文书
            _inpatient("PID0003", "1", datetime(2026, 11, 9, 6, 0)),      # 有签名文书
            _inpatient("PID0005", "1", datetime(2026, 11, 8, 8, 0)),      # 手术患者
        ],
        discharges=[
            _discharge("PID0004", "1", datetime(2026, 11, 9, 18, 0)),     # 出院已写记录
        ],
        operations=[
            {"patient_id": "PID0005", "visit_id": "1", "operation_no": "OP1",
             "operation_desc": "鼻骨折闭合性复位术", "operating_date": datetime(2026, 11, 10, 1, 0),
             "operating_end_date": datetime(2026, 11, 10, 2, 0)},          # 窗口内
            {"patient_id": "PID0005", "visit_id": "1", "operation_no": "OP0",
             "operation_desc": "旧手术", "operating_date": datetime(2026, 10, 1, 9, 0),
             "operating_end_date": datetime(2026, 10, 1, 10, 0)},          # 超 7 天窗口，应过滤
        ],
        files=[
            _file("PID0003", "1", "F1", "EMR09.00.01", topic="鼻骨骨折",
                  sign=datetime(2026, 11, 9, 20, 0)),                      # 入院记录按时完成
            _file("PID0003", "1", "F2", "EMR10.00.01", topic="首次病程记录",
                  sign=datetime(2026, 11, 10, 3, 0)),                      # 首程超时完成
            _file("PID0004", "1", "F3", "EMR12.00", topic="鼻息肉出院",
                  sign=datetime(2026, 11, 9, 20, 0)),                      # 出院记录按时完成
        ],
    )


EXPECTED_FIRST_SCAN = {  # event_uid → 期望状态（P5 为在院患者，同样产生入院族事件）
    "ADM_REC:PID0001:1:1": "PENDING",
    "FIRST_COURSE:PID0001:1:1": "PENDING",
    "ADM_REC:PID0002:1:1": "OVERDUE",
    "FIRST_COURSE:PID0002:1:1": "OVERDUE",
    "ADM_REC:PID0003:1:1": "COMPLETED_ON_TIME",
    "FIRST_COURSE:PID0003:1:1": "COMPLETED_LATE",
    "DISCHARGE_REC:PID0004:1:1": "COMPLETED_ON_TIME",
    "ADM_REC:PID0005:1:1": "OVERDUE",
    "FIRST_COURSE:PID0005:1:1": "OVERDUE",
    "POSTOP_FIRST_COURSE:PID0005:1:OP1": "OVERDUE",
}


def run_once(db, reader, *, lock=None, now=NOW, **kwargs):
    lock = lock or FakeLock()
    scanner = TimelinessScanner(db, reader, now_fn=_clock(now), acquire_lock=lock.acquire,
                                release_lock=lock.release, **kwargs)
    return scanner.run_scan(), lock


# ---- 完整扫描（T1 fixture 列口径） ----


def test_fake_rows_match_t1_fixture_columns():
    """假数据行列名必须是 T1 fixture 实证列的子集（T1 口径一致性守卫）。"""
    fixture = json.loads(T1_FIXTURE.read_text(encoding="utf-8"))
    columns = {
        table: set(spec["columns"])
        for table, spec in fixture["tables"].items()
    }
    reader = build_reader()
    for row in reader.inpatients + reader.discharges:
        assert set(row) <= columns["jhemr.pats_in_hospital"] | columns["jhemr.pat_visit"]
    for row in reader.operations:
        assert set(row) <= columns["jhemr.operation"]
    for row in reader.files:
        assert set(row) <= columns["jhemr.jhmr_file_index"]


def test_full_scan_creates_ledger_and_histories(db):
    _enable(db, "ADM_REC", "FIRST_COURSE", "DISCHARGE_REC", "POSTOP_FIRST_COURSE")
    summary, lock = run_once(db, build_reader())

    assert summary["status"] == "SUCCESS"
    assert summary["skipped"] is False and summary["failed"] is False
    assert summary["patients_scanned"] == 5
    assert summary["events_created"] == 10
    assert summary["events_updated"] == 0
    assert lock.released == ["owner-me"]           # 正常结束释放锁

    events = {e.event_uid: e for e in db.query(TLEvent).all()}
    assert set(events) == set(EXPECTED_FIRST_SCAN)
    for uid, status in EXPECTED_FIRST_SCAN.items():
        assert events[uid].status == status, uid
    # 只处理 enabled 规则：CHIEF_FIRST_ROUND 未启用，不应有任何事件
    assert not [u for u in events if u.startswith("CHIEF_FIRST_ROUND")]
    # 近 7 天手术窗口：旧手术 OP0 被过滤，不产生事件
    assert "POSTOP_FIRST_COURSE:PID0005:1:OP0" not in events
    # 超时事件带 overdue_minutes
    assert events["ADM_REC:PID0002:1:1"].overdue_minutes == 360
    # 每个新建事件各有一条 from_status=None 的历史
    histories = db.query(TLEventHistory).all()
    assert len(histories) == 10
    assert all(h.from_status is None and h.to_status for h in histories)
    assert {h.scan_run_id for h in histories} == {summary["scan_run_id"]}
    # tl_scan_run 落一行 SUCCESS
    runs = db.query(TLScanRun).all()
    assert len(runs) == 1 and runs[0].status == "SUCCESS"
    assert runs[0].events_created == 10 and runs[0].patients_scanned == 5


def test_repeat_scan_is_idempotent(db):
    _enable(db, "ADM_REC", "FIRST_COURSE", "DISCHARGE_REC", "POSTOP_FIRST_COURSE")
    reader = build_reader()
    run_once(db, reader)
    summary2, _ = run_once(db, reader)

    assert summary2["status"] == "SUCCESS"
    assert summary2["events_created"] == 0          # 不重复建事件
    assert summary2["events_updated"] == 10         # 既有事件全部刷新 last_scan_at
    assert db.query(TLEvent).count() == 10
    assert db.query(TLEventHistory).count() == 10   # 无状态变化 → 不新增历史
    assert db.query(TLScanRun).count() == 2


def test_status_change_writes_history(db):
    _enable(db, "ADM_REC")
    reader = build_reader()
    run_once(db, reader)
    # 复扫前补签名入院记录：OVERDUE → COMPLETED_LATE
    reader.files.append(
        _file("PID0002", "1", "F9", "EMR09.00.01", topic="入院记录",
              sign=datetime(2026, 11, 10, 10, 0))
    )
    summary3, _ = run_once(db, reader)

    assert summary3["events_created"] == 0
    event = db.query(TLEvent).filter(
        TLEvent.event_uid == "ADM_REC:PID0002:1:1").one()
    assert event.status == "COMPLETED_LATE"
    change = (db.query(TLEventHistory)
              .filter(TLEventHistory.event_id == event.id,
                      TLEventHistory.from_status == "OVERDUE")
              .one())
    assert change.to_status == "COMPLETED_LATE"
    assert change.scan_run_id == summary3["scan_run_id"]


def test_disabled_rules_produce_nothing(db):
    """全部规则保持种子停用态：扫描成功但零事件。"""
    summary, _ = run_once(db, build_reader())
    assert summary["status"] == "SUCCESS"
    assert summary["events_created"] == 0
    assert db.query(TLEvent).count() == 0


# ---- 锁与异常路径 ----


def test_scan_skipped_when_lock_held(db):
    _enable(db, "ADM_REC", "FIRST_COURSE")
    summary, lock = run_once(db, build_reader(), lock=FakeLock(hold=True))

    assert summary["status"] == "SKIPPED" and summary["skipped"] is True
    assert "not acquired" in summary["error_text"]
    assert db.query(TLEvent).count() == 0            # 不做任何扫描动作
    assert db.query(TLEventHistory).count() == 0
    run_row = db.query(TLScanRun).one()
    assert run_row.status == "SKIPPED" and run_row.finished_at is not None
    assert lock.released == []                       # 未获取锁不释放


def test_permission_missing_records_table_and_exits_safely(db):
    _enable(db, "ADM_REC")
    reader = build_reader()
    reader.permission_table = "pat_visit"
    summary, lock = run_once(db, reader)

    assert summary["status"] == "FAILED" and summary["failed"] is True
    assert "jhemr.pat_visit" in summary["error_text"]   # 缺权限表名清晰入账
    assert "SELECT" in summary["error_text"]
    assert db.query(TLEvent).count() == 0
    assert db.query(TLScanRun).one().status == "FAILED"
    assert lock.released == ["owner-me"]            # 已获取的锁安全释放


def test_scan_timeout_marks_failed_without_retry(db):
    _enable(db, "ADM_REC", "FIRST_COURSE")
    summary, _ = run_once(db, build_reader(), timeout_seconds=-1)  # 固定时钟 elapsed=0，负阈值立即超时

    assert summary["status"] == "FAILED"
    assert "timeout" in summary["error_text"]
    assert db.query(TLEvent).count() == 0
    run_row = db.query(TLScanRun).one()
    assert run_row.status == "FAILED" and run_row.finished_at is not None


def test_fetch_phase_timeout_uses_live_clock(db):
    """修订回归（2026-11-11）：取数阶段超时必须按活时钟生效。

    此前 fetch_scan_snapshot 用 now-started 静态差值（扫描器传 now==started_at，
    elapsed 恒为 0），取数阶段的 4 分钟上限永不触发；本用例用步进时钟证明
    取数第一个探针即超时（elapsed=300s > 240s 上限）。
    """
    _enable(db, "ADM_REC", "FIRST_COURSE")
    clock_state = {"now": NOW}

    def advancing_clock() -> datetime:
        value = clock_state["now"]
        clock_state["now"] = value + timedelta(seconds=300)   # 每次读钟 +5 分钟
        return value

    lock = FakeLock()
    scanner = TimelinessScanner(
        db, build_reader(),
        now_fn=advancing_clock,
        timeout_seconds=240,
        acquire_lock=lock.acquire, release_lock=lock.release,
    )
    summary = scanner.run_scan()

    assert summary["status"] == "FAILED"
    assert "timeout" in summary["error_text"] and "240" in summary["error_text"]
    assert db.query(TLEvent).count() == 0    # 取数阶段超时：零事件落库
    assert lock.released == ["owner-me"]
    run_row = db.query(TLScanRun).one()
    assert run_row.status == "FAILED" and run_row.finished_at is not None


# ---- 调度注册（timeliness.enabled=false 不注册） ----


class FakeScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, func, *, trigger=None, id=None, **kwargs):
        self.jobs.append(SimpleNamespace(func=func, trigger=trigger, id=id, **kwargs))


def test_register_not_done_when_timeliness_disabled():
    scheduler = FakeScheduler()
    result = register_timeliness_job(
        scheduler, config={"timeliness": {"enabled": False, "scan_interval_minutes": 5}}
    )
    assert result is False
    assert scheduler.jobs == []


def test_register_not_done_when_section_missing():
    scheduler = FakeScheduler()
    assert register_timeliness_job(scheduler, config={}) is False
    assert scheduler.jobs == []


def test_register_adds_interval_job_when_enabled():
    scheduler = FakeScheduler()
    result = register_timeliness_job(
        scheduler,
        config={"timeliness": {"enabled": True, "scan_interval_minutes": 15}},
    )
    assert result is True
    assert len(scheduler.jobs) == 1
    job = scheduler.jobs[0]
    assert job.id == SCAN_JOB_ID == "timeliness_scan"
    assert job.trigger.interval == timedelta(minutes=15)


def test_register_rejects_invalid_interval():
    scheduler = FakeScheduler()
    assert register_timeliness_job(
        scheduler, config={"timeliness": {"enabled": True, "scan_interval_minutes": 0}}
    ) is False
    assert scheduler.jobs == []


def test_scheduler_py_wires_registration_and_lock_name():
    """源码守卫：start_scheduler 追加了注册调用；锁名/任务 ID 与文档一致。"""
    source = (REPO_ROOT / "app" / "scheduler.py").read_text(encoding="utf-8")
    assert "register_timeliness_job(_scheduler)" in source
    assert SCAN_LOCK_NAME == "timeliness_scan"


# ---- 对账分类（含 R3 幽灵行） ----


def _load_reconcile_module():
    spec = importlib.util.spec_from_file_location("timeliness_reconcile_native", RECONCILE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def reconcile():
    return _load_reconcile_module()


def _event(pid, rule_code, status):
    return {"patient_id": pid, "visit_id": "1", "rule_code": rule_code, "status": status}


def _monitor(pid, item_code, completed):
    return {"patient_id": pid, "visit_id": "1", "item_code": item_code,
            "completed_date": completed}


def test_reconcile_classifies_four_categories_including_ghost_rows(reconcile):
    """四类 + 补充清单逐患者分类：B 类即实证 R3 幽灵行。"""
    events = [
        _event("P1000001", "FIRST_COURSE", "OVERDUE"),            # → A 两边都未完成
        _event("P2000002", "FIRST_COURSE", "COMPLETED_ON_TIME"),  # → B 幽灵行（R3）
        _event("P3000003", "FIRST_COURSE", "PENDING"),            # → C 原生完成引擎未完成
        _event("P4000004", "FIRST_COURSE", "COMPLETED_LATE"),     # → D 两边都完成
        _event("P5000005", "FIRST_COURSE", "OVERDUE"),            # → 补充1 仅引擎
    ]
    monitor_rows = [
        _monitor("P1000001", "JH04.02.002", None),                # 未关闭
        _monitor("P2000002", "JH04.02.002", None),                # 引擎完成但未关闭 → 幽灵行
        _monitor("P3000003", "JH04.02.002", "2026-11-09 10:00"),
        _monitor("P4000004", "JH04.02.002", "2026-11-09 09:00"),
        _monitor("P6000006", "JH04.02.002", None),                # → 补充2 仅原生
        # 其他监控码不参与本规则对账
        _monitor("P1000001", "JH04.02.001", None),
    ]
    classified = reconcile.classify_reconciliation(
        events, monitor_rows, rule_code="FIRST_COURSE", item_code="JH04.02.002")

    assert [e["patient_id_masked"] for e in classified["both_open"]] == ["****0001"]
    ghost = classified["engine_done_native_open"]
    assert [e["patient_id_masked"] for e in ghost] == ["****0002"]
    assert ghost[0]["engine_done"] is True and ghost[0]["native_state"] == "open"
    assert [e["patient_id_masked"] for e in classified["native_done_engine_open"]] == ["****0003"]
    assert [e["patient_id_masked"] for e in classified["both_done"]] == ["****0004"]
    assert [e["patient_id_masked"] for e in classified["engine_only"]] == ["****0005"]
    assert [e["patient_id_masked"] for e in classified["native_only"]] == ["****0006"]


def test_reconcile_multi_row_native_open_beats_closed(reconcile):
    """患者有多行监控行（如转科重复生成）：任一行未关闭即视为原生未关闭。"""
    events = [_event("P7000007", "ADM_REC", "COMPLETED_ON_TIME")]
    monitor_rows = [
        _monitor("P7000007", "JH04.02.001", "2026-11-08 09:00"),  # 已关闭
        _monitor("P7000007", "JH04.02.001", None),                 # 未关闭（重复行）
    ]
    classified = reconcile.classify_reconciliation(
        events, monitor_rows, rule_code="ADM_REC", item_code="JH04.02.001")
    assert len(classified["engine_done_native_open"]) == 1       # 幽灵行
    assert classified["both_done"] == []
    entry = classified["engine_done_native_open"][0]
    assert entry["monitor_rows"] == 2


def test_reconcile_masks_patient_ids(reconcile):
    assert reconcile.mask_patient_id("0123456789") == "****6789"
    assert reconcile.mask_patient_id("1234") == "****1234"
    assert reconcile.mask_patient_id("") == ""   # 空号原样返回（分类层已跳过空号）


def test_reconcile_fixture_flow_and_report_render(reconcile, tmp_path):
    """fixture 全链路：classify_from_fixture → render_report 输出脱敏 Markdown。"""
    fixture = {
        "events": [
            _event("P1000001", "ADM_REC", "COMPLETED_ON_TIME"),
            _event("P2000002", "ADM_REC", "OVERDUE"),
            _event("P1000001", "FIRST_COURSE", "COMPLETED_ON_TIME"),
        ],
        "monitor_rows": [
            _monitor("P1000001", "JH04.02.001", None),            # 幽灵行
            _monitor("P1000001", "JH04.02.002", "2026-11-09 08:00"),
            _monitor("P2000002", "JH04.02.001", "2026-11-09 07:00"),
        ],
    }
    classified = reconcile.classify_from_fixture(fixture)
    assert len(classified["ADM_REC"]["engine_done_native_open"]) == 1
    assert len(classified["ADM_REC"]["native_done_engine_open"]) == 1
    assert len(classified["FIRST_COURSE"]["both_done"]) == 1

    report = reconcile.render_report(
        classified, generated_at="2026-11-10 12:00:00", source_label="fixture(test)")
    assert "引擎完成但原生未关闭" in report
    assert "****0001" in report and "P1000001" not in report   # 全文无完整患者号
    assert "JH04.02.001" in report and "幽灵行" in report
    out = tmp_path / "report.md"
    out.write_text(report, encoding="utf-8")
    assert out.exists()
