from app.schemas import AuditTypeConfig
from app.services.data_source_loader import PatientBundle
from app.services.payload_composer import compose


def test_compose_generic_multi_source_builds_text_template():
    audit_type = AuditTypeConfig.model_validate(
        {
            "code": "labexam_vs_progress",
            "name": "检验检查 vs 病程",
            "sources": {
                "primary": {"type": "sql", "query_sql": "SELECT 1", "field_mapping": {"patient_id": "患者ID", "visit_number": "次数", "patient_name": "患者姓名"}},
                "reference": {"type": "sql", "query_sql": "SELECT 1", "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"}},
            },
            "payload": {
                "builder": "generic_multi_source",
                "text_template": "[检验]\n{primary}\n\n[病程]\n{reference}",
            },
            "dify": {"base_url": "http://example.com/v1"},
        }
    )
    bundle = PatientBundle(
        bundle_id="p001::1",
        group_values={"patient_id": "p001", "visit_number": "1"},
        sources={
            "primary": [{"患者ID": "p001", "次数": "1", "患者姓名": "张三", "项目": "白细胞", "结果": "高"}],
            "reference": [{"患者ID": "p001", "次数": "1", "病程内容": "已记录白细胞升高"}],
        },
        source_field_mappings={
            "primary": {"patient_id": "患者ID", "visit_number": "次数", "patient_name": "患者姓名"},
            "reference": {"patient_id": "患者ID", "visit_number": "次数"},
        },
        primary_source="primary",
        query_date="2026-04-17",
    )

    payload, mr_text = compose(audit_type, bundle, "2026-04-17")

    assert payload["audit_type_code"] == "labexam_vs_progress"
    assert payload["patient_info"]["patient_name"] == "张三"
    assert "mr_text" in payload
    assert "mr_txt" not in payload
    assert payload["mr_text"] == mr_text
    assert "白细胞" in mr_text
    assert "已记录白细胞升高" in mr_text
