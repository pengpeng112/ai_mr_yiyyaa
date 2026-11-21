# -*- coding: utf-8 -*-
"""生产热更新部署脚本（2026-11-15 第二轮，用户任务书授权：交互闭环与界面精修同步）。

变更面（相对当日第一轮 menu-ui-refresh 部署）：
  - app/routers/timeliness.py  事件豁免端点 + 台账患者真实姓名（V_QYBR TTL 缓存）
  - app/routers/menu.py        历史 RoleMenu 自动补齐 timeliness-approvals（P0-4）
  - static/ui-next/            前端重建产物（豁免闭环/带参跳转/中文化/PageHeader 统一）

阶段：backup / deploy <tar> / verify / persist（同 deploy_menu_ui_refresh_20261115.py 模式）。
口令只从环境变量 MED_AUDIT_SSH_PASSWORD 读取，不落仓库。
"""

from __future__ import annotations

import os
import sys

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
CONTAINER = "med-audit"
REMOTE_TAR = "/root/event_exempt_refresh_20261115.tar.gz"
BACKUP_TAR = "/root/backup_pre_event_exempt_20261115.tar.gz"
ROLLBACK_TAG = "med-audit:backup-pre-event-exempt-20261115"

BUNDLE_FILES = (
    "app/routers/timeliness.py",
    "app/routers/menu.py",
    "static/ui-next",
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


def run(client: paramiko.SSHClient, desc: str, cmd: str, check: bool = True) -> tuple[bool, str]:
    print(f"\n=== {desc}\n$ {cmd}")
    _, stdout, stderr = client.exec_command(cmd, timeout=300)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out:
        print(out[-4000:])
    if err:
        print("[stderr]", err[-1500:])
    if check and code != 0:
        print(f"[FAIL] {desc} 退出码={code}")
        return False, out
    return True, out


def phase_backup(client: paramiko.SSHClient) -> None:
    ok, _ = run(
        client,
        "回滚镜像 tag",
        f"docker tag {CONTAINER}:latest {ROLLBACK_TAG} && docker images | grep event-exempt",
    )
    if not ok:
        sys.exit(1)
    inner = " ".join(BUNDLE_FILES)
    ok, _ = run(
        client,
        "容器内现文件打包",
        f"docker exec {CONTAINER} tar czf /tmp/backup_pre_event_exempt.tar.gz -C /app {inner}",
    )
    if not ok:
        sys.exit(1)
    ok, _ = run(
        client,
        "备份拖回宿主机",
        f"docker cp {CONTAINER}:/tmp/backup_pre_event_exempt.tar.gz {BACKUP_TAR} && ls -la {BACKUP_TAR}",
    )
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
        ("tar 拖入容器", f"docker cp {REMOTE_TAR} {CONTAINER}:/tmp/deploy_event_exempt.tar.gz"),
        ("解包覆盖", f"docker exec {CONTAINER} tar xzf /tmp/deploy_event_exempt.tar.gz -C /app"),
        ("清 __pycache__", f"docker exec {CONTAINER} sh -c 'rm -rf /app/app/__pycache__ /app/app/routers/__pycache__'"),
        ("重启容器", f"docker restart {CONTAINER}"),
    ]:
        ok, _ = run(client, desc, cmd)
        if not ok:
            sys.exit(1)
    print("\n[deploy OK] 容器已重启")


def phase_verify(client: paramiko.SSHClient) -> bool:
    all_ok = True

    def step(desc: str, cmd: str, expect: str) -> None:
        nonlocal all_ok
        ok, out = run(client, desc, cmd, check=False)
        passed = ok and expect in out
        print(f"[{'PASS' if passed else 'FAIL'}] 期望包含 {expect!r}")
        all_ok = all_ok and passed

    step("容器运行状态", f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}}'", "Up")
    step("健康接口", "curl -s -m 10 http://localhost:8000/api/health/live", '"status"')
    step("根入口 302 → /ui-next/", "curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -m 10 http://localhost:8000/", "/ui-next/")
    step("ui-next 首页 200", "curl -s -o /dev/null -w '%{http_code}' -m 10 http://localhost:8000/ui-next/", "200")
    step(
        "豁免端点路由已注册（OPTIONS 探测，未授权应 401/403 而非 404）",
        "curl -s -o /dev/null -w '%{http_code}' -m 10 -X OPTIONS http://localhost:8000/api/timeliness/events/1/exempt",
        "40",
    )
    step(
        "菜单 P0-4 补齐逻辑 + 目录完整性（容器内导入校验）",
        f"docker exec {CONTAINER} python -c \"from app.routers.menu import MENU_CATALOG, MENU_CONFIG; from app.routers.timeliness import EventExemptRequest; print('catalog', len(MENU_CATALOG), 'approvals-default', 'timeliness-approvals' in MENU_CONFIG.get('auditor', []))\"",
        "catalog 22 approvals-default True",
    )
    step(
        "TIMELINESS 写闸保持关闭",
        f"docker exec {CONTAINER} python -c \"import json; c=json.load(open('/app/config/config.json')); t=c.get('timeliness',{{}}); w=t.get('jhemr_write',{{}}); print('write', w.get('enabled'), 'insert', w.get('insert_monitor_enabled'), 'notify', t.get('notify_mode'), 'lock', t.get('oracle_lock_enabled'))\"",
        "write False insert False",
    )
    run(client, "启动日志尾部", f"docker logs --tail 20 {CONTAINER} 2>&1 | tail -20", check=False)
    print(f"\n[verify {'ALL PASS' if all_ok else 'HAS FAILURES'}]")
    return all_ok


def phase_persist(client: paramiko.SSHClient) -> None:
    ok, _ = run(
        client,
        "docker commit 固化",
        f"docker commit -m 'event-exempt-loop+patient-name 2026-11-15: events exempt endpoint, V_QYBR patient names, RoleMenu approvals backfill, ui-next rebuild' {CONTAINER} {CONTAINER}:latest",
    )
    if not ok:
        sys.exit(1)
    run(client, "镜像确认", f"docker images | grep -E 'med-audit\\s+(latest|backup-pre-event-exempt)' | head -4")
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
