"""直接对比程序连接和手动连接"""
import sys
sys.path.insert(0, "/app")
import psycopg2

# 测试1：直接连接（之前成功的）
print("=== 直接连接 ===")
try:
    conn = psycopg2.connect(host='10.10.8.177', port=5432, dbname='jhemr', user='aizk_user', password='aizk_user@123', connect_timeout=10)
    print("直接连接 OK:", conn.server_version)
    conn.close()
except Exception as e:
    print("直接连接 FAIL:", e)

# 测试2：通过程序配置连接
print("\n=== 程序配置连接 ===")
from app.config import load_config
from app.services.config_parser import ConfigParser

cfg = load_config()
emr_cfg = ConfigParser.parse_emr_vastbase_config(cfg)
print("host:", emr_cfg.get("host"))
print("port:", emr_cfg.get("port"))
print("database:", emr_cfg.get("database"))
print("username:", emr_cfg.get("username"))
print("password:", repr(emr_cfg.get("password")))
print("password_len:", len(emr_cfg.get("password", "")))

try:
    conn = psycopg2.connect(
        host=emr_cfg["host"],
        port=int(emr_cfg["port"]),
        dbname=emr_cfg["database"],
        user=emr_cfg["username"],
        password=emr_cfg["password"],
        connect_timeout=10,
    )
    print("程序连接 OK:", conn.server_version)
    conn.close()
except Exception as e:
    print("程序连接 FAIL:", e)

# 测试3：通过 get_emr_vastbase_connection
print("\n=== get_emr_vastbase_connection ===")
from app.emr_vastbase_client import get_emr_vastbase_connection
try:
    conn = get_emr_vastbase_connection(emr_cfg)
    print("get_emr_vastbase_connection OK:", conn.server_version)
    conn.close()
except Exception as e:
    print("get_emr_vastbase_connection FAIL:", e)
