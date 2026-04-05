# FEATURE BASELINE 2026-04（对话沉淀）

## 1. 本轮目标与范围

本轮连续迭代聚焦：

- Oracle 模式下的后端稳定性修复（推送、统计、日志、调度）
- 推送策略增强（已推送未复核跳过、人工覆盖）
- 调度可配置与可诊断（10分钟/30分钟/每天/自定义 cron）
- 日志与质控反馈页面可用性提升（中文化、可读性、筛选）

明确不扩展：

- 不做前端全面重构
- 不做消息调度系统重构
- 不引入分布式调度组件

---

## 2. 已完成能力（功能基线）

### 2.1 Oracle 兼容性修复

1. 修复 `EXISTS` 在 Oracle 下的 SQL 问题（避免 `SELECT EXISTS (...) FROM DUAL`）
2. 修复 `db.func.date(...)` 的 Oracle 兼容问题（改为统一日期桶逻辑）
3. 修复布尔条件写法与聚合表达式兼容问题（`== True/False`、分组表达式复用）
4. 清理高风险 emoji contains 统计逻辑，改为规范状态值等值匹配

### 2.2 Dify 推送链路稳定性

1. `mr_txt` 主输入统一按字符串传递（避免 Dify 400: paragraph must be a string）
2. 推送失败事务隔离：批量路径引入 `begin_nested()`，避免单条失败污染整批会话
3. 重推路径与单条重推路径对齐，避免 payload 类型漂移

### 2.3 PushLog / 数据模型增强

`PushLog` 增强字段（已迁移兼容 Oracle/SQLite）：

- `pushed_flag`
- `reviewed_flag`
- `reviewed_at`
- `reviewed_by`
- `manual_override`
- `skip_reason`

并完成对应 schema 自检要求（`database._verify_required_schema`）与迁移补齐。

### 2.4 推送规则增强

新增跳过规则（统一接入执行器）：

- `unreviewed_pending`：已推送但未人工复核，且未手动覆盖 -> 跳过
- `rectified_suppressed`：整改后抑制 AI 推送 -> 跳过

并在结果中返回 `skip_reason`，落日志可追踪。

### 2.5 调度器改造

1. 调度配置支持模式化：`every_10m`、`every_30m`、`daily`、`cron`
2. cron 在保存前做合法性校验（统一校验函数）
3. 调度更新接口返回应用结果（是否生效、失败原因、next_run）
4. 调度状态接口增加诊断字段：
   - `env_enabled`
   - `job_exists` / `job_id`
   - `next_run`
   - `last_error`
   - `diagnostics[]`
5. job 参数增强：`coalesce`、`misfire_grace_time`、`max_instances`

### 2.6 日志与可观测性

1. 修复 `/api/logs` 历史脏数据 NULL 导致的 Pydantic 500
2. 日志接口增加标记字段返回与筛选：
   - `reviewed_flag`
   - `manual_override`
   - `skip_reason`
3. CSV 导出同步支持上述筛选和新增列
4. 新增 `GET /api/logs/filters/options`，前端可动态拉取筛选项与数量
5. Oracle SQL 日志增强：完整 SQL、参数、耗时、行数（用于 Docker 日志比对）
6. 推送漏斗日志增强：
   - `raw_rows/filtered_rows/grouped/success/failed/skipped`
   - `skip_reason_counts`

### 2.8 通知模块可扩展性改造

1. `notifier.py` 已改为渠道注册表分发（策略模式）
2. 新增 `app/notify_channels.py`，将企微/钉钉/邮件/webhook 渠道实现解耦
3. 后续新增通知渠道只需新增渠道类并注册，不需改动主发送流程

### 2.9 数据库客户端公共基类（DRY）

1. 新增 `app/db_client_base.py`，沉淀 Oracle/PostgreSQL 共用 SQL 校验与注入工具
2. `oracle_client.py`、`postgresql_client.py` 改为复用公共工具，去除重复正则与重复校验函数
3. PostgreSQL 查询路径对齐 Oracle：支持尾部分隔符归一化、条件注入、连接/游标显式释放

### 2.10 SQLite 并发与容器安全加固

1. `database.py` 的 SQLite 连接池从 `StaticPool` 调整为 `NullPool`（配合 WAL）
2. `Dockerfile` 增加 `medaudit` 非 root 运行用户，并将 `/app` 目录授权给该用户
3. `docker-compose.yml` 补充资源限制（memory=1G, cpus=2.0）

### 2.11 pytest 基础框架与首批用例

1. 新增 `requirements.dev.txt`（pytest / pytest-mock / httpx）与 `pytest.ini`
2. 新增 `tests/conftest.py` 统一注入项目根路径
3. 新增首批测试文件：
   - `tests/test_db_client_base.py`
   - `tests/test_oracle_client.py`
   - `tests/test_scheduler.py`
   - `tests/test_notifier.py`
   - `tests/test_qc_feedback_api.py`

### 2.12 前端 F-2/F-3 收口改造

1. 推送日志详情弹窗新增“上一条/下一条”快速翻阅
2. 数据源切换增加确认弹窗，取消时自动回滚为原值
3. 日志筛选输入支持防抖与自动重置分页
4. 推送日志操作列合并为“详情 + 更多菜单（重推/报告/打印）”
5. 质控详情中的病程/护理文本支持截断与“展开查看完整内容”
6. 关键弹窗宽度改为响应式 `min(92vw, 1100px)`，并在关闭后清理详情状态
7. 管理端邮箱输入新增格式校验
8. 全局 API 错误展示统一为 `showApiError`，替代分散提示
9. 新增移动端抽屉导航（<900px），侧栏不再截断菜单
10. 增加 `.table-container` 横向滚动、`1200px` 中间断点、搜索输入防抖
11. 图标删除按钮补充 `aria-label` 语义标签

### 2.13 未达标尾项补齐

1. JSON 配置字段补充实时校验提示（Dify 额外参数、Debug 额外参数/结构化 JSON、通知渠道 JSON）
2. 新增 `tests/test_push_executor.py`，覆盖关键字段覆盖与跳过日志构造
3. 前端边角错误路径继续收敛到统一错误提示（`showApiError`）

### 2.7 质控反馈界面改造（前端）

1. 英文枚举展示中文化：
   - `high/medium/low -> 高/中/低`
   - `success/failed/skipped/pending/error -> 成功/失败/跳过/待处理/错误`
2. 反馈历史状态中文化
3. 质控详情中的病程/护理内容改为多行可读展示（保留换行）
4. 维度状态统一通过中文标签函数展示

---

## 3. 差异化总结（改造前 vs 改造后）

### 改造前

- Oracle 场景存在多处 SQL 方言不兼容
- 推送错误会污染会话，导致批量任务连锁失败
- 调度“配置成功但不执行”难以定位
- 日志接口对历史 NULL 数据不健壮
- 质控界面存在英文术语，核查文本可读性一般

### 改造后

- Oracle 关键链路可执行性显著提升
- 推送失败隔离和重推链路稳定性提升
- 调度具备可配置、可生效、可诊断能力
- 日志筛选、导出、筛选项接口成体系
- 质控界面中文化，病程/护理记录核查更直观

---

## 4. 仍需整改（建议分级）

## P0（优先）

1. `oracle_client` 连接池/连接超时策略仍需进一步压测与保护（防连接耗尽）
2. 调度失败后的内存状态与持久化状态一致性需再做故障演练
3. Oracle 迁移阶段异常现在仍有“宽泛吞异常”历史逻辑，建议逐步收敛为可观测失败

## P1（次优先）

1. `qc_feedback` 列表在大数据量场景下存在全量加载 + 内存分页风险
2. 手动触发调度防抖/并发保护可继续增强（避免极端重复触发）
3. 重推逻辑存在多入口，建议继续合并到单一服务路径，避免字段漂移

## P2（持续优化）

1. SQL 安全校验可进一步扩展（注释/UNION 等边界）
2. 统计口径在部分页面仍可能有时窗定义差异，建议统一“统计口径说明”
3. 质控文本对比可考虑后续增加差异高亮（非本轮必须）

---

## 5. 回归检查清单（后续每次发布）

1. `/api/logs?page=1&limit=20`（含历史数据）必须 200
2. `/api/scheduler/status` 必须包含 diagnostics 且能解释未执行原因
3. 调度配置切换（10m/30m/daily）后 `next_run` 必须刷新
4. 手动推送结果必须包含漏斗字段与 `skip_reason`
5. 质控详情页必须可见病程/护理记录且状态/严重度为中文显示
