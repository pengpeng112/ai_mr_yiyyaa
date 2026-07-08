"""Test Vastbase connection variants using environment-provided credentials."""
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
db = env("MED_AUDIT_VASTBASE_DB")
user = env("MED_AUDIT_VASTBASE_USER")
pwd = env("MED_AUDIT_VASTBASE_PASSWORD")

s = socket.socket()
s.settimeout(5)
s.connect((host, port))
print("Socket OK")
s.close()

tests = [
    {"host": host, "port": port, "dbname": db, "user": user, "password": pwd, "connect_timeout": 10, "sslmode": "disable"},
    {"host": host, "port": port, "dbname": db, "user": user, "password": pwd, "connect_timeout": 10, "sslmode": "prefer"},
    {"host": host, "port": port, "dbname": db, "user": user, "password": pwd, "connect_timeout": 10},
    {"host": host, "port": port, "dbname": db, "user": user, "password": pwd, "connect_timeout": 10, "gssencmode": "disable", "sslmode": "disable"},
]

for i, params in enumerate(tests):
    safe_params = {**params, "password": "***"}
    try:
        print(f"\nTest {i + 1}: {safe_params}")
        conn = psycopg2.connect(**params)
        print(f"  SUCCESS! version={conn.server_version}")
        conn.close()
    except Exception as exc:
        print(f"  FAILED: {exc}")
