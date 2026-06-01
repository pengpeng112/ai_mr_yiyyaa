# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

医疗记录一致性审计系统（Med-Audit）—— Python 3.11 + FastAPI 后端服务，核心流程：从 Oracle/PostgreSQL 抽取病历数据 → 调用 Dify AI Workflow 进行一致性分析 → 存储结果 → 多渠道推送预警。

## 常用命令

```bash
# 启动开发服务器（热重载）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 健康检查
curl http://localhost:8000/api/health

# 运行全部单元测试
pytest tests/ -v

# 运行单个测试文件
pytest tests/test_push_executor.py -v

# 运行单个测试函数
pytest tests/test_push_executor.py::test_function_name -v

# 脚本集成测试（需先启动服务）
python scripts/test_api.py
python scripts/quick_start.py

# Dify 解析器测试
python scripts/test_parser_v2.py

# RBAC 初始化（首次部署，创建角色和权限）
python scripts/init_rbac.py

# Docker 构建与启动
docker-compose up -d --build

# 查看容器日志
docker logs -f med-audit
```

## 架构与核心模块

### 技术栈

Python 3.11 + FastAPI + SQLAlchemy 2.0 + APScheduler + Pydantic v2 + cx_Oracle + PyJWT

### 应用数据库支持

- **SQLite**（开发/演示）：`data/med_audit.db`，WAL 模式，无需外部依赖
- **Oracle**（生产）：通过 `APP_DB_TYPE=oracle` 环境变量切换，需要 Oracle Instant Client
- **PostgreSQL**（可选）：通过 `APP_DB_TYPE=postgresql` 切换

应用数据库（存储审计结果、用户、配置）与业务数据库（Oracle/PostgreSQL，存储病历数据）是两套不同连接。

### 核心数据流

```
Oracle/PostgreSQL 病历库（含 extra_sources：医嘱/首页/检验等）
    ↓ services/data_source_loader.py（多源拉取 + 按患者+次数分组为 PatientBundle）
    ↓ services/payload_composer.py（按 audit_type.payload.builder 组装 Dify 入参）
        - legacy_progress_nursing：走 payload_builder.build_dify_payload（旧版病历+护理）
        - generic_multi_source：按 text_template 渲染多源文本
    ↓ services/push_executor.py（串行）或 bulk_push_executor.py（并行）
逐患者轮询（默认间隔 500ms）
    ↓ dify_pusher.py
Dify Workflow AI 分析（超时 90s，Blocking 模式，每个 audit_type 可绑定独立 Workflow）
    ↓ models.py (push_log / audit_dimension_result / audit_conclusion)
存储至应用数据库
    ↓ notifier.py / notify_channels.py
企微 / 钉钉 / 邮件 / HTTP 回调
```

### 关键模块

| 模块 | 职责 |
|------|------|
| `app/config.py` | 三层配置（环境变量 > JSON 文件 > SQLite），Fernet 加密存储敏感字段 |
| `app/database.py` | 数据库连接管理，支持多数据库类型切换，手动 ALTER TABLE 迁移 |
| `app/models.py` | SQLAlchemy ORM 定义（push_log, qc_feedback, users, roles, permissions 等） |
| `app/schemas.py` | Pydantic v2 请求/响应模型 |
| `app/auth.py` | JWT 认证（PyJWT + passlib） |
| `app/permissions.py` | RBAC 权限中间件，用户-角色-权限三层 |
| `app/oracle_client.py` | Oracle 病历数据抽取，可配置 SQL 和字段映射 |
| `app/postgresql_client.py` | PostgreSQL 数据查询，同 Oracle client 接口一致 |
| `app/db_client_base.py` | Oracle/PostgreSQL 客户端公共基类（SQL 注入校验、字段映射工具） |
| `app/dify_pusher.py` | Dify Workflow API 调用，解析 AI 结构化输出 |
| `app/scheduler.py` | APScheduler 定时调度，支持 Cron 表达式，记录调度历史 |
| `app/services/push_executor.py` | 串行推送核心（调度器/重试路径），失败重试（最多 3 次） |
| `app/services/bulk_push_executor.py` | 仅用于 `/api/push/manual` 的**并行**推送器，多 Dify 目标加权轮询 + 熔断冷却 |
| `app/services/task_manager.py` | 线程安全的 `TaskProgressManager`，支持取消/进度查询 |
| `app/services/payload_builder.py` | 组装结构化 Dify 入参（`build_dify_payload` / `build_dify_mr_text`），支持中英文字段别名映射，仅供 `legacy_progress_nursing` builder 使用 |
| `app/services/record_identity.py` | 病历记录唯一键提取（`get_record_source_key` / `get_record_mrid`），用于跳过重复推送 |
| `app/services/audit_type_registry.py` | 审计类型 CRUD（`AuditTypeRegistry`），校验 SQL/JSONPath，敏感字段经 Fernet 加密落地 `config.json` |
| `app/services/data_source_loader.py` | 多数据源加载与按 `(patient_id, visit_number)` 分组为 `PatientBundle`，供审计类型派单 |
| `app/services/payload_composer.py` | 按 `audit_type.payload.builder` 调度生成 Dify payload + mr_text，支持模板化多源拼接 |
| `app/services/retention_service.py` | 三级数据留存清理（L1 元数据 90d / L2 审计摘要 365d / L3 病历原文 30d 后脱敏），可由 scheduler 周期触发 |
| `app/services/export_audit_service.py` | 记录数据导出行为（`record_export_audit`），写入 `ExportAuditLog` 表 |
| `app/services/export_service.py` | 日志/反馈 CSV 导出 |
| `app/services/feedback_stats.py` | 反馈统计分析（维度聚合） |
| `app/services/patient_snapshot.py` | 患者快照缓存（UI 前缀加载用） |
| `app/services/menu_service.py` | 菜单权限组装（基于 RBAC） |
| `app/services/config_parser.py` | 配置解析工具 |

### 审计类型（audit_types）

`config/config.json` 中的 `audit_types` 数组定义可用审计类型，每条包含：`code`、`name`、`enabled`、`primary_source`、`sources`（含 `query_sql` / `field_mapping`）、`dify`（`api_url` + `api_key_enc`）、`payload.builder`、`payload.text_template`、JSON 抽取 `*_path`。新增字段时务必经 `AuditTypeRegistry` 校验：SQL 走 `validate_configurable_sql`，JSONPath 必须以 `$` 起始。`api_key_enc` 由 Fernet 加密，前端读取时通过 `to_masked_dict` 脱敏为 `mask_secret` 形式。

调度器 / 推送器在工作时调用 `load_patient_bundles` 拿到 `PatientBundle` 列表，再交给 `payload_composer.compose` 按类型生成 payload。`legacy_progress_nursing` builder 会回退到旧版 `payload_builder`，保证兼容存量配置。

### 推送路径区分

手动推送（`/api/push/manual`）走 `BulkPushExecutor`（并发线程池），调度器和重试走 `PushExecutor`（串行）。两者共用 `PushConfig`/`PushResult` 数据类和 `TaskProgressManager`。

手动推送支持**日期维度**过滤，`date_dimension` 字段可选：
- `query_date`：按查询日期（默认）
- `record_create_date`：按病历/护理记录创建时间
- `admission_date`：按入院日期
- `discharge_date`：按出院日期

### API 路由前缀

| 前缀 | 功能 |
|------|------|
| `/api/config` | Oracle/Dify/定时任务等配置读写 |
| `/api/audit-types` | 审计类型 CRUD、克隆、数据源测试、Dify 联调（仅管理员） |
| `/api/audit/logs` | 数据导出审计日志查询（仅管理员可见全量；普通用户只看自己） |
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
| `/api/roles` | 角色管理（CRUD） |
| `/api/permissions` | 权限列表与创建 |
| `/api/menu` | 用户可见菜单（基于 RBAC） |
| `/api/demo` | 演示接口（演示数据、演示推送） |

### 前端

前端使用 Vue 3 + Element Plus + ECharts CDN 单页方式，构建产物位于 `static/`，由 FastAPI 静态挂载提供服务（`/`）。
- `static/index.html` — 入口（大部分页面逻辑在此）
- `static/scripts/` — 模块化 JS（已拆分）
- `static/styles/` — 样式文件

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
| `SECRET_KEY` | Fernet 配置加密密钥（生产必须修改） |
| `ALLOWED_ORIGINS` | CORS 允许源 |
| `ENABLE_SCHEDULER` | 是否启用定时任务（`true`/`false`） |

运行时配置存储在 `config/config.json`，模板见 `config/config.json.template`，编辑时会写 `config/backups/` 时间戳备份，通过 `/api/config` 与 `/api/audit-types` 接口读写，密码字段以 `password_enc`/`api_key_enc` 加密存储。

## 代码规范

### 命名约定

| 类型 | 约定 | 示例 |
|------|------|------|
| 文件名 | snake_case | `push_executor.py` |
| 类名 | PascalCase | `PushExecutor`, `ManualPushRequest` |
| 函数/方法 | snake_case | `manual_push()`, `_async_push()` |
| 私有函数 | 前缀 `_` | `_get_fernet()` |
| 常量 | UPPER_SNAKE | `JWT_SECRET_KEY` |

### Naming: mr_text vs mr_txt

- builder 输出字典统一使用 `mr_text`（本地存储语义，关联 `PushLog.mr_text`）。
- Dify Workflow 入参变量默认 `mr_txt`，仅由 `dify_pusher.py` 根据 `workflow_input_variable` 做映射。
- 禁止在 builder 或 payload 组装阶段直接写 `payload["mr_txt"]` 或返回 `{"mr_txt": ...}`。
- 可运行 `python scripts/check_naming_convention.py` 做快速约定检查（发现误用返回非 0）。

### 关键模式

**数据库会话**：路由中用 `Depends(get_db)`，后台线程手动 `SessionLocal()` + try/except/rollback/finally close。

**新增 ORM 字段**：在 `database.py` 的对应 `_migrate_xxx_columns()` 函数中添加 ALTER TABLE（无 Alembic）。

**路由认证**：需要认证用 `Depends(get_current_user)`，需要权限用 `Depends(require_permission("xxx"))`。

**错误处理**：HTTP 错误用 `HTTPException`（detail 用英文），业务错误返回 `MessageResponse(message="...", success=False)`，数据库操作 try/except 后 `db.rollback()`。

**中文内容**：代码注释、日志消息、Swagger 描述均使用中文；HTTP 错误 detail 使用英文。

**导入顺序**：标准库 → 第三方库 → 项目内模块（无 isort 强制，保持顺序即可）。

## 测试

- **单元测试**：`tests/` 目录，pytest 运行，数据库使用 SQLite 内存库或 conftest.py fixture
- **集成测试脚本**：`scripts/test_api.py`、`scripts/test_phase2.py` 等，需先启动服务
- **无 linter/formatter**：无 ruff、flake8、black、mypy 配置

生产 Oracle 连接不在单元测试中使用，Oracle 相关测试通过 Mock 隔离。

## 关键注意事项

1. **单 Worker**：uvicorn 保持 `--workers 1`，APScheduler 不支持多进程
2. **SQLite 并发**：WAL 模式 + `StaticPool`，不支持高并发写入
3. **数据库迁移**：无 Alembic，在 `database.py` 中手动 ALTER TABLE 添加新字段
4. **Oracle Client**：需要 Instant Client `.so` 文件，Docker 中已打包于 `/opt/oracle/`
5. **离线部署**：目标服务器（EulerOS x64）无外网，所有依赖必须打包进 Docker 镜像
6. **数据留存**：`RetentionService` 默认 L1=90d / L2=365d / L3=30d，启用前确认业务方对原始病历文本（`mr_text` / `request_json` / `response_json`）的脱敏窗口
7. **导出留痕**：经 `/api/logs`、`/api/qc/feedback` 导出的请求需通过 `record_export_audit` 落 `ExportAuditLog`，新增导出端点时务必接入

## Docker 部署注意

- 容器以非 root 用户（uid=1000）运行，`logs/`、`data/`、`config/` 目录需有写权限
- 挂载卷：`./data:/app/data`、`./config:/app/config`、`./logs:/app/logs`
- 依赖文件：`requirements.txt`（通用含 cx_Oracle）、`requirements.linux.txt`（Docker 用）、`requirements.windows.txt`（本地 Windows）、`requirements.dev.txt`（开发工具）
