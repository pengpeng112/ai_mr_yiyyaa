"""测试 data_source_loader 的 join_rules 行为。"""
import pytest

from app.schemas import AuditTypeConfig

pytest.importorskip("cryptography")

from app.services import data_source_loader


def _audit_type_with_join_rules(join_rules=None):
    def source(name, field_mapping=None, required=False):
        return {
            "type": "sql",
            "query_sql": f"SELECT '{name}' AS source_name",
            "field_mapping": field_mapping or {"patient_id": "患者ID", "visit_number": "次数"},
            "required": required,
        }

    cfg = {
        "code": "lab_exam_vs_progress_nursing",
        "name": "检验检查 vs 病程护理",
        "sources": {
            "patient": source("patient", {"patient_id": "患者ID", "visit_number": "次数", "patient_name": "患者姓名"}),
            "lab": source("lab", {"patient_id": "患者ID", "visit_number": "次数", "test_no": "检验单号"}),
            "exam": source("exam", {"patient_id": "患者ID", "visit_number": "次数", "exam_no": "检查号"}),
            "progress": source("progress"),
            "nursing": source("nursing"),
        },
        "group_key": ["patient_id", "visit_number", "audit_date"],
        "payload": {"builder": "lab_exam_structured_progress_nursing"},
        "dify": {"base_url": "http://example.com/v1"},
    }
    if join_rules:
        cfg["join_rules"] = join_rules
    return AuditTypeConfig.model_validate(cfg)


def test_join_rules_preserves_patient_source(monkeypatch):
    """join_rules 后 patient 源仍然存在。"""
    records_by_source = {
        "patient": [
            {"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "患者姓名": "张三"},
        ],
        "lab": [
            {"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检验单号": "LAB-001"},
        ],
        "exam": [
            {"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检查号": "EXAM-001"},
        ],
        "progress": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29"}],
        "nursing": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29"}],
    }

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        sql = source_cfg.get("query_sql", "")
        for source_name in records_by_source:
            if f"'{source_name}'" in sql:
                return records_by_source[source_name]
        return []

    join_rules = [{
        "name": "lab_to_exam",
        "left_source": "lab",
        "right_source": "exam",
        "join_keys": [{"left": "patient_id", "right": "患者ID"}, {"left": "visit_number", "right": "次数"}],
        "join_type": "inner",
    }]
    audit_type = _audit_type_with_join_rules(join_rules)
    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)

    bundles = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
    )

    assert len(bundles) == 1
    bundle = bundles[0]
    assert "patient" in bundle.sources, "join_rules 后 patient 源应保留"
    assert len(bundle.sources["patient"]) == 1
    assert bundle.sources["patient"][0]["患者姓名"] == "张三"


def test_join_rules_preserves_context_sources(monkeypatch):
    """join_rules 后 progress/nursing 上下文源仍然存在。"""
    records_by_source = {
        "patient": [],
        "lab": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检验单号": "LAB-001"}],
        "exam": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检查号": "EXAM-001"}],
        "progress": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "病程内容": "病程记录"}],
        "nursing": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "护理内容": "护理记录"}],
    }

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        sql = source_cfg.get("query_sql", "")
        for source_name in records_by_source:
            if f"'{source_name}'" in sql:
                return records_by_source[source_name]
        return []

    join_rules = [{
        "name": "lab_to_exam",
        "left_source": "lab",
        "right_source": "exam",
        "join_keys": [{"left": "patient_id", "right": "患者ID"}, {"left": "visit_number", "right": "次数"}],
        "join_type": "inner",
    }]
    audit_type = _audit_type_with_join_rules(join_rules)
    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)

    bundles = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
    )

    assert len(bundles) == 1
    bundle = bundles[0]
    assert "progress" in bundle.sources, "join_rules 后 progress 源应保留"
    assert "nursing" in bundle.sources, "join_rules 后 nursing 源应保留"


def test_join_rules_does_not_merge_across_patients(monkeypatch):
    """两个患者存在相同检查号时不应互相合并。"""
    records_by_source = {
        "patient": [
            {"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "患者姓名": "张三"},
            {"患者ID": "P002", "次数": "1", "audit_date": "2026-04-29", "患者姓名": "李四"},
        ],
        "lab": [
            {"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检验单号": "LAB-001"},
            {"患者ID": "P002", "次数": "1", "audit_date": "2026-04-29", "检验单号": "LAB-002"},
        ],
        "exam": [
            {"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检查号": "EXAM-SHARED"},
            {"患者ID": "P002", "次数": "1", "audit_date": "2026-04-29", "检查号": "EXAM-SHARED"},
        ],
        "progress": [],
        "nursing": [],
    }

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        sql = source_cfg.get("query_sql", "")
        for source_name in records_by_source:
            if f"'{source_name}'" in sql:
                return records_by_source[source_name]
        return []

    # 关联键只用检查号（两个患者共享），但应按 bundle 内 join，不跨患者
    join_rules = [{
        "name": "lab_to_exam",
        "left_source": "lab",
        "right_source": "exam",
        "join_keys": [{"left": "patient_id", "right": "患者ID"}, {"left": "visit_number", "right": "次数"}],
        "join_type": "inner",
    }]
    audit_type = _audit_type_with_join_rules(join_rules)
    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)

    bundles = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
    )

    bundle_ids = sorted([b.bundle_id for b in bundles])
    assert bundle_ids == ["P001::1::2026-04-29", "P002::1::2026-04-29"], "两个患者应各自独立"
    for bundle in bundles:
        # 每个 bundle 的 lab 和 exam 应只包含自己的记录
        lab_records = bundle.sources.get("lab", [])
        exam_records = bundle.sources.get("exam", [])
        pid = bundle.group_values["patient_id"]
        for rec in lab_records:
            assert rec.get("患者ID") == pid, f"lab 记录应属于 {pid}"
        for rec in exam_records:
            assert rec.get("患者ID") == pid, f"exam 记录应属于 {pid}"


def test_inner_join_removes_unmatched(monkeypatch):
    """内连接时，未匹配的左侧记录应被移除。"""
    records_by_source = {
        "patient": [],
        "lab": [
            {"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检验单号": "LAB-001"},
            {"患者ID": "P001", "次数": "2", "audit_date": "2026-04-29", "检验单号": "LAB-NO-MATCH"},
        ],
        "exam": [
            {"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检查号": "EXAM-001"},
        ],
        "progress": [],
        "nursing": [],
    }

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        sql = source_cfg.get("query_sql", "")
        for source_name in records_by_source:
            if f"'{source_name}'" in sql:
                return records_by_source[source_name]
        return []

    # 关联键包含 visit_number，LAB-NO-MATCH 的次数=2 不匹配 exam 的次数=1
    join_rules = [{
        "name": "lab_to_exam",
        "left_source": "lab",
        "right_source": "exam",
        "join_keys": [{"left": "patient_id", "right": "患者ID"}, {"left": "visit_number", "right": "次数"}],
        "join_type": "inner",
    }]
    audit_type = _audit_type_with_join_rules(join_rules)
    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)

    bundles = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
    )

    # 次数=2 的 lab 记录不匹配 exam（次数=1），内连接后左侧记录应被清空
    assert len(bundles) == 1
    bundle_by_visit = {b.group_values["visit_number"]: b for b in bundles}
    # visit_number=1 的 bundle 匹配成功，lab 记录保留
    assert len(bundle_by_visit["1"].sources.get("lab", [])) == 1
    assert bundle_by_visit["1"].sources["lab"][0].get("检验单号") == "LAB-001"
    # visit_number=2 的 bundle 无 exam 数据，内连接后无 anchor 源并被过滤
    assert "2" not in bundle_by_visit


def test_left_join_preserves_unmatched(monkeypatch):
    """左连接时，未匹配的左侧记录应保留。"""
    records_by_source = {
        "patient": [],
        "lab": [
            {"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检验单号": "LAB-001"},
            {"患者ID": "P001", "次数": "2", "audit_date": "2026-04-29", "检验单号": "LAB-NO-MATCH"},
        ],
        "exam": [
            {"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检查号": "EXAM-001"},
        ],
        "progress": [],
        "nursing": [],
    }

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        sql = source_cfg.get("query_sql", "")
        for source_name in records_by_source:
            if f"'{source_name}'" in sql:
                return records_by_source[source_name]
        return []

    join_rules = [{
        "name": "lab_to_exam",
        "left_source": "lab",
        "right_source": "exam",
        "join_keys": [{"left": "patient_id", "right": "患者ID"}, {"left": "visit_number", "right": "次数"}],
        "join_type": "left",
    }]
    audit_type = _audit_type_with_join_rules(join_rules)
    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)

    bundles = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
    )

    # 左连接时，visit_number=2 的 lab 记录虽然不匹配 exam，但仍应保留
    assert len(bundles) == 2
    bundle_by_visit = {b.group_values["visit_number"]: b for b in bundles}
    # visit_number=1 的 bundle 匹配成功，lab 记录保留
    assert len(bundle_by_visit["1"].sources.get("lab", [])) == 1
    # visit_number=2 的 bundle 不匹配，但左连接后 lab 记录仍保留
    assert len(bundle_by_visit["2"].sources.get("lab", [])) == 1
    assert bundle_by_visit["2"].sources["lab"][0].get("检验单号") == "LAB-NO-MATCH"


def test_no_join_rules_unchanged_behavior(monkeypatch):
    """不配置 join_rules 时原行为不变。"""
    records_by_source = {
        "patient": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "患者姓名": "张三"}],
        "lab": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检验单号": "LAB-001"}],
        "exam": [],
        "progress": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29"}],
        "nursing": [],
    }

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        sql = source_cfg.get("query_sql", "")
        for source_name in records_by_source:
            if f"'{source_name}'" in sql:
                return records_by_source[source_name]
        return []

    audit_type = _audit_type_with_join_rules(None)
    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)

    bundles = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
    )

    assert len(bundles) == 1
    bundle = bundles[0]
    assert "patient" in bundle.sources
    assert "progress" in bundle.sources
    assert bundle.sources["patient"][0]["患者姓名"] == "张三"


def test_inner_join_missing_right_source_clears_left(monkeypatch):
    """内连接时，右侧源完全不存在应清空左侧源。"""
    records_by_source = {
        "patient": [],
        "lab": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检验单号": "LAB-001"}],
        "exam": [],
        "progress": [],
        "nursing": [],
    }

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        sql = source_cfg.get("query_sql", "")
        for source_name in records_by_source:
            if f"'{source_name}'" in sql:
                return records_by_source[source_name]
        return []

    # exam 源完全为空，但 inner join 规则要求匹配
    join_rules = [{
        "name": "lab_to_exam",
        "left_source": "lab",
        "right_source": "exam",
        "join_keys": [{"left": "patient_id", "right": "患者ID"}, {"left": "visit_number", "right": "次数"}],
        "join_type": "inner",
    }]
    audit_type = _audit_type_with_join_rules(join_rules)
    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)

    bundles = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
    )

    # exam 为空，内连接后 lab 被清空，且无 anchor 源的 bundle 应被过滤
    assert len(bundles) == 0


def test_left_join_missing_right_source_preserves_left(monkeypatch):
    """左连接时，右侧源完全不存在应保留左侧源。"""
    records_by_source = {
        "patient": [],
        "lab": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检验单号": "LAB-001"}],
        "exam": [],
        "progress": [],
        "nursing": [],
    }

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        sql = source_cfg.get("query_sql", "")
        for source_name in records_by_source:
            if f"'{source_name}'" in sql:
                return records_by_source[source_name]
        return []

    join_rules = [{
        "name": "lab_to_exam",
        "left_source": "lab",
        "right_source": "exam",
        "join_keys": [{"left": "patient_id", "right": "患者ID"}, {"left": "visit_number", "right": "次数"}],
        "join_type": "left",
    }]
    audit_type = _audit_type_with_join_rules(join_rules)
    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)

    bundles = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
    )

    # exam 为空，左连接后 lab 应保留
    assert len(bundles) == 1
    assert len(bundles[0].sources.get("lab", [])) == 1


def test_right_fields_do_not_overwrite_left_identity(monkeypatch):
    """右侧字段不应覆盖左侧身份字段。"""
    records_by_source = {
        "patient": [],
        "lab": [
            {"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检验单号": "LAB-001", "患者姓名": "张三"},
        ],
        "exam": [
            {"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检查号": "EXAM-001", "患者姓名": "李四"},
        ],
        "progress": [],
        "nursing": [],
    }

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        sql = source_cfg.get("query_sql", "")
        for source_name in records_by_source:
            if f"'{source_name}'" in sql:
                return records_by_source[source_name]
        return []

    join_rules = [{
        "name": "lab_to_exam",
        "left_source": "lab",
        "right_source": "exam",
        "join_keys": [{"left": "patient_id", "right": "患者ID"}, {"left": "visit_number", "right": "次数"}],
        "join_type": "inner",
    }]
    audit_type = _audit_type_with_join_rules(join_rules)
    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)

    bundles = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
    )

    assert len(bundles) == 1
    lab_records = bundles[0].sources.get("lab", [])
    assert len(lab_records) == 1
    # 左侧的患者姓名应保留，不被右侧覆盖
    assert lab_records[0].get("患者姓名") == "张三"
    # 右侧冲突字段应以 exam.患者姓名 保留
    assert lab_records[0].get("exam.患者姓名") == "李四"
    # 右侧非冲突字段应正常合并
    assert lab_records[0].get("检查号") == "EXAM-001"
