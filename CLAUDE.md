# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

医疗记录一致性审计系统（Med-Audit）—— FastAPI 后端服务，核心流程：从 Oracle/PostgreSQL 抽取病历数据 → 调用 Dify AI Workflow 进行一致性分析 → 存储结果 → 多渠道推送预警。

## 常用命令

```bash
# 启动开发服务器（热重载）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 运行全部测试
pytest tests/ -v

# 运行单个测试文件
pytest tests/test_oracle_client.py -v

# 运行单个测试函数
pytest tests/test_oracle_client.py::test_function_name -v

# Docker 构建与启动
docker-compose up -d --build

# 查看容器日志
docker logs -f med-audit
```

## 架构与核心模块

### 技术栈

FastAPI + SQLAlchemy 2.0 + APScheduler + Pydantic 2 + cx_Oracle + PyJWT

### 应用数据库支持

- **SQLite**（开发/演示）：`data/med_audit.db`，无需外部依赖
- **Oracle**（生产）：通过 `APP_DB_TYPE=oracle` 环境变量切换，需要 Oracle Instant Client
- **PostgreSQL**（可选）：通过 `APP_DB_TYPE=postgresql` 切换

应用数据库（存储审计结果、用户、配置）与业务数据库（Oracle/PostgreSQL，存储病历数据）是两套不同连接。

### 核心数据流

```
Oracle/PostgreSQL 病历库
    ↓ oracle_client.py / postgresql_client.py
按患者分组的病历+护理数据
    ↓ services/push_executor.py
逐患者轮询（默认间隔 500ms）
    ↓ dify_pusher.py
Dify Workflow AI 分析（超时 90s，Blocking 模式）
    ↓ models.py (push_log / audit_dimension_result / audit_conclusion)
存储至应用数据库
    ↓ notifier.py / notify_channels.py
企微 / 钉钉 / 邮件 / HTTP 回调
```

### 关键模块

| 模块 | 职责 |
|------|------|
| `app/config.py` | 三层配置（环境变量 > JSON 文件 > SQLite），加密存储敏感字段 |
| `app/database.py` | 数据库连接管理，支持多数据库类型切换 |
| `app/models.py` | SQLAlchemy ORM 定义（push_log, qc_feedback, users, roles, permissions 等） |
| `app/schemas.py` | Pydantic 请求/响应模型 |
| `app/oracle_client.py` | Oracle 病历数据抽取，可配置 SQL 和字段映射 |
| `app/dify_pusher.py` | Dify Workflow API 调用，解析 AI 结构化输出 |
| `app/scheduler.py` | APScheduler 定时调度，支持 Cron 表达式，记录调度历史 |
| `app/services/push_executor.py` | 批量推送核心，失败重试（最多 3 次），进度跟踪 |
| `app/services/config_parser.py` | 配置解析，支持运行时自检 |
| `app/permissions.py` | RBAC 权限中间件，用户-角色-权限三层 |

### API 路由前缀

| 前缀 | 功能 |
|------|------|
| `/api/config` | Oracle/Dify/定时任务等配置读写 |
| `/api/push` | 手动触发推送、重试、进度查询 |
| `/api/logs` | 推送日志列表/详情/导出 |
| `/api/scheduler` | 定时任务状态、触发、更新 |
| `/api/stats` | 汇总统计、趋势、维度分析 |
| `/api/notify` | 通知渠道配置与测试 |
| `/api/health` | 系统健康检查（DB/Dify/Scheduler） |
| `/api/users` | 登录、注册、用户信息 |
| `/api/qc/feedback` | 质控反馈闭环管理 |
| `/api/departments` | 科室管理 |
| `/api/reports` | 审计报告导出 |

### 日志

- `logs/app.log` — 应用运行日志（轮转，10MB×5）
- `logs/audit_detail.log` — Dify 请求/响应、Oracle 查询详情（审计专用）

Logger 名称：`audit.dify`、`audit.oracle`

## 关键配置

关键环境变量（参见 `.env.example`）：

| 变量 | 说明 |
|------|------|
| `APP_DB_TYPE` | 应用库类型：`sqlite` / `oracle` / `postgresql` |
| `JWT_SECRET_KEY` | JWT 签名密钥（生产必须修改） |
| `SECRET_KEY` | 配置加密密钥（生产必须修改） |
| `ALLOWED_ORIGINS` | CORS 允许源 |
| `ENABLE_SCHEDULER` | 是否启用定时任务（`true`/`false`） |

运行时配置存储在 `config/config.json`，通过 `/api/config` 接口读写，敏感字段加密存储。

## 测试

测试配置在 `pytest.ini`，测试文件在 `tests/`，数据库使用 SQLite 内存库或 conftest.py 中的 fixture。

生产 Oracle 连接不在单元测试中使用，Oracle 相关测试通过 Mock 或测试专用连接字符串隔离。

## Docker 部署注意

- 容器以非 root 用户（uid=1000）运行，`logs/`、`data/`、`config/` 目录需有写权限
- 挂载卷：`./data:/app/data`、`./config:/app/config`、`./logs:/app/logs`
- 单 worker 模式（`--workers 1`），APScheduler 不支持多进程
- Oracle Instant Client 需在镜像构建时集成（见 `Dockerfile`）
