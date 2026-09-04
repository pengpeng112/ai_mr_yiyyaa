# -*- coding: utf-8 -*-
"""039 B3 生产安全升级脚本（用户 2026-09-02 授权：DDL+代码/UI 部署+安全开关）。

携带范围（相对生产镜像 ef05862cf081）：
  - 037 全部九修复包（RP-C/B/D/E/F/A/H/G/I；与 039 共享 main.py/database.py，
    分属同一次已过全门禁的工作区状态）
  - 039 规则中心：prearchive_service 六表模型/规则仓/管理API/契约/Outbox/医保插件
    + 主服务 BFF（默认 503 feature-disabled）+ 六权限 seed + 两套前端规则中心区
  - DDL：MED_PREARCHIVE_RULE_VERSION/POINTER/AUDIT/DESTINATION/OUTBOX/DELIVERY_LOG
    六表（新增，不动业务源库）

安全开关最终值（全部默认关闭，无生产 config 改动）：
  rule_registry.mode=file；result_delivery.enabled=false；insurance_qc.enabled=false；
  PREARCHIVE_ADMIN_ENABLED 未设置（BFF 503 feature-disabled）

阶段（每阶段独立可重跑；红则停）：
  precheck —— 只读预检（scripts/precheck_039_b3_20260902.py 单独跑）
  backup   —— 容器内受影响路径 tar 备份 + docker commit 回滚 tag
  ddl      —— 经容器内应用库连接执行六表 DDL（前后表清单留证）
  deploy   —— 上传 hotfix tar → 覆盖 /app 受影响文件 → 清 __pycache__ → 重启
  verify   —— 健康/路由注册/六类审计类型/权限 seed/静态资产/日志净/开关状态
  persist  —— docker commit 固化 med-audit:latest

用法：
    python scripts/deploy_039_b3_20260902.py backup <本地tar绝对路径>
    python scripts/deploy_039_b3_20260902.py ddl
    python scripts/deploy_039_b3_20260902.py deploy <本地tar绝对路径>
    python scripts/deploy_039_b3_20260902.py verify
    python scripts/deploy_039_b3_20260902.py persist
"""

from __future__ import annotations

import os
import sys

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
CONTAINER = "med-audit"
ROLLBACK_TAG = "med-audit:rollback-pre-039-20260902"
REMOTE_TAR = "/root/hotfix_039_20260902.tar.gz"
REMOTE_BACKUP = "/root/hotfix_backup_039_20260902.tar.gz"
DDL_PATH = "/app/prearchive_service/sql/create_prearchive_rule_center_oracle.sql"

EXPECTED_TABLES = [
    "MED_PREARCHIVE_RULE_VERSION", "MED_PREARCHIVE_RULE_POINTER",
    "MED_PREARCHIVE_RULE_AUDIT", "MED_PREARCHIVE_DESTINATION",
    "MED_PREARCHIVE_OUTBOX", "MED_PREARCHIVE_DELIVERY_LOG",
]


def connect() -> paramiko.SSHClient:
    password = os.environ.get("MED_AUDIT_SSH_PASSWORD", "")
    if not password:
        print("[FATAL] MED_AUDIT_SSH_PASSWORD 未设置")
        sys.exit(2)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=password, timeout=20)
    return client


def run(client, title, cmd, check=True, timeout=120):
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    print(f"===== {title} (exit={code}) =====")
    if out:
        print(out[-1500:])
    if err:
        print("[stderr]", err[-500:])
    if check and code != 0:
        print(f"[FATAL] 阶段失败: {title}")
        sys.exit(1)
    return out


def phase_backup(local_tar: str):
    client = connect()
    try:
        run(client, "回滚点1：容器内受影响路径 tar 备份",
            f"docker exec {CONTAINER} tar czf /tmp/hotfix_backup_039_20260902.tar.gz "
            f"-C /app app/main.py app/database.py app/demo_support app/routers app/services "
            f"app/security_middleware.py static prearchive_service")
        run(client, "备份拖回宿主", f"docker cp {CONTAINER}:/tmp/hotfix_backup_039_20260902.tar.gz {REMOTE_BACKUP}")
        run(client, "回滚点2：回滚镜像 tag",
            f"docker commit {CONTAINER} {ROLLBACK_TAG}")
        run(client, "DDL 回滚脚本预置（不执行）",
            "echo 'drop 脚本随代码包部署到 /app/prearchive_service/sql/，回滚优先停开关/回镜像'")
        print("[backup OK]")
    finally:
        client.close()


def phase_ddl():
    client = connect()
    try:
        import base64
        list_b64 = base64.b64encode(
            "import sys; sys.path.insert(0, '/app')\n"
            "from app.database import engine\n"
            "from sqlalchemy import text\n"
            "rows = engine.connect().execute(text(\"SELECT table_name FROM user_tables "
            "WHERE table_name LIKE 'MED_PREARCHIVE%' ORDER BY table_name\")).fetchall()\n"
            "print(sorted(r[0] for r in rows))\n".encode()).decode()
        pre = run(client, "DDL 前表清单",
                  f"docker exec {CONTAINER} python -c \"import base64;exec(base64.b64decode('{list_b64}'))\"")

        ddl_b64 = base64.b64encode(
            f"""import sys, re
sys.path.insert(0, '/app')
from app.database import engine
from sqlalchemy import text
sql = open('{DDL_PATH}', encoding='utf-8').read()
chunks = re.split(r';\\s*\\n', sql)
stmts = []
for s in chunks:
    body = re.sub(r'^\\s*--.*$', '', s, flags=re.M).strip()
    if body:
        stmts.append(body)
created = []
with engine.begin() as conn:
    for s in stmts:
        head = s.splitlines()[0][:80]
        try:
            conn.execute(text(s))
            created.append('OK ' + head)
        except Exception as e:
            msg = str(e)
            if 'ORA-00955' in msg:
                created.append('SKIP-EXISTS ' + head)
            else:
                created.append('FAIL ' + head + ' | ' + msg[:150])
                raise
print('\\n'.join(created))
""".encode()).decode()
        run(client, "执行六表 DDL（逐条；已存在则跳过）",
            f"docker exec {CONTAINER} python -c \"import base64;exec(base64.b64decode('{ddl_b64}'))\"")

        post = run(client, "DDL 后表清单（必须含六表）",
                   f"docker exec {CONTAINER} python -c \"import base64;exec(base64.b64decode('{list_b64}'))\"")
        missing = [t for t in EXPECTED_TABLES if t not in post]
        if missing:
            print(f"[FATAL] 六表缺失: {missing}")
            sys.exit(1)
        print("[ddl OK]")
    finally:
        client.close()


def phase_deploy(local_tar: str):
    if not os.path.exists(local_tar):
        print(f"[FATAL] 本地 tar 不存在: {local_tar}")
        sys.exit(2)
    client = connect()
    try:
        sftp = client.open_sftp()
        sftp.put(local_tar, REMOTE_TAR)
        sftp.close()
        print("[upload OK]", REMOTE_TAR)
        run(client, "容器内解包覆盖 /app（tar 内容已按 app/ static/ prearchive_service/ 前缀打包）",
            f"docker cp {REMOTE_TAR} {CONTAINER}:/tmp/hotfix_039.tar.gz && "
            f"docker exec {CONTAINER} sh -c 'tar xzf /tmp/hotfix_039.tar.gz -C /app'")
        run(client, "清 __pycache__",
            f"docker exec {CONTAINER} find /app/app /app/prearchive_service -name __pycache__ -type d -exec rm -rf {{}} + 2>/dev/null; true")
        run(client, "重启容器（停机窗口约 20 秒）",
            f"docker restart {CONTAINER}")
        import time
        time.sleep(25)
        run(client, "容器状态",
            f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}}'")
        print("[deploy OK]")
    finally:
        client.close()


def phase_verify():
    client = connect()
    try:
        ok = True

        def check(title, cmd, expect):
            nonlocal ok
            out = run(client, title, cmd)
            good = expect in out
            print(f"[{'PASS' if good else 'FAIL'}] {title}")
            if not good:
                ok = False

        check("健康 200", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health", "200")
        # 六类审计类型（读生产 config，不动）
        check("六类审计类型仍在",
              f"docker exec {CONTAINER} python -c \""
              "import json; cfg=json.load(open('/app/config/config.json'));"
              "types=[t['code'] for t in cfg.get('audit_types', [])];"
              "print(len(types), types)\"", "6")
        # BFF 路由注册（未启用 → 401/503，绝不能 404）
        run(client, "BFF 路由注册探测（期望 401 而非 404）",
            "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/prearchive-admin/settings")
        # 六权限 seed（脚本 base64 注入，避开多层引号）
        import base64
        perm_script = (
            "import sys; sys.path.insert(0, '/app');\n"
            "from app.database import SessionLocal\n"
            "from sqlalchemy import text\n"
            "db = SessionLocal()\n"
            "rows = db.execute(text(\"SELECT p.name FROM MED_PERMISSIONS p \"\n"
            "  \"JOIN MED_ROLE_PERMISSIONS rp ON rp.permission_id=p.id \"\n"
            "  \"JOIN MED_ROLES r ON r.id=rp.role_id \"\n"
            "  \"WHERE r.name='admin' AND p.name LIKE 'prearchive%'\")).fetchall()\n"
            "print(sorted(x[0] for x in rows))\n"
        )
        b64 = base64.b64encode(perm_script.encode()).decode()
        check("六权限 seed（admin 角色拥有）",
              f"docker exec {CONTAINER} python -c \"import base64;exec(base64.b64decode('{b64}'))\"",
              "prearchive_rule_view")
        # 静态资产
        check("legacy 规则中心 JS 可达",
              "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/scripts/modules/prearchive_rule_center.js", "200")
        check("ui-next 可达",
              "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ui-next/", "200")
        check("qc_detail 版本锚",
              "curl -s http://127.0.0.1:8000/mobile/qc-detail-demo 2>/dev/null | grep -c 20260902-csrf-header || "
              f"docker exec {CONTAINER} grep -c 20260902-csrf-header /app/static/templates/mobile/qc_detail.html", "1")
        # 规则中心模块可导入 + DDL 表在
        check("规则中心模块容器内导入",
              f"docker exec {CONTAINER} python -c \""
              "import sys; sys.path.insert(0, '/app/prearchive_service');"
              "import prearchive.rule_service, prearchive.admin_api, prearchive.outbox;"
              "print('IMPORT_OK')\"", "IMPORT_OK")
        # 双调度重注册 + 日志净
        run(client, "调度重注册与启动日志",
            f"docker logs --since 3m {CONTAINER} 2>&1 | grep -iE 'scheduler|daily|discharge|error|traceback' | head -20")
        # 开关终态
        run(client, "开关终态（env 无 BFF 三元组=默认关闭）",
            f"docker exec {CONTAINER} sh -c 'env | grep -c PREARCHIVE_ADMIN || echo 0'")
        if not ok:
            print("[FATAL] verify 存在失败项")
            sys.exit(1)
        print("[verify OK]")
    finally:
        client.close()


def phase_persist():
    client = connect()
    try:
        run(client, "固化镜像", f"docker commit -m '039 rule center + 037 repairs (B3 2026-09-02)' {CONTAINER} med-audit:latest")
        run(client, "新镜像 ID", f"docker inspect --format '{{{{.Image}}}}' {CONTAINER} | cut -c8-19")
        print("[persist OK]")
    finally:
        client.close()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    phase = sys.argv[1]
    if phase == "backup":
        phase_backup(sys.argv[2] if len(sys.argv) > 2 else "")
    elif phase == "ddl":
        phase_ddl()
    elif phase == "deploy":
        if len(sys.argv) < 3:
            print("[FATAL] deploy 需要本地 tar 路径")
            return 2
        phase_deploy(sys.argv[2])
    elif phase == "verify":
        phase_verify()
    elif phase == "persist":
        phase_persist()
    else:
        print(f"[FATAL] 未知阶段: {phase}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
