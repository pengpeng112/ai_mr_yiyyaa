# -*- coding: utf-8 -*-
"""生产热更新部署脚本（2026-08-30，用户当次授权：push+升级服务器）。

本次变更面=prearchive_service/（034：T8-2b 四源采集器实测列转正 + T8-3 hisbase
工号映射接线；app/ static/ scripts/ 相对 2026-08-29 已部署镜像零改动），故打包
范围只含 prearchive_service/（排除 tests/reminder_agent/data/logs/__pycache__）。
口令只从环境变量 MED_AUDIT_SSH_PASSWORD 读取，不落仓库。

阶段：
  backup  —— 容器内 prearchive_service tar 备份拖回服务器 /root/ + docker commit 回滚镜像 tag
  deploy  —— 上传 tar → docker cp 进容器 → 解包覆盖 → 清 __pycache__ → 重启
  verify  —— 容器状态/健康接口/预检模块导入/预检规则视图/启动日志无异常
  persist —— docker commit 固化为 med-audit:latest

用法：
    python scripts/deploy_hotfix_20260830.py backup
    python scripts/deploy_hotfix_20260830.py deploy <本地tar绝对路径>
    python scripts/deploy_hotfix_20260830.py verify
    python scripts/deploy_hotfix_20260830.py persist
"""

from __future__ import annotations

import os
import sys

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
CONTAINER = "med-audit"
REMOTE_TAR = "/root/hotfix_20260830.tar.gz"
ROLLBACK_TAG = "med-audit:rollback-pre-hotfix-20260830"


def connect() -> paramiko.SSHClient:
    password = os.environ.get("MED_AUDIT_SSH_PASSWORD", "")
    if not password:
        print("[FATAL] MED_AUDIT_SSH_PASSWORD 未设置")
        sys.exit(2)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=password, timeout=20)
    return client


def run(client: paramiko.SSHClient, desc: str, cmd: str, check: bool = True) -> bool:
    print(f"\n=== {desc}\n$ {cmd}")
    _, stdout, stderr = client.exec_command(cmd, timeout=180)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out:
        print(out[-3000:])
    if err:
        print("[stderr]", err[-1500:])
    if check and code != 0:
        print(f"[FAIL] {desc} 退出码={code}")
        return False
    print(f"[ok] {desc}")
    return True


def main(argv: list) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    stage = argv[1]
    client = connect()
    try:
        if stage == "backup":
            ok = run(client, "容器内 prearchive_service 备份(回滚点1)",
                     f"docker exec {CONTAINER} tar czf /tmp/prearchive_backup_20260830.tar.gz "
                     f"-C /app prearchive_service")
            ok &= run(client, "备份拖回服务器 /root/",
                      f"docker cp {CONTAINER}:/tmp/prearchive_backup_20260830.tar.gz /root/")
            ok &= run(client, "回滚镜像 tag(回滚点2)",
                      f"docker commit -m 'rollback point before hotfix 20260830' "
                      f"{CONTAINER} {ROLLBACK_TAG}")
            return 0 if ok else 1

        if stage == "deploy":
            local_tar = argv[2]
            size_mb = os.path.getsize(local_tar) / 1048576
            print(f"上传 {local_tar}（{size_mb:.1f} MB）→ {REMOTE_TAR}")
            sftp = client.open_sftp()
            sftp.put(local_tar, REMOTE_TAR)
            sftp.close()
            print("[ok] 上传完成")
            ok = run(client, "tar 进容器", f"docker cp {REMOTE_TAR} {CONTAINER}:/tmp/")
            ok &= run(client, "解包覆盖 /app",
                      f"docker exec {CONTAINER} tar xzf /tmp/hotfix_20260830.tar.gz -C /app")
            ok &= run(client, "清 __pycache__",
                      f"docker exec {CONTAINER} find /app -name '__pycache__' -type d "
                      f"-exec rm -rf {{}} + || true", check=False)
            ok &= run(client, "重启容器", f"docker restart {CONTAINER}")
            return 0 if ok else 1

        if stage == "verify":
            ok = run(client, "容器运行状态",
                     f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}}'")
            ok &= run(client, "健康接口",
                      f"docker exec {CONTAINER} python -c "
                      "\"import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=10).status)\"")
            ok &= run(client, "预检模块导入检查(034 新代码)",
                      f"docker exec {CONTAINER} python -c "
                      "\"import sys;sys.path.insert(0,'/app/prearchive_service');"
                      "import prearchive.collectors as c;import prearchive.his_base as h;"
                      "import prearchive.receivers as r;"
                      "print('SqlBlGateway table ok:', 'dbo.T_ITF_BL' in c.SqlBlGateway.ITF_SQL);"
                      "print('SqlQgjGateway quoted ok:', '\\\"T_ITF_HisQuery\\\"' in c.SqlQgjGateway.ITF_SQL);"
                      "print('xt sql no IDNo ok:', 'IDNo' not in c.SqlXtGateway.ITF_SQL);"
                      "print('HisBaseUserIdMapper ok:', hasattr(r,'HisBaseUserIdMapper'));"
                      "print('SqlHisBaseGateway views ok:', 'hisuser.VW_user_info' in h.SqlHisBaseGateway.USER_SQL)\"")
            ok &= run(client, "预检规则视图可用",
                      f"docker exec {CONTAINER} python -c "
                      "\"import sys;sys.path.insert(0,'/app');"
                      "from app.services.prearchive_rules_view import load_prearchive_rules_view;"
                      "v=load_prearchive_rules_view('/app/prearchive_service/rules');"
                      "print('available=',v['available']);"
                      "print([ (c['key'],len(c['rules'])) for c in v['categories'] ])\"")
            ok &= run(client, "启动日志无异常",
                      f"docker logs --since 3m {CONTAINER} 2>&1 | grep -iE 'traceback|error' | head -5 || true",
                      check=False)
            return 0 if ok else 1

        if stage == "persist":
            ok = run(client, "固化镜像 med-audit:latest",
                     f"docker commit -m 'hotfix 20260830: 034 T8-2b four-source collectors + T8-3 hisbase wiring' "
                     f"{CONTAINER} med-audit:latest")
            ok &= run(client, "镜像清单",
                      "docker images med-audit --format '{{.Tag}} {{.ID}} {{.CreatedSince}}'")
            return 0 if ok else 1

        print(f"未知阶段: {stage}")
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
