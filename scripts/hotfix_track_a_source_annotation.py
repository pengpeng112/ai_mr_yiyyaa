# -*- coding: utf-8 -*-
"""热更轨A：将本地 data_source_loader.py（含 [source= 标注）推入 med-audit 容器并 docker commit 持久化。

约束：不重建镜像、不重启容器；密码仅走 MED_AUDIT_SSH_PASSWORD 环境变量。
"""
import os
import sys

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
PASSWORD = os.environ.get("MED_AUDIT_SSH_PASSWORD", "")
if not PASSWORD:
    sys.exit("MED_AUDIT_SSH_PASSWORD 未设置")

LOCAL_FILE = os.path.join(
    os.path.dirname(__file__), "..", "app", "services", "data_source_loader.py"
)
REMOTE_TMP = "/tmp/data_source_loader.py.hotfix"
CONTAINER = "med-audit"
CONTAINER_PATH = "/app/app/services/data_source_loader.py"


def run(client, title, cmd, timeout=120):
    print(f"\n===== {title} =====")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace").strip()
    err = stderr.read().decode(errors="replace").strip()
    print(out if out else "(无输出)")
    if err:
        print(f"[stderr] {err[:500]}")
    return out


def main():
    # 本地自证：待推文件必须含轨A标注，且不含 mr_txt（红线）
    with open(LOCAL_FILE, encoding="utf-8") as f:
        content = f.read()
    assert "[source=" in content, "本地文件缺少 [source= 标注，中止"
    assert "mr_txt" not in content, "本地文件含 mr_txt，触碰红线，中止"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15)
    try:
        # 0) 推前备份容器内原文件
        run(client, "备份容器内原文件",
            f"docker exec {CONTAINER} cp {CONTAINER_PATH} {CONTAINER_PATH}.bak_20260808")

        # 1) SFTP 上传
        sftp = client.open_sftp()
        sftp.put(os.path.abspath(LOCAL_FILE), REMOTE_TMP)
        sftp.close()
        print(f"\n===== SFTP 上传完成：{REMOTE_TMP} =====")

        # 2) 拷入容器并校验
        run(client, "docker cp 进容器",
            f"docker cp {REMOTE_TMP} {CONTAINER}:{CONTAINER_PATH}")
        cnt = run(client, "容器内验证 [source= 计数",
                  f"docker exec {CONTAINER} grep -c '\\[source=' {CONTAINER_PATH}")
        if cnt.strip() == "0":
            sys.exit("热更失败：容器内仍无 [source= 标注")

        # 3) 语法校验（容器内 python 编译，防坏文件遗留在镜像）
        run(client, "容器内语法校验",
            f"docker exec {CONTAINER} python -m py_compile {CONTAINER_PATH} && echo COMPILE_OK")

        # 4) docker commit 持久化（不重启容器）
        run(client, "docker commit 持久化",
            f"docker commit {CONTAINER} med-audit:latest", timeout=300)
        run(client, "新镜像ID",
            "docker images med-audit:latest --format '{{.ID}} {{.CreatedAt}}'")

        # 5) 清理服务器临时文件
        run(client, "清理临时文件", f"rm -f {REMOTE_TMP}")
        run(client, "容器状态复核",
            f"docker ps --filter name={CONTAINER} --format '{{{{.Names}}}} {{{{.Status}}}}'")
    finally:
        client.close()

    print("\n提示：进程内旧代码仍在运行，[source= 标注需容器重启后生效（本次未重启）。")


if __name__ == "__main__":
    main()
