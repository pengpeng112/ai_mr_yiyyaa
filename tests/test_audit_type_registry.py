from app.services.audit_type_registry import AuditTypeRegistry


def test_registry_loads_default_seed_when_missing():
    registry = AuditTypeRegistry(
        {
            "data_source": {"type": "oracle"},
            "oracle": {"query_sql": "SELECT 1", "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"}},
            "dify": {"base_url": "http://example.com/v1", "workflow_input_variable": "mr_txt", "workflow_output_key": "aa"},
            "audit_types": [],
        }
    )

    item = registry.get("progress_vs_nursing")
    assert item.code == "progress_vs_nursing"
    assert item.payload["builder"] == "legacy_progress_nursing"


def test_registry_validate_for_save_rejects_bad_jsonpath():
    registry = AuditTypeRegistry()
    payload = registry.get("progress_vs_nursing").model_copy(deep=True)
    payload.display.summary_blocks[0].path = "$.["
    try:
        registry.validate_for_save(payload, existing_code=payload.code)
    except Exception as exc:
        assert "invalid" in str(exc).lower() or "parse" in str(type(exc)).lower()
    else:
        raise AssertionError("expected invalid jsonpath to raise")


def test_prepare_for_save_encrypts_plain_api_key_and_removes_plaintext():
    registry = AuditTypeRegistry()
    payload = registry.get("progress_vs_nursing").model_copy(deep=True)
    payload.dify.api_key = "plain-secret"
    payload.dify.api_key_enc = None

    prepared = registry._prepare_for_save(payload, existing_code=payload.code)

    assert prepared["dify"]["api_key_enc"]
    assert prepared["dify"]["api_key_enc"] != "plain-secret"
    assert "api_key" not in prepared["dify"]


def test_prepare_for_save_preserves_existing_encrypted_key_when_api_key_blank():
    registry = AuditTypeRegistry(
        {
            "data_source": {"type": "oracle"},
            "oracle": {"query_sql": "SELECT 1", "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"}},
            "dify": {"base_url": "http://example.com/v1", "workflow_input_variable": "mr_txt", "workflow_output_key": "aa"},
            "audit_types": [
                {
                    "code": "custom_audit",
                    "name": "Custom Audit",
                    "enabled": True,
                    "sort_order": 10,
                    "default_for_schedule": False,
                    "sources": {"primary": {"type": "sql", "query_sql": "SELECT 1", "field_mapping": {}, "required": True}},
                    "group_key": ["patient_id", "visit_number"],
                    "payload": {"builder": "generic_multi_source"},
                    "dify": {
                        "base_url": "http://example.com/v1",
                        "api_key_enc": "encrypted-old",
                        "workflow_input_variable": "mr_txt",
                        "workflow_output_key": "aa",
                        "user_identifier": "x",
                        "timeout_seconds": 30,
                        "extra_inputs": {},
                        "targets": [],
                    },
                    "response": {},
                    "display": {"summary_blocks": [], "detail_blocks": []},
                }
            ],
        }
    )
    payload = registry.get("custom_audit").model_copy(deep=True)
    payload.dify.api_key = ""
    payload.dify.api_key_enc = "***"

    prepared = registry._prepare_for_save(payload, existing_code="custom_audit")

    assert prepared["dify"]["api_key_enc"] == "encrypted-old"
    assert "api_key" not in prepared["dify"]
