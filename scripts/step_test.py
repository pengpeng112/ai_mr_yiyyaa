"""测试 get_emr_vastbase_connection 每一步"""
import sys; sys.path.insert(0,"/app")
import time, psycopg2
from app.config import load_config
from app.services.config_parser import ConfigParser

cfg = load_config()
e = ConfigParser.parse_emr_vastbase_config(cfg)
print("step1 config loaded")

# 直接用 psycopg2 测试参数
print("step2 direct connect...")
t = time.time()
conn = psycopg2.connect(host=e["host"], port=int(e["port"]), dbname=e["database"], user=e["username"], password=e["password"], connect_timeout=10)
print("  connected in %.1fs, ver=%s" % (time.time()-t, conn.server_version))

# 测试 set_session
print("step3 set_session...")
try:
    conn.set_session(readonly=True, autocommit=True)
    print("  set_session OK")
except Exception as ex:
    print("  set_session FAIL:", ex)

# 测试 statement_timeout
print("step4 SET statement_timeout...")
try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = 60000")
    print("  OK")
except Exception as ex:
    print("  FAIL:", ex)

# 测试简单查询
print("step5 simple query...")
cur = conn.cursor()
cur.execute("SELECT 1 FROM jhemr.v_blws WHERE patient_id=%s LIMIT 1", ("00018069",))
print("  rows:", len(cur.fetchall()))

# 测试 fetch_emr_documents_by_visits
print("step6 fetch_emr_documents_by_visits...")
from app.emr_vastbase_client import fetch_emr_documents_by_visits
r = fetch_emr_documents_by_visits(e, [("00018069","3")], document_kind="all")
print("  all:", len(r.get(("00018069","3"),[])))

conn.close()
print("done")
