"""只读诊断 Vastbase 病历数量，不输出患者标识或病历正文。"""

import hashlib
import os

from app.config import load_config
from app.emr_vastbase_client import get_emr_vastbase_connection
from app.services.config_parser import ConfigParser


patient_id = str(os.getenv("MED_AUDIT_DEBUG_PATIENT_ID", "") or "").strip()
if not patient_id:
    raise SystemExit("请通过 MED_AUDIT_DEBUG_PATIENT_ID 显式提供诊断患者 ID")

fingerprint = hashlib.sha256(patient_id.encode("utf-8")).hexdigest()[:12]
cfg = load_config()
emr_cfg = ConfigParser.parse_emr_vastbase_config(cfg)

print("enabled:", bool(emr_cfg.get("enabled")))
print("use_for_export_progress:", bool(emr_cfg.get("use_for_export_progress")))
print("use_for_export_discharge:", bool(emr_cfg.get("use_for_export_discharge")))
print("patient_sha256:", fingerprint)

conn = get_emr_vastbase_connection(emr_cfg)
try:
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT count(*) FROM jhemr.v_blws "
            "WHERE patient_id=%s AND progress_template_name = '出院记录'",
            (patient_id,),
        )
        print("discharge_count:", int(cur.fetchone()[0] or 0))
        cur.execute(
            "SELECT count(*) FROM jhemr.v_blws "
            "WHERE patient_id=%s AND progress_template_name LIKE '%病程%'",
            (patient_id,),
        )
        print("progress_count:", int(cur.fetchone()[0] or 0))
    finally:
        cur.close()
finally:
    conn.close()
