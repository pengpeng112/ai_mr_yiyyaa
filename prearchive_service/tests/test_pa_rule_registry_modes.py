# -*- coding: utf-8 -*-
"""file/compare/registry 三模式 + 文件导入 + 零差异 golden 测试（039 T2 / §12.1 Golden parity、Modes）。"""

import json
from pathlib import Path

import pytest

from prearchive.engine import RuleEngine
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.rule_repository import RuleRepository
from prearchive.rule_service import Actor, RuleService, compare_outputs
from prearchive.rules import load_rules_multi
from prearchive.rules import validate_rule

from helpers import doc, make_ctx, dt, surgery

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"
PATHS = [RULES_DIR / "example_rules.json", RULES_DIR / "system_push_rules.json"]
ADMIN = Actor(id="importer", name="导入器")


@pytest.fixture()
def service():
    repo = RuleRepository(build_session_factory(build_sqlite_engine(":memory:")))
    return RuleService(repo), repo


def test_import_dry_run_reports_without_writing(service):
    svc, repo = service
    report = svc.import_files([str(p) for p in PATHS], apply=False, actor=ADMIN)
    assert report["apply"] is False
    assert report["created"] == 14
    rows, total = repo.list_rules()
    assert total == 0 and rows == []          # dry-run 未落库


def test_import_apply_then_idempotent(service):
    svc, repo = service
    first = svc.import_files([str(p) for p in PATHS], apply=True, actor=ADMIN)
    assert first["created"] == 14 and not first["errors"]
    second = svc.import_files([str(p) for p in PATHS], apply=True, actor=ADMIN)
    assert second["created"] == 0 and second["skipped"] == 14


def test_rule_files_unchanged_by_import(service, tmp_path):
    """导入不得改写原 JSON 文件（039 §5.5 约束 3）。"""
    svc, _ = service
    import hashlib
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in PATHS}
    svc.import_files([str(p) for p in PATHS], apply=True, actor=ADMIN)
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in PATHS}
    assert before == after


def _golden_contexts():
    """覆盖四类判定器的合成上下文集合（全虚构数据）。"""
    return [
        # 1: 手术患者缺手术安全核查表（missing_doc fail）
        make_ctx(
            surgeries=[surgery("阑尾切除术", dt("2026-08-22 09:30:00"))],
            documents=[doc("jhemr_blws", "术后首次病程记录", dt("2026-08-22 15:00:00"))],
        ),
        # 2: 齐全文书（pass 基线）
        make_ctx(
            surgeries=[surgery("阑尾切除术", dt("2026-08-22 09:30:00"))],
            documents=[
                doc("jhemr_blws", "术后首次病程记录", dt("2026-08-22 15:00:00")),
                doc("sm_itf", "手术安全核查表", dt("2026-08-22 09:40:00")),
                doc("sm_itf", "手术清点记录", dt("2026-08-22 09:45:00")),
            ],
        ),
        # 3: 空上下文（水位/豁免负例路径）
        make_ctx(documents=[]),
    ]


def test_golden_parity_file_vs_registry(service):
    """导入当前两轨正式规则后，file 与 registry 的 fixture 结果逐字段零差异。"""
    svc, repo = service
    svc.import_files([str(p) for p in PATHS], apply=True, actor=ADMIN)

    file_specs, file_version = load_rules_multi([str(p) for p in PATHS])
    effective = svc.effective_rules("registry", [str(p) for p in PATHS])
    reg_specs = effective["specs"]

    assert len(file_specs) == len(reg_specs) == 14
    # 逐条规则内容等价（canonical dict 相同 → 同一 RuleSpec 行为）
    file_by_id = {s.rule_id: s for s in file_specs}
    reg_by_id = {s.rule_id: s for s in reg_specs}
    assert set(file_by_id) == set(reg_by_id)
    for rule_id in file_by_id:
        f, r = file_by_id[rule_id], reg_by_id[rule_id]
        assert f.rule_type == r.rule_type
        assert f.severity == r.severity
        assert f.version == r.version
        assert f.mark_item_fid == r.mark_item_fid
        assert f.message == r.message
        assert f.deduct_ref == r.deduct_ref
        assert f.dept_codes == r.dept_codes
        assert f.enabled == r.enabled

    # 引擎层零差异：同一上下文集合 problem 逐字段一致
    file_engine = RuleEngine(file_specs, rule_version=file_version)
    reg_engine = RuleEngine(reg_specs, rule_version=effective["rule_version"])
    for ctx in _golden_contexts():
        file_output = file_engine.evaluate(ctx)
        reg_output = reg_engine.evaluate(ctx)
        diffs = compare_outputs(file_output, reg_output)
        assert diffs == [], f"registry drift on patient {ctx.patient_id}: {diffs}"
        assert [p["rule_id"] for p in file_output.problems] == \
               [p["rule_id"] for p in reg_output.problems]


def test_registry_mode_reads_only_published(service):
    """registry 运行时只读指针→published；draft 不入运行时。"""
    svc, repo = service
    svc.import_files([str(p) for p in PATHS], apply=True, actor=ADMIN)
    # 造一条 draft（不发布）
    svc.create_draft({
        "rule_id": "R-DRAFT-ONLY", "name": "草稿", "message": "m",
        "type": "empty_field", "fields": ["过敏史"], "version": "2026.09.03.1",
    }, ADMIN)
    effective = svc.effective_rules("registry", [str(p) for p in PATHS])
    ids = [s.rule_id for s in effective["specs"]]
    assert "R-DRAFT-ONLY" not in ids
    assert len(ids) == 14


def test_compare_mode_never_changes_business_result(service):
    svc, repo = service
    svc.import_files([str(p) for p in PATHS], apply=True, actor=ADMIN)
    effective = svc.effective_rules("compare", [str(p) for p in PATHS])
    # compare 模式 specs= file 结果（业务口径）
    file_specs, file_version = load_rules_multi([str(p) for p in PATHS])
    assert len(effective["specs"]) == len(file_specs)
    ctx = _golden_contexts()[0]
    file_engine = RuleEngine(file_specs, rule_version=file_version)
    assert [p["rule_id"] for p in file_engine.evaluate(ctx).problems] == \
           [p["rule_id"] for p in RuleEngine(effective["specs"],
                                             rule_version=file_version).evaluate(ctx).problems]


def test_invalid_mode_rejected(service):
    svc, _ = service
    with pytest.raises(ValueError):
        svc.effective_rules("registry-lite", [str(p) for p in PATHS])


def test_registry_reruns_published_content_validation(service):
    """已发布内容被外部篡改（DB 直改）时 registry 启动二次校验拒绝。"""
    svc, repo = service
    svc.import_files([str(p) for p in PATHS], apply=True, actor=ADMIN)
    rows = repo.published_rules()
    assert rows
    tampered = rows[0]
    from prearchive.rule_models import canonical_json, content_sha256
    # 模拟 DB 直改：改内容但状态仍 published → 二次校验抛错
    with repo.session_factory() as session:
        row = session.get(type(tampered), tampered.id)
        broken = json.loads(row.content_json)
        broken["type"] = "not-a-type"
        row.content_json = canonical_json(broken)
        row.content_sha256 = content_sha256(broken)
        session.commit()
    from prearchive.rules import RuleValidationError
    with pytest.raises(RuleValidationError):
        svc.effective_rules("registry", [str(p) for p in PATHS])
