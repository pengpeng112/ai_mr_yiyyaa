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
print('=== candidate rows/progress grouped ===')
print(py("import sys;sys.path.insert(0,'/app');from app.config import load_config;from app.services.config_parser import ConfigParser;from app.oracle_client import fetch_records;c=load_config();cfg=ConfigParser.parse_oracle_config(c);rows=fetch_records(cfg,['020103'],'2026-06-03');groups={};\nfor r in rows:\n    pid=str(r.get('患者ID') or r.get('patient_id') or ''); visit=str(r.get('次数') or r.get('visit_number') or ''); name=str(r.get('患者姓名') or ''); dept=str(r.get('所在科室名称') or r.get('dept') or ''); key=(pid,visit,name,dept); groups.setdefault(key,0); groups[key]+=1\nprint('raw_rows',len(rows),'groups',len(groups));\n[print(k,'rows',v) for k,v in groups.items()]"))
print('=== push logs for these patients all dates ===')
print(py("import sys;sys.path.insert(0,'/app');from app.database import init_db,SessionLocal;from app.models import PushLog;from sqlalchemy import desc;init_db();db=SessionLocal();pids=['c0979412','c1010904','c1014431','c1020217','c1022009'];rows=db.query(PushLog).filter(PushLog.patient_id.in_(pids)).order_by(desc(PushLog.push_time)).limit(50).all();[print(f'id={r.id} time={str(r.push_time)[:19]} patient={r.patient_id} visit={r.visit_number} status={r.status} reviewed={getattr(r,\"reviewed_flag\",None)} manual={getattr(r,\"manual_override\",None)} code={getattr(r,\"audit_type_code\",\"\")} skip={(r.skip_reason or \"\")[:60]}') for r in rows];db.close()"))
print('=== recent alerts after 10am ===')
print(py("import sys;sys.path.insert(0,'/app');from app.database import init_db,SessionLocal;from app.models import QCRecordAlertLog;from sqlalchemy import desc;init_db();db=SessionLocal();rows=db.query(QCRecordAlertLog).filter(QCRecordAlertLog.created_at>='2026-06-04 10:00:00').order_by(desc(QCRecordAlertLog.created_at)).limit(20).all();print('count_after_10',len(rows));[print(f'id={r.id} created={r.created_at} push={r.push_log_id} patient={r.patient_id} severity={r.severity} status={r.status} err={(r.last_error or \"\")[:80]}') for r in rows];db.close()"))
c.close()
