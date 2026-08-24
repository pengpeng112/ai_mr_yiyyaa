# -*- coding: utf-8 -*-
"""新增 6 类质控类型（A–F，2026-08-13 用户确认的正式功能，非演示 mock，后期继续完善）。

新增：orders_vs_progress / surgery_vs_anesthesia / transfusion_vs_orders /
     critical_value_closure / consent_completeness / rounds_completeness

规则：沿用现有六类的配置骨架；sources/dify/payload/response 留空（schema 均有默认值），
enabled=true 使其在质控类型页与选项接口可见，default_for_schedule=false 不参与自动调度，
不影响现有调度任务。config 为容器挂载卷，改完无需重启（AuditTypeRegistry 每请求实例化）。

用法：
  python scripts/add_audit_types_20260813.py local     # 更新本仓库 config/config.json
  python scripts/add_audit_types_20260813.py remote    # 更新生产容器挂载的 config（SSH）
  python scripts/add_audit_types_20260813.py all       # 两者都执行
"""
import base64
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_CONFIG = ROOT / "config" / "config.json"
REMOTE_CONFIG = "/app/config/config.json"  # 容器内路径（挂载自 /opt/med-audit-docker/config）
BACKUP_SUFFIX = ".bak-20260813-audit-types"

NEW_TYPES = [
    {"code": "orders_vs_progress", "name": "医嘱与病程记录一致性质控",
     "description": "长期/临时医嘱的执行情况与病程记录描述是否一致", "sort_order": 18},
    {"code": "surgery_vs_anesthesia", "name": "手术记录与麻醉记录一致性质控",
     "description": "手术时间、术式、术者、术中情况在手术记录与麻醉单间是否一致", "sort_order": 19},
    {"code": "transfusion_vs_orders", "name": "输血记录与医嘱一致性质控",
     "description": "输血医嘱、输血记录单、病程中的输血描述三者是否一致", "sort_order": 20},
    {"code": "critical_value_closure", "name": "危急值处理闭环核查",
     "description": "危急值报告后是否在规定时限内有处理记录与复查记录", "sort_order": 21},
    {"code": "consent_completeness", "name": "知情同意书完整性核查",
     "description": "手术/输血/特殊检查前知情同意书是否齐全、签署时点是否合规", "sort_order": 22},
    {"code": "rounds_completeness", "name": "三级查房记录完整性核查",
     "description": "入院 48 小时内主治/主任查房记录是否齐全，查房频次是否达标", "sort_order": 23},
]

SKELETON = {
    "enabled": True,
    "default_for_schedule": False,
    "dimension_codes": [],
    # schema 校验 sources 不能为空；占位 primary 源（空 SQL、非必需），不影响调度（default_for_schedule=false），后期完善时替换
    "sources": {"primary": {"type": "sql", "backend": "default", "query_sql": "", "required": False}},
    "group_key": ["patient_id", "visit_number"],
    "join_rules": [],
    "payload": {},
    "dify": {},
    "response": {},
    "display": {"summary_blocks": [], "detail_blocks": []},
}


def build_entries():
    return [dict(SKELETON, **t) for t in NEW_TYPES]


def apply_to_text(text: str) -> tuple[str, list[str]]:
    """向 config 文本追加/修复新类型，返回 (新文本, 实际写入的 code 列表)。
    幂等：code 已存在则整体替换为本脚本骨架（用于修复首次空 sources 校验失败项）。"""
    cfg = json.loads(text)
    ats = cfg.setdefault("audit_types", [])
    by_code = {a.get("code"): i for i, a in enumerate(ats)}
    added = []
    for entry in build_entries():
        if entry["code"] in by_code:
            ats[by_code[entry["code"]]] = entry
        else:
            ats.append(entry)
        added.append(entry["code"])
    return json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", added


def apply_local():
    if not LOCAL_CONFIG.exists():
        sys.exit(f"本地配置不存在: {LOCAL_CONFIG}")
    backup = LOCAL_CONFIG.with_suffix(LOCAL_CONFIG.suffix + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(LOCAL_CONFIG, backup)
    new_text, added = apply_to_text(LOCAL_CONFIG.read_text(encoding="utf-8"))
    if added:
        LOCAL_CONFIG.write_text(new_text, encoding="utf-8")
    print(f"[local] 新增 {len(added)} 类: {added or '（均已存在，跳过）'} 备份: {backup.name}")


REMOTE_SNIPPET = r'''
import json, shutil
path = "/app/config/config.json"
backup = path + ".bak-20260813-audit-types"
entries = json.loads(ENTRIES_JSON)
cfg = json.load(open(path, encoding="utf-8"))
ats = cfg.setdefault("audit_types", [])
by_code = {a.get("code"): i for i, a in enumerate(ats)}
added = []
for e in entries:
    if e["code"] in by_code:
        ats[by_code[e["code"]]] = e
    else:
        ats.append(e)
    added.append(e["code"])
if added:
    import os
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
    json.dump(cfg, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("ADDED=" + ",".join(added) if added else "ADDED=none(already-exists)")

# 校验：注册表可正常加载且新类型可见
from app.services.audit_type_registry import AuditTypeRegistry
reg = AuditTypeRegistry()
names = {t.code: t.name for t in reg.list_all()}
for e in entries:
    print("VERIFY", e["code"], "->", names.get(e["code"], "MISSING"))
'''


def apply_remote():
    import paramiko
    password = os.environ.get("MED_AUDIT_SSH_PASSWORD", "")
    if not password:
        sys.exit("MED_AUDIT_SSH_PASSWORD 未设置")
    entries_json = json.dumps(build_entries(), ensure_ascii=False)
    snippet = REMOTE_SNIPPET.replace("ENTRIES_JSON", repr(entries_json))
    encoded = base64.b64encode(snippet.encode("utf-8")).decode()

    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect("10.10.8.84", port=40022, username="root", password=password, timeout=15)
    try:
        cmd = f"docker exec med-audit python -c \"import base64;exec(base64.b64decode('{encoded}').decode())\""
        print(">>> docker exec med-audit python -c <add audit types>")
        _in, out, err = ssh.exec_command(cmd, timeout=60)
        code = out.channel.recv_exit_status()
        print(out.read().decode(errors="replace"))
        stderr = err.read().decode(errors="replace").strip()
        if stderr:
            print(f"[stderr] {stderr}", file=sys.stderr)
        if code != 0:
            sys.exit(f"远端执行失败(exit={code})")
    finally:
        ssh.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    if target in ("local", "all"):
        apply_local()
    if target in ("remote", "all"):
        apply_remote()
    print("DONE")
