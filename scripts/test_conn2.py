"""快速连接测试"""
import socket
host = "10.10.8.177"
port = 5432
s = socket.socket()
s.settimeout(5)
s.connect((host, port))
print("Socket OK")
s.close()

import psycopg2
try:
    conn = psycopg2.connect(host=host, port=port, dbname="jhemr", user="aizk_user", password="aizk_user@123", connect_timeout=10, sslmode="disable", gssencmode="disable")
    print(f"PG OK: {conn.server_version}")
    conn.close()
except Exception as e:
    print(f"PG FAIL: {e}")
