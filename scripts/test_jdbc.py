"""Test Vastbase JDBC connection using environment-provided credentials."""
import os

import jaydebeapi

os.environ.setdefault("JAVA_HOME", r"C:\Program Files\AdoptOpenJDK\jdk-8.0.292.10-hotspot")


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise SystemExit(f"Set {name} before running this diagnostic script.")
    return value


jar = env("MED_AUDIT_VASTBASE_JDBC_JAR", r"F:\python\前后端代码\ai_mrzk\oracle-client\linux\Vastbase-G100-2.15_pg-2026033109.jar")
url = env("MED_AUDIT_VASTBASE_JDBC_URL")
user = env("MED_AUDIT_VASTBASE_USER")
password = env("MED_AUDIT_VASTBASE_PASSWORD")

print("Connecting...")
conn = jaydebeapi.connect("com.vastbase.Driver", url, [user, password], jar)
print("JDBC OK!")

cur = conn.cursor()
cur.execute(
    "SELECT patient_id, visit_id, progress_type_name FROM jhemr.v_blws "
    "WHERE patient_id='00018069' AND (progress_type_name LIKE '%%出院%%' "
    "OR progress_title_name LIKE '%%出院%%') LIMIT 5"
)
rows = cur.fetchall()
print(f"出院记录: {len(rows)}")
for row in rows:
    print(f"  {row}")

cur.execute(
    "SELECT patient_id, visit_id, progress_type_name FROM jhemr.v_blws "
    "WHERE patient_id='00018069' AND progress_type_name NOT LIKE '%%出院%%' LIMIT 3"
)
rows = cur.fetchall()
print(f"病程记录(前3): {len(rows)}")
for row in rows:
    print(f"  {row}")

conn.close()
