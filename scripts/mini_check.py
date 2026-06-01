import sys; sys.path.insert(0,"/app")
import psycopg2
from app.config import load_config
from app.services.config_parser import ConfigParser
cfg = load_config()
e = ConfigParser.parse_emr_vastbase_config(cfg)
conn = psycopg2.connect(host=e["host"],port=int(e["port"]),dbname=e["database"],user=e["username"],password=e["password"],connect_timeout=10)
cur = conn.cursor()
cur.execute("SELECT count(*), count(progress_message) FROM jhemr.v_blws WHERE patient_id=%s AND visit_id=%s", ("00018069","3"))
r = cur.fetchone()
print("total=%s non-null-content=%s" % (r[0], r[1]))
conn.close()
