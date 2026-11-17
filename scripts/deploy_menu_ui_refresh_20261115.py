# -*- coding: utf-8 -*-
"""生产热更新部署脚本（2026-11-15，用户当次授权：同步菜单重构/ui-next 默认入口到 84 容器）。

变更面（相对 2026-11-14 影子部署后生产状态）：
  - app/main.py                默认前端入口 legacy → ui-next（仅显式 legacy 回退；/ 302）
  - app/routers/menu.py        菜单 6 组→5 组、21→22 项（+timeliness-approvals）、角色矩阵
  - app/routers/timeliness.py  台账中文字段（monitor_code→规则名反查、patient_name/inp_no 占位）
  - static/ui-next/            前端重建产物（5 大分组侧栏、审批中心页、AuditTypes 双页签等）

阶段：
  backup  —— 容器内现文件 tar 备份拖回 /root/ + 回滚镜像 tag
  inspect —— 容器 env（UI_DEFAULT_ENTRY/TIMELINESS 锁）与宿主机 compose 检查
  deploy  —— 上传 tar → docker cp → 解包覆盖 → 清 __pycache__ → 重启
  verify  —— 容器状态/健康接口/根入口 302/ui-next 200/菜单目录导入/启动日志
  persist —— docker commit 固化为 med-audit:latest

口令只从环境变量 MED_AUDIT_SSH_PASSWORD 读取，不落仓库。
用法：
    python scripts/deploy_menu_ui_refresh_20261115.py backup
    python scripts/deploy_menu_ui_refresh_20261115.py inspect
    python scripts/deploy_menu_ui_refresh_20261115.py deploy <本地tar绝对路径>
    python scripts/deploy_menu_ui_refresh_20261115.py verify
    python scripts/deploy_menu_ui_refresh_20261115.py persist
"""

from __future__ import annotations

import os
import sys

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
CONTAINER = "med-audit"
REMOTE_TAR = "/root/menu_ui_refresh_20261115.tar.gz"
BACKUP_TAR = "/root/backup_pre_menu_refresh_20261115.tar.gz"
ROLLBACK_TAG = "med-audit:backup-pre-menu-refresh-20261115"
COMPOSE_DIR = "/opt/med-audit-docker"

BUNDLE_FILES = (
    "app/main.py",
    "app/routers/menu.py",
    "app/routers/timeliness.py",
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
        "回滚镜像 tag（当前 latest 固化为备份点）",
        f"docker tag {CONTAINER}:latest {ROLLBACK_TAG} && docker images | grep menu-refresh",
    )
    if not ok:
        sys.exit(1)
    inner = " ".join(BUNDLE_FILES)
    ok, _ = run(
        client,
        "容器内现文件打包",
        f"docker exec {CONTAINER} tar czf /tmp/backup_pre_menu_refresh.tar.gz -C /app {inner}",
    )
    if not ok:
        sys.exit(1)
    ok, _ = run(
        client,
        "备份拖回宿主机",
        f"docker cp {CONTAINER}:/tmp/backup_pre_menu_refresh.tar.gz {BACKUP_TAR} && ls -la {BACKUP_TAR}",
    )
    if not ok:
        sys.exit(1)
    print(f"\n[backup OK] 回滚点：镜像 {ROLLBACK_TAG} + 文件 {BACKUP_TAR}")


def phase_inspect(client: paramiko.SSHClient) -> dict[str, str]:
    info: dict[str, str] = {}
    _, env = run(
        client,
        "容器 env（UI 默认入口 / 时效写锁）",
        f"docker exec {CONTAINER} env | grep -E 'UI_DEFAULT_ENTRY|TIMELINESS' || echo '(no match)'",
        check=False,
    )
    info["env"] = env
    _, compose = run(
        client,
        "宿主机 compose UI_DEFAULT_ENTRY 行",
        f"grep -n 'UI_DEFAULT_ENTRY' {COMPOSE_DIR}/docker-compose.yml || echo '(compose 无该键)'",
        check=False,
    )
    info["compose"] = compose
    run(client, "容器当前状态", f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}}'")
    return info


def phase_deploy(client: paramiko.SSHClient, local_tar: str) -> None:
    if not os.path.isfile(local_tar):
        print(f"[FATAL] 本地包不存在: {local_tar}")
        sys.exit(2)
    sftp = client.open_sftp()
    print(f"\n=== 上传 {local_tar} -> {REMOTE_TAR}")
    sftp.put(local_tar, REMOTE_TAR)
    sftp.close()
    print("上传完成", os.path.getsize(local_tar), "bytes")
    ok, _ = run(
        client,
        "tar 拖入容器",
        f"docker cp {REMOTE_TAR} {CONTAINER}:/tmp/deploy_menu_ui_refresh.tar.gz",
    )
    if not ok:
        sys.exit(1)
    ok, _ = run(
        client,
        "解包覆盖（-C /app，覆盖 3 个 py + static/ui-next）",
        f"docker exec {CONTAINER} tar xzf /tmp/deploy_menu_ui_refresh.tar.gz -C /app",
    )
    if not ok:
        sys.exit(1)
    ok, _ = run(
        client,
        "清理受影响模块 __pycache__（app / app/routers）",
        f"docker exec {CONTAINER} sh -c 'rm -rf /app/app/__pycache__ /app/app/routers/__pycache__'",
    )
    if not ok:
        sys.exit(1)
    ok, _ = run(client, "重启容器（单 worker，加载新代码）", f"docker restart {CONTAINER}")
    if not ok:
        sys.exit(1)
    print("\n[deploy OK] 容器已重启，进入 verify")


def phase_verify(client: paramiko.SSHClient) -> bool:
    all_ok = True

    def step(desc: str, cmd: str, expect: str) -> None:
        nonlocal all_ok
        ok, out = run(client, desc, cmd, check=False)
        passed = ok and expect in out
        print(f"[{'PASS' if passed else 'FAIL'}] 期望包含 {expect!r}")
        all_ok = all_ok and passed

    step("容器运行状态", f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}}'", "up")
    step("健康接口", "curl -s -m 10 http://localhost:8000/api/health/live", '"status"')
    step("根入口默认 302 → /ui-next/", "curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -m 10 http://localhost:8000/", "/ui-next/")
    step("ui-next 首页 200", "curl -s -o /dev/null -w '%{http_code}' -m 10 http://localhost:8000/ui-next/", "200")
    step(
        "菜单目录 22 项 + 5 分组（容器内导入校验）",
        f"docker exec {CONTAINER} python -c \"from app.routers.menu import MENU_CATALOG, MENU_GROUPS; print('catalog', len(MENU_CATALOG), 'groups', len(MENU_GROUPS), 'approvals', any(i['id']=='timeliness-approvals' for i in MENU_CATALOG), 'hidden', [i['id'] for i in MENU_CATALOG if i.get('hidden')])\"",
        "catalog 22 groups 5 approvals True",
    )
    step(
        "根入口解析默认 ui-next（容器内）",
        f"docker exec {CONTAINER} python -c \"import os; os.environ.pop('UI_DEFAULT_ENTRY', None); from app.main import resolve_ui_default_entry; print('entry', resolve_ui_default_entry())\"",
        "entry ui-next",
    )
    ok, out = run(
        client,
        "TIMELINESS 写锁保持关闭（env + 运行时）",
        f"docker exec {CONTAINER} sh -c \"env | grep TIMELINESS_ORACLE_LOCK_ENABLED || echo env-not-set\" ; docker exec {CONTAINER} python -c \"import json; c=json.load(open('/app/config/config.json')); t=c.get('timeliness',{{}}); w=t.get('jhemr_write',{{}}); print('lock_enabled', t.get('oracle_lock_enabled'), 'write_enabled', w.get('enabled'), 'insert_monitor', w.get('insert_monitor_enabled'))\"",
        check=False,
    )
    passed = "true" not in out.lower().replace("env-not-set", "") or ("lock_enabled" in out and ("lock_enabled False" in out or "lock_enabled None" in out))
    print(f"[{'PASS' if passed else 'FAIL'}] 锁开关检查输出见上（期望 env-not-set 且 lock 关）")
    all_ok = all_ok and passed
    run(client, "启动日志尾部（确认无异常栈）", f"docker logs --tail 25 {CONTAINER} 2>&1 | tail -25", check=False)
    print(f"\n[verify {'ALL PASS' if all_ok else 'HAS FAILURES'}]")
    return all_ok


def phase_persist(client: paramiko.SSHClient) -> None:
    ok, _ = run(
        client,
        "docker commit 固化",
        f"docker commit -m 'menu-ui-refresh 2026-11-15: 5-group menu/22 items, ui-next default entry, timeliness display fields' {CONTAINER} {CONTAINER}:latest",
    )
    if not ok:
        sys.exit(1)
    run(client, "镜像确认", f"docker images | grep -E 'med-audit\\s+(latest|backup-pre-menu-refresh)' | head -4")
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
        elif phase == "inspect":
            phase_inspect(client)
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
