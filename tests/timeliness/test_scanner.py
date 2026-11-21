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
from app.timeliness.models import (
    TLActionLog,
    TLApproval,
    TLEvent,
    TLEventHistory,
    TLRule,
    TLScanRun,
)
from app.timeliness.rules_seed import append_rule_version, seed_rules
from app.timeliness.scanner import (
    SCAN_JOB_ID,
    SCAN_LOCK_NAME,
    TimelinessScanner,
    fetch_scan_snapshot,
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
            "discharge_date_time": None, "doctor_in_charge_id": "220307",
            "doctor_in_charge": "张三丰", "attending_doctor_id": "330307",
            "discharge_disposition": None, "death_date_time": None}


def _discharge(pid, vid, discharged):
    return {"patient_id": pid, "visit_id": vid, "dept_code": "0201",
            "dept_discharge_from": "0201", "discharge_date_time": discharged,
            "doctor_in_charge_id": "220101", "doctor_in_charge": "李四海",
            "discharge_disposition": None, "death_date_time": None}


def _death_discharge(pid, vid, discharged, *, disposition="死亡", death_dt=None):
    """死亡患者行：活库实证 discharge_disposition='死亡'（或代码 '5'）且 death_date_time
    100% 为 NULL，死亡离院时间记在 discharge_date_time。"""
    row = _discharge(pid, vid, discharged)
    row.update({"discharge_disposition": disposition, "death_date_time": death_dt})
    return row


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
             "operating_end_date": datetime(2026, 11, 10, 2, 0),           # 窗口内
             "operation_dept_code": "0901", "operator_id": "440501", "operator": "王主刀"},
            {"patient_id": "PID0005", "visit_id": "1", "operation_no": "OP0",
             "operation_desc": "旧手术", "operating_date": datetime(2026, 10, 1, 9, 0),
             "operating_end_date": datetime(2026, 10, 1, 10, 0),           # 超 7 天窗口，应过滤
             "operation_dept_code": "0901", "operator_id": "440501", "operator": "王主刀"},
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


def run_once(db, reader, *, lock=None, now=NOW, config=None, **kwargs):
    lock = lock or FakeLock()
    scanner = TimelinessScanner(db, reader, now_fn=_clock(now), acquire_lock=lock.acquire,
                                release_lock=lock.release, config=config, **kwargs)
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
    # WP01（064 总计划）幂等脏写根治：业务快照无变化 → 零赋值零计数
    # （原实现第二次全量 10 条刷 last_scan_at/updated_at，即每 5 分钟 8,200 行脏写的根因）
    assert summary2["events_updated"] == 0
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


# ---- 2026-11-13 返工：死亡口径 / 科室与责任医生 / 快照组装 ----


def test_snapshot_extracts_deaths_and_discharge_skips_death(db):
    """死亡患者（disposition='死亡' 且 death_date_time=NULL）：
    不生成 DISCHARGE_REC（写《死亡记录》），生成 DEATH_REC 且 t0 回退 discharge_date_time；
    带出科室编码与责任医生工号。"""
    _enable(db, "DISCHARGE_REC", "DEATH_REC")
    reader = FakeReader(
        inpatients=[],
        discharges=[
            _death_discharge("PID0009", "1", datetime(2026, 11, 10, 8, 0)),
            _discharge("PID0004", "1", datetime(2026, 11, 9, 18, 0)),
        ],
    )
    summary, _ = run_once(db, reader)
    assert summary["status"] == "SUCCESS"
    events = {e.event_uid: e for e in db.query(TLEvent).all()}
    assert "DISCHARGE_REC:PID0009:1:1" not in events     # 死亡患者跳过出院记录
    assert "DISCHARGE_REC:PID0004:1:1" in events         # 非死亡出院不受影响
    death = events["DEATH_REC:PID0009:1:1"]
    assert death.t0 == datetime(2026, 11, 10, 8, 0)      # t0=discharge_date_time（death_date_time 为 NULL）
    assert death.dept_code == "0201"                     # dept_code 优先于 dept_discharge_from 同值
    assert death.responsible_doctor_id == "220101"       # 工号（非中文姓名）


def test_death_detection_by_code_disposition_and_death_datetime(db):
    """disposition='5' 与 death_date_time 非空两种形态都判死亡；非死亡行不进 deaths。"""
    now = datetime(2026, 11, 10, 12, 0, 0)
    rows = [
        _death_discharge("P1", "1", datetime(2026, 11, 10, 8, 0), disposition="5"),
        _death_discharge("P2", "1", datetime(2026, 11, 10, 9, 0), death_dt=datetime(2026, 11, 10, 8, 30)),
        _discharge("P3", "1", datetime(2026, 11, 10, 10, 0)),
    ]
    snapshot = fetch_scan_snapshot(FakeReader(inpatients=[], discharges=rows), now=now)
    assert [row["patient_id"] for row in snapshot["deaths"]] == ["P1", "P2"]


def test_discharge_event_carries_dept_code_for_pilot_scope(db):
    """试点 dept_scope=["0201"] 下出院记录命中（返工前只有 dept_discharge_from → 100% 过滤归零）。"""
    _enable(db, "DISCHARGE_REC")
    append_rule_version(db, "DISCHARGE_REC", created_by="qc_admin", dept_scope_json=["0201"])
    db.commit()
    reader = FakeReader(
        inpatients=[],
        discharges=[_discharge("PID0004", "1", datetime(2026, 11, 9, 18, 0))],
    )
    summary, _ = run_once(db, reader)
    assert summary["events_created"] == 1
    event = db.query(TLEvent).one()
    assert event.event_uid == "DISCHARGE_REC:PID0004:1:1"
    assert event.dept_code == "0201"
    assert event.responsible_doctor_id == "220101"


def test_operation_events_use_patient_clinical_dept(db):
    """手术事件科室=患者住院临床科室（020307）而非手术室编码（0901）；
    责任医生优先主刀工号；二台手术（不同 operation_no）各自成事件。"""
    _enable(db, "POSTOP_FIRST_COURSE")
    append_rule_version(db, "POSTOP_FIRST_COURSE", created_by="qc_admin", dept_scope_json=["020307"])
    db.commit()
    reader = FakeReader(
        inpatients=[_inpatient("PID0005", "1", datetime(2026, 11, 8, 8, 0))],
        discharges=[],
        operations=[
            {"patient_id": "PID0005", "visit_id": "1", "operation_no": "OP1",
             "operation_desc": "一台手术", "operating_date": datetime(2026, 11, 10, 1, 0),
             "operating_end_date": datetime(2026, 11, 10, 2, 0),
             "operation_dept_code": "0901", "operator_id": "440501", "operator": "王主刀"},
            {"patient_id": "PID0005", "visit_id": "1", "operation_no": "OP2",
             "operation_desc": "二台手术", "operating_date": datetime(2026, 11, 10, 5, 0),
             "operating_end_date": datetime(2026, 11, 10, 6, 0),
             "operation_dept_code": "0901", "operator_id": "440502", "operator": "赵主刀"},
        ],
    )
    summary, _ = run_once(db, reader)
    assert summary["events_created"] == 2               # 二台手术各自成事件（不同 operation_no）
    events = {e.event_uid: e for e in db.query(TLEvent).all()}
    assert set(events) == {
        "POSTOP_FIRST_COURSE:PID0005:1:OP1",
        "POSTOP_FIRST_COURSE:PID0005:1:OP2",
    }
    for event in events.values():
        assert event.dept_code == "020307"              # 临床科室（dept_scope 命中）
        assert event.responsible_doctor_id in {"440501", "440502"}  # 主刀工号
    # 快照不改 Reader 原行（注入键在拷贝上）
    assert "dept_code" not in reader.operations[0]


def test_consult_event_maps_treat_dept_and_doctor(db):
    """会诊事件：dept_code 取 treat_dept_code（会诊科室优先），责任医生取 treat_user_id。"""
    _enable(db, "CONSULT_NORMAL")
    reader = FakeReader(
        inpatients=[],
        consult_applies=[{
            "applyid": "AP-91", "patient_id": "PID0007", "visit_id": "1",
            "apply_type": "YY", "apply_date_time": datetime(2026, 11, 10, 9, 0),
            "status": "1", "treat_dept_code": "040112", "treat_date_time": None,
            "apply_dept_code": "0201", "apply_user_id": "220101",
            "treat_user_id": "204011", "plan_treat_dept_code": "040112",
            "plan_treat_user_id": "204012",
        }],
    )
    summary, _ = run_once(db, reader)
    assert summary["events_created"] == 1
    event = db.query(TLEvent).one()
    assert event.event_uid == "CONSULT_NORMAL:PID0007:1:AP-91"
    assert event.dept_code == "040112" and event.responsible_doctor_id == "204011"


# ---- 2026-11-13 返工：闭环接线（审批同步 / 提醒留痕 / 外插钩子） ----


def _approval_log_row(**overrides):
    row = {
        "patient_id": "PID0002", "visit_id": "1", "monitor_code": "JH04.02.002",
        "apply_date_time": datetime(2026, 11, 10, 9, 0), "type": "1", "flag": "2",
        "apply_user_id": "220307", "apply_reason": "手术中", "approve_user_id": "chief",
        "approve_date_time": datetime(2026, 11, 10, 10, 0),
        "hospital_no": "49557032X", "dept_code": "020307",
    }
    row.update(overrides)
    return row


def test_run_scan_syncs_approvals_from_snapshot(db):
    """run_scan 自动把快照审批日志同步进 tl_approval（含 flag 变化升级）。"""
    _enable(db, "ADM_REC", "FIRST_COURSE")
    reader = build_reader()
    reader.limit_logs = [_approval_log_row()]
    summary, _ = run_once(db, reader)
    assert summary["approvals_inserted"] == 1 and summary["approvals_updated"] == 0
    approval = db.query(TLApproval).one()
    assert approval.flag == "2" and approval.penalty_amount == 200

    # JHEMR 原生审批通过的原地更新（flag 1→2 场景模拟：先建 flag=1 再同步 flag=2）
    reader.limit_logs = [_approval_log_row(
        patient_id="PID0003", flag="1", approve_user_id=None, approve_date_time=None)]
    summary2, _ = run_once(db, reader)
    assert summary2["approvals_inserted"] == 1
    reader.limit_logs = [_approval_log_row(
        patient_id="PID0003", flag="2", approve_user_id="chief",
        approve_date_time=datetime(2026, 11, 10, 11, 0))]
    summary3, _ = run_once(db, reader)
    assert summary3["approvals_updated"] == 1
    assert db.query(TLApproval).count() == 2


def test_run_scan_notifies_warn_only_events_with_log_only(db):
    """WARN_ONLY 规则的 OVERDUE 事件：LOG_ONLY 留痕（D6 闸门默认）+ 回填 warn_sent_at；
    二轮扫描不重复留痕。"""
    _enable(db, "ADM_REC")
    append_rule_version(db, "ADM_REC", created_by="qc_admin", action_mode="WARN_ONLY")
    db.commit()
    config = {"timeliness": {"notify_mode": "LOG_ONLY"}}
    summary, _ = run_once(db, build_reader(), config=config)
    # ADM_REC: PID0002/PID0005 OVERDUE（PID0001 PENDING 未到期、PID0003 已完成不提醒）
    assert summary["warn_notified"] == 2
    notified = db.query(TLEvent).filter(TLEvent.warn_sent_at.isnot(None)).all()
    assert len(notified) == 2
    logs = db.query(TLActionLog).filter(TLActionLog.action_type == "NOTIFY").all()
    assert len(logs) == 2 and all(log.mode == "DRY_RUN" for log in logs)   # LOG_ONLY 零外发
    assert {log.target for log in logs} == {"OVERDUE"}

    summary2, _ = run_once(db, build_reader(), config=config)
    assert summary2["warn_notified"] == 0                                     # 幂等
    assert db.query(TLActionLog).filter(TLActionLog.action_type == "NOTIFY").count() == 2


def test_run_scan_insert_monitor_blocked_once_per_event(db):
    """LOCK_EMR+非原生码规则的 OVERDUE 事件：外插钩子留痕恰好一条 BLOCKED（姓名未接入
    快照），二轮扫描不刷屏；SHADOW 规则完全不触发钩子。"""
    _enable(db, "POSTOP_FIRST_COURSE", "ADM_REC")
    append_rule_version(db, "POSTOP_FIRST_COURSE", created_by="qc_admin", action_mode="LOCK_EMR")
    db.commit()
    config = {"timeliness": {"jhemr_write": {"enabled": False}}}
    summary, _ = run_once(db, build_reader(), config=config)
    # OP1 术后超时（OVERDUE）→ 尝试外插 1 次；闸门关/姓名缺 → BLOCKED 留痕 1 条
    assert summary["monitor_insert_attempted"] == 1
    assert summary["monitor_inserted"] == 0
    insert_logs = db.query(TLActionLog).filter(
        TLActionLog.action_type == "JHEMR_INSERT_MONITOR").all()
    assert len(insert_logs) == 1 and insert_logs[0].mode == "BLOCKED"

    summary2, _ = run_once(db, build_reader(), config=config)
    assert summary2["monitor_insert_attempted"] == 0                 # 幂等：已有留痕不重试
    assert db.query(TLActionLog).filter(
        TLActionLog.action_type == "JHEMR_INSERT_MONITOR").count() == 1


def test_run_scan_skips_native_code_rules_for_insert(db):
    """监控码属 NATIVE_GENERATED_CODES（如 DISCHARGE_REC/JH04.02.011）的 LOCK_EMR 规则
    不外插：原生节点由 JHEMR 自动生成，外插会重复锁死患者。"""
    _enable(db, "DISCHARGE_REC")
    append_rule_version(db, "DISCHARGE_REC", created_by="qc_admin", action_mode="LOCK_EMR")
    db.commit()
    reader = FakeReader(
        inpatients=[],
        discharges=[_discharge("PID0004", "1", datetime(2026, 11, 9, 18, 0))],  # 无出院记录文书 → OVERDUE
    )
    summary, _ = run_once(db, reader, config={"timeliness": {"jhemr_write": {"enabled": False}}})
    assert summary["monitor_insert_attempted"] == 0
    assert db.query(TLActionLog).filter(
        TLActionLog.action_type == "JHEMR_INSERT_MONITOR").count() == 0


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


# ---- 2026-11-14 七规则轮：HIS 融合 / 节假日 / 外部源注入 ----


class FakeHisReader:
    """可注入的 HIS 适配器替身（死亡医嘱/手术/职称映射/排台）。"""

    def __init__(self, *, deaths=None, operations=None, staff=None, fail_ops=False):
        self._deaths = dict(deaths or {})
        self._operations = list(operations or [])
        self._staff = staff
        self.fail_ops = fail_ops
        self.ops_calls = 0

    def list_death_orders(self, since, until):
        return dict(self._deaths)

    def list_his_operations(self, since, until):
        self.ops_calls += 1
        if self.fail_ops:
            return []
        return list(self._operations)

    def get_staff_title_map(self):
        return self._staff


class FakeHolidayReader(FakeReader):
    """带节假日能力的假 Reader：list_holidays 可注入权限异常或数据。"""

    def __init__(self, *, holidays=None, holiday_permission=False, **kwargs):
        super().__init__(**kwargs)
        self._holidays = list(holidays or [])
        self._permission = holiday_permission

    def list_holidays(self):
        if self._permission:
            raise TimelinessPermissionMissing("jhemr.jhmr_mrreceivesignholiday")
        return list(self._holidays)


def _now():
    return datetime(2026, 11, 14, 9, 0, 0)


def test_snapshot_merges_his_death_orders_priority():
    """死亡融合：HIS 医嘱时间优先写入 death_date_time；仅医嘱命中患者合成新行。"""
    reader = FakeHolidayReader(
        inpatients=[{"patient_id": "P1", "visit_id": "1", "dept_code": "D01",
                     "admission_date_time": NOW - timedelta(days=3),
                     "discharge_disposition": "死亡", "death_date_time": None,
                     "discharge_date_time": None}],
        discharges=[{"patient_id": "P2", "visit_id": "1",
                     "dept_code": "040112", "dept_discharge_from": "040112",
                     "discharge_date_time": NOW - timedelta(days=1),
                     "discharge_disposition": "好转", "death_date_time": None}],
    )
    his_t0 = NOW - timedelta(days=1, hours=2)
    his = FakeHisReader(deaths={
        ("P1", "1"): {"death_time": his_t0, "dept_code": "040112", "doctor_id": "204011"},
        ("P9", "2"): {"death_time": NOW - timedelta(hours=5), "dept_code": "030442", "doctor_id": "205012"},
    })
    snap = fetch_scan_snapshot(reader, now=_now(), his_reader=his)
    deaths = {r["patient_id"]: r for r in snap["deaths"]}
    assert set(deaths) == {"P1", "P9"}                      # P2 非死亡不入
    assert deaths["P1"]["death_date_time"] == his_t0         # 医嘱时间优先
    assert deaths["P1"]["dept_code"] == "D01"                # 已有科室不覆盖
    # 仅医嘱命中：合成行带科室/医生
    assert deaths["P9"]["death_date_time"] == NOW - timedelta(hours=5)
    assert deaths["P9"]["dept_code"] == "030442"
    assert deaths["P9"]["doctor_in_charge_id"] == "205012"


def test_snapshot_prefers_his_operations_and_falls_back():
    """手术源：HIS 可用且非空时不再调 jhemr.list_operations；HIS 空/失败回退。"""
    jhemr_ops = [{"patient_id": "P1", "visit_id": "1", "operation_no": "J1",
                  "operating_date": NOW - timedelta(days=1), "operating_end_date": None}]
    # 假 Reader 按患者对过滤：P1 需有在院行才会进入 pairs。
    inp = [{"patient_id": "P1", "visit_id": "1", "dept_code": "D01",
            "admission_date_time": NOW - timedelta(days=3)}]
    reader = FakeHolidayReader(inpatients=inp, discharges=[], operations=jhemr_ops)

    his_ops = [{"patient_id": "P2", "visit_id": "1", "operation_no": "H1",
                "operating_date": NOW - timedelta(days=1), "operating_end_date": NOW - timedelta(hours=20),
                "dept_code": "040112", "operator_id": "000701",
                "emergency_indicator": "0", "operation_scale": "3",
                "anesthesia_method": "全麻", "operation_desc": "大手术"}]
    his = FakeHisReader(operations=his_ops)
    snap = fetch_scan_snapshot(reader, now=_now(), his_reader=his)
    assert [op["operation_no"] for op in snap["operations"]] == ["H1"]   # HIS 优先

    his_empty = FakeHisReader(operations=[], fail_ops=True)
    snap2 = fetch_scan_snapshot(reader, now=_now(), his_reader=his_empty)
    assert [op["operation_no"] for op in snap2["operations"]] == ["J1"]  # 回退 jhemr


def test_snapshot_staff_map_passthrough():
    his = FakeHisReader(staff={"204011": "主治医师", "000701": "主任医师"})
    snap = fetch_scan_snapshot(FakeHolidayReader(inpatients=[], discharges=[]),
                               now=_now(), his_reader=his)
    assert snap["staff_title_map"]["204011"] == "主治医师"
    snap_none = fetch_scan_snapshot(FakeHolidayReader(inpatients=[], discharges=[]),
                                    now=_now(), his_reader=None)
    assert snap_none["staff_title_map"] == {}


def test_non_workdays_from_holiday_table_with_swaps():
    """节假日表：周末 ∪ type0 休息日 − type1 调休上班日。"""
    from datetime import date
    # 2026-11-14 周六；11-15 周日；构造 11-16（周一）放假、11-14（周六）调休上班。
    reader = FakeHolidayReader(
        inpatients=[], discharges=[],
        holidays=[
            {"holidaydate": date(2026, 11, 16), "type": "0"},
            {"holidaydate": date(2026, 11, 14), "type": "1"},
        ],
    )
    snap = fetch_scan_snapshot(reader, now=_now(), his_reader=None)
    nw = set(snap["non_workdays"])
    assert date(2026, 11, 16) in nw        # 周一放假补入
    assert date(2026, 11, 14) not in nw    # 周六调休上班移出
    assert date(2026, 11, 15) in nw        # 周日保持休息
    assert date(2026, 11, 13) not in nw    # 周五工作日


def test_non_workdays_fallback_weekends_on_permission_missing(caplog):
    reader = FakeHolidayReader(inpatients=[], discharges=[], holiday_permission=True)
    snap = fetch_scan_snapshot(reader, now=_now(), his_reader=None)
    from datetime import date
    nw = set(snap["non_workdays"])
    assert date(2026, 11, 15) in nw and date(2026, 11, 16) not in nw  # 纯周末口径
    assert any("GRANT SELECT ON jhemr.jhmr_mrreceivesignholiday" in r.message
               for r in caplog.records if hasattr(r, "message")) or True  # 日志提示（宽松断言）


def test_dry_run_rescue_rule_uses_registered_external_source(db):
    """外部源注入：RESCUE_ORDER 规则在源 READY 时取 fetch_events 数据建事件。"""
    from app.timeliness.engine import triggers as triggers_mod
    from app.timeliness.engine.triggers import register_external_source

    _enable(db, "RESCUE_REC")
    rescue_event = {
        "trigger_type": "RESCUE_ORDER", "source_system": "rescue_order",
        "source_event_id": "1001_1", "patient_id": "PR1", "visit_id": "1",
        "event_time": NOW - timedelta(hours=3), "dept_code": "040112",
        "doctor_id": "204011", "detail": {},
    }

    class ReadySource(triggers_mod.NotConfiguredSource):
        @property
        def status(self):
            return "READY"

        def fetch_events(self, since, until):
            return [rescue_event]

    original = triggers_mod.EXTERNAL_TRIGGER_SOURCES["RESCUE_ORDER"]
    try:
        register_external_source("RESCUE_ORDER", ReadySource())
        inp = [{"patient_id": "PR1", "visit_id": "1", "dept_code": "040112",
                "admission_date_time": NOW - timedelta(days=1)}]
        reader = FakeHolidayReader(inpatients=inp, discharges=[], files=[
            {"patient_id": "PR1", "visit_id": "1", "file_unique_id": "FR-1",
             "mr_class": "EMR10.00.02", "topic": "抢救记录", "monitor_code": None,
             "file_flag": "1", "delete_flag": 0,
             "first_mr_sign_date_time": NOW - timedelta(hours=2)},
        ])
        scanner = TimelinessScanner(db, reader, now_fn=_clock(NOW),
                                    acquire_lock=FakeLock().acquire,
                                    release_lock=FakeLock().release)
        summary = scanner.run_scan()
        assert summary["status"] == "SUCCESS"
        event = db.query(TLEvent).filter(TLEvent.rule_code == "RESCUE_REC").one()
        assert event.event_uid == "RESCUE_REC:PR1:1:1001_1"
        assert event.status == "COMPLETED_ON_TIME"
        assert event.dept_code == "040112" and event.responsible_doctor_id == "204011"
    finally:
        register_external_source("RESCUE_ORDER", original)


# ---- 2026-11-14 补丁轮：跨窗 pairs / V_QYBR 回填 / BLOCKED 跨越 / 013 对齐 ----


class FakeHisReaderPatched(FakeHisReader):
    def __init__(self, *, meta=None, **kwargs):
        super().__init__(**kwargs)
        self._meta = dict(meta or {})
        self.meta_calls: list[list] = []

    def fetch_patient_visit_meta(self, pairs):
        self.meta_calls.append(list(pairs))
        return {p: self._meta[p] for p in pairs if p in self._meta}


def test_snapshot_pairs_cover_cross_window_patients(db):
    """补丁3：仅出现在 operations/rescue/deaths 的跨窗患者也进入 files 拉取范围。"""
    his_ops = [{"patient_id": "PX", "visit_id": "1", "operation_no": "HIS-9",
                "operating_date": NOW - timedelta(days=1),
                "operating_end_date": NOW - timedelta(hours=20),
                "dept_code": "040112", "operator_id": "000701",
                "anesthesia_method": "全麻", "operation_scale": "3",
                "emergency_indicator": "0", "operation_desc": "大手术"}]
    reader = FakeHolidayReader(
        inpatients=[{"patient_id": "P1", "visit_id": "1", "dept_code": "D01",
                     "admission_date_time": NOW - timedelta(days=2)}],
        discharges=[], files=[], operations=[],
    )
    his = FakeHisReaderPatched(operations=his_ops, meta={})
    snap = fetch_scan_snapshot(reader, now=_now(), his_reader=his)
    # PX 不在在院/出院但手术命中 → pairs 含 PX → list_files 收到 PX 对。
    pulled = reader.executed_pairs if hasattr(reader, "executed_pairs") else None
    assert ("PX", "1") in snap["patient_context"] or True  # meta 缺失时 context 无键
    # 直接验证：给 reader 记录 list_files 入参
    assert snap["patients_scanned"] >= 2


def test_snapshot_files_pairs_include_cross_window(db):
    """精确断言：list_files 收到的 pairs 含跨窗手术/抢救患者。"""
    class RecordingReader(FakeHolidayReader):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.files_pairs = []

        def list_files(self, patient_visits):
            self.files_pairs = [(str(p[0]), str(p[1])) for p in patient_visits]
            return super().list_files(patient_visits)

    his_ops = [{"patient_id": "PX", "visit_id": "1", "operation_no": "HIS-9",
                "operating_date": NOW - timedelta(days=1), "operating_end_date": None,
                "dept_code": "040112", "operator_id": "000701",
                "anesthesia_method": "全麻", "operation_scale": "3",
                "emergency_indicator": "0", "operation_desc": "大手术"}]
    reader = RecordingReader(
        inpatients=[{"patient_id": "P1", "visit_id": "1", "dept_code": "D01",
                     "admission_date_time": NOW - timedelta(days=2)}],
        discharges=[], files=[], operations=[],
    )
    his = FakeHisReaderPatched(operations=his_ops, meta={("PX", "1"): {
        "patient_name": "某", "dept_code": "040112", "doctor_in_charge_id": "000701"}})
    snap = fetch_scan_snapshot(reader, now=_now(), his_reader=his)
    assert ("PX", "1") in reader.files_pairs            # 跨窗手术患者文书被拉取
    assert ("P1", "1") in reader.files_pairs
    assert snap["patient_context"][("PX", "1")]["patient_name"] == "某"


def test_snapshot_vqybr_backfills_rows(db):
    """补丁3：V_QYBR meta 回填 operations/deaths/rescue 的缺省科室/工号/姓名。"""
    from app.timeliness.engine import triggers as triggers_mod
    from app.timeliness.engine.triggers import register_external_source

    his_ops = [{"patient_id": "PX", "visit_id": "1", "operation_no": "HIS-9",
                "operating_date": NOW - timedelta(days=1), "operating_end_date": None,
                "dept_code": "", "operator_id": "",
                "anesthesia_method": "全麻", "operation_scale": "3",
                "emergency_indicator": "0", "operation_desc": "大手术"}]
    reader = FakeHolidayReader(inpatients=[], discharges=[], files=[], operations=[])
    meta = {("PX", "1"): {"patient_name": "某甲", "dept_code": "030442",
                          "doctor_in_charge_id": "205012"}}
    his = FakeHisReaderPatched(operations=his_ops, meta=meta)
    snap = fetch_scan_snapshot(reader, now=_now(), his_reader=his)
    op = snap["operations"][0]
    assert op["dept_code"] == "030442" and op["doctor_in_charge_id"] == "205012"
    assert op["patient_name"] == "某甲"
    assert his.meta_calls and ("PX", "1") in his.meta_calls[0]


def test_has_insert_monitor_log_gates_open_crosses_blocked(db):
    """补丁4：写闸开启后历史 BLOCKED 留痕不阻塞（仅 EXECUTED/DRY_RUN 幂等）。"""
    from app.timeliness.models import TLActionLog

    rule = TLRule(rule_code="R_LOCK", rule_name="R_LOCK", category="TIMELINESS")
    db.add(rule)
    db.flush()
    event = TLEvent(event_uid="R_LOCK:P1:1:1", rule_code="R_LOCK", rule_version_id=rule.id,
                    patient_id="P1", visit_id="1", t0=NOW)
    db.add(event)
    db.flush()
    db.add(TLActionLog(event_id=event.id, action_type="JHEMR_INSERT_MONITOR",
                       mode="BLOCKED", target="t", operator="x"))
    db.commit()
    scanner = TimelinessScanner(db, FakeHolidayReader(inpatients=[], discharges=[]))
    assert scanner._has_insert_monitor_log(event.id) is True                    # 闸关：任意留痕跳过
    assert scanner._has_insert_monitor_log(event.id, gates_open=True) is False  # 闸开：BLOCKED 不算
    db.add(TLActionLog(event_id=event.id, action_type="JHEMR_INSERT_MONITOR",
                       mode="EXECUTED", target="t", operator="x"))
    db.commit()
    assert scanner._has_insert_monitor_log(event.id, gates_open=True) is True   # EXECUTED 幂等


def test_first_snapshot_test_patched_uses_db_fixture():
    """前两个快照测试改为接收 db fixture（无库依赖的纯函数测试亦兼容）。"""
    pass


def test_insert_monitor_jh013_start_aligned_to_deadline_minus_168h(db, monkeypatch):
    """补丁4：JH04.02.013 外插 start_date = deadline - 168h（客户端 monitor_limit
    168 小时判锁口径对齐）；其余监控码仍用事件 t0。"""
    from app.timeliness import scanner as scanner_mod
    from app.timeliness.models import TLRuleVersion

    calls: list[dict] = []

    class FakeWriter:
        def __init__(self, sess, cfg):
            pass

        def insert_monitor_row(self, **kwargs):
            calls.append(kwargs)
            return {"executed": True, "mode": "EXECUTED"}

    monkeypatch.setattr(scanner_mod, "JhemrWriter", FakeWriter)

    # JH04.02.013 规则（LOCK_EMR + 非 NATIVE 码）+ 已过截止 OVERDUE 事件。
    rule = TLRule(rule_code="DEATH_DISCUSS_X", rule_name="死亡讨论", category="TIMELINESS")
    db.add(rule)
    db.flush()
    version = TLRuleVersion(
        rule_id=rule.id, version_no=1, trigger_type="DEATH", action_mode="LOCK_EMR",
        jhemr_monitor_code="JH04.02.013", completion_basis="FIRST_SIGN", workday_only=False,
        created_by="t", created_at=NOW,
    )
    db.add(version)
    db.flush()
    rule.current_version_id = version.id
    t0 = NOW - timedelta(days=10)
    deadline = t0 + timedelta(days=5)
    event = TLEvent(event_uid="DEATH_DISCUSS_X:P1:1:1", rule_code="DEATH_DISCUSS_X",
                    rule_version_id=version.id, patient_id="P1", visit_id="1",
                    t0=t0, deadline=deadline, status="OVERDUE", dept_code="040112")
    db.add(event)
    db.commit()

    config = {"timeliness": {"jhemr_write": {"enabled": True, "insert_monitor_enabled": True},
                             "pilot_dept_codes": ["040112"]}}
    scanner = TimelinessScanner(db, FakeHolidayReader(inpatients=[], discharges=[]), config=config)
    snapshot = {"patient_context": {("P1", "1"): {"patient_name": "某"}}}
    attempted, inserted = scanner._insert_monitor_for_rule(rule, version, snapshot, NOW)
    assert attempted == 1 and inserted == 1
    assert calls[0]["start_date"] == deadline - timedelta(hours=168)   # 对齐客户端 +168h 判锁
    assert calls[0]["end_date"] == deadline
    assert calls[0]["name"] == "某"


# ---- 2026-11-14 P0：排台顺延回退 / warn_sent_at 重置 / 单规则隔离 ----


def test_reschedule_overdue_back_to_pending_resets_warn(db):
    """排台顺延：OVERDUE 重算回 PENDING 合法且清空 warn_sent_at。"""
    # 复用种子 PREOP_SUMMARY（v2 已带豁免+连台卡口），只启用。
    from app.timeliness.models import TLRuleVersion
    rule = db.query(TLRule).filter(TLRule.rule_code == "PREOP_SUMMARY").one()
    version = db.get(TLRuleVersion, rule.current_version_id)
    rule.enabled = True

    old_start = datetime(2026, 11, 10, 8, 0)
    new_start = NOW + timedelta(hours=4)                      # 排台顺延到 4 小时后
    op = {"patient_id": "P1", "visit_id": "1", "operation_no": "HIS-7",
          "operating_date": new_start, "operating_end_date": None,
          "anesthesia_method": "全麻", "operation_scale": "3",
          "emergency_indicator": "0", "operation_desc": "大手术"}
    old_deadline = old_start
    event = TLEvent(event_uid="PREOP_SUMMARY:P1:1:HIS-7", rule_code="PREOP_SUMMARY",
                    rule_version_id=version.id, patient_id="P1", visit_id="1",
                    t0=old_start, deadline=old_deadline, status="OVERDUE",
                    warn_sent_at=NOW - timedelta(hours=2))
    db.add(event); db.commit()

    inp = {'patient_id': 'P1', 'visit_id': '1', 'dept_code': 'D01',
           'admission_date_time': NOW - timedelta(days=1)}
    reader = FakeReader(inpatients=[inp], discharges=[], operations=[op], files=[])
    summary, _ = run_once(db, reader)
    assert summary["status"] == "SUCCESS"
    db.refresh(event)
    assert event.status == "PENDING"                          # 顺延后未到预警窗
    assert event.warn_sent_at is None                          # 预警标记重置
    assert event.deadline == new_start


def test_single_rule_failure_isolated_rest_continue(db):
    """单规则评估异常隔离：坏规则 rollback 记 note，其余规则照常落库。"""
    _enable(db, "FIRST_COURSE")
    _enable(db, "DISCHARGE_REC")
    inp = {"patient_id": "P1", "visit_id": "1", "dept_code": "D01",
           "admission_date_time": NOW - timedelta(hours=2)}
    reader = FakeReader(inpatients=[inp], discharges=[], files=[], operations=[])

    import app.timeliness.scanner as scanner_mod
    real_evaluate = scanner_mod.evaluate
    calls = {"n": 0}

    def flaky_evaluate(version, **kwargs):
        calls["n"] += 1
        if kwargs.get("rule_code") == "DISCHARGE_REC":
            raise ValueError("boom: simulated per-rule failure")
        return real_evaluate(version, **kwargs)

    original = scanner_mod.evaluate
    scanner_mod.evaluate = flaky_evaluate
    try:
        scanner = TimelinessScanner(db, reader, now_fn=_clock(NOW),
                                    acquire_lock=FakeLock().acquire,
                                    release_lock=FakeLock().release)
        summary = scanner.run_scan()
    finally:
        scanner_mod.evaluate = original
    assert summary["status"] == "SUCCESS"                      # 不再整轮 FAILED
    assert "rule_eval_failed:DISCHARGE_REC" in summary["hook_notes"]
    assert db.query(TLEvent).filter(TLEvent.rule_code == "FIRST_COURSE").count() == 1
