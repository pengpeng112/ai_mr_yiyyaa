# -*- coding: utf-8 -*-
"""生产热更新部署脚本（2026-09-01，用户当次授权：C2乱码修复+RP2/RP3后端变更+requests2.32.4）。

携带范围（相对生产镜像 bb7104f4f7e0）：
  - 035/RP2  app/services/scheduler_run_modes.py + app/routers/{scheduler,config}.py
             （discharge 生效性诊断：status discharge_effectiveness 键+保存告警）
  - 035/RP3  app/routers/{stats,logs}.py + app/schemas.py
             + static/{index.html,templates/pages/audit.html,scripts/{app.js,modules/stats.js}}
             （统计/导出口径元数据块 + 前端口径行，版本锚 20260901-stats-meta）
  - 035/RP5  requests 2.32.3→2.32.4（离线轮子安装，CVE-2024-47081）
  - 035/RP9  config.json jyjc nursing field_mapping ??ID/?? → 患者ID/次数（卷挂载文件，独立阶段）

口令只从环境变量 MED_AUDIT_SSH_PASSWORD 读取，不落仓库。

阶段：
  precheck  —— 只读预检：容器/当前 requests 版本/jyjc 映射现状/镜像 id
  fixconfig —— 生产 config.json C2 修复（宿主卷文件；备份至 config/backups/，可整文件回滚）
  backup    —— 容器内受影响路径 tar 备份 + docker commit 回滚镜像 tag
  deploy    —— 上传 tar+wheel → 覆盖 /app → 装轮子 → 清 __pycache__ → 重启
  verify    —— 容器/健康接口/新代码导入断言/C2 映射/静态版本锚/requests 版本/日志
  persist   —— docker commit 固化 med-audit:latest

用法：
    python scripts/deploy_hotfix_20260901.py precheck
    python scripts/deploy_hotfix_20260901.py fixconfig
    python scripts/deploy_hotfix_20260901.py backup
    python scripts/deploy_hotfix_20260901.py deploy <本地tar绝对路径> <本地wheel绝对路径>
    python scripts/deploy_hotfix_20260901.py verify
    python scripts/deploy_hotfix_20260901.py persist
"""

from __future__ import annotations

import os
import sys

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
CONTAINER = "med-audit"
REMOTE_TAR = "/root/hotfix_20260901.tar.gz"
REMOTE_WHEEL = "/root/requests-2.32.4-py3-none-any.whl"
ROLLBACK_TAG = "med-audit:rollback-pre-hotfix-20260901"
HOST_CONFIG = "/opt/med-audit-docker/config/config.json"
HOST_CONFIG_BACKUP = "/opt/med-audit-docker/config/backups/config_pre_c2fix_20260901.json"


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
    _, stdout, stderr = client.exec_command(cmd, timeout=300)
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
        if stage == "precheck":
            ok = run(client, "容器状态", f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}}'")
            ok &= run(client, "当前镜像 id",
                      f"docker inspect --format '{{{{.Image}}}}' {CONTAINER} | cut -c8-19")
            ok &= run(client, "容器内 requests 版本",
                      f"docker exec {CONTAINER} python -c \"import requests;print(requests.__version__)\"")
            ok &= run(client, "生产 jyjc nursing 映射现状（预期 ??ID/??）",
                      "docker exec med-audit python -c \"import json;"
                      "cfg=json.load(open('/app/config/config.json',encoding='utf-8'));"
                      "fm=next(a for a in cfg['audit_types'] if a['code']=='jyjc_vs_bcnursing')"
                      "['sources']['nursing']['field_mapping'];"
                      "print('patient_id=',repr(fm.get('patient_id')),'visit_number=',repr(fm.get('visit_number')))\"")
            ok &= run(client, "日志尾部现状", f"docker logs --tail 5 {CONTAINER} 2>&1 | tail -5", check=False)
            return 0 if ok else 1

        if stage == "fixconfig":
            ok = run(client, "备份生产 config（回滚点A）",
                     f"mkdir -p /opt/med-audit-docker/config/backups && "
                     f"cp {HOST_CONFIG} {HOST_CONFIG_BACKUP} && ls -l {HOST_CONFIG_BACKUP}")
            ok &= run(client, "C2 修复（仅改两个键，JSON 整体往返）", (
                "docker exec med-audit python -c \""
                "import json;"
                "p='/app/config/config.json';"
                "cfg=json.load(open(p,encoding='utf-8'));"
                "fm=next(a for a in cfg['audit_types'] if a['code']=='jyjc_vs_bcnursing')"
                "['sources']['nursing']['field_mapping'];"
                "assert fm['patient_id']=='??ID' and fm['visit_number']=='??', fm;"
                "fm['patient_id']='患者ID'; fm['visit_number']='次数';"
                "json.dump(cfg,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2);"
                "print('fixed: patient_id=',fm['patient_id'],' visit_number=',fm['visit_number'])\""
            ))
            ok &= run(client, "验证：重读+全 JSON 可解析", (
                "docker exec med-audit python -c \""
                "import json;"
                "cfg=json.load(open('/app/config/config.json',encoding='utf-8'));"
                "fm=next(a for a in cfg['audit_types'] if a['code']=='jyjc_vs_bcnursing')"
                "['sources']['nursing']['field_mapping'];"
                "print('reread:',repr(fm['patient_id']),repr(fm['visit_number']));"
                "print('audit_types count:',len(cfg['audit_types']),'| relay enabled:',"
                "cfg['relay_alert']['enabled'],'| sched daily enabled:',cfg['scheduler_daily']['enabled'])\""
            ))
            return 0 if ok else 1

        if stage == "backup":
            ok = run(client, "容器内受影响路径备份(回滚点B)",
                     f"docker exec {CONTAINER} tar czf /tmp/hotfix_backup_20260901.tar.gz -C /app "
                     f"app/services/scheduler_run_modes.py app/routers app/schemas.py "
                     f"static/index.html static/templates/pages/audit.html static/scripts/app.js "
                     f"static/scripts/modules/stats.js")
            ok &= run(client, "备份拖回服务器 /root/",
                      f"docker cp {CONTAINER}:/tmp/hotfix_backup_20260901.tar.gz /root/ && ls -l /root/hotfix_backup_20260901.tar.gz")
            ok &= run(client, "回滚镜像 tag(回滚点C)",
                      f"docker commit -m 'rollback point before hotfix 20260901 (C2+RP2+RP3+RP5)' "
                      f"{CONTAINER} {ROLLBACK_TAG}")
            return 0 if ok else 1

        if stage == "deploy":
            if len(argv) < 4:
                print("[FATAL] deploy 需要本地 tar 与 wheel 绝对路径")
                return 2
            local_tar, local_wheel = argv[2], argv[3]
            for path in (local_tar, local_wheel):
                if not os.path.isfile(path):
                    print(f"[FATAL] 文件不存在: {path}")
                    return 2
            sftp = client.open_sftp()
            print(f"上传 {local_tar}（{os.path.getsize(local_tar)/1048576:.2f} MB）")
            sftp.put(local_tar, REMOTE_TAR)
            print(f"上传 {local_wheel}（{os.path.getsize(local_wheel)/1048576:.2f} MB）")
            sftp.put(local_wheel, REMOTE_WHEEL)
            sftp.close()
            print("[ok] 上传完成")
            ok = run(client, "tar/wheel 进容器",
                     f"docker cp {REMOTE_TAR} {CONTAINER}:/tmp/ && docker cp {REMOTE_WHEEL} {CONTAINER}:/tmp/")
            ok &= run(client, "解包覆盖 /app", f"docker exec {CONTAINER} tar xzf /tmp/hotfix_20260901.tar.gz -C /app")
            ok &= run(client, "安装 requests==2.32.4（离线轮子，--no-deps）",
                      f"docker exec {CONTAINER} pip install --no-deps --no-cache-dir /tmp/requests-2.32.4-py3-none-any.whl")
            ok &= run(client, "清 __pycache__",
                      f"docker exec {CONTAINER} find /app -name '__pycache__' -type d -exec rm -rf {{}} + || true",
                      check=False)
            ok &= run(client, "重启容器", f"docker restart {CONTAINER}")
            return 0 if ok else 1

        if stage == "verify":
            ok = run(client, "容器运行状态",
                     f"docker ps --filter name={CONTAINER} --format '{{{{.Status}}}}'")
            ok &= run(client, "健康接口 200",
                      f"docker exec {CONTAINER} python -c "
                      "\"import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=15).status)\"")
            ok &= run(client, "requests 版本（预期 2.32.4）",
                      f"docker exec {CONTAINER} python -c \"import requests;print(requests.__version__)\"")
            ok &= run(client, "RP2 新代码：discharge_effectiveness_warnings 存在+EMR 判定",
                      f"docker exec -w /app {CONTAINER} python -c \""
                      "from app.services.scheduler_run_modes import discharge_effectiveness_warnings as f;"
                      "cfg={'audit_types':[{'code':'surgery_chain','name':'x','sources':"
                      "{'s':{'type':'sql','query_sql':'SELECT p.x FROM t p WHERE {dept_filter}'}}}],"
                      "'scheduler_discharge':{'enabled':True,'audit_type_codes':['surgery_chain']}};"
                      "w=f(cfg);assert w and 'ORA-00904' in w[0]['detail'],w;"
                      "print('warn ok:',w[0]['code'],w[0]['source'])\"")
            ok &= run(client, "RP3 新代码：stats 元数据块函数",
                      f"docker exec -w /app {CONTAINER} python -c \""
                      "from app.routers.stats import _stats_metadata;"
                      "m=_stats_metadata(filters={'x':1},date_from='2026-09-01',date_to='2026-09-01');"
                      "assert m['timezone']=='Asia/Shanghai' and m['semantics']=='current-only',m;"
                      "print('meta keys:',sorted(m.keys()))\"")
            ok &= run(client, "C2 修复生效（运行容器内重读）",
                      "docker exec med-audit python -c \""
                      "import json;cfg=json.load(open('/app/config/config.json',encoding='utf-8'));"
                      "fm=next(a for a in cfg['audit_types'] if a['code']=='jyjc_vs_bcnursing')"
                      "['sources']['nursing']['field_mapping'];"
                      "assert fm['patient_id']=='患者ID' and fm['visit_number']=='次数',fm;"
                      "print('C2 ok')\"")
            ok &= run(client, "静态版本锚（首页含 20260901-stats-meta）",
                      f"docker exec {CONTAINER} python -c "
                      "\"import urllib.request;"
                      "h=urllib.request.urlopen('http://127.0.0.1:8000/index.html',timeout=15).read().decode('utf-8');"
                      "assert 'v=20260901-stats-meta' in h,'version anchor missing';"
                      "print('index anchor ok')\"")
            ok &= run(client, "stats.js 可达",
                      f"docker exec {CONTAINER} python -c "
                      "\"import urllib.request;"
                      "r=urllib.request.urlopen('http://127.0.0.1:8000/scripts/modules/stats.js',timeout=15);"
                      "b=r.read().decode('utf-8');"
                      "assert 'statsMeta' in b and r.status==200;"
                      "print('stats.js ok',r.status)\"")
            ok &= run(client, "启动日志无 traceback/error",
                      f"docker logs --since 3m {CONTAINER} 2>&1 | grep -iE 'traceback|error' | grep -v 'error_code' | head -5 || echo LOG_CLEAN",
                      check=False)
            return 0 if ok else 1

        if stage == "persist":
            ok = run(client, "docker commit 固化 med-audit:latest",
                     f"docker commit -m 'hotfix 20260901: C2 jyjc mapping + RP2 discharge warnings + RP3 stats meta + requests 2.32.4' "
                     f"{CONTAINER} med-audit:latest")
            ok &= run(client, "镜像清单确认",
                      "docker images med-audit --format '{{.Tag}} {{.ID}} {{.CreatedAt}}' | head -5")
            return 0 if ok else 1

        print(f"[FATAL] 未知阶段: {stage}")
        return 2
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
