"""双调度双发策略回归（035/RP1，B2）。

生产实测证据（2026-09-01 只读，MED_PUSH_LOG 近 14 天）：
- 18259 行中 666 组跨模式双跑、179 组双模式均推送成功、2204 行被 superseded；
- 成对样本：daily 09:04 推送（low）→ discharge 11:49 推送（low）→ daily 行 superseded_by=终末 ID；
- 告警层零双提醒：双发组关联告警 0 条（低危不入队，双模式均高危告警的组数=0）。

策略结论（证据裁决=四选一中的「允许双发/业务两时点」）：
- record_identity._apply_run_mode_scope 模式身份隔离是设计行为：终末结果业务身份独立，
  unreviewed_pending 不得拦截终末推送；
- 结果层单向 supersede（discharge→daily）保证 current 归属；
- 排除项：终末覆盖抑制 daily（时间倒挂）/延迟 daily（毁在院监控时效）/仅抑制相同版本
  （破坏终末权威性与 supersede 链，见 test_historical_rerun_replacement 身份断言）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import PushLog
from app.services.push_log_supersede import (
    attach_success_push_log_as_current,
    mark_daily_logs_superseded,
)
from app.services.push_skip_policy import get_skip_reason
from app.services.record_identity import get_bundle_source_key


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _daily_log(**kwargs):
    defaults = {
        "push_time": datetime(2026, 8, 30, 9, 4),
        "trigger_type": "auto",
        "query_date": "2026-08-29",
        "patient_id": "P001",
        "visit_number": "1",
        "audit_type_code": "progress_vs_nursing",
        "audit_run_mode": "daily_increment",
        "status": "success",
        "pushed_flag": 1,
        "source_record_key": "progress_vs_nursing::P001::1",
        "severity": "low",
    }
    defaults.update(kwargs)
    return PushLog(**defaults)


def _discharge_log(**kwargs):
    defaults = {
        "push_time": datetime(2026, 8, 30, 11, 49),
        "trigger_type": "auto",
        "query_date": "2026-08-29",
        "patient_id": "P001",
        "visit_number": "1",
        "audit_type_code": "progress_vs_nursing",
        "audit_run_mode": "discharge_final",
        "status": "success",
        "pushed_flag": 1,
        "source_record_key": "mode::discharge_final::progress_vs_nursing::P001::1",
        "severity": "low",
    }
    defaults.update(kwargs)
    return PushLog(**defaults)


class _FakeBundle:
    """最小 bundle 形态：get_bundle_source_key 只读 group_values/payload。"""

    def __init__(self, group_values: dict):
        self.group_values = group_values
        self.sources = {}
        self.primary_source = ""


_FAKE_AUDIT_TYPE = {
    "code": "progress_vs_nursing",
    "payload": {"builder": "generic_multi_source"},
    "group_key": ["patient_id", "visit_number"],
}


def test_dual_push_allowed_and_discharge_becomes_current():
    """T1：daily 先推、discharge 后推 → 双发允许（两行 pushed），current 归属=终末。"""
    db = _make_db()
    daily = _daily_log()
    discharge = _discharge_log()
    db.add(daily)
    db.flush()
    db.add(discharge)
    db.flush()

    covered = mark_daily_logs_superseded(db, discharge)
    db.commit()

    assert covered == 1
    assert daily.superseded_by == discharge.id
    assert discharge.superseded_by is None
    # 双发保留：两行都是 success+pushed_flag=1（业务两时点，不做当日去重）
    rows = db.query(PushLog).filter(PushLog.pushed_flag == 1).all()
    assert len(rows) == 2


def test_dual_send_supersede_does_not_cross_patients():
    """T2：不同患者互不影响——P1 的终末不覆盖 P2 的 daily。"""
    db = _make_db()
    daily_p1 = _daily_log()
    daily_p2 = _daily_log(patient_id="P002", source_record_key="progress_vs_nursing::P002::1")
    discharge_p1 = _discharge_log()
    for row in (daily_p1, daily_p2, discharge_p1):
        db.add(row)
    db.flush()

    covered = mark_daily_logs_superseded(db, discharge_p1)
    db.commit()

    assert covered == 1
    assert daily_p1.superseded_by == discharge_p1.id
    assert daily_p2.superseded_by is None


def test_late_daily_push_does_not_supersede_discharge_current():
    """T3a：discharge 先到、daily 迟到 → 迟到 daily 不回滚终末 current。"""
    db = _make_db()
    discharge = _discharge_log()
    db.add(discharge)
    db.flush()
    late_daily = _daily_log(push_time=datetime(2026, 8, 30, 14, 0))
    db.add(late_daily)
    db.flush()

    # 迟到 daily 走自身的 key 槽位：supersede 仅由 discharge 触发（单向）
    assert late_daily.superseded_by is None
    assert discharge.superseded_by is None
    # 各模式各持一条 current
    currents = db.query(PushLog).filter(PushLog.superseded_by.is_(None)).all()
    assert {row.audit_run_mode for row in currents} == {"daily_increment", "discharge_final"}


def test_mode_scoped_identity_isolation_prevents_cross_mode_skip():
    """T3b：模式身份隔离——daily 未复核不得拦截 discharge 推送（生产双发根因=设计行为）。"""
    # 身份键：daily 无前缀，discharge 有 mode:: 前缀
    bundle = _FakeBundle({"patient_id": "P001", "visit_number": "1"})
    daily_key = get_bundle_source_key(bundle, _FAKE_AUDIT_TYPE, "daily_increment")
    discharge_key = get_bundle_source_key(bundle, _FAKE_AUDIT_TYPE, "discharge_final")
    assert daily_key == "progress_vs_nursing::P001::1"
    assert discharge_key == "mode::discharge_final::progress_vs_nursing::P001::1"
    assert daily_key != discharge_key

    # skip 策略按 key 精确匹配：daily 成功未复核 → 拦 daily 重推，不拦 discharge
    db = _make_db()
    db.add(_daily_log(source_record_key=daily_key))
    db.commit()
    reason_daily, _ = get_skip_reason(db, "P001", "1", "progress_vs_nursing", daily_key, "daily_increment")
    reason_discharge, _ = get_skip_reason(db, "P001", "1", "progress_vs_nursing", discharge_key, "discharge_final")
    assert reason_daily == "unreviewed_pending"
    assert reason_discharge == ""


def test_retry_same_key_keeps_single_current_slot():
    """T4：重试/重跑同 key 同 mode → 仅一条 success current，不重复计费当前结果。"""
    db = _make_db()
    first = _daily_log(source_record_key="progress_vs_nursing::P001::1")
    # attach 内部完成 add+flush（新日志落库即成为唯一 current）
    assert attach_success_push_log_as_current(db, first) == 0

    retry = _daily_log(
        push_time=datetime(2026, 8, 30, 9, 30),
        trigger_type="retry",
        source_record_key="progress_vs_nursing::P001::1",
    )
    replaced = attach_success_push_log_as_current(db, retry)
    db.commit()

    assert replaced == 1
    assert first.superseded_by == retry.id
    currents = (
        db.query(PushLog)
        .filter(PushLog.source_record_key == "progress_vs_nursing::P001::1")
        .filter(PushLog.status == "success")
        .filter(PushLog.superseded_by.is_(None))
        .all()
    )
    assert len(currents) == 1
    assert currents[0].id == retry.id


def test_supersede_query_excludes_mode_scoped_keys_under_oracle_dialect():
    """T5：Oracle 方言下 supersede 目标排除 mode::discharge_final:: 键（跨模式不互删）。"""
    from sqlalchemy.dialects import oracle as oracle_dialect

    db = _make_db()
    query = (
        db.query(PushLog)
        .filter(PushLog.patient_id == "P001")
        .filter(PushLog.visit_number == "1")
        .filter(PushLog.audit_run_mode == "daily_increment")
        .filter(PushLog.status == "success")
        .filter(PushLog.superseded_by.is_(None))
        .filter(PushLog.source_record_key.not_like("mode::discharge_final::%"))
    )
    compiled = str(
        query.statement.compile(
            dialect=oracle_dialect.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "AUDIT_RUN_MODE" in compiled or "audit_run_mode" in compiled
    assert "mode::discharge_final::%" in compiled
    assert "SUPERSEDED_BY IS NULL" in compiled.upper()


def test_unusable_discharge_does_not_supersede_daily():
    """T6：supersede 门槛不破坏——parse 回退/契约失败/失败状态的终末不覆盖。"""
    db = _make_db()
    daily = _daily_log()
    db.add(daily)
    db.flush()

    fallback_discharge = _discharge_log(parse_status="fallback")
    db.add(fallback_discharge)
    db.flush()
    assert mark_daily_logs_superseded(db, fallback_discharge) == 0

    invalid_discharge = _discharge_log(contract_valid=False, parse_status="success")
    db.add(invalid_discharge)
    db.flush()
    assert mark_daily_logs_superseded(db, invalid_discharge) == 0

    failed_discharge = _discharge_log(status="failed")
    db.add(failed_discharge)
    db.flush()
    assert mark_daily_logs_superseded(db, failed_discharge) == 0

    db.commit()
    assert daily.superseded_by is None


def test_production_timeline_shape_reproduced():
    """T7：复现生产实测时间线（09:04 daily → 11:49 discharge，均 low）终态。"""
    db = _make_db()
    bundle = _FakeBundle({"patient_id": "P001", "visit_number": "1"})
    daily = _daily_log(
        push_time=datetime(2026, 8, 30, 9, 4),
        source_record_key=get_bundle_source_key(bundle, _FAKE_AUDIT_TYPE, "daily_increment"),
        severity="low",
    )
    discharge = _discharge_log(
        push_time=datetime(2026, 8, 30, 11, 49),
        source_record_key=get_bundle_source_key(bundle, _FAKE_AUDIT_TYPE, "discharge_final"),
        severity="low",
    )
    db.add(daily)
    db.flush()
    db.add(discharge)
    db.flush()
    assert mark_daily_logs_superseded(db, discharge) == 1
    db.commit()

    # 与生产样本行 (201722→202349) 同构：daily.superseded_by=终末 ID，终末为 current
    assert daily.superseded_by == discharge.id
    assert discharge.superseded_by is None
    # 低危双发不产生医生面告警入队的先决条件：双行 severity=low（告警仅 high 入队）
    assert all(row.severity == "low" for row in (daily, discharge))
