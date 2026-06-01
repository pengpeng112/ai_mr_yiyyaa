"""深度诊断 fetch_emr_documents_by_visits"""
import sys; sys.path.insert(0,"/app")
import psycopg2
from app.config import load_config
from app.services.config_parser import ConfigParser
from app.emr_vastbase_client import _build_base_sql_fields, _validate_schema_view, _build_kind_filter, get_emr_vastbase_connection

cfg = load_config()
e = ConfigParser.parse_emr_vastbase_config(cfg)

# 检查字段名
pid_f, vid_f, dept_f, content_f, title_f, type_f, tmpl_f, rtime_f, ftime_f, fstime_f, cdate_f, doctor_f, status_f = _build_base_sql_fields(e)
schema, view = _validate_schema_view(e)
print("pid_f:", pid_f)
print("vid_f:", vid_f)
print("content_f:", content_f)
print("schema.view:", schema + "." + view)

# 打印实际 SQL
kind_filter = _build_kind_filter(type_f, title_f, tmpl_f, "all")
sql = f"""
    WITH target(pid, vid) AS (VALUES (%s,%s))
    SELECT b.{pid_f} AS patient_id, b.{vid_f} AS visit_number
    FROM "{schema}"."{view}" b
    JOIN target t ON b.{pid_f} = t.pid AND b.{vid_f} = t.vid
    WHERE b.{content_f} IS NOT NULL
    {kind_filter}
    LIMIT 5
"""
print("\nSQL:")
print(sql)

# 直接执行
conn = get_emr_vastbase_connection(e)
cur = conn.cursor()
cur.execute(sql, ("00018069", "3"))
rows = cur.fetchall()
print(f"\nRows: {len(rows)}")
for r in rows:
    print(f"  {r}")

# 检查类型匹配
cur.execute("SELECT patient_id, visit_id, pg_typeof(patient_id), pg_typeof(visit_id) FROM jhemr.v_blws WHERE patient_id=%s LIMIT 1", ("00018069",))
r = cur.fetchone()
print(f"\n类型: pid={r[0]}({r[2]}), vid={r[1]}({r[3]})")

# 用模糊匹配测试
cur.execute("""
    WITH target(pid, vid) AS (VALUES (%s::text, %s::text))
    SELECT b.""" + pid_f + """ AS pid, b.""" + vid_f + """ AS vid
    FROM """ + '"' + schema + '"."' + view + '"' + """ b
    JOIN target t ON b.""" + pid_f + """::text = t.pid AND b.""" + vid_f + """::text = t.vid
    WHERE b.""" + content_f + """ IS NOT NULL
    LIMIT 5
""", ("00018069", "3"))
rows = cur.fetchall()
print(f"\n带类型转换 Rows: {len(rows)}")
for r in rows:
    print(f"  {r}")

conn.close()
