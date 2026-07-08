"""Write emr_vastbase config to /app/config/config.json.

Connection values are read from environment variables to avoid storing
credentials in source.
"""
import json
import os
import sys

sys.path.insert(0, "/app")

from app.config import encrypt_value


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise SystemExit(f"Set {name} before running this script.")
    return value


cfg_path = "/app/config/config.json"

with open(cfg_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)

cfg["emr_vastbase"] = {
    "enabled": True,
    "host": env("MED_AUDIT_VASTBASE_HOST"),
    "port": int(env("MED_AUDIT_VASTBASE_PORT", "5432")),
    "database": env("MED_AUDIT_VASTBASE_DB"),
    "username": env("MED_AUDIT_VASTBASE_USER"),
    "password_enc": encrypt_value(env("MED_AUDIT_VASTBASE_PASSWORD")),
    "schema": env("MED_AUDIT_VASTBASE_SCHEMA", "jhemr"),
    "view": env("MED_AUDIT_VASTBASE_VIEW", "v_blws"),
    "patient_id_field": "patient_id",
    "visit_id_field": "visit_id",
    "dept_field": "dept_name",
    "content_field": "progress_message",
    "title_field": "progress_title_name",
    "type_field": "progress_type_name",
    "template_field": "progress_template_name",
    "record_time_field": "record_time_format",
    "finish_time_field": "finish_time_format",
    "first_save_time_field": "first_save_time",
    "create_date_field": "create_date",
    "doctor_field": "doctor_name",
    "status_field": "progress_status",
    "connect_timeout_seconds": 10,
    "statement_timeout_ms": 60000,
    "max_records": 50000,
    "batch_size": 500,
    "use_for_export_progress": True,
    "use_for_export_discharge": True,
    "fallback_to_oracle": True,
}

with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

print("emr_vastbase config written")

with open(cfg_path, "r", encoding="utf-8") as f:
    verify = json.load(f)
print("verify - emr_vastbase in cfg:", "emr_vastbase" in verify)
print("verify - enabled:", verify.get("emr_vastbase", {}).get("enabled"))
print("verify - host:", verify.get("emr_vastbase", {}).get("host"))
