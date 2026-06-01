"""测试不同连接方式"""
import socket
import psycopg2

host = "10.10.8.177"
port = 5432
db = "jhemr"
user = "aizk_user"
pwd = "aizk_user@123"

# 测试 socket 连通性
s = socket.socket()
s.settimeout(5)
s.connect((host, port))
print("Socket OK")
s.close()

# 尝试不同连接参数
tests = [
    {"host": host, "port": port, "dbname": db, "user": user, "password": pwd, "connect_timeout": 10, "sslmode": "disable"},
    {"host": host, "port": port, "dbname": db, "user": user, "password": pwd, "connect_timeout": 10, "sslmode": "prefer"},
    {"host": host, "port": port, "dbname": db, "user": user, "password": pwd, "connect_timeout": 10},
    {"host": host, "port": port, "dbname": db, "user": user, "password": pwd, "connect_timeout": 10, "gssencmode": "disable", "sslmode": "disable"},
]

for i, params in enumerate(tests):
    try:
        print(f"\nTest {i+1}: {params}")
        conn = psycopg2.connect(**params)
        print(f"  SUCCESS! version={conn.server_version}")
        conn.close()
    except Exception as e:
        print(f"  FAILED: {e}")
