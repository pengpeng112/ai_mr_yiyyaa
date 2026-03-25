# 医疗记录一致性审计系统 —— 数据抽取服务

## 系统简介

本系统定时从医院 Oracle 数据库抽取 **病程记录** 与 **护理记录**，组装为结构化数据，推送至 **Dify Workflow API** 进行 AI 一致性分析，发现不一致后实时预警通知临床人员。

```
Oracle DB (jhemr / ydhl)
    │
    ▼  数据抽取服务（FastAPI）
    │
 Dify Workflow API（AI 一致性分析）
    │
    ▼
 分级预警推送 → 企微/钉钉/邮件/Webhook → 临床人员
```

## 技术栈

| 层次 | 方案 |
|------|------|
| 后端框架 | Python FastAPI（Swagger UI `/docs`） |
| Oracle 连接 | cx_Oracle + Oracle Instant Client |
| 定时任务 | APScheduler（Cron 表达式） |
| 配置/日志存储 | SQLite（volume 挂载持久化） |
| 容器编排 | docker-compose |

## 快速启动

### 方式一：Windows 本地直接运行

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
# 访问 http://localhost:8080/docs
```

### 方式二：Docker 开发环境（热重载）

```bash
docker-compose -f docker-compose.dev.yml up
# 访问 http://localhost:8080/docs
```

### 方式三：Docker 生产环境

```bash
# 创建 .env 文件
echo "SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" > .env

docker-compose up -d
```

## 离线部署至 EulerOS 服务器

```bash
# 1. Windows 构建 amd64 镜像
docker buildx build --platform linux/amd64 -t med-audit:1.0 ./backend --load
docker save med-audit:1.0 | gzip > med-audit-1.0.tar.gz

# 2. 传输至内网服务器（U盘/sftp）

# 3. EulerOS 导入并启动
docker load -i med-audit-1.0.tar.gz
mkdir -p data config logs
echo "SECRET_KEY=your-strong-secret-key" > .env
docker-compose up -d

# 4. 验证
curl http://localhost:8080/api/health
```

## API 接口总览

访问 `http://localhost:8080/docs` 查看完整 Swagger 文档。

| 分组 | 主要接口 |
|------|---------|
| ⚙️ 配置管理 | Oracle/Dify/科室/定时规则 CRUD + 测试连接 |
| 🚀 数据推送 | 手动推送、dry-run预览、批量重推、进度查询 |
| 📋 推送日志 | 分页查询、详情、CSV导出、单条重推 |
| ⏰ 定时任务 | 状态查询、启停、立即触发、执行历史 |
| 📊 数据统计 | 每日趋势、科室分布、严重等级、月报、异常Top10 |
| 🔔 预警通知 | 通知渠道配置与测试 |
| 💚 系统健康 | Oracle/Dify/调度器状态监控 |

## 项目结构

```
med-audit/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口
│   │   ├── config.py            # 配置读取（加密存储）
│   │   ├── database.py          # SQLAlchemy + SQLite
│   │   ├── models.py            # ORM 模型
│   │   ├── schemas.py           # Pydantic Schema
│   │   ├── oracle_client.py     # Oracle 连接与查询
│   │   ├── dify_pusher.py       # Dify API 推送
│   │   ├── scheduler.py         # APScheduler 定时任务
│   │   ├── notifier.py          # 预警通知（企微/钉钉/邮件/Webhook）
│   │   └── routers/             # API 路由
│   │       ├── config.py        # /api/config/*
│   │       ├── push.py          # /api/push/*
│   │       ├── logs.py          # /api/logs/*
│   │       ├── scheduler.py     # /api/scheduler/*
│   │       ├── health.py        # /api/health/*
│   │       ├── stats.py         # /api/stats/*
│   │       └── notify.py        # /api/notify/*
│   ├── oracle-client/           # Oracle Instant Client
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── data/                        # SQLite 持久化
├── config/                      # 配置文件
├── logs/                        # 应用日志
├── docker-compose.yml           # 生产
├── docker-compose.dev.yml       # 开发
└── README.md
```

## 安全注意事项

1. **密码加密**：Oracle 密码和 Dify API Key 使用 AES-256 加密存储
2. **SECRET_KEY**：通过环境变量注入，不写入镜像
3. **患者隐私**：日志中患者姓名可配置脱敏
4. **限流防护**：批量推送可配置间隔（interval_ms）
5. **失败重试**：支持手动重推，最多3次（可配置）

## 部署 Checklist

- [ ] Oracle Instant Client 已放入 `./backend/oracle-client/`
- [ ] `.env` 文件含 `SECRET_KEY`
- [ ] `docker buildx build --platform linux/amd64` 构建
- [ ] 服务器已安装 Docker 和 docker-compose
- [ ] `./data/`、`./config/`、`./logs/` 目录已创建
- [ ] `docker load` 导入镜像成功
- [ ] `/api/health` 返回 `healthy`
