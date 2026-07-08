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
    return stdout.read().decode('utf-8','replace') or stderr.read().decode('utf-8','replace')
def py(script,t=60):
    esc=script.replace('"','\\"')
    return run(f'docker exec med-audit python3 -c "{esc}" 2>/dev/null',t)
print(py("import sys;sys.path.insert(0,'/app');from app.database import init_db,SessionLocal;from app.models import PushLog;from sqlalchemy import desc;init_db();db=SessionLocal();pids=['c0938437','c0933914','c0965210','c1008350','c1045840'];rows=db.query(PushLog).filter(PushLog.patient_id.in_(pids)).order_by(desc(PushLog.push_time)).limit(80).all();print('rows',len(rows));[print(f'id={r.id} time={str(r.push_time)[:19]} patient={r.patient_id} visit={r.visit_number} status={r.status} reviewed={getattr(r,\"reviewed_flag\",None)} manual={getattr(r,\"manual_override\",None)} code={getattr(r,\"audit_type_code\",\"\")} skip={(r.skip_reason or \"\")[:80]}') for r in rows];db.close()"))
c.close()
