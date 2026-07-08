"""Quick Vastbase connectivity test using environment-provided credentials."""
import os
import socket

import psycopg2


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise SystemExit(f"Set {name} before running this diagnostic script.")
    return value


host = env("MED_AUDIT_VASTBASE_HOST")
port = int(env("MED_AUDIT_VASTBASE_PORT", "5432"))

s = socket.socket()
s.settimeout(5)
s.connect((host, port))
print("Socket OK")
s.close()

try:
    conn = psycopg2.connect(
        host=host,
        port=port,
        dbname=env("MED_AUDIT_VASTBASE_DB"),
        user=env("MED_AUDIT_VASTBASE_USER"),
        password=env("MED_AUDIT_VASTBASE_PASSWORD"),
        connect_timeout=10,
        sslmode="disable",
        gssencmode="disable",
    )
    print(f"PG OK: {conn.server_version}")
    conn.close()
except Exception as exc:
    print(f"PG FAIL: {exc}")
