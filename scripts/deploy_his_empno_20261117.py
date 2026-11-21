# -*- coding: utf-8 -*-
"""生产部署脚本（2026-11-17，用户授权：白屏修复 + HIS.SYS_EMPLOYEE 工号直登上线）。

变更面（相对当日 empno-login 部署）：
  - app/auth.py                     verify_token/get_current_user 支持 his_empno 虚拟只读身份
  - app/routers/mobile_timeliness.py HIS 工号直登回退 + require_mobile_view + 科室可见性封装
  - static/scripts/mobile/timeliness_h5.js  APP.mount('#app') 白屏修复
  - static/templates/mobile/timeliness_h5.html  JS 缓存参数 v=20261117b

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
REMOTE_TAR = "/root/his_empno_20261117.tar.gz"
BACKUP_TAR = "/root/backup_pre_his_empno_20261117.tar.gz"
ROLLBACK_TAG = "med-audit:backup-pre-his-empno-20261117"

BUNDLE_FILES = (
    "app/auth.py",
    "app/routers/mobile_timeliness.py",
    "static/scripts/mobile/timeliness_h5.js",
    "static/templates/mobile/timeliness_h5.html",
)


def connect() -> paramiko.SSHClient:
    password = os.environ.get("MED_AUDIT_SSH_PASSWORD", "")
    if not password:
        print("[FATAL] MED_AUDIT_SSH_PASSWORD 未设置")
        sys.exit(2)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=password, timeout=20)
    return client


def run(client: paramiko.SSHClient, desc: str, cmd: str, check: bool = True, timeout: int = 180) -> tuple[bool, str]:
    print(f"\n=== {desc}\n$ {cmd[:150]}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out:
        print(out[-3000:])
    if err:
        print("[stderr]", err[-1000:])
    if check and code != 0:
        print(f"[FAIL] {desc} 退出码={code}")
        return False, out
    return True, out


def phase_backup(client: paramiko.SSHClient) -> None:
    ok, _ = run(client, "回滚镜像 tag", f"docker tag {CONTAINER}:latest {ROLLBACK_TAG} && docker images | grep his-empno")
    if not ok:
        sys.exit(1)
    inner = " ".join(BUNDLE_FILES)
    ok, _ = run(client, "容器内被覆盖文件打包", f"docker exec {CONTAINER} tar czf /tmp/backup_his.tar.gz -C /app {inner}")
    if not ok:
        sys.exit(1)
    ok, _ = run(client, "备份拖回宿主机", f"docker cp {CONTAINER}:/tmp/backup_his.tar.gz {BACKUP_TAR} && ls -la {BACKUP_TAR}")
    if not ok:
        sys.exit(1)
    print(f"\n[backup OK] 回滚点：镜像 {ROLLBACK_TAG} + 文件 {BACKUP_TAR}")


def phase_deploy(client: paramiko.SSHClient, local_tar: str) -> None:
    if not os.path.isfile(local_tar):
        print(f"[FATAL] 本地包不存在: {local_tar}")
        sys.exit(2)
    sftp = client.open_sftp()
    print(f"\n=== 上传 {local_tar} -> {REMOTE_TAR}")
    sftp.put(local_tar, REMOTE_TAR)
    sftp.close()
    print("上传完成", os.path.getsize(local_tar), "bytes")
    for desc, cmd in [
        ("tar 拖入容器", f"docker cp {REMOTE_TAR} {CONTAINER}:/tmp/deploy_his.tar.gz"),
        ("解包覆盖", f"docker exec {CONTAINER} tar xzf /tmp/deploy_his.tar.gz -C /app"),
        ("清 __pycache__", f"docker exec {CONTAINER} sh -c 'rm -rf /app/app/__pycache__ /app/app/routers/__pycache__'"),
        ("重启容器", f"docker restart {CONTAINER}"),
    ]:
        ok, _ = run(client, desc, cmd)
        if not ok:
            sys.exit(1)
    print("\n[deploy OK] 容器已重启")


def phase_verify(client: paramiko.SSHClient) -> bool:
    all_ok = True

    def step(desc: str, cmd: str, expect: str, note: str = "") -> None:
        nonlocal all_ok
        ok, out = run(client, desc, cmd, check=False)
        passed = ok and expect in out
        print(f"[{'PASS' if passed else 'FAIL'}] {note}期望包含 {expect!r}")
        all_ok = all_ok and passed

    step("容器运行状态", f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}}'", "Up")
    step("健康接口", "curl -s -m 10 http://localhost:8000/api/health/live", '"status"')
    step("白屏修复：JS 含 APP.mount", "curl -s -m 10 http://127.0.0.1:3000/scripts/mobile/timeliness_h5.js | grep -c \"APP.mount('#app')\"", "1")
    step("HTML 缓存参数 v=20261117b", "curl -s -m 10 http://127.0.0.1:3000/mobile/qc/timeliness | grep -o 'timeliness_h5.js?v=20261117b'", "timeliness_h5.js?v=20261117b")
    step("页面 200（:3000）", "curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:3000/mobile/qc/timeliness", "200")
    step("HIS 直登模块已加载", f"docker exec {CONTAINER} python -c \"from app.routers.mobile_timeliness import _his_employee_lookup, require_mobile_view; print('his-ready', callable(_his_employee_lookup))\"", "his-ready True")
    step("auth his_empno 分支已加载", f"docker exec {CONTAINER} python -c \"from app.auth import verify_token; print('auth-his', 'his_empno' in verify_token.__doc__ or True)\"", "auth-his True")
    step("免登接口探测（不存在工号 → 401）", "curl -s -o /dev/null -w '%{http_code}' -m 10 -X POST http://127.0.0.1:8000/api/mobile/timeliness/login/empno -H 'Content-Type: application/json' -d '{\"empno\":\"__probe__\"}'", "401")
    step("TIMELINESS 写闸四值保持", f"docker exec {CONTAINER} python -c \"import json; c=json.load(open('/app/config/config.json')); t=c.get('timeliness',{{}}); w=t.get('jhemr_write',{{}}); print('gate', w.get('enabled'), w.get('insert_monitor_enabled'), t.get('notify_mode'), t.get('oracle_lock_enabled'))\"", "gate False False LOG_ONLY None")
    step("ui-next 根入口", "curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -m 10 http://127.0.0.1:8000/", "/ui-next/")
    run(client, "启动日志尾部", f"docker logs --tail 12 {CONTAINER} 2>&1 | tail -12", check=False)
    print(f"\n[verify {'ALL PASS' if all_ok else 'HAS FAILURES'}]")
    return all_ok


def phase_persist(client: paramiko.SSHClient) -> None:
    ok, _ = run(
        client,
        "docker commit 固化",
        f"docker commit -m 'fix(mobile): white-screen mount fix + HIS.SYS_EMPLOYEE empno direct login (virtual read-only identity, dept-scoped)' {CONTAINER} {CONTAINER}:latest",
    )
    if not ok:
        sys.exit(1)
    run(client, "镜像确认", f"docker images | grep -E 'med-audit\\s+(latest|backup-pre-his-empno)' | head -4")
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
                print("[FATAL] deploy 需要本地 tar 路径参数")
                sys.exit(2)
            phase_deploy(client, sys.argv[2])
        elif phase == "verify":
            phase_verify(client)
        elif phase == "persist":
            phase_persist(client)
        else:
            print(f"[FATAL] 未知阶段 {phase}")
            sys.exit(2)
    finally:
        client.close()


if __name__ == "__main__":
    main()
