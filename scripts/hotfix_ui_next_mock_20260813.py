# -*- coding: utf-8 -*-
"""【MOCK-20260813】临时演示热更：将本地 frontend/dist 覆盖进生产容器 /app/static/ui-next。

背景：演示用写死数据（系统正常 / 医生未查看=45 / 前置机成功率=98.5%）已在本地构建，
但生产以 Docker 镜像整体部署，static 未挂载卷，本地构建不影响服务器。
本脚本走"docker cp 热更"路径，容器重建后失效；正式恢复见根目录 需要修改回去的说明.md。

安全约束：SSH 密码仅从环境变量 MED_AUDIT_SSH_PASSWORD 读取，不落盘、不打印。
"""
import os
import sys
import tarfile
import time
from pathlib import Path

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
PASSWORD = os.environ.get("MED_AUDIT_SSH_PASSWORD", "")
if not PASSWORD:
    sys.exit("MED_AUDIT_SSH_PASSWORD 未设置")

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "frontend" / "dist"
CONTAINER = "med-audit"
REMOTE_TAR = "/tmp/ui-next-dist-20260813.tar.gz"
STAMP = "20260813"

if not (DIST / "index.html").exists():
    sys.exit(f"本地构建产物不存在: {DIST}，先执行 npm run build")


def run(ssh, cmd, timeout=120):
    print(f"\n>>> {cmd}")
    _in, out, err = ssh.exec_command(cmd, timeout=timeout)
    code = out.channel.recv_exit_status()
    stdout = out.read().decode(errors="replace").strip()
    stderr = err.read().decode(errors="replace").strip()
    if stdout:
        print(stdout)
    if stderr:
        print(f"[stderr] {stderr}", file=sys.stderr)
    if code != 0:
        sys.exit(f"命令失败(exit={code}): {cmd}")
    return stdout


def main():
    # 1) 本地打包 dist
    local_tar = ROOT / "scripts" / f"ui-next-dist-{STAMP}.tar.gz"
    with tarfile.open(local_tar, "w:gz") as tf:
        for p in sorted(DIST.rglob("*")):
            tf.add(p, arcname=p.relative_to(DIST))
    print(f"[1/5] 本地打包完成: {local_tar} ({local_tar.stat().st_size // 1024} KB)")

    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15)
    print(f"[2/5] SSH 已连接 {USER}@{HOST}:{PORT}")
    try:
        # 2) 上传 tar 到服务器 /tmp
        with ssh.open_sftp() as sftp:
            sftp.put(str(local_tar), REMOTE_TAR)
        print(f"[3/5] 已上传 {REMOTE_TAR}")

        # 3) 容器内备份现有 ui-next（幂等：已存在则跳过），再热更
        run(ssh, f"docker exec {CONTAINER} sh -c 'test -d /app/static/ui-next.bak-{STAMP} || cp -r /app/static/ui-next /app/static/ui-next.bak-{STAMP}'")
        run(ssh, f"docker cp {REMOTE_TAR} {CONTAINER}:/tmp/")
        run(ssh, f"docker exec {CONTAINER} sh -c '"
                 f"rm -rf /tmp/ui-next-new && mkdir -p /tmp/ui-next-new && "
                 f"tar xzf /tmp/ui-next-dist-{STAMP}.tar.gz -C /tmp/ui-next-new && "
                 f"rm -rf /app/static/ui-next/* && "
                 f"cp -r /tmp/ui-next-new/* /app/static/ui-next/ && "
                 f"rm -rf /tmp/ui-next-new /tmp/ui-next-dist-{STAMP}.tar.gz'")
        print(f"[4/5] 容器内 /app/static/ui-next 已覆盖（备份在 ui-next.bak-{STAMP}）")

        # 4) 验证：容器内新 JS 含写死值 98.5，且页面可访问
        run(ssh, f"docker exec {CONTAINER} sh -c \"grep -l '98.5' /app/static/ui-next/assets/WorkbenchPage-*.js\"")
        run(ssh, "curl -s -o /dev/null -w 'HTTP %{http_code}\\n' http://localhost:8000/ui-next/")
        print("[5/5] 验证通过")
    finally:
        ssh.close()
        run_cleanup(local_tar)


def run_cleanup(local_tar):
    try:
        local_tar.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nDONE in {time.time() - t0:.1f}s —— 浏览器 Ctrl+F5 强刷验证")
