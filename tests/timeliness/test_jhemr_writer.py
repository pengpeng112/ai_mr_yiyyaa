"""T8+D3 落实：JHEMR 受控写入器单元测试（2026-11-13 返工口径）。

覆盖（§15 T8 验收口径 + 2026-11-12 D3 答复落实 + 勘误 E6/R1 + 2026-11-13 返工）：
- 三重闸门逐一拦截：总开关（enabled 非 True 的各形态）、科室白名单（非试点/
  空科室/空白名单）→ tl_action_log(mode=BLOCKED)、零连库（必炸哨兵连接工厂）；
- 模板 A 入口校验（2026-11-13 返工，dry_run 与真实执行均生效、闸门之前）：
  NATIVE_GENERATED_CODES（001/002/006/008/011 原生自动生成码）→ BLOCKED 拒绝
  外插；不在 MONITOR_TYPE_ZERO_CODES（monitor_type=0 时效码白名单）→ BLOCKED
  拒绝；全链路零 SELECT jhinpat_mr_monitor_items（专用写账号无该表权限）；
- 模板 A（插入监控行）：闸门 0 子开关默认 false → BLOCKED 零连库；全闸门开 +
  dry_run → DRY_RUN 留痕；真实执行 rowcount=1 成功、rowcount=0 幂等防重命中
  （duplicate 不抛）、异常回滚抛出；先留痕后连库；
- NOT EXISTS 防重条件（2026-11-13 返工）：按 patient+visit+item 且
  （completed_date IS NULL OR start_date = %s）判重——不再限定
  source_system_identity='AI_MRZK'（原生未完成行也防重；同起算时间已有行不重插；
  前次已完成且新 start_date 不同的二台手术允许插入）；
- 模板 B 演练：闸门通过 + dry_run=True → tl_action_log(mode=DRY_RUN) 记录完整
  SQL 与参数，零连库；
- 模板 B 真实执行：先留痕 EXECUTED 再连库；SQL 与参数顺序逐项核对；rowcount==1
  提交；rowcount==0/2 立即回滚并抛 JhemrWriteRowCountError；执行异常回滚后抛出；
- 写连接独立性：缺 host/账号/口令 → 拦截（BLOCKED）；账号复用只读账号
  aizk_user → 拒绝（T8：读写账号必须分离）；口令环境变量与 password_enc 两路；
- 源码扫描：含写语句关键词的字符串常量必须恰为两个写模板；模板 A 的 INSERT
  列清单不得含 completed_date（勘误 R1/E4；NOT EXISTS 子查询中的
  completed_date IS NULL 为只读判定条件）；模板 A 列清单 ⊆ T1 真实列 fixture；
  模板 B 与任务书逐字节一致；监控码常量与路由字典/规则种子一致。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.timeliness import jhemr_writer as writer_module
from app.timeliness.jhemr_writer import (
    SQL_APPROVE_LIMIT_LOG_TEMPLATE,
    SQL_INSERT_MONITOR_TEMPLATE,
    HOSPITAL_NO_DEFAULT,
    MONITOR_TYPE_ZERO_CODES,
    NATIVE_GENERATED_CODES,
    SOURCE_SYSTEM_IDENTITY,
    JhemrWriteError,
    JhemrWriteRowCountError,
    JhemrWriter,
    resolve_jhemr_write,
)
from app.timeliness.config import TimelinessNotConfigured
from app.timeliness.models import TLActionLog

# 任务书给定的模板 B 原文（逐字节锁定，防止后续被改写）。
APPROVE_TEMPLATE_FROM_TASK = (
    "UPDATE jhemr.jhmr_monitor_limit_log SET approve_user_id=%s, approve_date_time=%s, "
    "flag=2 WHERE patient_id=%s AND visit_id=%s AND monitor_code=%s AND "
    "apply_date_time=%s AND type=%s AND hospital_no=%s AND flag=1"
)

# 2026-11-13 返工任务书给定的模板 A NOT EXISTS 条件（逐字节锁定防回退）。
INSERT_NOT_EXISTS_CLAUSE = (
    "WHERE NOT EXISTS (SELECT 1 FROM jhemr.emr_online_monitor "
    "WHERE patient_id = %s AND visit_id = %s AND item_code = %s "
    "AND (completed_date IS NULL OR start_date = %s))"
)

FIXTURE_REAL_COLUMNS = Path(__file__).parent / "fixtures" / "jhemr_real_columns_20261110.json"


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng, tables=[TLActionLog.__table__])
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()


def _must_not_connect(**kwargs):
    pytest.fail(f"本用例不允许连库，却发起了连接: {sorted(kwargs)}")


def _config(*, enabled=False, pilots=("0101",), write_extra: dict | None = None) -> dict:
    jw: dict = {"enabled": enabled}
    if write_extra:
        jw.update(write_extra)
    return {"timeliness": {"jhemr_write": jw, "pilot_dept_codes": list(pilots)}}


_WRITE_CONN_OK = {
    "host": "10.10.8.177",
    "port": 5432,
    "database": "jhemr",
    "username": "mrzk_write",
}


def _approve_kwargs(**overrides):
    kwargs = dict(
        patient_id="P008",
        visit_id="1",
        dept_code="0101",
        monitor_code="JH04.02.002",
        apply_date_time=datetime(2026, 11, 11, 9, 0, 0),
        limit_type=1,
        hospital_no="H001",
        approve_user_id="chief01",
        approve_date_time=datetime(2026, 11, 11, 10, 30, 0),
    )
    kwargs.update(overrides)
    return kwargs


class FakeCursor:
    def __init__(self, conn: "FakeConn"):
        self._conn = conn
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, list(params or [])))
        self.rowcount = self._conn.next_rowcount

    def fetchone(self):
        raise AssertionError("模板 A 已无字典 SELECT（2026-11-13 返工删除），不应调用 fetchone")


class FakeConn:
    def __init__(self, *, rowcount: int = 1, exc: Exception | None = None):
        self.next_rowcount = rowcount
        self.raise_exc = exc
        self.executed: list[tuple[str, list]] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.closed = True


def _last_action_log(db) -> TLActionLog:
    return db.query(TLActionLog).order_by(TLActionLog.id.desc()).first()


# ---- 闸门 1：总开关 ----


class TestGate1Enabled:
    @pytest.mark.parametrize(
        "write_cfg",
        [
            {},                       # 段缺失（默认 false）
            {"enabled": False},       # 显式 false
            {"enabled": "true"},      # 字符串不放行（fail-closed）
            {"enabled": 1},           # 非布尔不放行
            {"enabled": None},
        ],
        ids=["missing", "false", "string", "int", "none"],
    )
    def test_blocked_when_not_boolean_true(self, db, write_cfg):
        config = {"timeliness": {"jhemr_write": write_cfg, "pilot_dept_codes": ["0101"]}}
        writer = JhemrWriter(db, config, connect=_must_not_connect)
        result = writer.approve_limit_log(**_approve_kwargs(), dry_run=False)
        assert result["mode"] == "BLOCKED"
        assert result["reason"].startswith("gate1")
        log = _last_action_log(db)
        assert log.mode == "BLOCKED"
        assert log.action_type == "JHEMR_APPROVE"
        assert log.sql_text == SQL_APPROVE_LIMIT_LOG_TEMPLATE
        assert json.loads(log.params_json)["patient_id"] == "P008"

    def test_enabled_true_proceeds_to_gate2(self, db):
        # enabled=True 但科室不在白名单 → 拦截原因应来自闸门 2（证明闸门 1 已通过）。
        writer = JhemrWriter(db, _config(enabled=True, pilots=("0202",)), connect=_must_not_connect)
        result = writer.approve_limit_log(**_approve_kwargs(), dry_run=False)
        assert result["mode"] == "BLOCKED"
        assert result["reason"].startswith("gate2")


# ---- 闸门 2：试点科室白名单 ----


class TestGate2PilotDept:
    @pytest.mark.parametrize(
        ("dept_code", "pilots"),
        [
            ("0999", ["0101", "0202"]),   # 非试点科室
            ("", ["0101"]),               # 空科室
            (None, ["0101"]),             # 缺科室
            ("0101", []),                 # 白名单为空 = 全部拦截
        ],
        ids=["not-in-list", "empty-dept", "none-dept", "empty-pilots"],
    )
    def test_blocked_when_dept_not_piloted(self, db, dept_code, pilots):
        writer = JhemrWriter(db, _config(enabled=True, pilots=pilots), connect=_must_not_connect)
        result = writer.approve_limit_log(**_approve_kwargs(dept_code=dept_code), dry_run=False)
        assert result["mode"] == "BLOCKED"
        assert result["reason"].startswith("gate2")
        assert _last_action_log(db).mode == "BLOCKED"

    def test_piloted_dept_passes_to_dry_run(self, db):
        writer = JhemrWriter(db, _config(enabled=True, pilots=("0101",)), connect=_must_not_connect)
        result = writer.approve_limit_log(**_approve_kwargs(), dry_run=True)
        assert result["mode"] == "DRY_RUN"


# ---- 闸门 0 + 模板 A：插入监控行（D3 答复 2026-11-12 后实现，默认关闭） ----


def _insert_kwargs(**overrides):
    kwargs = dict(
        patient_id="P008", visit_id="1", name="张测试", item_code="JH04.03.012",
        item_name="手术记录", start_date=datetime(2026, 11, 12, 9, 0, 0),
        end_date=datetime(2026, 11, 12, 21, 0, 0), dept_code="0101",
    )
    kwargs.update(overrides)
    return kwargs


def _config_gate0_open(pilots=("0101",), extra: dict | None = None) -> dict:
    write_extra = {**_WRITE_CONN_OK, "insert_monitor_enabled": True}
    if extra:
        write_extra.update(extra)
    return _config(enabled=True, pilots=pilots, write_extra=write_extra)


class TestTemplateAInsertMonitor:
    # ---- 入口校验（2026-11-13 返工：闸门之前，dry_run 与真实执行均生效） ----

    @pytest.mark.parametrize("native_code", sorted(NATIVE_GENERATED_CODES))
    def test_native_generated_code_blocked_at_entry_real(self, db, native_code):
        """原生自动生成码（001/002/006/008/011）外插一律拒绝——闸门全开也不放行。"""
        writer = JhemrWriter(db, _config_gate0_open(), connect=_must_not_connect)
        result = writer.insert_monitor_row(**_insert_kwargs(item_code=native_code), dry_run=False)
        assert result["mode"] == "BLOCKED"
        assert "natively generated" in result["reason"]
        log = _last_action_log(db)
        assert log.mode == "BLOCKED" and log.action_type == "JHEMR_INSERT_MONITOR"

    def test_native_generated_code_blocked_at_entry_dry_run(self, db):
        """dry_run 同样拒绝原生码（不留 DRY_RUN 拟执行语句，直接 BLOCKED）。"""
        writer = JhemrWriter(db, _config_gate0_open(), connect=_must_not_connect)
        result = writer.insert_monitor_row(**_insert_kwargs(item_code="JH04.02.011"), dry_run=True)
        assert result["mode"] == "BLOCKED" and result["handled"] is False

    def test_native_code_blocked_before_gates(self, db):
        """闸门 0 关闭 + 原生码 → 拦截原因来自原生码校验（证明入口校验先于闸门）。"""
        writer = JhemrWriter(db, _config(enabled=True, write_extra=_WRITE_CONN_OK),
                             connect=_must_not_connect)
        result = writer.insert_monitor_row(**_insert_kwargs(item_code="JH04.02.001"), dry_run=False)
        assert result["mode"] == "BLOCKED"
        assert "natively generated" in result["reason"]  # 而非 gate0

    def test_unknown_item_code_blocked_at_entry(self, db):
        """不在 MONITOR_TYPE_ZERO_CODES 白名单的码（应用层校验，替代原连库字典查询）。"""
        writer = JhemrWriter(db, _config_gate0_open(), connect=_must_not_connect)
        result = writer.insert_monitor_row(**_insert_kwargs(item_code="JH99.99.999"), dry_run=False)
        assert result["mode"] == "BLOCKED"
        assert "MONITOR_TYPE_ZERO_CODES" in result["reason"]

    def test_whitelist_codes_are_currently_valid_non_native(self):
        """白名单剔除全部原生码后仍有可用码（跨系统节点外插对象存在）。"""
        assert MONITOR_TYPE_ZERO_CODES - NATIVE_GENERATED_CODES
        assert NATIVE_GENERATED_CODES <= MONITOR_TYPE_ZERO_CODES

    def test_gate0_disabled_by_default_blocks_without_connect(self, db):
        # 默认配置（无 insert_monitor_enabled 键）→ BLOCKED 留痕，零连库。
        writer = JhemrWriter(db, _config(enabled=True, write_extra=_WRITE_CONN_OK), connect=_must_not_connect)
        result = writer.insert_monitor_row(**_insert_kwargs(), dry_run=False)
        assert result["mode"] == "BLOCKED"
        assert result["reason"].startswith("gate0")
        log = _last_action_log(db)
        assert log.mode == "BLOCKED" and log.action_type == "JHEMR_INSERT_MONITOR"
        assert log.sql_text == SQL_INSERT_MONITOR_TEMPLATE

    def test_gate0_explicit_false_blocks(self, db):
        writer = JhemrWriter(db, _config_gate0_open(extra={"insert_monitor_enabled": False}),
                             connect=_must_not_connect)
        result = writer.insert_monitor_row(**_insert_kwargs(), dry_run=False)
        assert result["mode"] == "BLOCKED" and result["reason"].startswith("gate0")

    def test_gate0_open_but_gate1_closed_blocks_with_gate1_reason(self, db):
        # 子开关开 + 总开关关 → 拦截原因来自闸门 1（证明闸门次序 0→1→2）。
        config = {"timeliness": {"jhemr_write": {"insert_monitor_enabled": True},
                                 "pilot_dept_codes": ["0101"]}}
        writer = JhemrWriter(db, config, connect=_must_not_connect)
        result = writer.insert_monitor_row(**_insert_kwargs(), dry_run=False)
        assert result["mode"] == "BLOCKED" and result["reason"].startswith("gate1")

    def test_gate2_not_piloted_blocks(self, db):
        writer = JhemrWriter(db, _config_gate0_open(pilots=("0101",)), connect=_must_not_connect)
        result = writer.insert_monitor_row(**_insert_kwargs(dept_code="0999"), dry_run=False)
        assert result["mode"] == "BLOCKED" and result["reason"].startswith("gate2")

    def test_dry_run_records_sql_and_params_without_connect(self, db):
        writer = JhemrWriter(db, _config_gate0_open(), connect=_must_not_connect)
        result = writer.insert_monitor_row(**_insert_kwargs(), dry_run=True)
        assert result["mode"] == "DRY_RUN" and result["handled"] is True
        log = _last_action_log(db)
        assert log.mode == "DRY_RUN" and log.action_type == "JHEMR_INSERT_MONITOR"
        assert log.sql_text == SQL_INSERT_MONITOR_TEMPLATE
        params = json.loads(log.params_json)
        assert params["item_code"] == "JH04.03.012"
        assert params["source_system_identity"] == "AI_MRZK"
        assert params["completed_date"] is None          # 勘误 R1/E4
        assert "MAX(monitor_no)" in params["monitor_no"]
        assert "NOT EXISTS" in params["dedupe"]

    def test_dry_run_default_when_omitted(self, db):
        # dry_run 缺省 True（fail-safe）：不传也绝不连库。
        writer = JhemrWriter(db, _config_gate0_open(), connect=_must_not_connect)
        result = writer.insert_monitor_row(**_insert_kwargs())
        assert result["mode"] == "DRY_RUN"

    def _writer(self, db, conn: FakeConn):
        captured: dict = {}

        def connect_factory(**kwargs):
            # 先留痕后连库：进入连接工厂时，EXECUTED/executing 台账行必须已存在。
            log = (
                db.query(TLActionLog)
                .filter(TLActionLog.mode == "EXECUTED", TLActionLog.result == "executing")
                .first()
            )
            assert log is not None, "模板 A 真实执行必须先写 tl_action_log(executing) 再连库"
            captured["kwargs"] = kwargs
            return conn

        return JhemrWriter(db, _config_gate0_open(), connect=connect_factory), captured

    def test_success_rowcount_1(self, db, monkeypatch):
        monkeypatch.setenv("TIMELINESS_JHEMR_WRITE_PASSWORD", "unit-test-write-pwd")
        conn = FakeConn(rowcount=1)
        writer, captured = self._writer(db, conn)
        result = writer.insert_monitor_row(**_insert_kwargs(), dry_run=False)
        assert result["mode"] == "EXECUTED" and result["executed"] is True
        assert result["duplicate"] is False
        assert captured["kwargs"]["user"] == "mrzk_write"
        assert conn.closed is True
        # 2026-11-13 返工：字典校验已改应用层常量，全程不得出现字典表 SELECT。
        assert all("jhinpat_mr_monitor_items" not in sql for sql, _ in conn.executed)
        # 唯一业务语句 = 模板 A INSERT（前一条是 SET statement_timeout），参数顺序精确核对
        # （NOT EXISTS 防重 4 参：patient/visit/item/start_date——同起算时间已有行不重插）。
        sql, params = conn.executed[-1]
        assert sql == SQL_INSERT_MONITOR_TEMPLATE
        assert params == [
            "P008", "1", "张测试", "49557032X", "49557032X", "JH04.03.012", "手术记录",
            datetime(2026, 11, 12, 9, 0, 0), datetime(2026, 11, 12, 21, 0, 0),
            "49557032X", "0101",
            "P008", "1", "JH04.03.012", datetime(2026, 11, 12, 9, 0, 0),
        ]
        assert conn.commit_calls == 1 and conn.rollback_calls == 0
        assert "success" in _last_action_log(db).result

    def test_duplicate_rowcount_0_is_idempotent_not_error(self, db, monkeypatch):
        monkeypatch.setenv("TIMELINESS_JHEMR_WRITE_PASSWORD", "unit-test-write-pwd")
        conn = FakeConn(rowcount=0)  # NOT EXISTS 防重命中
        writer, _ = self._writer(db, conn)
        result = writer.insert_monitor_row(**_insert_kwargs(), dry_run=False)
        assert result["duplicate"] is True and result["executed"] is False
        assert conn.rollback_calls == 1
        assert "duplicate" in _last_action_log(db).result

    def test_insert_error_rolls_back_and_reraises(self, db, monkeypatch):
        monkeypatch.setenv("TIMELINESS_JHEMR_WRITE_PASSWORD", "unit-test-write-pwd")
        conn = FakeConn(rowcount=1, exc=RuntimeError("boom"))

        original_execute = FakeCursor.execute

        def execute(self, sql, params=None):
            if "INSERT INTO" in sql:
                raise conn.raise_exc
            return original_execute(self, sql, params)

        with mock.patch.object(FakeCursor, "execute", execute):
            writer, _ = self._writer(db, conn)
            with pytest.raises(RuntimeError, match="boom"):
                writer.insert_monitor_row(**_insert_kwargs(), dry_run=False)
        assert conn.rollback_calls == 1
        assert "RuntimeError" in _last_action_log(db).result

    def test_rowcount_2_rolls_back_and_raises(self, db, monkeypatch):
        monkeypatch.setenv("TIMELINESS_JHEMR_WRITE_PASSWORD", "unit-test-write-pwd")
        conn = FakeConn(rowcount=2)
        writer, _ = self._writer(db, conn)
        with pytest.raises(JhemrWriteRowCountError):
            writer.insert_monitor_row(**_insert_kwargs(), dry_run=False)
        assert conn.rollback_calls == 1
        assert "rowcount=2" in _last_action_log(db).result

    def test_write_connection_missing_blocks_without_connect(self, db, monkeypatch):
        monkeypatch.delenv("TIMELINESS_JHEMR_WRITE_PASSWORD", raising=False)
        config = _config_gate0_open(extra={"host": "", "username": "", "password_enc": ""})
        writer = JhemrWriter(db, config, connect=_must_not_connect)
        result = writer.insert_monitor_row(**_insert_kwargs(), dry_run=False)
        assert result["mode"] == "BLOCKED" and "not configured" in result["reason"]

    def test_missing_required_args_raises_without_log(self, db):
        writer = JhemrWriter(db, _config_gate0_open(), connect=_must_not_connect)
        with pytest.raises(JhemrWriteError, match="item_name"):
            writer.insert_monitor_row(**_insert_kwargs(item_name=""), dry_run=True)
        assert db.query(TLActionLog).count() == 0


# ---- 模板 B：演练（DRY_RUN） ----


class TestTemplateBDryRun:
    def test_dry_run_records_sql_and_params_without_connection(self, db):
        writer = JhemrWriter(db, _config(enabled=True, write_extra=_WRITE_CONN_OK), connect=_must_not_connect)
        result = writer.approve_limit_log(**_approve_kwargs(), dry_run=True)
        assert result == {
            "handled": True, "executed": False, "mode": "DRY_RUN", "rowcount": None,
            "action_log_id": result["action_log_id"], "reason": "",
        }
        log = _last_action_log(db)
        assert log.mode == "DRY_RUN"
        assert log.action_type == "JHEMR_APPROVE"
        assert log.sql_text == SQL_APPROVE_LIMIT_LOG_TEMPLATE
        params = json.loads(log.params_json)
        assert params["approve_user_id"] == "chief01"
        assert params["monitor_code"] == "JH04.02.002"
        assert params["type"] == 1
        assert params["hospital_no"] == "H001"
        assert "dry_run" in log.result

    def test_dry_run_default_when_omitted(self, db):
        # dry_run 缺省 True（fail-safe）：不传也绝不连库。
        writer = JhemrWriter(db, _config(enabled=True), connect=_must_not_connect)
        result = writer.approve_limit_log(**_approve_kwargs())
        assert result["mode"] == "DRY_RUN"

    def test_dry_run_uses_default_approve_time(self, db):
        fixed_now = datetime(2026, 11, 11, 12, 0, 0)
        writer = JhemrWriter(
            db, _config(enabled=True), connect=_must_not_connect, now_fn=lambda: fixed_now
        )
        writer.approve_limit_log(**_approve_kwargs(approve_date_time=None), dry_run=True)
        # _dump_params 用 default=str 序列化 datetime（与 str() 同格式）。
        assert json.loads(_last_action_log(db).params_json)["approve_date_time"] == str(fixed_now)


# ---- 模板 B：真实执行 ----


class TestTemplateBExecution:
    def _writer(self, db, conn: FakeConn):
        captured: dict[str, FakeConn] = {}

        def connect_factory(**kwargs):
            # 先留痕后连库：进入连接工厂时，EXECUTED/executing 台账行必须已存在。
            log = (
                db.query(TLActionLog)
                .filter(TLActionLog.mode == "EXECUTED", TLActionLog.result == "executing")
                .first()
            )
            assert log is not None, "真实执行必须先写 tl_action_log(executing) 再连库"
            captured["kwargs"] = kwargs
            captured["conn"] = conn
            return conn

        writer = JhemrWriter(db, _config(enabled=True, write_extra=_WRITE_CONN_OK), connect=connect_factory)
        return writer, captured

    def test_success_rowcount_1(self, db, monkeypatch):
        monkeypatch.setenv("TIMELINESS_JHEMR_WRITE_PASSWORD", "unit-test-write-pwd")
        conn = FakeConn(rowcount=1)
        writer, captured = self._writer(db, conn)
        result = writer.approve_limit_log(**_approve_kwargs(), dry_run=False)
        assert result["mode"] == "EXECUTED"
        assert result["executed"] is True
        assert result["rowcount"] == 1
        # 连接参数来自独立写段（非只读账号）。
        assert captured["kwargs"]["user"] == "mrzk_write"
        assert captured["kwargs"]["host"] == "10.10.8.177"
        assert captured["kwargs"]["password"] == "unit-test-write-pwd"
        # 最后一条执行语句 = 模板 B 原文 + 参数顺序（前一条是 SET statement_timeout）。
        sql, params = conn.executed[-1]
        assert sql == APPROVE_TEMPLATE_FROM_TASK
        assert params == [
            "chief01", datetime(2026, 11, 11, 10, 30, 0), "P008", "1", "JH04.02.002",
            datetime(2026, 11, 11, 9, 0, 0), 1, "H001",
        ]
        assert conn.commit_calls == 1
        assert conn.rollback_calls == 0
        assert conn.closed is True
        log = _last_action_log(db)
        assert log.mode == "EXECUTED"
        assert log.result == "success: rowcount=1"

    def test_rowcount_0_rolls_back_and_raises(self, db, monkeypatch):
        monkeypatch.setenv("TIMELINESS_JHEMR_WRITE_PASSWORD", "unit-test-write-pwd")
        conn = FakeConn(rowcount=0)
        writer, _ = self._writer(db, conn)
        with pytest.raises(JhemrWriteRowCountError):
            writer.approve_limit_log(**_approve_kwargs(), dry_run=False)
        assert conn.rollback_calls == 1
        assert conn.commit_calls == 0   # 业务提交为零（回滚优先）
        assert conn.closed is True
        log = _last_action_log(db)
        assert log.mode == "EXECUTED"
        assert "rowcount=0" in log.result
        assert "rolled back" in log.result

    def test_rowcount_2_rolls_back_and_raises(self, db, monkeypatch):
        monkeypatch.setenv("TIMELINESS_JHEMR_WRITE_PASSWORD", "unit-test-write-pwd")
        conn = FakeConn(rowcount=2)
        writer, _ = self._writer(db, conn)
        with pytest.raises(JhemrWriteRowCountError):
            writer.approve_limit_log(**_approve_kwargs(), dry_run=False)
        assert conn.rollback_calls == 1
        assert "rowcount=2" in _last_action_log(db).result

    def test_execution_error_rolls_back_and_reraises(self, db, monkeypatch):
        monkeypatch.setenv("TIMELINESS_JHEMR_WRITE_PASSWORD", "unit-test-write-pwd")
        conn = FakeConn(rowcount=1, exc=RuntimeError("boom"))

        original_execute = FakeCursor.execute

        def execute(self, sql, params=None):
            if "statement_timeout" not in sql:
                raise conn.raise_exc
            return original_execute(self, sql, params)

        with mock.patch.object(FakeCursor, "execute", execute):
            writer, _ = self._writer(db, conn)
            with pytest.raises(RuntimeError, match="boom"):
                writer.approve_limit_log(**_approve_kwargs(), dry_run=False)
        assert conn.rollback_calls == 1
        log = _last_action_log(db)
        assert "RuntimeError" in log.result

    def test_write_connection_missing_blocks_without_connect(self, db, monkeypatch):
        # 闸门 1/2 通过但写连接未配置（缺 host/账号/口令）→ 拦截且不连库。
        monkeypatch.delenv("TIMELINESS_JHEMR_WRITE_PASSWORD", raising=False)
        writer = JhemrWriter(db, _config(enabled=True), connect=_must_not_connect)
        result = writer.approve_limit_log(**_approve_kwargs(), dry_run=False)
        assert result["mode"] == "BLOCKED"
        assert "not configured" in result["reason"]
        assert _last_action_log(db).mode == "BLOCKED"


# ---- 入参与配置解析 ----


class TestInputsAndConnectionConfig:
    def test_missing_required_argument_raises_without_log(self, db):
        writer = JhemrWriter(db, _config(enabled=True), connect=_must_not_connect)
        with pytest.raises(JhemrWriteError, match="hospital_no"):
            writer.approve_limit_log(**_approve_kwargs(hospital_no=""))
        assert db.query(TLActionLog).count() == 0

    def test_resolve_rejects_missing_host(self):
        with pytest.raises(TimelinessNotConfigured, match="host"):
            resolve_jhemr_write({"jhemr_write": {"enabled": True, "username": "mrzk_write"}})

    def test_resolve_rejects_missing_username(self):
        with pytest.raises(TimelinessNotConfigured, match="username"):
            resolve_jhemr_write({"jhemr_write": {"host": "10.10.8.177"}})

    def test_resolve_rejects_readonly_account_reuse(self):
        # T8：写账号严禁复用只读账号 aizk_user（读写分离）。
        with pytest.raises(TimelinessNotConfigured, match="aizk_user"):
            resolve_jhemr_write(
                {"jhemr_write": {"host": "10.10.8.177", "username": "aizk_user"}}
            )

    def test_resolve_rejects_missing_password(self, monkeypatch):
        monkeypatch.delenv("TIMELINESS_JHEMR_WRITE_PASSWORD", raising=False)
        with pytest.raises(TimelinessNotConfigured, match="口令"):
            resolve_jhemr_write({"jhemr_write": {"host": "10.10.8.177", "username": "mrzk_write"}})

    def test_resolve_password_from_env(self, monkeypatch):
        monkeypatch.setenv("TIMELINESS_JHEMR_WRITE_PASSWORD", "env-pwd")
        params = resolve_jhemr_write({"jhemr_write": {"host": "10.10.8.177", "username": "mrzk_write"}})
        assert params["password"] == "env-pwd"
        assert params["port"] == 5432
        assert params["database"] == "jhemr"

    def test_resolve_password_from_encrypted_token(self, monkeypatch):
        monkeypatch.delenv("TIMELINESS_JHEMR_WRITE_PASSWORD", raising=False)
        from app.config import encrypt_value

        token = encrypt_value("enc-pwd")
        params = resolve_jhemr_write(
            {"jhemr_write": {"host": "10.10.8.177", "username": "mrzk_write", "password_enc": token}}
        )
        assert params["password"] == "enc-pwd"

    def test_sslmode_only_when_configured(self, monkeypatch):
        monkeypatch.setenv("TIMELINESS_JHEMR_WRITE_PASSWORD", "env-pwd")
        params = resolve_jhemr_write(
            {"jhemr_write": {"host": "h", "username": "u", "sslmode": ""}}
        )
        assert params["sslmode"] == ""


# ---- 源码扫描：语句模板白名单 ----


class TestSourceCodeGuard:
    WRITE_KEYWORD_RE = re.compile(
        r"(?i)\b(insert\s+into|update\s+\S+|delete\s+from|alter\s+table|grant\s+on|"
        r"revoke\s+on|truncate\s+table|drop\s+table|merge\s+into|create\s+table)\b"
    )

    def test_no_write_statements_outside_two_templates(self):
        # 解析 AST 收集全部字符串常量（含 docstring）：含写语句关键词的字符串
        # 必须恰好等于两个模板常量，杜绝白名单外的任何写语句文本。
        import ast

        source = Path(writer_module.__file__).read_text(encoding="utf-8")
        offenders = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if self.WRITE_KEYWORD_RE.search(node.value):
                    offenders.add(node.value)
        assert offenders == {SQL_INSERT_MONITOR_TEMPLATE, SQL_APPROVE_LIMIT_LOG_TEMPLATE}, (
            f"出现模板白名单之外的写语句字符串: {offenders - {SQL_INSERT_MONITOR_TEMPLATE, SQL_APPROVE_LIMIT_LOG_TEMPLATE}}"
        )

    def test_templates_never_write_completed_date(self):
        # 勘误 R1/E4：completed_date 只能由 JHEMR 原生维护，外挂严禁写入。
        # 2026-11-13 返工：NOT EXISTS 子查询允许只读判定 completed_date IS NULL，
        # 但 INSERT 列清单与 SET 子句绝不包含该列。
        match = re.match(r"\s*INSERT INTO jhemr\.emr_online_monitor \((.*?)\) SELECT", SQL_INSERT_MONITOR_TEMPLATE, re.S)
        assert match, "模板 A 应为 INSERT...SELECT 形态"
        template_cols = [c.strip() for c in match.group(1).split(",")]
        assert "completed_date" not in template_cols
        assert "completed_date" not in SQL_APPROVE_LIMIT_LOG_TEMPLATE.split("SET", 1)[-1].split("WHERE", 1)[0]
        # 模板 A 中 completed_date 只允许出现在 NOT EXISTS 只读判定条件里。
        head, _, tail = SQL_INSERT_MONITOR_TEMPLATE.partition("WHERE NOT EXISTS")
        assert "completed_date" not in head
        assert "completed_date IS NULL" in tail

    def test_insert_template_not_exists_clause_matches_rework_spec(self):
        # 2026-11-13 返工任务书原文（逐字节锁定）：去掉 AI_MRZK 限定——同患者同码
        # 存在未完成行（含原生行）或同一起算时间已有行均不重插；mul_time_flag=1
        # 的二台手术/二次抢救/多次会诊（前次已完成且新 start_date）允许插入。
        assert SQL_INSERT_MONITOR_TEMPLATE.endswith(INSERT_NOT_EXISTS_CLAUSE)
        assert "source_system_identity = 'AI_MRZK'" not in SQL_INSERT_MONITOR_TEMPLATE.split("WHERE NOT EXISTS")[-1]

    def test_insert_template_columns_are_subset_of_t1_real_columns(self):
        fixture = json.loads(FIXTURE_REAL_COLUMNS.read_text(encoding="utf-8"))
        real_cols = [c["column_name"] for c in fixture["tables"]["jhemr.emr_online_monitor"]]
        match = re.match(r"\s*INSERT INTO jhemr\.emr_online_monitor \((.*?)\) SELECT", SQL_INSERT_MONITOR_TEMPLATE, re.S)
        assert match, "模板 A 应为 INSERT...SELECT 形态"
        template_cols = [c.strip() for c in match.group(1).split(",")]
        assert "completed_date" not in template_cols          # 勘误 R1/E4
        assert set(template_cols) <= set(real_cols), template_cols
        assert {"monitor_no", "source_system_identity", "hospital_no", "start_date"} <= set(template_cols)
        # 取号 CASE 与幂等防重（Q3 规范）必须在模板文本中。
        assert "MAX(monitor_no)" in SQL_INSERT_MONITOR_TEMPLATE
        assert "NOT EXISTS" in SQL_INSERT_MONITOR_TEMPLATE
        assert SOURCE_SYSTEM_IDENTITY == "AI_MRZK" and HOSPITAL_NO_DEFAULT == "49557032X"
        # 占位符计数：INSERT 11 + NOT EXISTS 防重 4（patient/visit/item/start_date）= 15。
        assert SQL_INSERT_MONITOR_TEMPLATE.count("%s") == 15

    def test_no_dict_table_select_in_module_source(self):
        # 2026-11-13 返工：专用写账号无 jhinpat_mr_monitor_items 的 SELECT 权限，
        # 全模块不得再出现对该表的任何查询语句字符串。
        source = Path(writer_module.__file__).read_text(encoding="utf-8")
        assert "SELECT item_code FROM jhemr.jhinpat_mr_monitor_items" not in source
        assert "SQL_CHECK_MONITOR_ITEM_TEMPLATE" not in source

    def test_monitor_code_constants_consistent_with_router_dict_and_seeds(self):
        # MONITOR_TYPE_ZERO_CODES 与路由字典（§10.1 生产实测 27 项）同源一致；
        # 覆盖全部规则种子的监控码（外插对象 ⊆ 白名单）。
        from app.routers.timeliness import MONITOR_ITEM_DICT
        from app.timeliness.rules_seed import RULE_SEEDS

        dict_codes = {item["code"] for item in MONITOR_ITEM_DICT}
        assert MONITOR_TYPE_ZERO_CODES == frozenset(dict_codes)
        seed_codes = {seed.jhemr_monitor_code for seed in RULE_SEEDS if seed.jhemr_monitor_code}
        assert seed_codes <= MONITOR_TYPE_ZERO_CODES

    def test_native_generated_codes_fixed(self):
        # 2026-11-13 返工任务书给定集合（011 自 2026-11-10 起原生自动触发）。
        assert NATIVE_GENERATED_CODES == frozenset({
            "JH04.02.001", "JH04.02.002", "JH04.02.006", "JH04.02.008", "JH04.02.011",
        })

    def test_approve_template_matches_task_verbatim(self):
        assert SQL_APPROVE_LIMIT_LOG_TEMPLATE == APPROVE_TEMPLATE_FROM_TASK
