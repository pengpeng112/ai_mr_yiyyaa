# Skill Card: med-audit-refactor-workflow

> 用途：在已有基础上持续“补充和完善”医疗审计后端时，统一检索、评估、实施、回归路径。  
> 适用：需求澄清、代码阅读、风险改造、上线前自检。

---

## A. 首次接手 15 分钟检索顺序

1. 阅读基线：
   - `docs/FEATURE_BASELINE_2026-04.md`
   - `docs/skills/med-audit-codex.md`
2. 看入口与生命周期：
   - `app/main.py`（路由注册、异常处理、CORS、scheduler 启停）
3. 看主链路：
   - 数据采集：`app/oracle_client.py`、`app/postgresql_client.py`
   - 推送执行：`app/services/push_executor.py`
   - 调度：`app/scheduler.py`、`app/routers/scheduler.py`
   - 日志：`app/routers/logs.py`
4. 看数据模型与迁移：
   - `app/models.py`
   - `app/database.py`（`_migrate_*`、`_verify_required_schema`）

---

## B. 改造优先级策略

1. P0 稳定性：连接池、超时、事务隔离、调度一致性、关键接口 500
2. P1 规模性：大数据量分页策略、并发保护、重复逻辑收敛
3. P2 可维护性：重复代码抽象、统计口径统一、前后端提示一致性

单次迭代优先做“一个闭环”：  
一个主题 + 对应代码 + 对应测试 + 回归清单。

---

## C. 实施模板（每次改造都遵循）

1. 明确不变量：
   - `mr_txt` 必须是字符串
   - `skip_reason` 必须可追踪
   - `/api/logs` 与 `/api/scheduler/status` 不能回归
2. 最小改动面：
   - 只改一个主模块 + 必要 schema/router
3. 补测试：
   - 优先新增与改造点直接关联的 `tests/test_*.py`
4. 执行验证：
   - `pytest -q`
   - 关键 API 人工检查（logs/scheduler/push）

---

## D. 常用改造切入点

1. Oracle 稳定性：
   - 连接池参数上收口（min/max/increment/timeout）
   - 获取连接等待超时保护
   - 避免连接池耗尽时无限制直连
2. 推送链路：
   - 保证结构化字段覆盖逻辑与落库一致
   - 跳过规则统一在执行器内判定
3. 调度链路：
   - 配置生效反馈 + 诊断字段闭环
4. 日志与质控：
   - `NULL` 兜底 + 中文化映射 + CSV 一致导出

---

## E. 结束标准（DoD）

1. 改造目标可验证（测试通过或接口返回可证据化）
2. 防回归字段不破坏（尤其 `skip_reason`、调度诊断、日志分页）
3. 文档更新至少一处（基线或 skill）
4. 输出“下一步建议”最多 3 条，按 P0/P1/P2 排序

