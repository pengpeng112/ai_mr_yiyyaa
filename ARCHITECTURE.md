# ARCHITECTURE

> 医疗记录一致性审计系统（Backend）

## Overview
- FastAPI 后端，从 Oracle / PostgreSQL 抽取病历与护理记录，推送到 Dify 做一致性审计，落库并提供统计、日志与质控反馈。
- 运行形态：单实例（uvicorn 单 worker），可 Docker 离线部署，SQLite/Oracle 作为应用库。

## Tech Stack
- Language: Python 3.11
- Web: FastAPI (`app/main.py`)
- DB: SQLite / Oracle（SQLAlchemy，`app/database.py`）
- External DB Source: Oracle / PostgreSQL（`app/oracle_client.py`, `app/postgresql_client.py`）
- Scheduler: APScheduler (`app/scheduler.py`)
- Auth/RBAC: JWT + RBAC（`app/auth.py`, `app/permissions.py`, `app/models.py`）
- AI: Dify Workflow API（`app/dify_pusher.py`）
- Notifications: 企业微信 / 钉钉 / 邮件 / Webhook（`app/notifier.py`）
- Storage: SQLite WAL 模式（默认）

## Directory Structure
```
app/
├── main.py              # FastAPI 入口、日志配置、路由注册
├── config.py            # 配置读写、加解密、运行时校验
├── database.py          # SQLAlchemy engine/Session + 迁移/自检/初始化
├── models.py            # ORM 模型（push_log / audit_* / RBAC / QC）
├── schemas.py           # Pydantic v2 请求/响应模型
├── auth.py              # JWT 认证
├── permissions.py       # RBAC 权限检查
├── oracle_client.py     # Oracle 数据查询与连接池
├── postgresql_client.py # PostgreSQL 数据查询
├── dify_pusher.py       # Dify Workflow API 推送
├── notifier.py          # 预警通知
├── scheduler.py         # APScheduler 定时任务
├── routers/             # API 路由（每文件一个 APIRouter）
└── services/            # 业务逻辑层（推送、导出、菜单等）

config/                  # 运行时配置（config.json）
data/                    # SQLite 数据库存放目录
logs/                    # 应用/审计日志
scripts/                 # 手动测试与运维脚本
tests/                   # pytest 用例（部分功能测试）
prompts/                 # Dify 提示词与 JSON 输出结构
static/                  # 前端构建产物（FastAPI 静态挂载）
docs/                    # 补充文档
```

## Core Components
- **API 入口**：`app/main.py`
  - 初始化日志、CORS、中间件
  - 注册所有路由
  - 生命周期内启动/关闭 scheduler
- **配置与安全**：`app/config.py`
  - `config/config.json` 线程安全读写
  - `SECRET_KEY` 派生 Fernet，保存 `password_enc` / `api_key_enc`
  - 运行时校验 Dify Base URL / SQL 占位符 / Oracle Client 路径
- **数据层**：`app/database.py` + `app/models.py`
  - SQLAlchemy ORM 模型与迁移
  - SQLite WAL + 自动字段迁移
  - Oracle 模式下自动序列与字段补齐
- **数据抽取**：`app/oracle_client.py`, `app/postgresql_client.py`
  - Oracle 连接池 / 直连、记录查询与科室列表
  - PostgreSQL 查询与连通性测试
- **推送执行器**：`app/services/push_executor.py`
  - 批量推送、结果解析、结构化审计结果落库
- **通知与反馈**：`app/notifier.py`, `app/routers/qc_feedback.py`
  - 预警消息推送与质控反馈流程
- **调度任务**：`app/scheduler.py`
  - 定时触发批量推送

## Data Flow
1. **触发**
   - 手动推送 API：`/api/push`（`app/routers/push.py`）
   - 定时推送：`app/scheduler.py`（APScheduler）
2. **数据抽取**
   - 从 Oracle/PostgreSQL 拉取病程/护理记录（`oracle_client.py` / `postgresql_client.py`）
3. **构造 payload**
   - `app/services/payload_builder.py` / `build_dify_mr_text()`
4. **推送 Dify**
   - `app/dify_pusher.py` 调用 Workflow API
5. **解析并落库**
   - `PushLog`、`AuditDimensionResult`、`AuditConclusion` 写入（`models.py`）
6. **通知/反馈**
   - `notifier.py` 触发通知
   - 质控反馈写入 `QCFeedback` 与历史表
7. **查询与统计**
   - 日志、统计、报告路由读取数据库结果

## External Integrations
- **Dify Workflow API**：`app/dify_pusher.py`
- **Oracle**：`cx_Oracle`（Instant Client，`oracle-client/` 打包进镜像）
- **PostgreSQL**：`psycopg2`
- **通知通道**：企业微信 / 钉钉 / 邮件 / Webhook（`app/notifier.py`）

## Configuration
- **环境变量**：`.env.example`
  - `JWT_SECRET_KEY`, `SECRET_KEY`, `APP_DB_TYPE`, `APP_ORACLE_*`, `ENABLE_SCHEDULER`, `ALLOWED_ORIGINS`
- **运行时配置**：`config/config.json`（加密字段：`password_enc`, `api_key_enc`）
- **配置自检**：`app/config.py::validate_runtime_config()`（启动时告警）

## Build & Deploy
- 本地开发：
  - `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
- Docker：
  - `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`
  - 单 worker（APScheduler 约束）
- 运维说明：`DEPLOY.md`

## Tests & Validation
- pytest：`pytest.ini`, `tests/`
- 手工脚本：`scripts/test_api.py`, `scripts/test_phase2.py`, `scripts/test_phase3.py`, `scripts/quick_start.py`
- 备注：文档中提到“无 pytest”，但仓库存在 `tests/` 与 `pytest.ini`（请以实际目录为准）
