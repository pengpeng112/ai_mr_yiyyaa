"""验证配置和简单查询"""
import sys
sys.path.insert(0, "/app")
from app.config import load_config
from app.services.config_parser import ConfigParser

cfg = load_config()
e = ConfigParser.parse_emr_vastbase_config(cfg)
print("enabled:", e.get("enabled"))
print("host:", e.get("host"))
print("database:", e.get("database"))
print("password_ok:", len(e.get("password", "")) > 0)

# 简单连接测试
import psycopg2
conn = psycopg2.connect(
    host=e["host"], port=int(e["port"]), dbname=e["database"],
    user=e["username"], password=e["password"], connect_timeout=10
)
print("psycopg2 OK:", conn.server_version)
cur = conn.cursor()
cur.execute("SELECT patient_id, visit_id, progress_type_name FROM jhemr.v_blws WHERE patient_id=%s LIMIT 3", ("00018069",))
for row in cur.fetchall():
    print("  row:", row)
conn.close()
