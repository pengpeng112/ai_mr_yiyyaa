"""验证海量库连接和出院/病程记录"""
import sys
sys.path.insert(0, ".")
from app.config import load_config
from app.services.config_parser import ConfigParser
from app.emr_vastbase_client import get_emr_vastbase_connection

cfg = load_config()
emr_cfg = ConfigParser.parse_emr_vastbase_config(cfg)
print("enabled:", emr_cfg.get("enabled"))
print("host:", emr_cfg.get("host"))
print("use_for_export_progress:", emr_cfg.get("use_for_export_progress"))
print("use_for_export_discharge:", emr_cfg.get("use_for_export_discharge"))

conn = get_emr_vastbase_connection(emr_cfg)
cur = conn.cursor()

cur.execute("SELECT patient_id, visit_id, progress_type_name, progress_title_name FROM jhemr.v_blws WHERE patient_id='00018069' AND (progress_type_name LIKE '%%出院%%' OR progress_title_name LIKE '%%出院%%')")
rows = cur.fetchall()
print(f"\n出院记录数: {len(rows)}")
for r in rows:
    print(f"  patient_id={r[0]}, visit_id={r[1]}, type={r[2]}, title={r[3]}")

cur.execute("SELECT patient_id, visit_id, progress_type_name FROM jhemr.v_blws WHERE patient_id='00018069' AND progress_type_name NOT LIKE '%%出院%%' LIMIT 5")
rows = cur.fetchall()
print(f"\n病程记录(前5): {len(rows)}")
for r in rows:
    print(f"  patient_id={r[0]}, visit_id={r[1]}, type={r[2]}")

conn.close()
