# AGENTS.md — 医疗记录一致性审计系统 (Backend)

## Skills
当任务涉及以下主题时，优先加载 skill `med-audit-codex`：
- 病程记录 / 护理记录 / 一致性核查
- Oracle 数据抽取
- Dify Workflow 推送
- FastAPI / Swagger
- Docker / docker-compose
- EulerOS / linux-amd64 离线部署
- 日志 / 统计 / 健康检查 / 异常重推 / 预警通知

---

## 项目概要

Python 3.11 + FastAPI 后端，从 Oracle/PostgreSQL 抽取病程与护理记录，推送至 Dify AI 做一致性审计。
SQLite 持久化（WAL 模式），APScheduler 定时任务，RBAC 权限管理，Docker 离线部署到 EulerOS。

## 启动与运行命令

```bash
# 本地开发（需先 pip install -r requirements.txt）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Docker 构建（Windows，双击或命令行）
docker_build.bat

# Docker 部署（Linux 服务器）
docker load -i med-audit-image.tar
bash docker_deploy.sh

# Docker Compose
docker-compose up -d
```

## 测试

本项目**没有 pytest 单元测试**。测试通过 `scripts/` 下的手动脚本执行：

```bash
# API 集成测试（需先启动服务）
python scripts/test_api.py          # RBAC 系统 API 测试
python scripts/test_phase2.py       # Phase 2 功能测试
python scripts/test_phase3.py       # Phase 3 功能测试
python scripts/quick_start.py       # 快速功能验证
```

无 linter / formatter 配置（无 ruff、flake8、black、mypy 配置文件）。

## 健康检查

```bash
curl http://localhost:8000/api/health    # 整体健康（Oracle + Dify + Scheduler）
# Swagger UI: http://localhost:8000/docs
```

---

## 代码风格与约定

### 目录结构

```
app/
├── main.py              # FastAPI 入口、日志配置、路由注册
├── config.py            # JSON 配置读写、加解密工具
├── database.py          # SQLAlchemy engine + SessionLocal + 迁移
├── models.py            # SQLAlchemy ORM 模型
├── schemas.py           # Pydantic v2 请求/响应 Schema
├── auth.py              # JWT 认证（PyJWT + passlib）
├── permissions.py       # RBAC 权限检查装饰器
├── oracle_client.py     # Oracle 数据查询
├── postgresql_client.py # PostgreSQL 数据查询
├── dify_pusher.py       # Dify Workflow API 推送
├── notifier.py          # 预警通知（企微/钉钉/邮件/webhook）
├── scheduler.py         # APScheduler 定时任务
├── routers/             # API 路由（每文件一个 APIRouter）
│   ├── config.py, push.py, logs.py, scheduler.py, health.py,
│   │   stats.py, notify.py, report.py, users.py, menu.py,
│   │   qc_feedback.py, roles.py, permissions.py, departments.py, demo.py
└── services/            # 业务逻辑层
    ├── config_parser.py, push_executor.py, payload_builder.py,
    │   task_manager.py, export_service.py, feedback_stats.py, menu_service.py
    └── __init__.py      # 统一 re-export
```

### 导入顺序

1. 标准库（`os`, `json`, `logging`, `threading`, `datetime`, `typing`）
2. 第三方库（`fastapi`, `sqlalchemy`, `pydantic`, `jwt`, `requests`）
3. 项目内模块（`from app.xxx import ...`）

无空行分隔各组——本项目不强制 isort 风格，但保持以上顺序。

### 模块级 Logger

每个模块顶部定义：
```python
logger = logging.getLogger(__name__)
```

### 命名约定

| 类型 | 约定 | 示例 |
|------|------|------|
| 文件名 | snake_case | `push_executor.py`, `oracle_client.py` |
| 类名 | PascalCase | `PushExecutor`, `ManualPushRequest` |
| 函数/方法 | snake_case | `manual_push()`, `_async_push()` |
| 私有函数 | 前缀 `_` | `_get_fernet()`, `_ensure_dirs()` |
| 常量 | UPPER_SNAKE | `JWT_SECRET_KEY`, `CONFIG_DIR` |
| API 路由函数 | snake_case 描述性 | `def overall_health()`, `def login()` |

### 类型标注

- Pydantic v2 模型使用 `Field(...)` 带中文 `description`
- 函数参数尽量标注类型，但非强制（codebase 中混用 typed / untyped）
- 使用 `constr(pattern=..., min_length=..., max_length=...)` 做字符串校验
- 使用 `@field_validator` + `@classmethod` 做自定义验证
- ORM 模型的 `Config` 子类设置 `from_attributes = True`

### Pydantic Schema 模式

```python
class XxxRequest(BaseModel):
    """中文 docstring"""
    field: type = Field(..., description="中文说明")

    @field_validator('field')
    @classmethod
    def validate_field(cls, v):
        # 验证逻辑
        return v
```

### SQLAlchemy ORM 模式

```python
class XxxModel(Base):
    """中文 docstring"""
    __tablename__ = "xxx"
    id = Column(Integer, primary_key=True, autoincrement=True)
    # 重要字段加 index=True
    # 复合索引写在 __table_args__
    __table_args__ = (
        Index('idx_xxx_a_b', 'col_a', 'col_b'),
    )
```

新增字段需在 `database.py` 的 `_migrate_xxx_columns()` 函数中添加 ALTER TABLE 兼容迁移。

### 路由模式

```python
# 每个路由文件顶部
router = APIRouter()
logger = logging.getLogger(__name__)

# 路由装饰器
@router.get("/path", response_model=XxxResponse, summary="中文摘要")
def endpoint_name(db: Session = Depends(get_db)):
    ...
```

- 路由前缀在 `main.py` 中统一注册：`app.include_router(xxx.router, prefix="/api/xxx", tags=[...])`
- Tag 使用 emoji + 中文：`["🚀 数据推送"]`
- 需要认证的路由使用 `Depends(get_current_user)`
- 需要权限的路由使用 `Depends(require_permission("xxx"))` 或 `Depends(require_role("xxx"))`

### 错误处理

- 使用 `HTTPException` 抛出 HTTP 错误，detail 使用英文
- 业务错误返回 `MessageResponse(message="...", success=False)`
- 日志用 `logger.error(f"中文描述: {e}")` 或 `logger.error(..., exc_info=True)`
- 数据库操作 try/except 后 `db.rollback()`

### 数据库会话

```python
# 路由中通过 FastAPI DI 获取
db: Session = Depends(get_db)

# 后台线程中手动创建
db = SessionLocal()
try:
    ...
    db.commit()
except Exception:
    db.rollback()
finally:
    db.close()
```

### 配置与敏感信息

- 运行时配置存于 `config/config.json`，通过 `load_config()` / `save_config()` 读写（线程安全）
- 密码字段在 JSON 中以 `password_enc` / `api_key_enc` 存储（Fernet 加密）
- 敏感值通过环境变量注入：`JWT_SECRET_KEY`, `SECRET_KEY`
- **绝不硬编码密钥到代码中**

### 通用响应模型

```python
class MessageResponse(BaseModel):
    message: str
    success: bool = True
    data: Optional[dict] = None
```

---

## 依赖管理

- `requirements.txt` — 主依赖（含 cx_Oracle）
- `requirements.linux.txt` — Linux 部署用（不含 cx_Oracle，Docker 中单独安装）
- `requirements.windows.txt` — Windows 开发用
- 包管理使用 conda 环境（见 `.vscode/settings.json`）

## 关键注意事项

1. **单 Worker**: uvicorn 保持 `--workers 1`，因为 APScheduler 在多进程下会重复执行
2. **SQLite 并发**: 使用 `StaticPool` + WAL 模式，不支持高并发写入
3. **数据库迁移**: 无 Alembic，手动在 `database.py` 中用 ALTER TABLE 添加新字段
4. **Oracle Client**: 需要 Instant Client `.so` 文件，Docker 中已打包于 `/opt/oracle/`
5. **离线部署**: 目标服务器无外网，所有依赖必须打包进 Docker 镜像
6. **中文内容**: 代码注释、日志消息、Swagger 描述均使用中文；HTTP 错误 detail 使用英文
7. **前端静态文件**: Vue3 构建产物放在 `static/` 目录，由 FastAPI 静态挂载提供服务
