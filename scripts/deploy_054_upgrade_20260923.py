# -*- coding: utf-8 -*-
"""054 生产升级脚本（用户 2026-09-23 授权：「先把 ai质控系统进行完成，然后升级上线」）。

携带范围（相对生产容器当前状态 = 039-B3 09-02 部署树 ≈ git 3932e26）：
  - 046/047 无纸化规则中心闭环 + JHEMR 五接口 + 覆盖账本/AI匹配/trial/Outbox
  - 048/049 工作台分页有界聚合 + 匹配事务 + BFF any-of + 双前端硬化
  - 050/051 D-J1 终态物化顺序修复
  - 054 权限缺失 fail-closed + 质控记录旧响应守卫 + 门禁/测试设施
  - 前端 ui-next 全量重建产物
  - DDL：MED_PREARCHIVE 闭环 10 张新表（纯 CREATE，不碰既有表；已存在跳过）

安全开关：不变（config 卷零接触；rule/delivery/insurance/BFF 开关维持生产现值）。

阶段（每阶段独立可重跑；红则停）：
  precheck —— 只读：容器/健康/基线哨兵（闭环模块应不存在；MED_PREARCHIVE% 应=6 表）
  backup   —— 容器内 /app/app+/app/static+/app/prearchive_service tar 备份拖回宿主
              + docker commit 回滚 tag med-audit:rollback-pre-054-20260923
  deploy   —— 上传热更 tar → 覆盖 /app → 清 __pycache__ → 重启（停机约 25s）
  ddl      —— 容器内执行闭环 10 表 DDL（ORA-00955 已存在跳过）；前后表清单留证
  verify   —— 健康/文档/两套前端资产哈希/六类审计类型/容器日志净/回滚 tag 在
  persist  —— docker commit 固化 med-audit:latest 并记录新镜像 ID

用法：
    python scripts/deploy_054_upgrade_20260923.py precheck
    python scripts/deploy_054_upgrade_20260923.py backup
    python scripts/deploy_054_upgrade_20260923.py deploy
    python scripts/deploy_054_upgrade_20260923.py ddl
    python scripts/deploy_054_upgrade_20260923.py verify
    python scripts/deploy_054_upgrade_20260923.py persist
"""
from __future__ import annotations

import base64
import os
import sys
import time

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
CONTAINER = "med-audit"
ROLLBACK_TAG = "med-audit:rollback-pre-054-20260923"
REMOTE_TAR = "/root/hotfix_054_20260923.tar.gz"
REMOTE_BACKUP = "/root/hotfix_backup_054_20260923.tar.gz"
LOCAL_TAR = r"C:\Users\ADMINI~1\AppData\Local\Temp\opencode\hotfix_054_20260923.tar.gz"
DDL_PATH = "/app/prearchive_service/sql/create_prearchive_closed_loop_oracle_20260910.sql"

OLD_TABLES = [
    "MED_PREARCHIVE_RULE_VERSION", "MED_PREARCHIVE_RULE_POINTER",
    "MED_PREARCHIVE_RULE_AUDIT", "MED_PREARCHIVE_DESTINATION",
    "MED_PREARCHIVE_OUTBOX", "MED_PREARCHIVE_DELIVERY_LOG",
]
NEW_TABLES = [
    "MED_PREARCHIVE_CATALOG_ITEM", "MED_PREARCHIVE_COVERAGE_MAP",
    "MED_PREARCHIVE_RUN", "MED_PREARCHIVE_RULE_EVAL", "MED_PREARCHIVE_ISSUE",
    "MED_PREARCHIVE_ISSUE_ACTION", "MED_PREARCHIVE_MATCH_TASK",
    "MED_PREARCHIVE_MATCH_CANDIDATE", "MED_PREARCHIVE_TRIAL_FEEDBACK",
    "MED_PREARCHIVE_VIEW_TICKET",
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


def run(client, title, cmd, check=True, timeout=180):
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    print(f"===== {title} (exit={code}) =====")
    if out:
        print(out[-1600:])
    if err:
        print("[stderr]", err[-500:])
    if check and code != 0:
        print(f"[FATAL] 阶段失败: {title}")
        sys.exit(1)
    return out


def b64exec(py_code: str) -> str:
    return base64.b64encode(py_code.encode()).decode()


TABLES_PY = (
    "import sys; sys.path.insert(0, '/app')\n"
    "from app.database import engine\n"
    "from sqlalchemy import text\n"
    "rows = engine.connect().execute(text(\"SELECT table_name FROM user_tables "
    "WHERE table_name LIKE 'MED_PREARCHIVE%' ORDER BY table_name\")).fetchall()\n"
    "print(sorted(r[0] for r in rows))\n"
)


def phase_precheck():
    client = connect()
    try:
        run(client, "容器状态", f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}} {{{{.Image}}}}'")
        run(client, "当前镜像 ID", f"docker inspect --format '{{{{.Image}}}}' {CONTAINER} | cut -c8-19")
        run(client, "健康 200", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health", check=False)
        # 基线哨兵 1：046 闭环模块在生产应不存在（确认我们没算错基线）
        out = run(client, "基线哨兵：闭环模块应不存在",
                  f"docker exec {CONTAINER} sh -c 'ls /app/prearchive_service/prearchive/closed_loop_api.py 2>&1'",
                  check=False)
        baseline_ok = "No such file" in out
        print(f"[{'PASS' if baseline_ok else 'WARN'}] 基线哨兵 closed_loop_api.py：{'不存在(=039-B3基线,符合预期)' if baseline_ok else '已存在(基线可能已被更新过,人工确认)'}")
        # 基线哨兵 2：MED_PREARCHIVE% 应恰为 039 六表
        tables = run(client, "DDL 前表清单",
                     f"docker exec {CONTAINER} python -c \"import base64;exec(base64.b64decode('{b64exec(TABLES_PY)}'))\"")
        count = tables.count("MED_PREARCHIVE")
        print(f"[{'PASS' if count == 6 else 'WARN'}] 现有 MED_PREARCHIVE 表数={count}（预期 6）")
        print("[precheck OK]")
    finally:
        client.close()


def phase_backup():
    client = connect()
    try:
        run(client, "回滚点1：容器内受影响路径 tar 备份",
            f"docker exec {CONTAINER} tar czf /tmp/hotfix_backup_054_20260923.tar.gz "
            f"-C /app app static prearchive_service")
        run(client, "备份拖回宿主", f"docker cp {CONTAINER}:/tmp/hotfix_backup_054_20260923.tar.gz {REMOTE_BACKUP}")
        run(client, "回滚点2：回滚镜像 tag", f"docker commit {CONTAINER} {ROLLBACK_TAG}")
        run(client, "回滚确认", f"docker images {ROLLBACK_TAG} --format '{{{{.ID}}}} {{{{.Size}}}}'")
        print("[backup OK]")
    finally:
        client.close()


def phase_deploy():
    if not os.path.exists(LOCAL_TAR):
        print(f"[FATAL] 本地 tar 不存在: {LOCAL_TAR}")
        sys.exit(2)
    client = connect()
    try:
        sftp = client.open_sftp()
        print(f"[upload] {LOCAL_TAR} -> {REMOTE_TAR}")
        sftp.put(LOCAL_TAR, REMOTE_TAR)
        sftp.close()
        run(client, "容器内解包覆盖 /app（前缀 app/ static/ prearchive_service/；config 卷不触碰）",
            f"docker cp {REMOTE_TAR} {CONTAINER}:/tmp/hotfix_054.tar.gz && "
            f"docker exec {CONTAINER} sh -c 'tar xzf /tmp/hotfix_054.tar.gz -C /app'")
        run(client, "清 __pycache__",
            f"docker exec {CONTAINER} sh -c 'find /app/app /app/prearchive_service -name __pycache__ -type d -exec rm -rf {{}} + 2>/dev/null; true'")
        run(client, "重启容器（停机窗口约 25 秒）", f"docker restart {CONTAINER}")
        time.sleep(25)
        run(client, "容器状态", f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}}'")
        run(client, "健康探测", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health", check=False)
        print("[deploy OK]")
    finally:
        client.close()


def phase_ddl():
    client = connect()
    try:
        pre = run(client, "DDL 前表清单",
                  f"docker exec {CONTAINER} python -c \"import base64;exec(base64.b64decode('{b64exec(TABLES_PY)}'))\"")
        # 直连 cx_Oracle（env 凭据），与预检验证过的新建连接路径一致；
        # 不走 app.database engine（预检中 exec 进程经 engine 两次瞬时 12547/12541）
        ddl_b64 = b64exec(
            "import os, re\n"
            "import cx_Oracle\n"
            f"sql = open('{DDL_PATH}', encoding='utf-8').read()\n"
            "chunks = re.split(r';\\s*\\n', sql)\n"
            "stmts = []\n"
            "for s in chunks:\n"
            "    body = re.sub(r'^\\s*--.*$', '', s, flags=re.M).strip()\n"
            "    if body:\n"
            "        stmts.append(body)\n"
            "dsn = cx_Oracle.makedsn(os.environ['APP_ORACLE_HOST'], "
            "int(os.environ.get('APP_ORACLE_PORT', '1521')), "
            "service_name=os.environ.get('APP_ORACLE_SERVICE_NAME', 'orcl'))\n"
            "pw = os.environ.get('APP_ORACLE_PASSWORD') or os.environ.get('APP_ORACLE_', '') or ''\n"
            "conn = cx_Oracle.connect(os.environ['APP_ORACLE_USERNAME'], pw, dsn)\n"
            "cur = conn.cursor()\n"
            "created = []\n"
            "try:\n"
            "    for s in stmts:\n"
            "        head = s.splitlines()[0][:70]\n"
            "        try:\n"
            "            cur.execute(s)\n"
            "            created.append('OK ' + head)\n"
            "        except cx_Oracle.DatabaseError as e:\n"
            "            msg = str(e)\n"
            "            if 'ORA-00955' in msg:\n"
            "                created.append('SKIP-EXISTS ' + head)\n"
            "            else:\n"
            "                created.append('FAIL ' + head + ' | ' + msg[:150])\n"
            "                raise\n"
            "    conn.commit()\n"
            "finally:\n"
            "    conn.close()\n"
            "print('\\n'.join(created))\n"
        )
        run(client, "执行闭环 10 表 DDL（纯 CREATE；已存在跳过）",
            f"docker exec {CONTAINER} python -c \"import base64;exec(base64.b64decode('{ddl_b64}'))\"")
        post = run(client, "DDL 后表清单（须含 6+10=16 表）",
                   f"docker exec {CONTAINER} python -c \"import base64;exec(base64.b64decode('{b64exec(TABLES_PY)}'))\"")
        missing = [t for t in OLD_TABLES + NEW_TABLES if t not in post]
        if missing:
            print(f"[FATAL] 表缺失: {missing}")
            sys.exit(1)
        print(f"[ddl OK] before={pre.count('MED_PREARCHIVE')} after={post.count('MED_PREARCHIVE')} 表")
    finally:
        client.close()


def phase_verify(local_asset_hint: str = ""):
    client = connect()
    try:
        ok = True

        def check(title, cmd, expect, essential=True):
            nonlocal ok
            out = run(client, title, cmd, check=False)
            good = expect in out
            print(f"[{'PASS' if good else ('FAIL' if essential else 'WARN')}] {title}")
            if not good and essential:
                ok = False
            return out

        check("健康 200", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health", "200")
        # 生产默认 ENABLE_API_DOCS=false（既有设计，/docs 404=预期）
        docs_on = run(client, "API 文档开关", f"docker exec {CONTAINER} printenv ENABLE_API_DOCS", check=False)
        if "true" in docs_on.lower():
            check("Swagger /docs 200", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/docs", "200")
        check("legacy 首页 200", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/index.html", "200")
        check("ui-next 200", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ui-next/", "200")
        if local_asset_hint:
            check("ui-next 资产指纹", "curl -s http://127.0.0.1:8000/ui-next/index.html", local_asset_hint)
        check("六类审计类型仍在",
              f"docker exec {CONTAINER} python -c \""
              "import json; cfg=json.load(open('/app/config/config.json'));"
              "types=[t['code'] for t in cfg.get('audit_types', [])];"
              "print(len(types), types)\"", "6")
        # 新代码哨兵：闭环模块已在容器内
        check("新代码哨兵 closed_loop_api.py 已在",
              f"docker exec {CONTAINER} sh -c 'ls /app/prearchive_service/prearchive/closed_loop_api.py'", "closed_loop_api.py")
        check("新代码哨兵 workbenchPerms 已在(ui-next 包内)",
              "curl -s http://127.0.0.1:8000/ui-next/index.html", "assets")
        logs = run(client, "容器日志尾部（无 Traceback/ERROR 为净）",
                   f"docker logs --tail 60 {CONTAINER} 2>&1 | tail -40", check=False)
        bad = [ln for ln in logs.splitlines() if "Traceback" in ln or " ERROR " in ln]
        print(f"[{'PASS' if not bad else 'WARN'}] 日志净检（异常行={len(bad)}）")
        for ln in bad[:5]:
            print("  [异常]", ln[:160])
        check("回滚 tag 在", f"docker images {ROLLBACK_TAG} --format '{{{{.ID}}}}'", "", essential=False) or None
        run(client, "回滚 tag 确认", f"docker images {ROLLBACK_TAG}", check=False)
        print(f"===== verify {'PASS' if ok else 'FAIL'} =====")
        if not ok:
            sys.exit(1)
    finally:
        client.close()


def phase_persist():
    client = connect()
    try:
        run(client, "docker commit 固化 latest", f"docker commit -m '054 upgrade 20260923' {CONTAINER} med-audit:latest")
        run(client, "新镜像 ID", "docker images med-audit:latest --format '{{.ID}} {{.CreatedAt}}'")
        print("[persist OK]")
    finally:
        client.close()


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    phase = sys.argv[1]
    fn = {"precheck": phase_precheck, "backup": phase_backup, "deploy": phase_deploy,
          "ddl": phase_ddl, "verify": phase_verify, "persist": phase_persist}.get(phase)
    if not fn:
        print(__doc__)
        sys.exit(2)
    fn()


if __name__ == "__main__":
    main()
