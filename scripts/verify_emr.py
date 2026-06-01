"""验证 emr_vastbase 配置和查询函数"""
import sys
sys.path.insert(0, "/app")

from app.config import load_config
from app.services.config_parser import ConfigParser
from app.services.patient_visit_export_service import _query_progress_notes_from_emr, _query_discharge_records_from_emr

cfg = load_config()
emr_cfg = ConfigParser.parse_emr_vastbase_config(cfg)

print("=== 配置验证 ===")
print("enabled:", emr_cfg.get("enabled"))
print("host:", emr_cfg.get("host"))
print("database:", emr_cfg.get("database"))
print("use_for_export_progress:", emr_cfg.get("use_for_export_progress"))
print("use_for_export_discharge:", emr_cfg.get("use_for_export_discharge"))

print("\n=== 查询验证 ===")
keys = [("00018069", "3")]

progress = _query_progress_notes_from_emr(emr_cfg, keys)
discharge = _query_discharge_records_from_emr(emr_cfg, keys)

print("progress count:", len(progress.get(("00018069", "3"), [])))
print("discharge count:", len(discharge.get(("00018069", "3"), [])))
if discharge.get(("00018069", "3")):
    print("discharge sample:", discharge[("00018069", "3")][:1])
