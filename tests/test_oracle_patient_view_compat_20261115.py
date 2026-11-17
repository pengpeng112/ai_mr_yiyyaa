"""2026-11-15 P0-1：Oracle 患者视图兼容降级模块单测（V_QYBR/V_CYBR 失效免疫）。"""
from __future__ import annotations

import pytest

from app.services import oracle_patient_view_compat as compat


def teardown_function():
    compat.reset_broken_state()


# ---- 错误识别 ----


class _OraErr(Exception):
    pass


def test_is_invalid_view_error_matches_ora_codes():
    assert compat.is_invalid_view_error(_OraErr('ORA-04063: view "JHEMR.V_QYBR" 有错误'))
    assert compat.is_invalid_view_error(_OraErr("ORA-01031: insufficient privileges"))
    assert compat.is_invalid_view_error(Exception("ORA-04063: package body 有错误"))
    assert not compat.is_invalid_view_error(Exception("ORA-00904: invalid identifier"))
    assert not compat.is_invalid_view_error(Exception("ORA-24459: pool timeout"))
    assert not compat.is_invalid_view_error(None)


# ---- 熔断记忆 ----


def test_broken_state_marks_and_expires():
    compat.mark_view_broken("jhemr.v_qybr")
    assert compat.is_view_broken("jhemr.v_qybr") is True
    assert compat.is_view_broken("jhemr.v_cybr") is False  # 分视图记录
    compat.reset_broken_state()
    assert compat.is_view_broken("jhemr.v_qybr") is False


# ---- 受控重写 ----


def test_rewrite_keeps_alias_and_other_text():
    sql = (
        'SELECT a."患者ID" FROM jhemr.V_QYBR a WHERE a."出院日期" IS NULL '
        "AND a.\"次数\" = :vn"
    )
    out = compat.rewrite_view_refs(sql, prefer_inpatient=True)
    # v_qybr 在在院场景 → V_ZYBR 平替（同构括号视图）
    assert "jhemr.v_zybr" in out.lower()
    assert "jhemr.v_qybr" not in out.lower()
    # 别名与其余文本保留
    assert " a " in out
    assert ':vn' in out


def test_rewrite_v_cybr_uses_base_tables_with_discharge_pushdown():
    sql = "SELECT * FROM jhemr.v_cybr a WHERE TRUNC(a.\"出院日期\") = :d"
    out = compat.rewrite_view_refs(sql)
    assert "his.PAT_VISIT" in out
    assert '"出院日期" IS NOT NULL' in out  # discharged_only 下推
    assert "jhemr.v_cybr" not in out.lower()


def test_rewrite_replaces_all_occurrences():
    sql = (
        "SELECT * FROM jhemr.v_qybr a JOIN jhemr.v_cybr b ON a.\"患者ID\" = b.\"患者ID\""
    )
    out = compat.rewrite_view_refs(sql)
    lowered = out.lower()
    assert "jhemr.v_qybr" not in lowered
    assert "jhemr.v_cybr" not in lowered
    # v_qybr（默认全量口径）与 v_cybr（出院下推）各一处基表内联
    assert lowered.count("his.pat_visit") == 2


# ---- 内联视图 40 列契约 ----


def test_inline_view_contains_full_contract_columns():
    view = compat.inline_patient_visit_view()
    for col in compat.PATIENT_VIEW_COLUMNS:
        assert f'"{col}"' in view, col
    # 纯只读：不含任何写关键词
    lowered = view.lower()
    for banned in ("insert ", "update ", "delete ", "drop ", "alter ", "grant "):
        assert banned not in lowered, banned
    # 日期/患者过滤条件下推开关
    discharged = compat.inline_patient_visit_view(discharged_only=True)
    assert '"出院日期" IS NOT NULL' in discharged


# ---- execute_with_view_compat ----


class _FakeCursor:
    def __init__(self, fail_once_with=None):
        self.executed: list[str] = []
        self._fail_once_with = fail_once_with

    def execute(self, sql, params=None):
        self.executed.append(sql)
        if len(self.executed) == 1 and self._fail_once_with is not None:
            raise self._fail_once_with
        return "ok"


def test_execute_retries_with_rewrite_on_invalid_view():
    cur = _FakeCursor(fail_once_with=_OraErr('ORA-04063: view "JHEMR.V_QYBR" 有错误'))
    result = compat.execute_with_view_compat(
        cur, "SELECT 1 FROM jhemr.v_qybr a", prefer_inpatient=True
    )
    assert result == "ok"
    assert len(cur.executed) == 2
    assert "jhemr.v_qybr" in cur.executed[0].lower()
    assert "jhemr.v_qybr" not in cur.executed[1].lower()
    # 首次失败即触发 5 分钟熔断
    assert compat.is_view_broken("jhemr.v_qybr") is True


def test_execute_skips_probe_when_circuit_open():
    compat.mark_view_broken("jhemr.v_qybr")
    cur = _FakeCursor()
    compat.execute_with_view_compat(cur, "SELECT 1 FROM jhemr.v_qybr a")
    # 熔断期：不先撞错，直接执行重写 SQL
    assert len(cur.executed) == 1
    assert "jhemr.v_qybr" not in cur.executed[0].lower()


def test_execute_reraises_non_view_errors():
    cur = _FakeCursor(fail_once_with=_OraErr("ORA-24459: pool borrow timeout"))
    with pytest.raises(_OraErr):
        compat.execute_with_view_compat(cur, "SELECT 1 FROM jhemr.v_qybr a")
    assert len(cur.executed) == 1  # 未重写重试


# ---- P0-2：ORA-24459 连接池修复（默认上限/等待策略/瞬时错误归类） ----


def test_pool_defaults_optimized_for_concurrency():
    from app.oracle_client import _resolve_oracle_pool_settings

    settings = _resolve_oracle_pool_settings({})
    assert settings["pool_max"] == 32          # 16→32：并发多页打开不再瞬满
    assert settings["acquire_timeout_seconds"] == 10  # 5s→10s：TIMEDWAIT 等更久
    assert settings["fallback_direct_connect"] is False  # 保守默认保持


def test_ora_24459_classified_as_transient():
    from app.oracle_client import classify_oracle_error, is_transient_oracle_error

    err = _OraErr("ORA-24459: connection pool request timed out")
    # 归类：池类错误（ORACLE_POOL_UNAVAILABLE，便于按错误层级统计与告警）；
    # is_transient=True → 触发既有"重建池后重试一次"路径 + 借出退避重借。
    assert is_transient_oracle_error(err) is True
    assert classify_oracle_error(err) == "ORACLE_POOL_UNAVAILABLE"
