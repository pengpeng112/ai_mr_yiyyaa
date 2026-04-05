# Skill Card: med-audit-codex

> 用途：医疗记录一致性审计系统的“防回归执行基线”。
> 适用：Oracle 抽取、Dify 推送、调度、日志、质控反馈改造。

---

## A. 执行前必查

1. 是否 Oracle 模式（`APP_DB_TYPE=oracle`）
2. 是否单 worker（避免 APScheduler 重复执行）
3. 是否存在历史脏数据（NULL）会影响 schema 校验
4. 是否涉及 `push/logs/scheduler/qc_feedback` 联动字段

---

## B. 不可回退的功能基线（必须保持）

### B1. 推送链路

- Dify 主输入变量（`mr_txt`）必须传字符串
- 批量推送必须有事务隔离（单条失败不污染整批）
- 推送日志必须落地 `skip_reason`（至少区分）：
  - `unreviewed_pending`
  - `rectified_suppressed`

### B2. 推送标记策略

- `pushed_flag/reviewed_flag/manual_override/skip_reason` 必须可用
- “已推送未复核且未覆盖”默认下次跳过
- 手工标记接口必须受管理员权限控制

### B3. 调度

- 支持 `every_10m/every_30m/daily/cron`
- 保存调度配置时必须验证 cron 合法性
- 状态接口必须输出诊断信息（`diagnostics`）

### B4. 日志

- `/api/logs` 必须对 NULL 字段健壮
- 列表与 CSV 导出必须支持：
  - `reviewed_flag`
  - `manual_override`
  - `skip_reason`
- 必须保留筛选选项接口：`/api/logs/filters/options`

### B5. 质控反馈界面

- 严重度/状态英文枚举需中文显示
- 质控详情必须展示病程记录与护理记录内容
- 文本展示需保留换行以提升核查可读性

---

## C. Oracle 约束清单

1. 布尔 SQL 比较使用 `== True/False`（避免 `.is_(True/False)`）
2. GROUP BY 与 SELECT 表达式对象一致（Oracle 严格）
3. 执行前清理 SQL 尾部分隔符（`;` / `；` / `/`）
4. 迁移新增字段需在 `database.py` 同步补齐（SQLite + Oracle）

---

## D. 标准回归命令

```bash
python -m py_compile app/**/*.py
python scripts/test_api.py
python scripts/quick_start.py
```

至少补充人工核验：

- `GET /api/logs?page=1&limit=20`
- `GET /api/scheduler/status`
- `POST /api/push/manual`
- `GET /api/qc/feedback/cases/{log_id}`

---

## E. 常见回归信号 -> 快速定位

1. 日志菜单 500（Pydantic string type on None）
   - 首查：`app/routers/logs.py` 的序列化兜底

2. 调度设置成功但不执行
   - 首查：`/api/scheduler/status` 的 `diagnostics`、`env_enabled`、`job_exists`

3. 查询 14 条但推送少于预期
   - 首查：推送漏斗日志 + `skip_reason_counts`

4. 质控页面显示英文枚举
   - 首查：`static/scripts/app.js` 映射函数是否被模板调用
