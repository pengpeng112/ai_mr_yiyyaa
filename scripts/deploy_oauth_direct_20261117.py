# -*- coding: utf-8 -*-
"""生产部署脚本（2026-11-17 第三轮，用户要求安全增强：OAuth 直签发 + 免登全局限流 + 外网最小暴露面基线）。

变更面（相对当日 reactive 部署）：
  - app/routers/mobile_timeliness.py  OAuth 回调直签发（Cookie 下发、Location 去凭证、HIS 回退）
                                      + 免登全局限流 60 次/分钟

阶段：backup / deploy <tar> / verify / persist（口令仅环境变量 MED_AUDIT_SSH_PASSWORD）。
"""
from __future__ import annotations

import os
import sys

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
CONTAINER = "med-audit"
REMOTE_TAR = "/root/oauth_direct_20261117.tar.gz"
BACKUP_TAR = "/root/backup_pre_oauth_direct_20261117.tar.gz"
ROLLBACK_TAG = "med-audit:backup-pre-oauth-direct-20261117"


def connect() -> paramiko.SSHClient:
    password = os.environ.get("MED_AUDIT_SSH_PASSWORD", "")
    if not password:
        print("[FATAL] MED_AUDIT_SSH_PASSWORD 未设置")
        sys.exit(2)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=password, timeout=20)
    return client


def run(client, desc, cmd, check=True, timeout=180):
    print(f"\n=== {desc}\n$ {cmd[:150]}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out:
        print(out[-3000:])
    if err:
        print("[stderr]", err[-800:])
    if check and code != 0:
        print(f"[FAIL] {desc} exit={code}")
        return False, out
    return True, out


def phase_backup(client) -> None:
    ok, _ = run(client, "回滚镜像 tag",
                f"docker tag {CONTAINER}:latest {ROLLBACK_TAG} && docker images | grep oauth-direct")
    if not ok:
        sys.exit(1)
    ok, _ = run(client, "被覆盖文件打包",
                f"docker exec {CONTAINER} tar czf /tmp/backup_oauth.tar.gz -C /app app/routers/mobile_timeliness.py")
    if not ok:
        sys.exit(1)
    ok, _ = run(client, "备份拖回宿主机",
                f"docker cp {CONTAINER}:/tmp/backup_oauth.tar.gz {BACKUP_TAR} && ls -la {BACKUP_TAR}")
    if not ok:
        sys.exit(1)
    print(f"\n[backup OK] rollback: {ROLLBACK_TAG} + {BACKUP_TAR}")


def phase_deploy(client, local_tar) -> None:
    if not os.path.isfile(local_tar):
        print(f"[FATAL] missing local tar: {local_tar}")
        sys.exit(2)
    sftp = client.open_sftp()
    sftp.put(local_tar, REMOTE_TAR)
    sftp.close()
    print("uploaded", os.path.getsize(local_tar), "bytes")
    for desc, cmd in [
        ("tar cp", f"docker cp {REMOTE_TAR} {CONTAINER}:/tmp/deploy_oauth.tar.gz"),
        ("extract", f"docker exec {CONTAINER} tar xzf /tmp/deploy_oauth.tar.gz -C /app"),
        ("pycache", f"docker exec {CONTAINER} sh -c 'rm -rf /app/app/__pycache__ /app/app/routers/__pycache__'"),
        ("restart", f"docker restart {CONTAINER}"),
    ]:
        ok, _ = run(client, desc, cmd)
        if not ok:
            sys.exit(1)
    print("\n[deploy OK]")


def phase_verify(client) -> bool:
    all_ok = True

    def step(desc, cmd, expect):
        nonlocal all_ok
        ok, out = run(client, desc, cmd, check=False)
        passed = ok and expect in out
        print("[PASS]" if passed else "[FAIL]", "expect", repr(expect))
        all_ok = all_ok and passed

    step("container up", f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}}'", "Up")
    step("health", "curl -s -m 10 http://localhost:8000/api/health/live", '"status"')
    step("page 200 via :3000",
         "curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:3000/mobile/qc/timeliness", "200")
    step("oauth callback bare-redirect w/o creds",
         "curl -s -o /dev/null -w '%{http_code}' -m 15 'http://127.0.0.1:3000/mobile/qc/timeliness/oauth/wecom/callback?code=x'",
         "302")
    step("direct-issue source present",
         f"docker exec {CONTAINER} grep -c 'redirect.set_cookie' /app/app/routers/mobile_timeliness.py", "2")
    step("legacy empno concat removed",
         f"docker exec {CONTAINER} sh -c 'grep -c \"?empno={{userid}}\" /app/app/routers/mobile_timeliness.py || true'", "0")
    step("global ip limit loaded",
         f"docker exec {CONTAINER} python -c \"from app.routers.mobile_timeliness import _IP_MAX_ATTEMPTS; print('ip-limit', _IP_MAX_ATTEMPTS)\"",
         "ip-limit 60")
    step("empno login 003966 via :3000",
         "curl -s -o /dev/null -w '%{http_code}' -m 20 -X POST http://127.0.0.1:3000/api/mobile/timeliness/login/empno -H 'Content-Type: application/json' -H 'X-Requested-With: XMLHttpRequest' -d '{\"empno\":\"003966\"}'",
         "200")
    step("write gates unchanged",
         f"docker exec {CONTAINER} python -c \"import json; c=json.load(open('/app/config/config.json')); t=c.get('timeliness',{{}}); w=t.get('jhemr_write',{{}}); print('gate', w.get('enabled'), w.get('insert_monitor_enabled'), t.get('notify_mode'), t.get('oracle_lock_enabled'))\"",
         "gate False False LOG_ONLY None")
    run(client, "startup log tail", f"docker logs --tail 10 {CONTAINER} 2>&1 | tail -10", check=False)
    print(f"\n[verify {'ALL PASS' if all_ok else 'HAS FAILURES'}]")
    return all_ok


def phase_persist(client) -> None:
    ok, _ = run(client, "docker commit",
                f"docker commit -m 'feat(mobile): wecom OAuth direct session issue + global login rate limit + minimal exposure baseline' {CONTAINER} {CONTAINER}:latest")
    if not ok:
        sys.exit(1)
    run(client, "images",
        f"docker images | grep -E 'med-audit.(latest|backup-pre-oauth-direct)' | head -4")
    print("\n[persist OK]")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    phase = sys.argv[1]
    client = connect()
    try:
        if phase == "backup":
            phase_backup(client)
        elif phase == "deploy":
            if len(sys.argv) < 3:
                print("[FATAL] deploy needs tar path")
                sys.exit(2)
            phase_deploy(client, sys.argv[2])
        elif phase == "verify":
            phase_verify(client)
        elif phase == "persist":
            phase_persist(client)
        else:
            print("[FATAL] unknown phase", phase)
            sys.exit(2)
    finally:
        client.close()


if __name__ == "__main__":
    main()
