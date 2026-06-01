"""写入 emr_vastbase 配置到 /app/config/config.json"""
import json
import sys
sys.path.insert(0, "/app")

from app.config import encrypt_value

cfg_path = "/app/config/config.json"

with open(cfg_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)

cfg["emr_vastbase"] = {
    "enabled": True,
    "host": "10.10.8.177",
    "port": 5432,
    "database": "jhemr",
    "username": "aizk_user",
    "password_enc": encrypt_value("aizk_user@123"),
    "schema": "jhemr",
    "view": "v_blws",
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
    "fallback_to_oracle": True
}

with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

print("emr_vastbase 配置已写入")

# 验证
with open(cfg_path, "r", encoding="utf-8") as f:
    verify = json.load(f)
print("验证 - emr_vastbase in cfg:", "emr_vastbase" in verify)
print("验证 - enabled:", verify.get("emr_vastbase", {}).get("enabled"))
print("验证 - host:", verify.get("emr_vastbase", {}).get("host"))
