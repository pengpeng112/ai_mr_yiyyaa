"""Run a few remote diagnostics over SSH.

Credentials are intentionally read from environment variables so this helper can
exist in the repository without embedding production secrets.
"""
import os

import paramiko


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Set {name} before running this diagnostic script.")
    return value


ssh_host = require_env("MED_AUDIT_SSH_HOST")
ssh_port = int(os.getenv("MED_AUDIT_SSH_PORT", "22"))
ssh_user = require_env("MED_AUDIT_SSH_USER")
ssh_password = require_env("MED_AUDIT_SSH_PASSWORD")

vastbase_host = require_env("MED_AUDIT_VASTBASE_HOST")
vastbase_port = int(os.getenv("MED_AUDIT_VASTBASE_PORT", "5432"))
vastbase_db = require_env("MED_AUDIT_VASTBASE_DB")
vastbase_user = require_env("MED_AUDIT_VASTBASE_USER")
vastbase_password = require_env("MED_AUDIT_VASTBASE_PASSWORD")

ssh = paramiko.SSHClient()
ssh.load_system_host_keys()
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(ssh_host, port=ssh_port, username=ssh_user, password=ssh_password, timeout=15)
print("=== SSH connected ===")


def run(cmd, timeout=20):
    print(f"\n>>> {cmd[:80]}...")
    _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    if out.strip():
        print(out.strip())
    if err.strip():
        print("[STDERR]", err.strip()[:500])
    return out, err


print("\n=== host info ===")
run("hostname")
run("docker ps --format '{{.Names}} {{.Status}}' | head -5")

print("\n=== container psycopg2 connection test ===")
run(
    "docker exec med-audit python -c "
    f"\"import psycopg2; conn=psycopg2.connect(host={vastbase_host!r},"
    f"port={vastbase_port!r},dbname={vastbase_db!r},user={vastbase_user!r},"
    f"password={vastbase_password!r},connect_timeout=10); "
    "print('OK',conn.server_version); conn.close()\" 2>&1"
)

print("\n=== container config check ===")
run(
    "docker exec med-audit python -c "
    "\"import json; cfg=json.load(open('/app/config/config.json')); "
    "e=cfg.get('emr_vastbase',{}); print('has_emr:', 'emr_vastbase' in cfg); "
    "print('enabled:', e.get('enabled')); print('host:', e.get('host'))\" 2>&1"
)

print("\n=== container network check ===")
run(
    "docker exec med-audit python -c "
    f"\"import socket; s=socket.socket(); s.settimeout(5); "
    f"s.connect(({vastbase_host!r},{vastbase_port!r})); print('socket OK'); s.close()\" 2>&1"
)

ssh.close()
