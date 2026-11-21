# -*- coding: utf-8 -*-
"""生产部署脚本（2026-11-17，用户任务：企微自建应用点击免登进入时效 H5）。

变更面（相对 2026-11-17 empno_login 部署）：
  - app/routers/mobile_timeliness.py  新增 GET /mobile/qc/timeliness/oauth/wecom/callback
    （企微 OAuth：code→userid→username==userid 建账者→302 H5?empno=工号；
    凭据读 env 优先、回退 config/config.json 的 "wecom" 节）

阶段：backup / [inject-config] / deploy <tar> / verify / persist。
口令仅环境变量 MED_AUDIT_SSH_PASSWORD；企微凭据仅环境变量
WECOM_CORPID / WECOM_SECRET / WECOM_AGENTID（操作机提供，注入容器 config.json
时不回显、不落日志；三者齐备才注入，否则跳过并提示）。

运行：python scripts/deploy_wecom_oauth_20261117.py deploy <本地tar路径>
"""

from __future__ import annotations

import json
import os
import sys

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
CONTAINER = "med-audit"
REMOTE_TAR = "/root/wecom_oauth_20261117.tar.gz"
BACKUP_TAR = "/root/backup_pre_wecom_oauth_20261117.tar.gz"
ROLLBACK_TAG = "med-audit:backup-pre-wecom-oauth-20261117"

BUNDLE_FILES = (
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
        print(out[-3500:])
    if err:
        print("[stderr]", err[-1000:])
    if check and code != 0:
        print(f"[FAIL] {desc} 退出码={code}")
        return False, out
    return True, out


def phase_backup(client: paramiko.SSHClient) -> None:
    ok, _ = run(client, "回滚镜像 tag", f"docker tag {CONTAINER}:latest {ROLLBACK_TAG}")
    if not ok:
        sys.exit(1)
    inner = " ".join(BUNDLE_FILES)
    ok, _ = run(client, "容器内被覆盖文件打包", f"docker exec {CONTAINER} tar czf /tmp/backup_wecom_oauth.tar.gz -C /app {inner}")
    if not ok:
        sys.exit(1)
    ok, _ = run(client, "备份拖回宿主机", f"docker cp {CONTAINER}:/tmp/backup_wecom_oauth.tar.gz {BACKUP_TAR} && ls -la {BACKUP_TAR}")
    if not ok:
        sys.exit(1)
    print(f"\n[backup OK] 回滚点：镜像 {ROLLBACK_TAG} + 文件 {BACKUP_TAR}")


def phase_inject_config(client: paramiko.SSHClient) -> None:
    """把操作机环境变量中的企微凭据合并进容器 config/config.json 的 wecom 节。

    值不回显、不写日志；WECOM_CORPID/WECOM_SECRET 任一缺失则跳过（保持既有值）。
    """
    corpid = os.environ.get("WECOM_CORPID", "").strip()
    secret = os.environ.get("WECOM_SECRET", "").strip()
    agentid = os.environ.get("WECOM_AGENTID", "").strip()
    if not corpid or not secret:
        print("\n[inject SKIP] 操作机未提供 WECOM_CORPID/WECOM_SECRET——保留容器既有 wecom 配置")
        return
    run(client, "容器内备份 config.json", "docker exec med-audit sh -c 'cp -a /app/config/config.json /app/config/config.json.bak-20261117-wecom'")
    payload = json.dumps({"corpid": corpid, "secret": secret, "agentid": agentid or ""})
    sftp = client.open_sftp()
    with sftp.open("/root/.wecom_oauth_payload_20261117.json", "w") as f:
        f.write(payload)
    sftp.close()
    ok, _ = run(client, "凭据合入 config.json（wecom 节）", (
        "docker cp /root/.wecom_oauth_payload_20261117.json med-audit:/tmp/.wecom_payload.json && "
        "docker exec med-audit python -c \""
        "import json;p='/app/config/config.json';"
        "c=json.load(open(p,encoding='utf-8'));"
        "w=json.load(open('/tmp/.wecom_payload.json'));"
        "old=c.get('wecom') or {};old.update(w);c['wecom']=old;"
        "json.dump(c,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2);"
        "print('injected keys:', sorted(c['wecom']))\" && "
        "docker exec med-audit sh -c 'rm -f /tmp/.wecom_payload.json'"
    ))
    run(client, "清理宿主机临时凭据文件", "sh -c 'rm -f /root/.wecom_oauth_payload_20261117.json'")
    if not ok:
        sys.exit(1)
    print("\n[inject OK] wecom 配置已写入容器 config.json（值未回显）")


def phase_deploy(client: paramiko.SSHClient, local_tar: str) -> None:
    if not os.path.isfile(local_tar):
        print(f"[FATAL] 本地包不存在: {local_tar}")
        sys.exit(2)
    sftp = client.open_sftp()
    print(f"\n=== 上传 {local_tar} -> {REMOTE_TAR}")
    sftp.put(local_tar, REMOTE_TAR)
    sftp.close()
    for desc, cmd in [
        ("tar 拖入容器", f"docker cp {REMOTE_TAR} {CONTAINER}:/tmp/deploy_wecom_oauth.tar.gz"),
        ("解包覆盖", f"docker exec {CONTAINER} tar xzf /tmp/deploy_wecom_oauth.tar.gz -C /app"),
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
    step(
        "OAuth 回调在线：缺 code → 302 回 H5（:8000）",
        "curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -m 10 'http://127.0.0.1:8000/mobile/qc/timeliness/oauth/wecom/callback'",
        "/mobile/qc/timeliness",
    )
    step(
        "OAuth 回调经 84 Nginx 前缀转发（:3000）",
        "curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -m 10 'http://127.0.0.1:3000/mobile/qc/timeliness/oauth/wecom/callback'",
        "/mobile/qc/timeliness",
    )
    step("wecom 凭据已配置（config.json 键存在性，不回显值）",
         "docker exec med-audit python -c \"import json;w=(json.load(open('/app/config/config.json',encoding='utf-8')).get('wecom') or {});print('wecom-cfg', 'corpid' in w and 'secret' in w)\"",
         "wecom-cfg True")
    # 回归 battery（与 empno 轮一致的关键项）
    step("H5 页面（:3000）", "curl -s -m 10 http://127.0.0.1:3000/mobile/qc/timeliness | grep -c 'timeliness_h5.js' || true", "1", "[:3000] ")
    step("工号免登接口在线（不存在工号 → 401）",
         "curl -s -o /dev/null -w '%{http_code}' -m 10 -X POST http://127.0.0.1:3000/api/mobile/timeliness/login/empno -H 'Content-Type: application/json' -d '{\"empno\":\"__probe_nonexistent__\"}'",
         "401", "[:3000] ")
    step("患者入口不受影响（:3000 /p/）", "curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:3000/p/", "200", "[:3000] ")
    step("PC 登录不受影响（:3000 /login）", "curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:3000/login", "200", "[:3000] ")
    step("医生端告警 H5 不受影响（:3000 无 token）", "curl -s -o /dev/null -w '%{http_code}' -m 10 'http://127.0.0.1:3000/mobile/qc/1?token=invalid'", "401", "[:3000] ")
    step("TIMELINESS 写闸四值保持（False/False/LOG_ONLY/None）",
         "docker exec med-audit python -c \"import json; c=json.load(open('/app/config/config.json')); t=c.get('timeliness',{}); w=t.get('jhemr_write',{}); print('gate', w.get('enabled'), w.get('insert_monitor_enabled'), t.get('notify_mode'), t.get('oracle_lock_enabled'))\"",
         "gate False False LOG_ONLY None")
    print("\n[verify] 全部通过" if all_ok else "\n[verify] 存在 FAIL——请按上表定位")
    return all_ok


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] != "deploy":
        print(__doc__)
        sys.exit(2)
    local_tar = sys.argv[2]
    client = connect()
    try:
        phase_backup(client)
        phase_inject_config(client)
        phase_deploy(client, local_tar)
        # 重启后等待应用就绪（避免验证电池在启动期打出 502 假失败）
        run(client, "等待应用就绪（最长 60s）", (
            "for i in $(seq 1 30); do "
            "code=$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://localhost:8000/api/health/live || true); "
            "[ \"$code\" = '200' ] && break; sleep 2; done; "
            "curl -s -m 5 -o /dev/null -w 'ready=%{http_code}' http://localhost:8000/api/health/live"
        ))
        if not phase_verify(client):
            sys.exit(1)
        print("\n[persist 提醒] 容器重启后热补丁仍在（docker cp 落盘 /app）；"
              "镜像化入库由下一轮发布收口，勿在本轮重建镜像。")
    finally:
        client.close()


if __name__ == "__main__":
    main()
