"""Compare direct Vastbase connection settings with application config.

Direct connection credentials are read from environment variables. Do not store
database passwords in this script.
"""
import os
import sys

import psycopg2

sys.path.insert(0, "/app")


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise SystemExit(f"Set {name} before running this diagnostic script.")
    return value


print("=== direct connection ===")
try:
    conn = psycopg2.connect(
        host=env("MED_AUDIT_VASTBASE_HOST"),
        port=int(env("MED_AUDIT_VASTBASE_PORT", "5432")),
        dbname=env("MED_AUDIT_VASTBASE_DB"),
        user=env("MED_AUDIT_VASTBASE_USER"),
        password=env("MED_AUDIT_VASTBASE_PASSWORD"),
        connect_timeout=10,
    )
    print("direct connection OK:", conn.server_version)
    conn.close()
except Exception as exc:
    print("direct connection FAIL:", exc)

print("\n=== application config connection ===")
from app.config import load_config
from app.services.config_parser import ConfigParser

cfg = load_config()
emr_cfg = ConfigParser.parse_emr_vastbase_config(cfg)
print("host:", emr_cfg.get("host"))
print("port:", emr_cfg.get("port"))
print("database:", emr_cfg.get("database"))
print("username:", emr_cfg.get("username"))
print("password_present:", bool(emr_cfg.get("password")))
print("password_len:", len(emr_cfg.get("password", "")))

try:
    conn = psycopg2.connect(
        host=emr_cfg["host"],
        port=int(emr_cfg["port"]),
        dbname=emr_cfg["database"],
        user=emr_cfg["username"],
        password=emr_cfg["password"],
        connect_timeout=10,
    )
    print("application config connection OK:", conn.server_version)
    conn.close()
except Exception as exc:
    print("application config connection FAIL:", exc)
