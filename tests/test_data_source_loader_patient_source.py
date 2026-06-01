import pytest

from app.schemas import AuditTypeConfig

pytest.importorskip("cryptography")

from app.services import data_source_loader


def _audit_type_with_patient_source() -> AuditTypeConfig:
    def source(name: str, field_mapping: dict | None = None) -> dict:
        return {
            "type": "sql",
            "query_sql": f"SELECT '{name}' AS source_name",
            "field_mapping": field_mapping or {"patient_id": "患者ID", "visit_number": "次数"},
            "required": False,
        }

    return AuditTypeConfig.model_validate(
        {
            "code": "lab_exam_vs_progress_nursing",
            "name": "检验检查 vs 病程护理",
            "sources": {
                "patient": source(
                    "patient",
                    {
                        "patient_id": "患者ID",
                        "visit_number": "次数",
                        "patient_name": "患者姓名",
                        "dept": "所在科室名称",
                        "admission_date": "入院日期",
                    },
                ),
                "lab": source("lab"),
                "exam": source("exam"),
                "progress": source("progress"),
                "nursing": source("nursing"),
            },
            "group_key": ["patient_id", "visit_number", "audit_date"],
            "payload": {
                "builder": "lab_exam_structured_progress_nursing",
                "max_lab_items": 30,
                "max_exam_reports": 10,
                "progress_followup_days": 1,
            },
            "dify": {"base_url": "http://example.com/v1"},
        }
    )


def test_patient_source_attaches_to_existing_bundle_only(monkeypatch):
    records_by_source = {
        "patient": [
            {"患者ID": "P001", "次数": "1", "患者姓名": "张三", "所在科室名称": "神经内科", "入院日期": "2026-04-20"},
            {"患者ID": "P002", "次数": "1", "患者姓名": "李四", "所在科室名称": "心内科", "入院日期": "2026-04-21"},
        ],
        "lab": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "test_no": "LAB-001"}],
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

    audit_type = _audit_type_with_patient_source()
    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)

    bundles = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
    )

    assert [bundle.bundle_id for bundle in bundles] == ["P001::1::2026-04-29"]
    assert bundles[0].primary_source == "lab"
    assert bundles[0].sources["patient"][0]["患者姓名"] == "张三"
    assert all(record.get("患者ID") != "P002" for record in bundles[0].sources["patient"])


def test_lab_exam_context_sources_do_not_create_push_bundles(monkeypatch):
    records_by_source = {
        "patient": [],
        "lab": [],
        "exam": [],
        "progress": [{"患者ID": "P002", "次数": "1", "audit_date": "2026-04-29", "病程内容": "仅病程"}],
        "nursing": [{"患者ID": "P003", "次数": "1", "audit_date": "2026-04-29", "护理内容": "仅护理"}],
    }

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        sql = source_cfg.get("query_sql", "")
        for source_name in records_by_source:
            if f"'{source_name}'" in sql:
                return records_by_source[source_name]
        return []

    audit_type = _audit_type_with_patient_source()
    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)

    bundles = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
    )

    assert bundles == []


def test_lab_exam_context_sources_attach_to_lab_exam_bundle(monkeypatch):
    records_by_source = {
        "patient": [],
        "lab": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "test_no": "LAB-001"}],
        "exam": [],
        "progress": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "病程内容": "病程响应"}],
        "nursing": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "护理内容": "护理记录"}],
    }

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        sql = source_cfg.get("query_sql", "")
        for source_name in records_by_source:
            if f"'{source_name}'" in sql:
                return records_by_source[source_name]
        return []

    audit_type = _audit_type_with_patient_source()
    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)

    bundles = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
    )

    assert [bundle.bundle_id for bundle in bundles] == ["P001::1::2026-04-29"]
    assert len(bundles[0].sources.get("lab", [])) == 1
    assert len(bundles[0].sources.get("progress", [])) == 1
    assert len(bundles[0].sources.get("nursing", [])) == 1
