import json
from pathlib import Path

from app.schemas import AuditTypeConfig
from app.services.audit_type_contracts import (
    DEPRECATED_AUDIT_TYPE_CODES,
    OFFICIAL_AUDIT_TYPE_CODES,
    audit_type_closure_errors,
)


def test_config_template_contains_safe_official_six_type_closure():
    template_path = Path("config/config.json.template")
    raw_text = template_path.read_text(encoding="utf-8")
    config = json.loads(raw_text)
    audit_types = config.get("audit_types") or []
    codes = tuple(str(item.get("code") or "") for item in audit_types)

    assert codes == OFFICIAL_AUDIT_TYPE_CODES
    assert not (set(codes) & DEPRECATED_AUDIT_TYPE_CODES)
    assert audit_type_closure_errors(config) == []
    assert "??" not in raw_text

    expected_builders = {
        "legacy_progress_nursing",
        "lab_exam_structured_progress_nursing",
        "frontpage_surgery_first_progress",
        "admission_first_progress",
        "surgery_chain",
        "discharge_frontpage",
    }
    for raw in audit_types:
        parsed = AuditTypeConfig.model_validate(raw)
        assert parsed.enabled is False
        assert parsed.default_for_schedule is False
        assert parsed.payload.get("requires_configuration") is True
        assert str(parsed.payload.get("builder") or "") in expected_builders

    for section in ("scheduler", "scheduler_daily", "scheduler_discharge"):
        assert config[section]["enabled"] is False
        assert config[section]["audit_type_codes"] == []
