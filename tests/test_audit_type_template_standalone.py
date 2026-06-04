import json
from pathlib import Path


def test_progress_vs_nursing_template_uses_bottom_table_sql():
    config = json.loads(Path("config/config.json.template").read_text(encoding="utf-8"))
    audit_type = next(item for item in config["audit_types"] if item.get("code") == "progress_vs_nursing")
    sql = audit_type["sources"]["primary"]["query_sql"]

    assert (audit_type.get("payload") or {}).get("builder") == "legacy_progress_nursing"
    assert "{dept_filter}" in sql
    assert "jhemr.v_zybr a" in sql.lower()
    assert "ydhl.v_hljl" not in sql.lower()
    assert "ydhl.mcs_doc_form_records" in sql.lower()
    assert "TO_DATE(:query_date" in sql
    assert "TO_CHAR(b.病历标题时间" not in sql
