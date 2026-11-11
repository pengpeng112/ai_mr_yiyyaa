"""T8：JHEMR 受控写入器单元测试。

覆盖（§15 T8 验收口径 + §18.1 D3 + 勘误 E6/R1）：
- 三重闸门逐一拦截：总开关（enabled 非 True 的各形态）、科室白名单（非试点/
  空科室/空白名单）→ tl_action_log(mode=BLOCKED)、零连库（必炸哨兵连接工厂）；
- 模板 A（插入监控行）：任何配置下调用都直接抛 NotImplementedError（D3 待嘉和
  确认），零留痕、零连库；
- 模板 B 演练：闸门通过 + dry_run=True → tl_action_log(mode=DRY_RUN) 记录完整
  SQL 与参数，零连库；
- 模板 B 真实执行：先留痕 EXECUTED 再连库；SQL 与参数顺序逐项核对；rowcount==1
  提交；rowcount==0/2 立即回滚并抛 JhemrWriteRowCountError；执行异常回滚后抛出；
- 写连接独立性：缺 host/账号/口令 → 拦截（BLOCKED）；账号复用只读账号
  aizk_user → 拒绝（T8：读写账号必须分离）；口令环境变量与 password_enc 两路；
- 源码扫描：除两个硬编码模板常量外，jhemr_writer.py 不得再含任何写语句；
  两模板均不得包含 completed_date（勘误 R1/E4）；模板 A 列清单与 T1 真实列
  fixture（剔除 completed_date）完全一致；模板 B 与任务书逐字节一致。
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


# ---- 闸门 3：模板 A 未实现（D3 待嘉和确认） ----


class TestTemplateANotImplemented:
    @pytest.mark.parametrize(
        "config",
        [
            _config(),                                                        # 总开关关
            _config(enabled=True, pilots=("0101",), write_extra=_WRITE_CONN_OK),  # 全闸门开
        ],
        ids=["gates-closed", "gates-open"],
    )
    def test_insert_monitor_row_always_raises(self, db, config):
        writer = JhemrWriter(db, config, connect=_must_not_connect)
        with pytest.raises(NotImplementedError, match="D3"):
            writer.insert_monitor_row(patient_id="P008", visit_id="1", monitor_code="JH04.02.018")
        # 未留痕、未连库。
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

    def test_templates_never_touch_completed_date(self):
        # 勘误 R1/E4：completed_date 只能由 JHEMR 原生维护，外挂严禁写入。
        assert "completed_date" not in SQL_INSERT_MONITOR_TEMPLATE
        assert "completed_date" not in SQL_APPROVE_LIMIT_LOG_TEMPLATE

    def test_insert_template_columns_match_t1_real_columns(self):
        fixture = json.loads(FIXTURE_REAL_COLUMNS.read_text(encoding="utf-8"))
        real_cols = [c["column_name"] for c in fixture["tables"]["jhemr.emr_online_monitor"]]
        expected = [c for c in real_cols if c != "completed_date"]
        match = re.match(r"\s*INSERT INTO jhemr\.emr_online_monitor \((.*?)\) VALUES", SQL_INSERT_MONITOR_TEMPLATE, re.S)
        assert match, "模板 A 应为可解析的插入语句骨架"
        template_cols = [c.strip() for c in match.group(1).split(",")]
        assert template_cols == expected
        assert SQL_INSERT_MONITOR_TEMPLATE.count("%s") == len(expected)

    def test_approve_template_matches_task_verbatim(self):
        assert SQL_APPROVE_LIMIT_LOG_TEMPLATE == APPROVE_TEMPLATE_FROM_TASK
