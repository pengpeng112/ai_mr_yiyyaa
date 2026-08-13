# -*- coding: utf-8 -*-
"""012 P0 只读：生产六类配置脱敏快照 + SHA-256 + nursing ??ID/?? 编码复核。

约束：只读容器内 config.json；所有 *_enc 字段仅输出哈希指纹与长度，不输出密文/明文。
"""
import base64
import hashlib
import json
import os
import sys

import paramiko

HOST = "10.10.8.84"
PORT = 40022
USER = "root"
PASSWORD = os.environ.get("MED_AUDIT_SSH_PASSWORD", "")
if not PASSWORD:
    sys.exit("MED_AUDIT_SSH_PASSWORD 未设置")

SNIPPET = r'''
import hashlib, json

with open("/app/config/config.json", "rb") as f:
    raw = f.read()
print("CONFIG_SHA256=" + hashlib.sha256(raw).hexdigest())
cfg = json.loads(raw.decode("utf-8"))

def mask(obj):
    sensitive_keys = {"api_key", "password", "secret", "token", "webhook_secret"}
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k.endswith("_enc") and isinstance(v, str) and v:
                out[k] = {"enc_sha256_12": hashlib.sha256(v.encode()).hexdigest()[:12], "len": len(v)}
            elif k.lower() in sensitive_keys and isinstance(v, str) and v:
                out[k] = {"plaintext_sha256_12": hashlib.sha256(v.encode()).hexdigest()[:12], "len": len(v), "masked": True}
            else:
                out[k] = mask(v)
        return out
    if isinstance(obj, list):
        return [mask(i) for i in obj]
    if isinstance(obj, str) and len(obj) > 2000:
        return obj[:200] + "...[truncated]"
    return obj

audit_types = cfg.get("audit_types") or []
print("AUDIT_TYPE_COUNT=" + str(len(audit_types)))
for at in audit_types:
    print("===AUDIT_TYPE===")
    print(json.dumps(mask(at), ensure_ascii=False, sort_keys=True))
'''

encoded = base64.b64encode(SNIPPET.encode()).decode()
client = paramiko.SSHClient()
client.load_system_host_keys()
client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15)
try:
    cmd = f"docker exec med-audit python -c \"import base64;exec(base64.b64decode('{encoded}').decode())\""
    _, stdout, stderr = client.exec_command(cmd, timeout=120)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace").strip()
    print(out)
    if err:
        print(f"[stderr] {err[:500]}")
finally:
    client.close()

# 本地落盘脱敏快照（供 P0 基线）
snapshot_path = os.path.join(
    os.path.dirname(__file__), "..", "docs", "ACTIVE", "p0_prod_config_snapshot_20260809_masked.json"
)
blocks = {}
current = None
sha256_line = ""
for line in out.splitlines():
    if line.startswith("CONFIG_SHA256="):
        sha256_line = line.split("=", 1)[1].strip()
    elif line.startswith("AUDIT_TYPE_COUNT="):
        blocks["_count"] = int(line.split("=", 1)[1])
    elif line == "===AUDIT_TYPE===":
        current = []
        blocks.setdefault("_items", []).append(current)
    elif current is not None and line.strip():
        current.append(line)

items = []
for raw_lines in blocks.get("_items", []):
    items.append(json.loads("".join(raw_lines)))
payload = {
    "snapshot_date": "2026-08-09",
    "config_sha256": sha256_line,
    "audit_type_count": blocks.get("_count"),
    "note": "脱敏快照：*_enc 仅保留哈希指纹与长度；仅用于 012 P0 基线，禁止据此回写生产配置",
    "audit_types": items,
}
with open(snapshot_path, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
print(f"SNAPSHOT_SAVED={os.path.abspath(snapshot_path)}")
