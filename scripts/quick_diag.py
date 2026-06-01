"""快速诊断 - 只检查 SQL 不调用大函数"""
import sys
sys.path.insert(0, "/app")
from app.config import load_config
from app.services.config_parser import ConfigParser
import psycopg2

cfg = load_config()
emr = ConfigParser.parse_emr_vastbase_config(cfg)

conn = psycopg2.connect(
    host=emr["host"], port=int(emr["port"]), dbname=emr["database"],
    user=emr["username"], password=emr["password"], connect_timeout=10
)
cur = conn.cursor()

# 1. 检查 progress_message 是否为 NULL
cur.execute("SELECT count(*), count(progress_message) FROM jhemr.v_blws WHERE patient_id='00018069' AND visit_id=3")
r = cur.fetchone()
print(f"total={r[0]}, non-null-content={r[1]}")

# 2. 检查 kind filter
cur.execute("SELECT patient_id, visit_id, progress_type_name FROM jhemr.v_blws WHERE patient_id='00018069' AND visit_id=3 AND progress_message IS NOT NULL AND (COALESCE(progress_type_name,'') LIKE '%%出院%%' OR COALESCE(progress_title_name,'') LIKE '%%出院%%') LIMIT 5")
rows = cur.fetchall()
print(f"discharge-filtered: {len(rows)}")
for r in rows:
    print(f"  {r}")

# 3. 检查 fetch_emr_documents_by_visits 是否可调用
from app.emr_vastbase_client import fetch_emr_documents_by_visits
print("\nTesting fetch_emr_documents_by_visits kind=all...")
result = fetch_emr_documents_by_visits(emr, [("00018069", "3")], document_kind="all")
print(f"all: {len(result.get(('00018069','3'), []))} records")
for r in result.get(('00018069','3'), [])[:3]:
    print(f"  type={r.get('record_type','')}, title={r.get('record_name','')}")

conn.close()
