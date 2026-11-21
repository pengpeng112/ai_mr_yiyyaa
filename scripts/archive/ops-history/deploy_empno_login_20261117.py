# -*- coding: utf-8 -*-
"""生产部署脚本（2026-11-16，用户任务书授权：企微手机端病历时效 H5 门户上线）。

变更面（相对 2026-11-16 mobile-timeliness 部署）：
  - app/routers/mobile_timeliness.py  新增 POST /login/empno 工号免登（开关/限流/8h JWT/Cookie/审计）
  - app/security_middleware.py        _CSRF_EXEMPT_PATHS 追加 /api/mobile/timeliness/login/empno
  - static/scripts/mobile/timeliness_h5.js  URL ?empno= 自动免登 + 失败回手动登录

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
REMOTE_TAR = "/root/empno_login_20261117.tar.gz"
BACKUP_TAR = "/root/backup_pre_empno_login_20261117.tar.gz"
ROLLBACK_TAG = "med-audit:backup-pre-empno-login-20261117"

BUNDLE_FILES = (
    "app/routers/mobile_timeliness.py",
    "app/security_middleware.py",
    "static/scripts/mobile/timeliness_h5.js",
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
        print(out[-3500:])
    if err:
        print("[stderr]", err[-1000:])
    if check and code != 0:
        print(f"[FAIL] {desc} 退出码={code}")
        return False, out
    return True, out


def phase_backup(client: paramiko.SSHClient) -> None:
    ok, _ = run(client, "回滚镜像 tag", f"docker tag {CONTAINER}:latest {ROLLBACK_TAG} && docker images | grep mobile-timeliness")
    if not ok:
        sys.exit(1)
    # 本轮三个文件容器内均已存在（2026-11-16 轮已部署 mobile_timeliness.py）
    inner = " ".join(BUNDLE_FILES)
    ok, _ = run(client, "容器内被覆盖文件打包（存量文件；新增文件无需备份）",
                f"docker exec {CONTAINER} tar czf /tmp/backup_mobile.tar.gz -C /app {inner}")
    if not ok:
        sys.exit(1)
    ok, _ = run(client, "备份拖回宿主机", f"docker cp {CONTAINER}:/tmp/backup_mobile.tar.gz {BACKUP_TAR} && ls -la {BACKUP_TAR}")
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
        ("tar 拖入容器", f"docker cp {REMOTE_TAR} {CONTAINER}:/tmp/deploy_mobile.tar.gz"),
        ("解包覆盖", f"docker exec {CONTAINER} tar xzf /tmp/deploy_mobile.tar.gz -C /app"),
        ("清 __pycache__", f"docker exec {CONTAINER} sh -c 'rm -rf /app/app/__pycache__ /app/app/routers/__pycache__'"),
        ("重启容器", f"docker restart {CONTAINER}"),
    ]:
        ok, _ = run(client, desc, cmd)
        if not ok:
            sys.exit(1)
    print("\n[deploy OK] 容器已重启")


def phase_verify(client: paramiko.SSHClient) -> bool:
    all_ok = True

    def step(desc: str, cmd: str, expect: str, port_note: str = "") -> None:
        nonlocal all_ok
        ok, out = run(client, desc, cmd, check=False)
        passed = ok and expect in out
        print(f"[{'PASS' if passed else 'FAIL'}] {port_note}期望包含 {expect!r}")
        all_ok = all_ok and passed

    step("容器运行状态", f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}}'", "Up")
    step("健康接口", "curl -s -m 10 http://localhost:8000/api/health/live", '"status"')

    # ---- 端口 8000 直连通道 ----
    step("H5 页面（:8000）", "curl -s -D - -m 10 http://127.0.0.1:8000/mobile/qc/timeliness | grep -c 'timeliness_h5.js' || true", "1", "[:8000] ")
    step("页面 no-store 缓存头（:8000）", "curl -s -D - -o /dev/null -m 10 http://127.0.0.1:8000/mobile/qc/timeliness | grep -c 'no-store'", "1", "[:8000] ")

    # ---- 宿主机 Nginx :3000 通道 ----
    step("H5 页面（:3000 Nginx 转发）", "curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:3000/mobile/qc/timeliness", "200", "[:3000] ")
    step("CSS（:3000）", "curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:3000/styles/mobile/timeliness_h5.css", "200", "[:3000] ")
    step("JS（:3000）", "curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:3000/scripts/mobile/timeliness_h5.js", "200", "[:3000] ")
    step("Vue 桥接（:3000）", "curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:3000/scripts/mobile/vue.global.prod.js", "200", "[:3000] ")
    step("ping（:3000）", "curl -s -m 10 http://127.0.0.1:3000/api/mobile/timeliness/ping", '"ok"', "[:3000] ")
    step("鉴权守卫 overview 未带 token（:3000）", "curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:3000/api/mobile/timeliness/overview", "403", "[:3000] ")
    step("原有血透首页不受影响（:3000 /）", "curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:3000/", "200", "[:3000] ")
    step("原有医生端 H5 不受影响（:3000 无 token）", "curl -s -o /dev/null -w '%{http_code}' -m 10 'http://127.0.0.1:3000/mobile/qc/1?token=invalid'", "401", "[:3000] ")
    step("ui-next 根入口（:8000）", "curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -m 10 http://127.0.0.1:8000/", "/ui-next/")

    step(
        "工号免登接口在线（不存在工号 → 401 校验生效）",
        "curl -s -o /dev/null -w '%{http_code}' -m 10 -X POST http://127.0.0.1:8000/api/mobile/timeliness/login/empno -H 'Content-Type: application/json' -d '{\"empno\":\"__probe_nonexistent__\"}'",
        "401",
    )
    step(
        "工号免登 CSRF 豁免已加载（security_middleware 静态断言）",
        f"docker exec {CONTAINER} python -c \"from app.security_middleware import _CSRF_EXEMPT_PATHS; print('empno-exempt', '/api/mobile/timeliness/login/empno' in _CSRF_EXEMPT_PATHS)\"",
        "empno-exempt True",
    )
    step(
        "TIMELINESS 写闸四值保持（False/False/LOG_ONLY/None）",
        f"docker exec {CONTAINER} python -c \"import json; c=json.load(open('/app/config/config.json')); t=c.get('timeliness',{{}}); w=t.get('jhemr_write',{{}}); print('gate', w.get('enabled'), w.get('insert_monitor_enabled'), t.get('notify_mode'), t.get('oracle_lock_enabled'))\"",
        "gate False False LOG_ONLY None",
    )
    step(
        "路由顺序防 422（容器内导入校验：timeliness 页在 qc/{alert_id:int} 之前可达）",
        "curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:8000/mobile/qc/timeliness",
        "200",
    )
    run(client, "启动日志尾部", f"docker logs --tail 15 {CONTAINER} 2>&1 | tail -15", check=False)
    print(f"\n[verify {'ALL PASS' if all_ok else 'HAS FAILURES'}]")
    return all_ok


def phase_persist(client: paramiko.SSHClient) -> None:
    ok, _ = run(
        client,
        "docker commit 固化",
        f"docker commit -m 'feat(mobile): add WeCom H5 timeliness unlock query and stats portal (2026-11-16)' {CONTAINER} {CONTAINER}:latest",
    )
    if not ok:
        sys.exit(1)
    run(client, "镜像确认", f"docker images | grep -E 'med-audit\\s+(latest|backup-pre-mobile-timeliness)' | head -4")
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
