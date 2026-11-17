"""061 D4：2026-10-06 复现用例，2026-10-08 转为保留当前结果的回归。

修复前（round-9 分歧表 D4，061 §二.2 路径②）：Dify 输出【非空且非法 JSON】时，
push_to_dify 仅按"输出是否为空"决定 transport 状态（app/dify_pusher.py status 分支），
返回 status="success" + parsed_output.parse_success=False；
push_executor._push_single_record 在 parse 判断【之前】调用
attach_success_push_log_as_current（app/services/push_executor.py 015/C1 腾槽），
同身份旧 success 当前被 superseded；随后 parse_ok=False 按 003-C 跳过
_save_audit_results——当前槽被"success + parse_status=failed + 0 维度"的新行占据，
旧可读结果（含维度）被挤出当前且新行 qc_usable=False。

修复后保留传输状态与 success-only 唯一索引；解析失败尝试引用保留的旧当前。
测试使用实际 SQLite 部分唯一索引，覆盖重试、后续成功、删除引用和两条执行路径。
"""

from datetime import datetime
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, _push_log_current_identity_index_ddl
from app.dify_pusher import push_to_dify
from app.models import AuditDimensionResult, PushLog
from app.services.push_log_supersede import attach_success_push_log_as_current
from app.services.qc_status_semantics import is_qc_usable

import pytest

SOURCE_KEY = "mode::daily_increment::progress_vs_nursing::P001::1"


def _dify_http_invalid_json_nonempty(monkeypatch):
    """mock Dify HTTP：workflow 输出【非空】且为非法 JSON。"""

    def mock_post(url, headers=None, json=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "workflow_run_id": "wr-d4",
            "task_id": "t-d4",
            "data": {"outputs": {"aa": "这不是JSON{{{模型格式异常输出"}},
        }
        return resp

    monkeypatch.setattr("app.dify_pusher.requests.post", mock_post)

    config = {
        "base_url": "http://dify.local/v1",
        "api_key": "k1",
        "workflow_input_variable": "mr_txt",
        "workflow_output_key": "aa",
        "timeout_seconds": 30,
    }
    return push_to_dify("test_mr_text", config, "P001")


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(_push_log_current_identity_index_ddl("push_log", "sqlite")))
    return sessionmaker(bind=engine)()


def _make_log(**kwargs):
    """PushLog 实例，字段默认值沿用 tests/test_push_log_supersede.py 口径。"""
    defaults = {
        "push_time": datetime.now(),
        "trigger_type": "auto",
        "query_date": "2026-06-01",
        "patient_id": "P001",
        "visit_number": "1",
        "audit_type_code": "progress_vs_nursing",
        "audit_run_mode": "daily_increment",
        "status": "success",
        "pushed_flag": 1,
        "source_record_key": SOURCE_KEY,
    }
    defaults.update(kwargs)
    return PushLog(**defaults)


def _seed_old_current_with_dimension(db):
    """旧当前槽：success + parse_status=success + 1 条维度（qc_usable=True）。"""
    old = _make_log(parse_status="success")
    db.add(old)
    db.flush()
    db.add(
        AuditDimensionResult(
            push_log_id=old.id,
            dimension_code="progress_vs_nursing",
            dimension="病程与护理一致性",
            status="❌",
            severity="medium",
        )
    )
    db.flush()
    return old


def _query_current(db):
    """当前槽口径与 attach_success_push_log_as_current 的腾槽查询一致。"""
    return (
        db.query(PushLog)
        .filter(
            PushLog.source_record_key == SOURCE_KEY,
            PushLog.audit_type_code == "progress_vs_nursing",
            PushLog.audit_run_mode == "daily_increment",
            PushLog.status == "success",
            PushLog.superseded_by.is_(None),
        )
        .all()
    )


def _new_log_from_dify_result(dify_result):
    """按 push_executor 语义构造新日志：status 取 transport 结果，
    parse_status 按 'failed' if not parse_ok else 'success'（push_executor 同式）。"""
    parse_ok = bool((dify_result.get("parsed_output") or {}).get("parse_success"))
    return _make_log(
        status=str(dify_result.get("status") or ""),
        parse_status="failed" if not parse_ok else "success",
    )


class TestD4Regression:
    """传输成功语义保留，解析不可用尝试不挤占旧当前。"""

    def test_nonempty_invalid_json_transport_status_is_success(self, monkeypatch):
        """路径②触发前提：非空+非法 JSON → status=success 且 parse_success=False。"""
        result = _dify_http_invalid_json_nonempty(monkeypatch)
        assert result["status"] == "success", "非空输出不应走 parse_failed（仅空输出才走）"
        assert (result["parsed_output"] or {}).get("parse_success") is False
        assert result["parse_error"], "解析错误信息应非空"

    def test_current_slot_kept_after_zero_dimension_parse_failed_row(self, monkeypatch):
        """真实索引下旧当前和维度保留，新尝试仍可审计。"""
        db = _make_db()
        try:
            old = _seed_old_current_with_dimension(db)
            assert len(_query_current(db)) == 1  # 前置：旧当前在位且可用
            assert is_qc_usable(old.status, old.parse_status) is True

            dify_result = _dify_http_invalid_json_nonempty(monkeypatch)
            assert dify_result["status"] == "success"

            new_log = _new_log_from_dify_result(dify_result)
            assert new_log.status == "success"
            assert new_log.parse_status == "failed"

            assert attach_success_push_log_as_current(db, new_log) == 0
            db.flush()

            assert old.superseded_by is None
            assert new_log.superseded_by == old.id
            currents = _query_current(db)
            assert [c.id for c in currents] == [old.id]
            dim_count = (
                db.query(AuditDimensionResult)
                .filter(AuditDimensionResult.push_log_id == new_log.id)
                .count()
            )
            assert dim_count == 0, "003-C：parse_failed 不落维度 → 新当前 0 维度"
            # 旧维度仍挂在保留的旧当前上，未迁移或删除
            old_dim_count = (
                db.query(AuditDimensionResult)
                .filter(AuditDimensionResult.push_log_id == old.id)
                .count()
            )
            assert old_dim_count == 1
            # 本次失败尝试不可用，但不会挤占旧当前结果
            assert is_qc_usable(new_log.status, new_log.parse_status) is False
        finally:
            db.close()


class TestD4Desired:
    """原 xfail 转正常回归；补齐失败尝试的生命周期。"""

    def test_parse_failed_row_should_not_evict_current(self, monkeypatch):
        """期望：parse_status=failed 的新行不应把可用旧当前挤出当前槽。"""
        db = _make_db()
        try:
            old = _seed_old_current_with_dimension(db)

            dify_result = _dify_http_invalid_json_nonempty(monkeypatch)
            new_log = _new_log_from_dify_result(dify_result)
            assert new_log.parse_status == "failed"

            attach_success_push_log_as_current(db, new_log)
            db.flush()

            assert old.superseded_by is None, "期望旧行保持当前"
            currents = _query_current(db)
            assert old.id in [c.id for c in currents], "期望旧当前仍在当前槽"
        finally:
            db.close()

    @pytest.mark.parametrize("parse_status", ["failed", "fallback"])
    def test_repeated_unusable_attempts_then_success(self, parse_status):
        db = _make_db()
        try:
            old = _seed_old_current_with_dimension(db)
            attempts = [_make_log(parse_status=parse_status) for _ in range(2)]
            for attempt in attempts:
                assert attach_success_push_log_as_current(db, attempt) == 0
                assert attempt.status == "success"
                assert attempt.superseded_by == old.id
            good = _make_log(parse_status="success")
            assert attach_success_push_log_as_current(db, good) == 1
            db.commit()
            assert old.superseded_by == good.id
            assert [row.id for row in _query_current(db)] == [good.id]
            assert db.query(PushLog).count() == 4
        finally:
            db.close()

    def test_unusable_first_attempt_still_saved_without_fake_result(self):
        db = _make_db()
        try:
            attempt = _make_log(parse_status="failed")
            assert attach_success_push_log_as_current(db, attempt) == 0
            db.commit()
            assert attempt.id
            assert attempt.superseded_by is None
            assert is_qc_usable(attempt.status, attempt.parse_status) is False
        finally:
            db.close()

    @pytest.mark.parametrize("delete_kind", ["attempt", "current", "all"])
    def test_delete_does_not_create_multiple_success_currents(self, delete_kind):
        from app.routers.logs import _delete_push_logs
        db = _make_db()
        try:
            old = _seed_old_current_with_dimension(db)
            attempts = [_make_log(parse_status="failed") for _ in range(2)]
            for attempt in attempts:
                attach_success_push_log_as_current(db, attempt)
            db.commit()
            old_id = old.id
            ids = [attempts[0].id] if delete_kind == "attempt" else [old_id]
            if delete_kind == "all":
                ids += [row.id for row in attempts]
            assert _delete_push_logs(db, ids) == len(ids)
            db.expire_all()
            remaining = db.query(PushLog).all()
            assert len(_query_current(db)) == (1 if remaining else 0)
            remaining_ids = {row.id for row in remaining}
            assert all(row.superseded_by is None or row.superseded_by in remaining_ids for row in remaining)
            if delete_kind == "attempt":
                assert _query_current(db)[0].id == old_id
        finally:
            db.close()


@pytest.mark.parametrize("path", ["serial", "bulk"])
def test_executors_keep_old_current_and_do_not_enqueue_on_parse_failure(monkeypatch, path):
    """直接运行两条执行路径；DB、唯一索引真实，外部调用全部 mock。"""
    from types import SimpleNamespace
    from app.services.push_executor import PushConfig, PushExecutor
    from app.services.bulk_push_executor import BulkPushExecutor
    db = _make_db()
    try:
        old = _seed_old_current_with_dimension(db)
        db.commit()
        old_id = old.id
        result = _dify_http_invalid_json_nonempty(monkeypatch)
        monkeypatch.setattr(PushExecutor, "_build_payload_and_mr_text", lambda *a: (
            SimpleNamespace(group_values={"patient_id": "P001", "visit_number": "1"}),
            {"patient_info": {"patient_id": "P001", "visit_number": "1"}}, "test", "P001", "1", [{}],
        ))
        monkeypatch.setattr(PushExecutor, "_get_skip_reason", lambda *a, **k: ("", ""))
        monkeypatch.setattr(PushExecutor, "_create_push_log", lambda *a, **k: _new_log_from_dify_result(result))
        monkeypatch.setattr("app.services.push_idempotency.claim_execution", lambda *a, **k: (None, True, ""))
        enqueue = MagicMock()
        save_results = MagicMock()
        monkeypatch.setattr("app.services.relay_alert_service.RelayAlertService.enqueue_high_severity_alerts", enqueue)
        monkeypatch.setattr("app.services.relay_alert_service.RelayAlertService.dispatch_pending", lambda *a, **k: {})
        monkeypatch.setattr(PushExecutor, "_save_audit_results", save_results)
        cfg = PushConfig(trigger_type="manual", query_date="2026-10-08", audit_type_code="progress_vs_nursing", existing_result_policy="replace_current")
        if path == "serial":
            monkeypatch.setattr("app.services.push_executor.push_to_dify", lambda *a, **k: result)
            actual = PushExecutor({})._push_single_record(db, "P001", [{}], cfg)
            db.commit()
        else:
            monkeypatch.setattr("app.services.bulk_push_executor.SessionLocal", sessionmaker(bind=db.get_bind()))
            monkeypatch.setattr(BulkPushExecutor, "_push_with_empty_retry", lambda *a, **k: result)
            actual = BulkPushExecutor({"base_url": "http://dify.local/v1", "api_key": "test"})._process_single("P001", [{}], cfg)
        assert actual["status"] == "success"
        db.expire_all()
        assert [row.id for row in _query_current(db)] == [old_id]
        assert db.query(PushLog).count() == 2
        assert db.query(AuditDimensionResult).count() == 1
        enqueue.assert_not_called()
        save_results.assert_not_called()
    finally:
        db.close()
