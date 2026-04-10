# CODE_STYLE

> 本文档描述当前代码库的**实际**编码风格与约定（以现有实现为准）。

## Naming Conventions

### 文件与模块
- `snake_case`：`app/push_executor.py`, `app/oracle_client.py`（`app/main.py` 引用）

### 类
- `PascalCase`：`PushExecutor`, `AuditConclusion`, `QCFeedback`（`app/models.py`）

### 函数/方法
- `snake_case`：`get_db`, `validate_runtime_config`, `build_mr_text`（`app/database.py`, `app/config.py`）
- 私有函数：前缀 `_`，如 `_get_fernet`, `_normalize_query_date_for_log`（`app/config.py`, `app/services/push_executor.py`）

### 常量
- `UPPER_SNAKE`：`CONFIG_DIR`, `APP_DB_TYPE`, `LOG_DIR`（`app/config.py`）
- 模块内私有常量可加 `_` 前缀：`_DEFAULT_QUERY_SQL`（`app/config.py`）

## File Organization

- `app/routers/`：每个文件一个 `APIRouter`，在 `app/main.py` 统一注册
- `app/services/`：业务逻辑集中层（推送、导出、菜单、统计等）
- `app/models.py`：所有 ORM 模型集中定义
- `app/schemas.py`：所有 Pydantic 请求/响应模型

## Import Style
按顺序组织导入（不强制 isort，通常无空行分组）：
1. 标准库（`os`, `json`, `logging`, `typing`）
2. 第三方库（`fastapi`, `sqlalchemy`, `pydantic`）
3. 项目内模块（`from app.xxx import ...`）

示例：`app/main.py`

## Code Patterns

### FastAPI 路由模式
```python
router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/path", response_model=XxxResponse, summary="中文摘要")
def endpoint_name(db: Session = Depends(get_db)):
    ...
```
（见：`app/routers/*`）

### 数据库会话
```python
# 路由中使用依赖注入
db: Session = Depends(get_db)

# 后台线程手动创建
db = SessionLocal()
try:
    ...
    db.commit()
except Exception:
    db.rollback()
finally:
    db.close()
```
（见：`app/database.py`, `app/scheduler.py`）

### ORM 模型
- 类 docstring 多为中文
- 重要字段 `index=True`
- 复合索引写在 `__table_args__`

示例：`app/models.py::PushLog`

### 配置与加解密
- 运行时配置存于 `config/config.json`
- 密码字段存储为 `password_enc` / `api_key_enc`
- `SECRET_KEY` 派生 Fernet 加密（`app/config.py`）

### 推送执行器（业务层）
- 使用 `dataclass` 描述结果/配置
- 主流程封装在 `PushExecutor.execute()`
- 结构化审计结果写入 `AuditDimensionResult` / `AuditConclusion`
（见：`app/services/push_executor.py`）

## Error Handling
- HTTP 错误使用 `HTTPException`，`detail` 使用英文
- 业务错误返回 `MessageResponse(success=False)`
- 数据库异常捕获后 `rollback()`
- 全局异常处理：`app/main.py` 使用 `exception_handler` 返回统一格式

## Logging
- 模块级 logger：`logger = logging.getLogger(__name__)`
- 主日志：`logs/app.log`（轮转）
- 审计日志：`logs/audit_detail.log`（Dify/Oracle 详细日志）
- 日志内容多为中文
（见：`app/main.py`）

## Testing
- pytest：`pytest.ini` + `tests/`
- 测试文件命名：`tests/test_*.py`
- 也保留脚本型测试：`scripts/test_*.py`

## Do’s and Don’ts

### Do
- 使用 `snake_case` 文件与函数名，`PascalCase` 类名
- 在新字段/新表后更新 `app/database.py` 的兼容迁移函数
- 通过 `load_config()` / `save_config()` 读写配置
- 使用 `logger = logging.getLogger(__name__)` 统一日志风格

### Don’t
- 不要硬编码密钥或 API Key（使用环境变量 + `config.json` 加密字段）
- 不要在生产环境用 `ALLOWED_ORIGINS=*`（`app/main.py` 会拒绝）
- 不要启用多 worker（APScheduler 会重复执行）
