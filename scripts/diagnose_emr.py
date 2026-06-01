"""诊断 fetch_emr_documents_by_visits 为什么返回空"""
import sys
sys.path.insert(0, "/app")
from app.config import load_config
from app.services.config_parser import ConfigParser

cfg = load_config()
emr = ConfigParser.parse_emr_vastbase_config(cfg)

# 检查内容字段是否为 NULL
import psycopg2
conn = psycopg2.connect(
    host=emr["host"], port=int(emr["port"]), dbname=emr["database"],
    user=emr["username"], password=emr["password"], connect_timeout=10
)
cur = conn.cursor()

# 查看 content 字段
cur.execute("""
    SELECT patient_id, visit_id, progress_type_name, 
           length(progress_message) as content_len,
           progress_message IS NULL as content_null
    FROM jhemr.v_blws 
    WHERE patient_id='00018069' AND visit_id=3
    LIMIT 10
""")
print("=== v_blws 字段检查 ===")
for row in cur.fetchall():
    print(f"  pid={row[0]}, vid={row[1]}, type={row[2]}, content_len={row[3]}, null={row[4]}")

# 模拟实际查询 SQL（不带 kind filter）
cur.execute("""
    SELECT patient_id, visit_id, progress_type_name as type_name
    FROM jhemr.v_blws
    WHERE patient_id='00018069' AND visit_id=3
      AND progress_message IS NOT NULL
    LIMIT 10
""")
print("\n=== IS NOT NULL 过滤后 ===")
rows = cur.fetchall()
print(f"  count: {len(rows)}")
for row in rows:
    print(f"  {row}")

# 模拟病程 kind filter
cur.execute("""
    SELECT patient_id, visit_id, progress_type_name as type_name
    FROM jhemr.v_blws
    WHERE patient_id='00018069' AND visit_id=3
      AND progress_message IS NOT NULL
      AND COALESCE(progress_type_name,'') NOT LIKE '%%出院%%' 
      AND COALESCE(progress_title_name,'') NOT LIKE '%%出院%%' 
      AND COALESCE(progress_template_name,'') NOT LIKE '%%出院%%'
    LIMIT 10
""")
print("\n=== 病程过滤后 ===")
rows = cur.fetchall()
print(f"  count: {len(rows)}")
for row in rows:
    print(f"  {row}")

# 模拟出院 kind filter
cur.execute("""
    SELECT patient_id, visit_id, progress_type_name as type_name
    FROM jhemr.v_blws
    WHERE patient_id='00018069' AND visit_id=3
      AND progress_message IS NOT NULL
      AND (COALESCE(progress_type_name,'') LIKE '%%出院%%' 
           OR COALESCE(progress_title_name,'') LIKE '%%出院%%' 
           OR COALESCE(progress_template_name,'') LIKE '%%出院%%')
    LIMIT 10
""")
print("\n=== 出院过滤后 ===")
rows = cur.fetchall()
print(f"  count: {len(rows)}")
for row in rows:
    print(f"  {row}")

# 检查字段名
for field in ["patient_id_field", "visit_id_field", "content_field", "title_field", "type_field", "template_field"]:
    val = emr.get(field, "")
    print(f"\n  {field}: {val}")

# 直接测试 fetch_emr_documents_by_visits
print("\n=== 直接调用 fetch_emr_documents_by_visits ===")
from app.emr_vastbase_client import fetch_emr_documents_by_visits
try:
    result = fetch_emr_documents_by_visits(emr, [("00018069", "3")], document_kind="all")
    print(f"  all records: {len(result.get(('00018069','3'), []))}")
    result = fetch_emr_documents_by_visits(emr, [("00018069", "3")], document_kind="progress")
    print(f"  progress: {len(result.get(('00018069','3'), []))}")
    result = fetch_emr_documents_by_visits(emr, [("00018069", "3")], document_kind="discharge")
    print(f"  discharge: {len(result.get(('00018069','3'), []))}")
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback
    traceback.print_exc()

conn.close()
