# -*- coding: utf-8 -*-
import os, paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
host = os.getenv("MED_AUDIT_SSH_HOST")
port = int(os.getenv("MED_AUDIT_SSH_PORT", "22"))
username = os.getenv("MED_AUDIT_SSH_USER")
password = os.getenv("MED_AUDIT_SSH_PASSWORD")
if not all([host, username, password]):
    raise SystemExit("Set MED_AUDIT_SSH_HOST, MED_AUDIT_SSH_USER and MED_AUDIT_SSH_PASSWORD before running this diagnostic script.")
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy()); c.connect(host, port=port, username=username, password=password, timeout=15)
def run(cmd,t=60):
    stdin,stdout,stderr=c.exec_command(cmd,timeout=t)
    out=stdout.read().decode('utf-8','replace'); err=stderr.read().decode('utf-8','replace')
    return out or err

def py(script,t=60):
    esc=script.replace('"','\\"')
    return run(f'docker exec med-audit python3 -c "{esc}" 2>/dev/null',t)
print('=== 1 config ===')
print(py("import json;c=json.load(open('/app/config/config.json'));print(json.dumps(c.get('scheduler',{}),ensure_ascii=False));print(json.dumps(c.get('departments',{}),ensure_ascii=False))"))
print('=== 2 scheduler history recent ===')
print(py("import sys;sys.path.insert(0,'/app');from app.database import init_db,SessionLocal;from app.models import SchedulerHistory;from sqlalchemy import desc;init_db();db=SessionLocal();rows=db.query(SchedulerHistory).order_by(desc(SchedulerHistory.run_time)).limit(12).all();[print(f'id={r.id} run={r.run_time} query={r.query_date} code={getattr(r,\"audit_type_code\",\"\")} total={r.total_records} succ={r.success_count} fail={r.failed_count} status={r.status}') for r in rows];db.close()"))
print('=== 3 funnel logs around today 10 ===')
print(run("docker exec med-audit sh -c \"grep '推送漏斗' /app/logs/app.log | grep -E '2026-06-04 09:|2026-06-04 10:|2026-06-04 11:'\" 2>/dev/null"))
print('=== 4 scheduler logs around today 10 ===')
print(run("docker exec med-audit sh -c \"grep -E '定时推送任务|Running job|executed successfully|next_run|dept_filter|trigger=auto' /app/logs/app.log | grep -E '2026-06-04 09:|2026-06-04 10:|2026-06-04 11:'\" 2>/dev/null"))
print('=== 5 push logs after today 10 ===')
print(py("import sys;sys.path.insert(0,'/app');from app.database import init_db,SessionLocal;from app.models import PushLog;from sqlalchemy import desc;init_db();db=SessionLocal();rows=db.query(PushLog).filter(PushLog.push_time>='2026-06-04 09:30:00').order_by(desc(PushLog.push_time)).limit(30).all();[print(f'id={r.id} time={str(r.push_time)[:19]} patient={r.patient_id} visit={r.visit_number} dept={r.dept} status={r.status} code={getattr(r,\"audit_type_code\",\"\")} skip={(r.skip_reason or \"\")[:50]}') for r in rows];db.close()"))
print('=== 6 direct source count for dept 020103 query_date yesterday ===')
print(py("import sys,json;sys.path.insert(0,'/app');from app.config import load_config;from app.services.audit_type_registry import AuditTypeRegistry;from app.services.data_source_loader import load_patient_bundles;from app.oracle_client import fetch_records;from app.services.config_parser import ConfigParser;c=load_config();reg=AuditTypeRegistry(c);q='2026-06-03';dept=['020103'];print('query_date',q,'dept',dept);\nfor code in ['progress_vs_nursing','jyjc_vs_bcnursing','syssvsscbc']:\n    at=reg.get(code);\n    if str((at.payload or {}).get('builder') or '')=='legacy_progress_nursing':\n        cfg=ConfigParser.parse_oracle_config(c); rows=fetch_records(cfg,dept,q); print(code,'raw_rows',len(rows),'patients',len(set((str(r.get('患者ID') or r.get('patient_id')),str(r.get('次数') or r.get('visit_number'))) for r in rows)));\n    else:\n        bundles=load_patient_bundles(at,c,q,dept_filter=dept); print(code,'bundles',len(bundles),'diag',getattr(bundles,'diagnostics',None) if hasattr(bundles,'diagnostics') else '')" ,120))
print('=== 7 direct Oracle broad counts 020103 ===')
print(py("import sys;sys.path.insert(0,'/app');from app.config import load_config;from app.services.config_parser import ConfigParser;from app.oracle_client import get_oracle_connection;c=load_config();oc=ConfigParser.parse_oracle_config(c);conn=get_oracle_connection(oc);cur=conn.cursor();\nfor d in ['2026-06-03','2026-06-04']:\n    print('DATE',d);\n    for sql,name in [(\"SELECT count(*) FROM jhemr.v_qybr a WHERE (a.\\\"所在科室编码\\\"='020103' OR a.\\\"出院科室编码\\\"='020103') AND a.\\\"出院日期\\\">=TO_DATE(:d,'yyyy-mm-dd') AND a.\\\"出院日期\\\"<TO_DATE(:d,'yyyy-mm-dd')+1\",'discharge patients'),(\"SELECT count(*) FROM jhemr.v_qybr a JOIN jhemr.v_bcjl b ON a.\\\"患者ID\\\"=b.\\\"患者ID\\\" AND a.\\\"次数\\\"=b.\\\"次数\\\" WHERE (a.\\\"所在科室编码\\\"='020103' OR a.\\\"出院科室编码\\\"='020103') AND b.\\\"病历标题时间\\\">=TO_DATE(:d,'yyyy-mm-dd') AND b.\\\"病历标题时间\\\"<TO_DATE(:d,'yyyy-mm-dd')+1\",'progress notes')]:\n        cur.execute(sql,{'d':d}); print(name,cur.fetchone()[0]);\ncur.close();conn.close()",120))
c.close()
