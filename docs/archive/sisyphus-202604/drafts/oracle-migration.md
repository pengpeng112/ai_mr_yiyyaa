# Draft: SQLite → Oracle 迁移 + EulerOS Docker 部署

## Requirements (confirmed)
- **数据库切换策略**: 双数据库支持 — 通过配置开关选择 SQLite 或 Oracle，开发用 SQLite，生产用 Oracle
- **Oracle Schema**: 使用现有的查询用户（查询病历的同一用户）来创建新表
- **表名前缀**: MED_ 前缀（如 MED_PUSH_LOG, MED_USERS 等），与 jhemr/ydhl 的病历视图区分
- **历史数据迁移**: 需要（数据量少，开发测试数据）
- **表创建方式**: 启动时自动创建（类似当前 SQLite 的 create_all 行为）
- **Oracle 用户权限**: 有 DDL 权限（可以建表）
- **部署目标**: EulerOS 内网服务器，纯内网无外网，x64 架构

## Technical Decisions
- **SQLAlchemy dialect**: Oracle 通过 cx_Oracle dialect（`oracle+cx_oracle://`）
- **连接池**: Oracle 使用 QueuePool（替代 SQLite 的 StaticPool）
- **表前缀实现**: 在 ORM 模型中使用 `__tablename__ = "MED_xxx"` 或通过 schema prefix
- **自动迁移**: 保持当前 ALTER TABLE 模式，但用 Oracle 兼容语法
- **双数据库切换**: 通过环境变量 `APP_DB_TYPE=sqlite|oracle` 控制

## Research Findings
- 当前 database.py 硬编码 SQLite（StaticPool, PRAGMA, check_same_thread）
- 当前 oracle_client.py 用原生 cx_Oracle（非 SQLAlchemy）做病历查询
- models.py 有 12 个 ORM 表，含复合索引和外键
- Dockerfile 已打包 Oracle Instant Client 11.2
- 迁移函数使用 SQLite 语法的 ALTER TABLE

## Scope Boundaries
- INCLUDE: database.py 改造、models.py 表名改造、config.py 新增配置、迁移脚本、Dockerfile/compose 更新、DEPLOY.md 更新
- EXCLUDE: 不改变业务逻辑、不改变 API 接口、不改变前端
