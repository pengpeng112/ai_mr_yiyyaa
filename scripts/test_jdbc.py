"""用 JDBC 驱动测试 Vastbase 连接"""
import os
os.environ["JAVA_HOME"] = r"C:\Program Files\AdoptOpenJDK\jdk-8.0.292.10-hotspot"
import jaydebeapi

jar = r'F:\python\前后端代码\ai_mrzk\oracle-client\linux\Vastbase-G100-2.15_pg-2026033109.jar'
url = 'jdbc:vastbase://10.10.8.177:5432/jhemr'
print("Connecting...")
conn = jaydebeapi.connect('com.vastbase.Driver', url, ['aizk_user', 'aizk_user@123'], jar)
print("JDBC OK!")

cur = conn.cursor()
cur.execute("SELECT patient_id, visit_id, progress_type_name FROM jhemr.v_blws WHERE patient_id='00018069' AND (progress_type_name LIKE '%%出院%%' OR progress_title_name LIKE '%%出院%%') LIMIT 5")
rows = cur.fetchall()
print(f"出院记录: {len(rows)}")
for r in rows:
    print(f"  {r}")

cur.execute("SELECT patient_id, visit_id, progress_type_name FROM jhemr.v_blws WHERE patient_id='00018069' AND progress_type_name NOT LIKE '%%出院%%' LIMIT 3")
rows = cur.fetchall()
print(f"病程记录(前3): {len(rows)}")
for r in rows:
    print(f"  {r}")

conn.close()
