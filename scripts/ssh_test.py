"""SSH 连接服务器并逐条执行命令"""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.10.8.84', port=40022, username='root', password='P@ssw0rd@123', timeout=15)
print("=== SSH 连接成功 ===")

def run(cmd, timeout=20):
    print(f"\n>>> {cmd[:80]}...")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors='replace')
    err = stderr.read().decode(errors='replace')
    if out.strip():
        print(out.strip())
    if err.strip():
        print("[STDERR]", err.strip()[:500])
    return out, err

# 1. 宿主机 psql（可能需要密码交互，跳过）
print("\n=== 宿主机信息 ===")
run("hostname")
run("docker ps --format '{{.Names}} {{.Status}}' | head -5")

# 2. 从容器内测试 psycopg2 连接
print("\n=== 容器内 psycopg2 连接测试 ===")
run("""docker exec med-audit python -c "import psycopg2; conn=psycopg2.connect(host='10.10.8.177',port=5432,dbname='jhemr',user='aizk_user',password='aizk_user@123',connect_timeout=10); print('OK',conn.server_version); conn.close()" 2>&1""")

# 3. 容器内配置文件检查
print("\n=== 容器内配置检查 ===")
run("""docker exec med-audit python -c "import json; cfg=json.load(open('/app/config/config.json')); e=cfg.get('emr_vastbase',{}); print('has_emr:', 'emr_vastbase' in cfg); print('enabled:', e.get('enabled')); print('host:', e.get('host'))" 2>&1""")

# 4. 容器内网络检查
print("\n=== 容器内网络检查 ===")
run("""docker exec med-audit python -c "import socket; s=socket.socket(); s.settimeout(5); s.connect(('10.10.8.177',5432)); print('socket OK'); s.close()" 2>&1""")

ssh.close()
