# -*- coding: utf-8 -*-
"""【MOCK-20260813】演示热更：把新增 doctor_name 字段的 patient_qc.py 推送进生产容器并重启。

配套前端演示（告警记录页查看人显示主管医师真实姓名），恢复见根目录 需要修改回去的说明.md。
安全约束：SSH 密码仅从环境变量 MED_AUDIT_SSH_PASSWORD 读取；先备份容器内原文件再覆盖。
"""
import os
import sys
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
LOCAL_PY = ROOT / "app" / "routers" / "patient_qc.py"
CONTAINER = "med-audit"
CONTAINER_PY = "/app/app/routers/patient_qc.py"
REMOTE_TMP = "/tmp/patient_qc.py.20260813"
STAMP = "20260813"


def run(ssh, cmd, timeout=120, check=True):
    print(f"\n>>> {cmd}")
    _in, out, err = ssh.exec_command(cmd, timeout=timeout)
    code = out.channel.recv_exit_status()
    stdout = out.read().decode(errors="replace").strip()
    stderr = err.read().decode(errors="replace").strip()
    if stdout:
        print(stdout)
    if stderr:
        print(f"[stderr] {stderr}", file=sys.stderr)
    if check and code != 0:
        sys.exit(f"命令失败(exit={code}): {cmd}")
    return stdout


def main():
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15)
    print(f"SSH 已连接 {USER}@{HOST}:{PORT}")
    try:
        with ssh.open_sftp() as sftp:
            sftp.put(str(LOCAL_PY), REMOTE_TMP)
        print(f"[1/4] 已上传 {REMOTE_TMP}")

        run(ssh, f"docker exec {CONTAINER} sh -c 'test -f {CONTAINER_PY}.bak-{STAMP} || cp {CONTAINER_PY} {CONTAINER_PY}.bak-{STAMP}'")
        run(ssh, f"docker cp {REMOTE_TMP} {CONTAINER}:{CONTAINER_PY}")
        run(ssh, f"docker exec {CONTAINER} grep -c _extract_payload_doctor_name {CONTAINER_PY}")
        print("[2/4] 容器内 patient_qc.py 已更新（原文件备份为 .bak-20260813）")

        run(ssh, f"docker restart {CONTAINER}", timeout=60)
        print("[3/4] 容器已重启，等待健康检查...")

        # 健康检查轮询（最长 90s）
        deadline = time.time() + 90
        ok = False
        while time.time() < deadline:
            time.sleep(5)
            out = run(ssh, "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/health/live", check=False)
            if out.strip() == "200":
                ok = True
                break
        if not ok:
            sys.exit("健康检查 90s 内未恢复 200，请人工核查容器日志：docker logs med-audit")
        print("[4/4] 健康检查通过 HTTP 200")
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
