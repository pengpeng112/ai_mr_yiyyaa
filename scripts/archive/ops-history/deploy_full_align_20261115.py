# -*- coding: utf-8 -*-
"""生产部署脚本（2026-11-15 第三轮，用户任务书授权：全链路修复+版本对齐+体检冒烟）。

变更面（相对当日第二轮 event-exempt 部署）：
  - app/ 全量对齐：107 个差异文件 + 新增 oracle_patient_view_compat.py（V_QYBR 降级免疫）
  - static/ui-next/             前端重建产物（P1 全站精修）
阶段：backup / deploy <tar> / verify / persist。
口令只从环境变量 MED_AUDIT_SSH_PASSWORD 读取，不落仓库。
"""

from __future__ import annotations

import os
import sys
import time

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
CONTAINER = "med-audit"
REMOTE_TAR = "/root/full_align_20261115.tar.gz"
BACKUP_APP_TAR = "/root/backup_app_full_20261115.tar.gz"
ROLLBACK_TAG = "med-audit:backup-pre-full-align-20261115"


def connect() -> paramiko.SSHClient:
    password = os.environ.get("MED_AUDIT_SSH_PASSWORD", "")
    if not password:
        print("[FATAL] MED_AUDIT_SSH_PASSWORD 未设置")
        sys.exit(2)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=password, timeout=20)
    return client


def run(client: paramiko.SSHClient, desc: str, cmd: str, check: bool = True, timeout: int = 300) -> tuple[bool, str]:
    print(f"\n=== {desc}\n$ {cmd[:160]}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out:
        print(out[-3500:])
    if err:
        print("[stderr]", err[-1200:])
    if check and code != 0:
        print(f"[FAIL] {desc} 退出码={code}")
        return False, out
    return True, out


def phase_backup(client: paramiko.SSHClient) -> None:
    ok, _ = run(client, "回滚镜像 tag（当日第二轮镜像 a33a44782087）",
                f"docker tag {CONTAINER}:latest {ROLLBACK_TAG} && docker images | grep full-align")
    if not ok:
        sys.exit(1)
    ok, _ = run(client, "容器内 app/ 全量文件备份",
                f"docker exec {CONTAINER} tar czf /tmp/backup_app_full.tar.gz -C /app app",
                timeout=300)
    if not ok:
        sys.exit(1)
    ok, _ = run(client, "备份拖回宿主机",
                f"docker cp {CONTAINER}:/tmp/backup_app_full.tar.gz {BACKUP_APP_TAR} && ls -la {BACKUP_APP_TAR}")
    if not ok:
        sys.exit(1)
    print(f"\n[backup OK] 回滚点：镜像 {ROLLBACK_TAG} + 文件 {BACKUP_APP_TAR}")


def phase_deploy(client: paramiko.SSHClient, local_tar: str) -> None:
    if not os.path.isfile(local_tar):
        print(f"[FATAL] 本地包不存在: {local_tar}")
        sys.exit(2)
    sftp = client.open_sftp()
    print(f"\n=== 上传 {local_tar} -> {REMOTE_TAR}")
    sftp.put(local_tar, REMOTE_TAR)
    sftp.close()
    print("上传完成", os.path.getsize(local_tar), "bytes")
    for desc, cmd, timeout in [
        ("tar 拖入容器", f"docker cp {REMOTE_TAR} {CONTAINER}:/tmp/deploy_full_align.tar.gz", 120),
        ("解包覆盖（108 文件 → /app）", f"docker exec {CONTAINER} tar xzf /tmp/deploy_full_align.tar.gz -C /app", 180),
        ("清 __pycache__（app 全树）",
         f"docker exec {CONTAINER} sh -c 'find /app/app -name __pycache__ -type d -not -path \"*/node_modules/*\" | xargs -r rm -rf'", 120),
        ("重启容器", f"docker restart {CONTAINER}", 120),
    ]:
        ok, _ = run(client, desc, cmd, timeout=timeout)
        if not ok:
            sys.exit(1)
    print("\n[deploy OK] 容器已重启")


def phase_verify(client: paramiko.SSHClient) -> bool:
    all_ok = True

    def step(desc: str, cmd: str, expect: str, timeout: int = 120) -> None:
        nonlocal all_ok
        ok, out = run(client, desc, cmd, check=False, timeout=timeout)
        passed = ok and expect in out
        print(f"[{'PASS' if passed else 'FAIL'}] 期望包含 {expect!r}")
        all_ok = all_ok and passed

    step("容器运行状态", f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}}'", "Up")
    step("健康接口", "curl -s -m 10 http://localhost:8000/api/health/live", '"status"')
    step("根入口 302 → /ui-next/", "curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -m 10 http://localhost:8000/", "/ui-next/")
    step(
        "兼容降级模块已加载（V_QYBR 免疫）",
        f"docker exec {CONTAINER} python -c \"from app.services.oracle_patient_view_compat import inline_patient_visit_view, PATIENT_VIEW_COLUMNS; v=inline_patient_visit_view(discharged_only=True); print('compat-cols', len(PATIENT_VIEW_COLUMNS), 'pushdown', chr(39)+'出院日期'+chr(39)+' IS NOT NULL' in v)\"",
        "compat-cols 40 pushdown True",
    )
    step(
        "bcrypt 修复生效（hash/verify 互通）",
        f"docker exec {CONTAINER} python -c \"from app.auth import hash_password, verify_password; h=hash_password('probe-pwd'); print('bcrypt-ok', verify_password('probe-pwd', h), not verify_password('wrong', h))\"",
        "bcrypt-ok True True",
    )
    step(
        "菜单目录 22 项 + 审批中心",
        f"docker exec {CONTAINER} python -c \"from app.routers.menu import MENU_CATALOG; print('catalog', len(MENU_CATALOG))\"",
        "catalog 22",
    )
    step(
        "V_QYBR 现状只读冒烟（视图当前 OK；降级 SQL 可在容器内编译）",
        "docker cp /tmp/vqybr_smoke_20261115.py med-audit:/tmp/vqybr_smoke.py && docker exec med-audit python /tmp/vqybr_smoke.py && docker exec med-audit rm -f /tmp/vqybr_smoke.py",
        "SMOKE_OK",
        timeout=300,
    )
    step(
        "TIMELINESS 写闸保持关闭（False/False/LOG_ONLY/None）",
        f"docker exec {CONTAINER} python -c \"import json; c=json.load(open('/app/config/config.json')); t=c.get('timeliness',{{}}); w=t.get('jhemr_write',{{}}); print('gate', w.get('enabled'), w.get('insert_monitor_enabled'), t.get('notify_mode'), t.get('oracle_lock_enabled'))\"",
        "gate False False LOG_ONLY None",
    )
    run(client, "启动日志尾部", f"docker logs --tail 20 {CONTAINER} 2>&1 | tail -20", check=False)
    print(f"\n[verify {'ALL PASS' if all_ok else 'HAS FAILURES'}]")
    return all_ok


def phase_persist(client: paramiko.SSHClient) -> None:
    ok, _ = run(
        client,
        "docker commit 固化",
        f"docker commit -m 'full-align+vqybr-compat 2026-11-15: 108-file backend alignment, V_QYBR degrade immunity, ORA-24459 pool backoff, bcrypt fix, ui-next P1 rebuild' {CONTAINER} {CONTAINER}:latest",
    )
    if not ok:
        sys.exit(1)
    run(client, "镜像确认", f"docker images | grep -E 'med-audit\\s+(latest|backup-pre-full-align)' | head -4")
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
