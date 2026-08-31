# -*- coding: utf-8 -*-
"""生产热更新部署脚本（2026-08-30 晚，用户当次授权：登录锁死热修）。

本次变更面 = app/security_middleware.py（登录 CSRF 豁免）+ static/index.html +
static/scripts/app.js（缓存版本击穿）。根因：T1-5 CSRF 门对「带旧 Cookie 的
登录」也拦截，叠加浏览器缓存旧版 auth.js（无 X-Requested-With 拦截器），
老用户登录被 403 锁死。
口令只从环境变量 MED_AUDIT_SSH_PASSWORD 读取，不落仓库。

用法：
    python scripts/deploy_hotfix_auth_csrf_20260830.py backup
    python scripts/deploy_hotfix_auth_csrf_20260830.py deploy <本地tar绝对路径>
    python scripts/deploy_hotfix_auth_csrf_20260830.py verify
    python scripts/deploy_hotfix_auth_csrf_20260830.py persist
"""

from __future__ import annotations

import os
import sys

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
CONTAINER = "med-audit"
REMOTE_TAR = "/root/hotfix_auth_csrf_20260830.tar.gz"
ROLLBACK_TAG = "med-audit:rollback-pre-authcsrf-20260830"


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
            ok = run(client, "容器内三文件备份(回滚点1)",
                     f"docker exec {CONTAINER} tar czf /tmp/authcsrf_backup_20260830.tar.gz "
                     f"-C /app app/security_middleware.py static/index.html static/scripts/app.js")
            ok &= run(client, "备份拖回服务器 /root/",
                      f"docker cp {CONTAINER}:/tmp/authcsrf_backup_20260830.tar.gz /root/")
            ok &= run(client, "回滚镜像 tag(回滚点2)",
                      f"docker commit -m 'rollback point before auth-csrf hotfix 20260830' "
                      f"{CONTAINER} {ROLLBACK_TAG}")
            return 0 if ok else 1

        if stage == "deploy":
            local_tar = argv[2]
            print(f"上传 {local_tar} → {REMOTE_TAR}")
            sftp = client.open_sftp()
            sftp.put(local_tar, REMOTE_TAR)
            sftp.close()
            print("[ok] 上传完成")
            ok = run(client, "tar 进容器", f"docker cp {REMOTE_TAR} {CONTAINER}:/tmp/")
            ok &= run(client, "解包覆盖 /app",
                      f"docker exec {CONTAINER} tar xzf /tmp/hotfix_auth_csrf_20260830.tar.gz -C /app")
            ok &= run(client, "清 __pycache__",
                      f"docker exec {CONTAINER} find /app/app -name '__pycache__' -type d "
                      f"-exec rm -rf {{}} + || true", check=False)
            ok &= run(client, "重启容器", f"docker restart {CONTAINER}")
            return 0 if ok else 1

        if stage == "verify":
            ok = run(client, "容器运行状态",
                     f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}}'")
            ok &= run(client, "健康接口",
                      f"docker exec {CONTAINER} python -c "
                      "\"import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=10).status)\"")
            ok &= run(client, "核心验证:带旧Cookie登录不再403(错误口令应401)",
                      f"docker exec {CONTAINER} python -c \""
                      "import urllib.request,http.cookiejar;"
                      "cj=http.cookiejar.CookieJar();"
                      "op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj));"
                      "op.addheaders=[('Cookie','med_audit_auth=stale-token-test')];"
                      "req=urllib.request.Request('http://127.0.0.1:8000/api/users/login',"
                      "data=b'{\\\"username\\\":\\\"x\\\",\\\"password\\\":\\\"y\\\"}',"
                      "headers={'Content-Type':'application/json'},method='POST');"
                      "import urllib.error;"
                      "try:"
                      "  r=op.open(req,timeout=10);print('status',r.status)"
                      "except urllib.error.HTTPError as e:"
                      "  print('status',e.code);"
                      "  assert e.code==401,'expect 401 got '+str(e.code)"
                      "\"")
            ok &= run(client, "index.html 已是新版本",
                      f"docker exec {CONTAINER} sh -c "
                      "\"curl -s http://127.0.0.1:8000/ | grep -o 'app.js?v=20260830-csrf-fix' | head -1\"")
            ok &= run(client, "启动日志无异常",
                      f"docker logs --since 3m {CONTAINER} 2>&1 | grep -iE 'traceback|error' | head -5 || true",
                      check=False)
            return 0 if ok else 1

        if stage == "persist":
            ok = run(client, "固化镜像 med-audit:latest",
                     f"docker commit -m 'hotfix 20260830: auth login CSRF exemption + static cache bust' "
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
