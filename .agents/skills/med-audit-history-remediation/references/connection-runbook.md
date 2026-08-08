# 服务器与数据库操作手册

## 凭据与连接原则

- SSH：`10.10.8.84:40022`，用户 `root`。
- 服务：`http://10.10.8.84:8000`；容器 `med-audit`；Compose 目录 `/opt/med-audit-docker`。
- SSH 密码只从本机秘密存储或 `MED_AUDIT_SSH_PASSWORD` 读取。
- Vastbase 密码只从 `MED_AUDIT_VASTBASE_PASSWORD` 读取。
- 不在命令行、日志、脚本、技能文件、聊天回复或进程列表中暴露密码。
- 首次连接必须核对主机指纹；禁止无条件接受未知 host key。

## 推荐连接方式

先做无凭据泄露的 SSH 探测，再进入容器复用应用配置和 SQLAlchemy `SessionLocal`：

```powershell
$env:MED_AUDIT_SSH_PASSWORD = (Read-Host -AsSecureString "SSH password")
ssh -p 40022 root@10.10.8.84 "hostname; docker ps --filter name=med-audit; curl -fsS http://127.0.0.1:8000/api/health/live"
```

如果自动化工具不能安全读取 SecureString，使用已经配置好密钥/凭据代理的 SSH 客户端；不得把密码拼进 `ssh`、`plink` 或 URL。

应用库查询优先在容器内运行仓库中经过复核的只读脚本：

```bash
docker exec -w /app med-audit python scripts/<approved_readonly_script>.py --dry-run
```

写入脚本必须具备 `--dry-run` 默认值，并要求同时提供 `--apply`、批准单号、run_id 和快照哈希才允许写入。禁止直接把临时 SQL 粘到生产 SQL 客户端执行。

## 生产预检

每次连接后先验证：

1. 容器唯一且健康，uvicorn 为单 worker。
2. 当前镜像 ID、启动时间和配置挂载位置。
3. `APP_DB_TYPE` 与实际应用库一致。
4. 业务源连接只做 `SELECT 1` 或受限聚合，不打印连接串。
5. 当前没有调度/手工推送正在处理相同记录；如无法证明，停止写入。
6. 备份目录位于持久化宿主机路径，不只存在于容器可写层。

## 外部 AI 隔离

生产服务器不得调用公网 AI。流程必须是：

`生产只读查询 -> 内网脱敏 -> 人工检查 -> 仅导出脱敏复核包 -> 外部 AI -> 返回决定文件 -> 内网 schema/规则校验 -> 人工批准 -> 生产执行`

本地 token-to-ID 映射、数据库 ID、患者/就诊标识和 before 快照不得放入外部复核包。

