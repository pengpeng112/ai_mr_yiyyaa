"""只读诊断 Oracle 出院记录关联，不输出患者标识或临床正文。"""

import hashlib
import os

from app.config import load_config
from app.oracle_client import get_oracle_connection
from app.services.config_parser import ConfigParser
from app.services.patient_visit_export_service import _safe_text


patient_id = str(os.getenv("MED_AUDIT_DEBUG_PATIENT_ID", "") or "").strip()
if not patient_id:
    raise SystemExit("请通过 MED_AUDIT_DEBUG_PATIENT_ID 显式提供诊断患者 ID")

print("patient_sha256:", hashlib.sha256(patient_id.encode("utf-8")).hexdigest()[:12])
cfg = load_config()
oracle_cfg = ConfigParser.parse_oracle_config(cfg)
emr_cfg = ConfigParser.parse_emr_vastbase_config(cfg)
conn = get_oracle_connection(oracle_cfg)

try:
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 住院次数 FROM TEMP_PAT_VISIT_LIST WHERE 患者ID=:p",
            {"p": patient_id},
        )
        temp_visits = [_safe_text(row[0]) for row in cursor.fetchall()]
        cursor.execute(
            "SELECT 次数 FROM jhemr.V_cyJL "
            "WHERE 患者ID=:p AND 病历名称 LIKE '%出院记录%' AND RN=1",
            {"p": patient_id},
        )
        discharge_visits = [_safe_text(row[0]) for row in cursor.fetchall()]
        print("temp_visit_count:", len(temp_visits))
        print("discharge_visit_count:", len(discharge_visits))
        print("matching_visit_count:", len(set(temp_visits) & set(discharge_visits)))
        print("emr_enabled:", bool(emr_cfg.get("enabled")))
        print("emr_export_discharge_enabled:", bool(emr_cfg.get("use_for_export_discharge")))
    finally:
        cursor.close()
finally:
    conn.close()
