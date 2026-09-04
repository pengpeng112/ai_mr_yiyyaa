# -*- coding: utf-8 -*-
"""规则中心生命周期与状态机测试（039 T2 / §12.1 Rule lifecycle + Concurrency）。"""

import pytest

from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.rule_repository import RuleConflictError, RuleNotFoundError, RuleRepository
from prearchive.rule_service import Actor, RuleService, scan_dangerous_content
from prearchive.rules import RuleValidationError

from helpers import dt  # noqa: F401


def _make_service(require_separate_approver=False):
    repo = RuleRepository(build_session_factory(build_sqlite_engine(":memory:")))
    return RuleService(repo, require_separate_approver=require_separate_approver), repo


def _rule_dict(rule_id="R-CENTER-1", version="2026.09.02.1", **over):
    base = {
        "rule_id": rule_id, "name": "规则中心测试", "message": "测试消息",
        "type": "empty_field", "fields": ["过敏史"], "version": version,
        "severity": "medium",
    }
    base.update(over)
    return base


ADMIN = Actor(id="admin-1", name="管理员", permissions=[
    "prearchive_rule_view", "prearchive_rule_edit", "prearchive_rule_approve",
    "prearchive_rule_publish"])


def test_full_lifecycle_draft_to_published():
    service, repo = _make_service()
    row = service.create_draft(_rule_dict(), ADMIN)
    assert row.status == "draft"

    result = service.validate("R-CENTER-1", "2026.09.02.1", ADMIN)
    assert result["valid"] is True
    assert repo.get_version("R-CENTER-1", "2026.09.02.1").status == "validated"

    service.approve("R-CENTER-1", "2026.09.02.1", ADMIN, reason="ok")
    publish = service.publish("R-CENTER-1", "2026.09.02.1", ADMIN)
    assert publish["pointer_version"] == 1
    pointer = repo.get_pointer("medical_record", "main", "R-CENTER-1")
    assert pointer.published_version == "2026.09.02.1"

    actions = [a.action for a in repo.list_audit(rule_key="R-CENTER-1")]
    assert actions[0] == "publish"                 # 时间倒序：最新在前
    assert actions[-1] == "create_draft"           # append-only：创建最早
    assert {"validate", "approve", "publish"} <= set(actions)


def test_illegal_transitions_rejected():
    service, repo = _make_service()
    service.create_draft(_rule_dict(), ADMIN)
    with pytest.raises(RuleConflictError):
        service.publish("R-CENTER-1", "2026.09.02.1", ADMIN)   # draft→publish 非法
    service.validate("R-CENTER-1", "2026.09.02.1", ADMIN)
    with pytest.raises(RuleConflictError):
        service.publish("R-CENTER-1", "2026.09.02.1", ADMIN)   # validated→publish 非法


def test_draft_edit_optimistic_lock():
    service, _ = _make_service()
    row = service.create_draft(_rule_dict(), ADMIN)
    updated = service.update_draft("R-CENTER-1", "2026.09.02.1",
                                   _rule_dict(message="改后消息"),
                                   expect_edit_version=row.draft_edit_version, actor=ADMIN)
    assert updated.draft_edit_version == 2
    with pytest.raises(RuleConflictError):
        service.update_draft("R-CENTER-1", "2026.09.02.1",
                             _rule_dict(message="旧锁写入"),
                             expect_edit_version=1, actor=ADMIN)


def test_published_content_immutable():
    service, _ = _make_service()
    service.create_draft(_rule_dict(), ADMIN)
    service.validate("R-CENTER-1", "2026.09.02.1", ADMIN)
    service.approve("R-CENTER-1", "2026.09.02.1", ADMIN)
    service.publish("R-CENTER-1", "2026.09.02.1", ADMIN)
    with pytest.raises(RuleConflictError):
        service.update_draft("R-CENTER-1", "2026.09.02.1",
                             _rule_dict(message="改已发布"),
                             expect_edit_version=1, actor=ADMIN)


def test_new_publish_retires_old_and_rollback():
    service, repo = _make_service()
    for version in ("2026.09.02.1", "2026.09.02.2"):
        service.create_draft(_rule_dict(version=version), ADMIN)
        service.validate("R-CENTER-1", version, ADMIN)
        service.approve("R-CENTER-1", version, ADMIN)
        service.publish("R-CENTER-1", version, ADMIN)
    old = repo.get_version("R-CENTER-1", "2026.09.02.1")
    assert old.status == "retired"                     # 旧版本让位
    pointer = repo.get_pointer("medical_record", "main", "R-CENTER-1")
    assert pointer.published_version == "2026.09.02.2"

    result = service.rollback("R-CENTER-1", "2026.09.02.1", ADMIN, reason="回滚验证")
    assert result["to"] == "2026.09.02.1"
    pointer2 = repo.get_pointer("medical_record", "main", "R-CENTER-1")
    assert pointer2.published_version == "2026.09.02.1"
    assert repo.get_version("R-CENTER-1", "2026.09.02.1").status == "published"
    rollback_audits = [a for a in repo.list_audit(rule_key="R-CENTER-1")
                       if a.action == "rollback"]
    assert rollback_audits and rollback_audits[0].version_from == "2026.09.02.2"


def test_separate_approver_flag():
    service, _ = _make_service(require_separate_approver=True)
    service.create_draft(_rule_dict(), ADMIN)
    service.validate("R-CENTER-1", "2026.09.02.1", ADMIN)
    with pytest.raises(RuleConflictError, match="separate"):
        service.approve("R-CENTER-1", "2026.09.02.1", ADMIN)
    other = Actor(id="admin-2", name="审批人", permissions=ADMIN.permissions)
    service.approve("R-CENTER-1", "2026.09.02.1", other)
    assert service.publish("R-CENTER-1", "2026.09.02.1", other)["rule_version"]


def test_paperless_fid_gate_blocks_deduct_publish():
    service, _ = _make_service()
    row = service.create_draft(
        _rule_dict(deduct_ref=2.0, mark_item_fid=None),
        ADMIN, origin="paperless_t_mark_item")
    # FID 未确认的草稿可以保存并校验通过
    assert service.validate("R-CENTER-1", row.rule_version, ADMIN)["valid"] is True
    # 但不得审批为扣分规则（039 §5.2 硬门）
    with pytest.raises(RuleConflictError, match="mark_item_fid"):
        service.approve("R-CENTER-1", row.rule_version, ADMIN)
    # 回填 FID（草稿仍在 draft→validated 迁移前可改：重新建草稿版本）
    row2 = service.create_draft(
        _rule_dict(version="2026.09.02.2", deduct_ref=2.0, mark_item_fid=60),
        ADMIN, origin="paperless_t_mark_item")
    service.validate("R-CENTER-1", row2.rule_version, ADMIN)
    service.approve("R-CENTER-1", row2.rule_version, ADMIN)
    assert service.publish("R-CENTER-1", row2.rule_version, ADMIN)["rule_version"]


def test_dangerous_content_rejected():
    problems = scan_dangerous_content({"rule_id": "R", "script": "print(1)"})
    assert any("forbidden key" in p for p in problems)
    problems2 = scan_dangerous_content({"rule_id": "R", "match": {"note": "eval(1)"}})
    assert any("dangerous pattern" in p for p in problems2)
    service, _ = _make_service()
    with pytest.raises(RuleValidationError):
        service.create_draft(_rule_dict(sql="SELECT * FROM dual"), ADMIN)


def test_diff_versions():
    service, _ = _make_service()
    for version, msg in (("2026.09.02.1", "消息一"), ("2026.09.02.2", "消息二")):
        service.create_draft(_rule_dict(version=version, message=msg), ADMIN)
    result = service.diff("R-CENTER-1", "2026.09.02.1", "2026.09.02.2")
    assert set(result["changed_keys"]) == {"message", "version"}
    message_change = next(c for c in result["changes"] if c["key"] == "message")
    assert message_change["from"] == "消息一"
    assert message_change["to"] == "消息二"


def test_unknown_rule_404_equivalent():
    service, _ = _make_service()
    with pytest.raises(RuleNotFoundError):
        service.validate("NOPE", "1", ADMIN)
