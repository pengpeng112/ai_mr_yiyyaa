# Med-Audit Docker 部署手册

> 文档导航：项目总入口见 `README_CN.md`，完整开发说明见 `开发文档.md`。

> 适用：内网服务器（Linux x86_64）· Docker 部署

---

## 一、Windows 端构建镜像

在开发机（已安装 Docker Desktop）上执行：

```bat
双击运行: backend\docker_build.bat
```

构建完成后输出两个文件：

| 文件 | 说明 |
|------|------|
| `med-audit-image.tar` | Docker 镜像包（~267 MB） |
| `med-audit-docker/` | 部署文件目录（含 docker-compose.yml、config） |

---

## 二、传输到服务器

```bash
# scp 传输（内网可达）
scp med-audit-image.tar user@192.168.x.x:/opt/
scp -r med-audit-docker user@192.168.x.x:/opt/
```

也可通过 U 盘或内网共享目录复制到服务器 `/opt/` 下。

---

## 三、服务器首次部署

SSH 登录服务器后执行：

```bash
cd /opt

# 1. 加载镜像
docker load -i med-audit-image.tar

# 2. 启动服务
bash med-audit-docker/docker_deploy.sh
```

启动成功后访问：
- 前端页面：`http://<服务器IP>:8000`
- API 文档：`http://<服务器IP>:8000/docs`
- 健康检查：`http://<服务器IP>:8000/api/health`

默认账户：`admin / Admin123456`

---

## 四、升级（重新构建后）

将新的 `med-audit-image.tar` 传输到服务器后：

```bash
docker load -i med-audit-image.tar
docker-compose -f /opt/med-audit-docker/docker-compose.yml up -d
```

### 4.1 安全升级（推荐，保留配置与快速回滚）

> 目标：升级镜像时不丢失 `config/data/logs`，并保留回滚能力。

#### 升级前备份（必须）

```bash
cd /opt

# 1) 备份部署目录（含 .env、config、data、logs）
cp -a med-audit-docker med-audit-docker.bak.$(date +%Y%m%d_%H%M%S)

# 2) 备份当前运行镜像（可选但强烈建议）
docker save med-audit:latest -o med-audit-image.backup.$(date +%Y%m%d_%H%M%S).tar
```

#### 升级执行

```bash
# 1) 停旧容器
docker stop med-audit 2>/dev/null || true
docker rm med-audit 2>/dev/null || true

# 2) 加载新镜像
docker load -i /opt/med-audit-image.tar

# 3) 使用原有部署目录重启（保留原配置与数据卷）
bash /opt/med-audit-docker/docker_deploy.sh
```

#### 升级后验证

```bash
# 应用数据库类型（Oracle 模式应输出 oracle）
docker exec med-audit python -c "from app.database import engine; print(engine.dialect.name)"

# 健康检查
curl -sS http://127.0.0.1:8000/api/health

# 运行日志
docker logs --tail 120 med-audit
#实时日志查看 docker
 docker logs -f med-audit
```

#### 回滚步骤（升级失败时）

```bash
# 1) 停止当前失败容器
docker stop med-audit 2>/dev/null || true
docker rm med-audit 2>/dev/null || true

# 2) 加载备份镜像
docker load -i /opt/med-audit-image.backup.YYYYmmdd_HHMMSS.tar

# 3) 使用原目录重启
bash /opt/med-audit-docker/docker_deploy.sh
```

#### 关键注意事项

- `SECRET_KEY` 必须保持不变，否则无法解密 `config/config.json` 中的 `password_enc/api_key_enc`。
- 不要删除 `/opt/med-audit-docker/config` 和 `/opt/med-audit-docker/data`。
- 升级镜像不会自动覆盖挂载目录中的配置文件；真正风险来自误删目录或修改 `SECRET_KEY`。

---

## 五、常用运维命令

```bash
# 查看容器状态
docker ps

# 查看应用日志
docker logs med-audit
docker logs -f med-audit   # 实时跟踪

# 重启容器
docker restart med-audit

# 停止 / 启动
docker stop med-audit
docker start med-audit

# 进入容器
docker exec -it med-audit bash

# 手动备份数据库（SQLite 模式）
docker cp med-audit:/app/data/med_audit.db ./med_audit.db.$(date +%Y%m%d)
```

---

## 六、配置说明

`med-audit-docker/config/config.json` 存放运行时配置（Oracle 连接信息、Dify API Key 等）。

容器通过 `docker-compose.yml` 中的环境变量注入密钥：

```yaml
environment:
  - JWT_SECRET_KEY=your-strong-secret-key   # 必须修改
  - SECRET_KEY=your-encryption-key          # 必须修改，用于解密 config.json 中的密码
```

> **重要**：`SECRET_KEY` 与 `config.json` 加密密钥必须一致，迁移服务器时两者需同步转移。

### Oracle Instant Client 目录填写规范（Docker / Linux）

- 若服务部署在 Docker 容器中，Oracle Client 目录应填写：`/opt/oracle`
- 不要填写 Windows 路径（例如 `D:\...`），容器内无法识别
- 如已在镜像内配置 `LD_LIBRARY_PATH`，该字段也可留空

### 应用数据库切换（SQLite / Oracle）

新增环境变量：

```env
APP_DB_TYPE=sqlite
APP_ORACLE_HOST=10.255.255.20
APP_ORACLE_PORT=1521
APP_ORACLE_SERVICE_NAME=orcl
APP_ORACLE_USERNAME=
APP_ORACLE_PASSWORD=
```

- `APP_DB_TYPE=sqlite`：保持当前本地 SQLite 持久化
- `APP_DB_TYPE=oracle`：应用业务表切换到 Oracle，表名自动使用 `MED_` 前缀

当使用 Oracle 作为应用库时：

1. 先在 `.env` 中将 `APP_DB_TYPE` 改为 `oracle`
2. 填写 `APP_ORACLE_*` 连接信息
3. 启动容器，应用会自动创建 `MED_*` 业务表
4. 如需迁移历史 SQLite 数据，执行：

```bash
docker exec -it med-audit python scripts/migrate_sqlite_to_oracle.py --source /app/data/med_audit.db
```

迁移脚本默认行为：
- 源表不存在则跳过
- 目标 Oracle 表非空则跳过，避免重复导入
- 适用于当前项目的小规模历史数据迁移

---

## 七、Oracle Client 说明

`oracle-client/linux/` 中已包含 Oracle 11.2 的 `.so` 文件，镜像构建时自动打包。

若 Oracle 连接报错，排查步骤：

```bash
# 进入容器检查
docker exec -it med-audit bash

# 检查 so 文件
ls /opt/oracle/*.so*

# 测试加载
python3 -c "import cx_Oracle; print('OK')"
```

**Oracle Client 不影响其他功能**，仅在从 Oracle 拉取病历数据或启用 Oracle 作为应用库时需要。

若启用 `APP_DB_TYPE=oracle`，建议额外验证：

```bash
docker exec -it med-audit python -c "from app.database import engine; print(engine.dialect.name)"
docker exec -it med-audit python -c "from app.database import test_app_db_connection; print(test_app_db_connection())"
```

---

## 八、生产安全检查

- [ ] `JWT_SECRET_KEY` 已修改为强随机密钥
- [ ] `SECRET_KEY` 已修改
- [ ] 默认用户密码已修改（`admin / Admin123456`）
- [ ] 服务器防火墙仅开放 8000 端口给内网
- [ ] 已根据部署模式备份数据：SQLite 模式备份 `data/`，Oracle 模式备份 Oracle 表和 `config/config.json`

---

## 九、四色预警分级系统（v2.0）

### 9.1 新增功能概述

系统新增四色灯预警分级模型，对 Dify AI 审计结果实现更精细化的风险分层：

| 灯号 | 含义 | 闭环时限 | 推送策略 |
|------|------|----------|----------|
| 🔴 红灯 (red) | 高风险，危及患者安全 | 24 小时 | 立即推送 (immediate) |
| 🟡 黄灯 (yellow) | 中度风险，影响病历质量 | 72 小时 | 批量推送 (batch) |
| 🔵 蓝灯 (blue) | 低风险/规范性问题 | 无强制 | 班次汇总 (shift_summary) |
| ⚪ 灰灯 (gray) | 不确定/置信度低 | 无 | 仅供复核 (review_only) |

**向后兼容**：旧版 Dify 输出（v1，无 alert 字段）仍可正常解析，新字段自动回退为默认空值。`alert_level` 与原有 `severity` 字段并存，不替换。

### 9.2 数据库自动迁移

升级部署后，应用启动时会**自动**执行 ALTER TABLE 添加新字段，无需手动操作。

**新增字段一览**：

| 表名 | 新字段 | 类型 | 说明 |
|------|--------|------|------|
| push_logs | `alert_level` | VARCHAR(10) | 总体预警灯号 |
| audit_dimension_results | `alert_level` | VARCHAR(10) | 维度预警灯号 |
| audit_dimension_results | `closure_hours` | INTEGER | 闭环时限（小时） |
| audit_dimension_results | `push_strategy` | VARCHAR(20) | 推送策略 |
| audit_dimension_results | `outcome_bucket` | VARCHAR(20) | 结局分桶 |
| audit_conclusions | `alert_level` | VARCHAR(10) | 总体预警灯号 |
| audit_conclusions | `closure_hours` | INTEGER | 闭环时限（小时） |
| audit_conclusions | `push_strategy` | VARCHAR(20) | 推送策略 |
| audit_conclusions | `outcome_bucket` | VARCHAR(20) | 结局分桶 |
| audit_conclusions | `overall_qc_summary` | TEXT | 整体质控结果描述 |

> Oracle 模式下表名带 `MED_` 前缀（如 `MED_PUSH_LOGS`），迁移逻辑同样自动执行。

### 9.3 Dify 提示词部署

升级需同步更新 Dify Workflow 中的两段提示词：

| 文件 | 用途 | 部署位置 |
|------|------|----------|
| `prompts/v2_consistency_audit.md` | 质控分析规则（精简版） | Dify Workflow — 分析提示词节点 |
| `prompts/v2_json_output_schema.md` | JSON 输出格式约束（精简版） | Dify Workflow — 输出格式提示词节点 |

**部署步骤**：
1. 登录 Dify 控制台
2. 打开对应的 Workflow
3. 将 `v2_consistency_audit.md` 内容替换到分析提示词节点
4. 将 `v2_json_output_schema.md` 内容替换到输出格式提示词节点
5. 发布 Workflow 新版本
6. 验证：手动推送一条记录，确认返回 JSON 包含 `alert_level`、`closure_hours`、`push_strategy`、`outcome_bucket`、`overall_qc_summary` 字段

### 9.4 升级验证

部署完成后执行以下检查：

```bash
# 1. 健康检查
curl http://<服务器IP>:8000/api/health

# 2. 确认新字段存在（SQLite 模式）
docker exec -it med-audit python -c "
from app.database import engine
from sqlalchemy import inspect
insp = inspect(engine)
cols = [c['name'] for c in insp.get_columns('audit_conclusions')]
assert 'alert_level' in cols, 'alert_level 字段缺失'
assert 'overall_qc_summary' in cols, 'overall_qc_summary 字段缺失'
print('✅ 数据库字段迁移正常')
"

# 3. 确认新字段存在（Oracle 模式）
docker exec -it med-audit python -c "
from app.database import engine
from sqlalchemy import inspect
insp = inspect(engine)
cols = [c['name'] for c in insp.get_columns('MED_AUDIT_CONCLUSIONS')]
assert 'alert_level' in cols or 'ALERT_LEVEL' in cols, 'alert_level 字段缺失'
print('✅ Oracle 数据库字段迁移正常')
"
```

### 9.5 回滚方案

若升级后出现异常，回滚步骤：

1. **应用回滚**：使用升级前的 Docker 镜像重新部署
   ```bash
   docker load -i med-audit-image-backup.tar
   docker-compose -f /opt/med-audit-docker/docker-compose.yml up -d
   ```

2. **数据库**：新增的字段不影响旧版代码运行（旧代码不读取新字段），无需删除字段

3. **Dify 提示词**：在 Dify 控制台将 Workflow 回退到上一个发布版本

> **重要**：升级前请务必备份数据库和当前 Docker 镜像。

---

## 十、内网 Oracle 实战部署命令清单（推荐）

> 适用于：你已在 Windows 端完成 `docker_build.bat`，并准备把新版镜像上线到内网 Linux 服务器。

### 10.1 Windows 端（打包 + 哈希）

```bat
cd /d D:\Users\Administrator\Desktop\AI应用\trae\ai_mr_yiyyaa\.claude\worktrees\youthful-hermann\backend0401
docker_build.bat

REM 记录 tar 包哈希（用于服务器核对，避免误用旧包）
certutil -hashfile "..\med-audit-image.tar" SHA256
```

### 10.2 传输到服务器

```bash
scp med-audit-image.tar root@<server-ip>:/opt/
scp -r med-audit-docker root@<server-ip>:/opt/
```

### 10.3 服务器侧（强制更新）

```bash
ssh root@<server-ip>
cd /opt/med-audit-docker

# 停旧容器
docker stop med-audit 2>/dev/null || true
docker rm med-audit 2>/dev/null || true

# 清理历史 override（如有）
rm -f docker-compose.override.yml

# 加载新镜像
docker load -i /opt/med-audit-image.tar
```

### 10.4 版本指纹校验（强烈建议）

```bash
# 1) 查看镜像 ID
docker images | grep med-audit

# 2) 确认镜像内含 Oracle sequence 修复代码关键字
docker run --rm --entrypoint /bin/sh med-audit:latest -c "grep -n 'get_pk_constraint\|START WITH 1\|Oracle sequence 起始值计算失败' /app/app/database.py"
```

若 grep 没命中上述关键字，说明服务器仍在使用旧镜像，请重新上传 tar。

### 10.5 Oracle 运行配置（.env）

```bash
cd /opt/med-audit-docker
cat > .env <<'EOF'
APP_DB_TYPE=oracle
APP_ORACLE_HOST=10.10.8.216
APP_ORACLE_PORT=1521
APP_ORACLE_SERVICE_NAME=orcl
APP_ORACLE_USERNAME=jhemr
APP_ORACLE_PASSWORD=jhemr123
EOF

cat .env
```

### 10.6 启动服务

```bash
chmod +x /opt/med-audit-docker/docker_deploy.sh
bash /opt/med-audit-docker/docker_deploy.sh
```

### 10.7 启动后验证

```bash
# 容器状态
docker ps | grep med-audit || true

# 应用日志
docker logs --tail 200 med-audit

# 应用数据库类型必须为 oracle
docker exec med-audit python -c "from app.database import engine; print(engine.dialect.name)"

# 健康检查
curl -sS http://127.0.0.1:8000/api/health
```

预期：
- `engine.dialect.name` 输出 `oracle`
- `/api/health` 至少 `app_db.status=up`

### 10.8 常见问题与处理

1) **`$'\r'` / shell 语法错误**
- 原因：Windows CRLF
- 处理：
```bash
sed -i 's/\r$//' /opt/med-audit-docker/docker_deploy.sh
sed -i 's/\r$//' /opt/med-audit-docker/docker-compose.yml
```

2) **`DPI-1047` / `libaio.so.1` 错误**
- 原因：Oracle 客户端动态库依赖
- 处理：使用最新版镜像（已内置兼容软链与 `LD_LIBRARY_PATH`）

3) **`ORA-01408`（重复索引）**
- 原因：旧版本模型索引定义冲突
- 处理：确保加载最新版镜像

4) **`ORA-02289`（sequence does not exist）**
- 原因：旧表存在但 sequence 缺失
- 处理：确保加载最新版镜像（已自动补 sequence）

5) **`ORA-00904: "id" invalid identifier`**
- 原因：旧版本 sequence 初始化用错列名大小写
- 处理：确保加载含 `get_pk_constraint` + `START WITH 1` 修复的最新镜像

6) **Health 显示 `degraded` 但服务可访问**
- 常见原因：PostgreSQL 或 Dify 不可达
- 若 `app_db=up` 且页面可访问，说明主服务已启动；再单独处理外部依赖连通性
