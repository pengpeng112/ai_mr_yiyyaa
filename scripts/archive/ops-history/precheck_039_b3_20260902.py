# -*- coding: utf-8 -*-
"""039 B3 生产只读预检（precheck）：容器/镜像/预检运行状态/规则中心表存在性。

零写入：只执行只读命令与 SELECT。口令只从环境变量 MED_AUDIT_SSH_PASSWORD 读取。
"""

from __future__ import annotations

import os
import sys

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
CONTAINER = "med-audit"


def connect() -> paramiko.SSHClient:
    password = os.environ.get("MED_AUDIT_SSH_PASSWORD", "")
    if not password:
        print("[FATAL] MED_AUDIT_SSH_PASSWORD 未设置")
        sys.exit(2)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=password, timeout=20)
    return client


def run(client, title, cmd, show=True):
    _, stdout, stderr = client.exec_command(cmd, timeout=60)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    print(f"===== {title} =====")
    if show and out:
        print(out)
    if err:
        print("[stderr]", err[:500])
    return out


def main() -> int:
    client = connect()
    try:
        run(client, "容器状态", f"docker ps --filter name={CONTAINER} --format '{{{{.Names}}}} {{{{.Image}}}} {{{{.Status}}}}'")
        run(client, "当前镜像ID", f"docker inspect --format '{{{{.Image}}}}' {CONTAINER} | cut -c8-19")
        run(client, "compose 目录", "ls /opt/med-audit-docker/")
        run(client, "容器内预检进程",
            f"docker exec {CONTAINER} ps aux | grep -i prearchive | grep -v grep || echo NO_PREARCHIVE_PROCESS")
        run(client, "容器内预检服务代码版本锚",
            f"docker exec {CONTAINER} ls /app/prearchive_service/prearchive/ | head -30")
        run(client, "容器内规则中心模块是否存在",
            f"docker exec {CONTAINER} ls /app/prearchive_service/prearchive/rule_models.py 2>/dev/null || echo RULE_CENTER_NOT_DEPLOYED")
        run(client, "主服务 BFF 是否存在",
            f"docker exec {CONTAINER} ls /app/app/routers/prearchive_admin.py 2>/dev/null || echo BFF_NOT_DEPLOYED")
        # 应用库表存在性（只读 user_tables）
        run(client, "MED_PREARCHIVE 表清单",
            f"docker exec {CONTAINER} python -c \""
            "import sys; sys.path.insert(0, '/app');"
            "from app.database import engine;"
            "from sqlalchemy import text;"
            "rows = engine.connect().execute(text("
            "'SELECT table_name FROM user_tables WHERE table_name LIKE %r ORDER BY table_name' % 'MED_%%PREARCHIVE%%')).fetchall();"
            "print([r[0] for r in rows])\"")
        # 预检服务生产配置（result_store 类型与新增节）
        run(client, "预检 config.json 关键节",
            f"docker exec {CONTAINER} python -c \""
            "import json; cfg=json.load(open('/app/prearchive_service/config.json'));"
            "print('result_store.type=', (cfg.get('result_store') or {}).get('type'));"
            "print('rule_registry=', cfg.get('rule_registry', 'ABSENT-default-file'));"
            "print('result_delivery=', cfg.get('result_delivery', 'ABSENT-default-false'));"
            "print('insurance_qc=', cfg.get('insurance_qc', 'ABSENT-default-false'));"
            "print('admin_api=', (cfg.get('admin_api') or {}).get('enabled', 'ABSENT'))\"")
        run(client, "主服务健康", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health")
        run(client, "双调度 job 现状",
            "curl -s http://127.0.0.1:8000/api/scheduler/status | head -c 400")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
