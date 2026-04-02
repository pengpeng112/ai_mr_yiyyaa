# Med-Audit Docker 部署手册

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

默认账户：`admin / admin123`

---

## 四、升级（重新构建后）

将新的 `med-audit-image.tar` 传输到服务器后：

```bash
docker load -i med-audit-image.tar
docker-compose -f /opt/med-audit-docker/docker-compose.yml up -d
```

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

# 手动备份数据库
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

**Oracle Client 不影响其他功能**，仅在从 Oracle 拉取病历数据时需要。

---

## 八、生产安全检查

- [ ] `JWT_SECRET_KEY` 已修改为强随机密钥
- [ ] `SECRET_KEY` 已修改
- [ ] 默认用户密码已修改（`admin / admin123`）
- [ ] 服务器防火墙仅开放 8000 端口给内网
- [ ] 定期备份 `data/` 目录（SQLite 数据库）和 `config/config.json`
