# -*- coding: utf-8 -*-
"""016 轨「观察」：011/P5 只读证据采集（不执行任何写操作）。"""
import os
import sys

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
PASSWORD = os.environ.get("MED_AUDIT_SSH_PASSWORD", "")
if not PASSWORD:
    sys.exit("MED_AUDIT_SSH_PASSWORD 未设置")

CMDS = [
    ("镜像ID", "docker images med-audit:latest --format '{{.ID}} {{.CreatedAt}}'"),
    ("容器状态", "docker ps --filter name=med-audit --format '{{.Names}} {{.Status}}'"),
    ("轨A标注是否在容器", "docker exec med-audit grep -c '\\[source=' /app/app/services/data_source_loader.py || echo 0"),
    ("72h内ORA-12609次数", "docker logs --since 72h med-audit 2>&1 | grep -c 'ORA-12609' || echo 0"),
    ("健康检查", "docker exec med-audit curl -s http://localhost:8000/api/health || echo HEALTH_FAIL"),
]

# 容器内应用库只读查询（SQLAlchemy text，SELECT 仅）
SQL = (
    "SELECT audit_run_mode, status, error_code, COUNT(*) AS cnt, MAX(run_time) AS last_rt "
    "FROM MED_SCHEDULER_HISTORY "
    "WHERE audit_type_code = 'progress_vs_nursing' "
    "GROUP BY audit_run_mode, status, error_code "
    "ORDER BY MAX(run_time) DESC"
)
PY_SNIPPET = (
    "from app.database import SessionLocal\n"
    "from sqlalchemy import text\n"
    "db = SessionLocal()\n"
    "try:\n"
    f"    rows = db.execute(text({SQL!r})).fetchall()\n"
    "    for r in rows:\n"
    "        print(tuple(r))\n"
    "finally:\n"
    "    db.close()\n"
)
import base64

encoded = base64.b64encode(PY_SNIPPET.encode()).decode()
CMDS.append((
    "P5进度:progress_vs_nursing近况",
    f"docker exec med-audit python -c \"import base64;exec(base64.b64decode('{encoded}').decode())\"",
))

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15)
try:
    for title, cmd in CMDS:
        print(f"\n===== {title} =====")
        stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
        out = stdout.read().decode(errors="replace").strip()
        err = stderr.read().decode(errors="replace").strip()
        print(out if out else "(无输出)")
        if err:
            print(f"[stderr] {err[:500]}")
finally:
    client.close()
