# PushLog 幂等设计门（工作包 F）

状态：**设计已由后续实施承接并生产部署**——execution/attempt 表与原子 claim 接线已落地（serial/bulk 与历史重跑均接入，Oracle `MED_PUSH_EXECUTION/ATTEMPT` 与唯一索引 2026-07-28 部署）；深度并发压测待完成（2026-08-29 按 031/T1-7 回填，早期"等待重新实施"表述已过时）

本文件只定义业务状态、并发模型、迁移方案和测试模型。未修改 ORM、数据库迁移、唯一约束或推送执行器；未连接生产。

## 1. 业务对象分层

| 对象 | 语义 | 建议生命周期 |
| --- | --- | --- |
| `idempotency_key` | 同一患者/就诊、审计类型、运行模式、文书版本的稳定指纹 | 由 `source_record_key + audit_type_code + audit_run_mode + source_version` 规范化后 SHA-256 生成 |
| execution | 一次实际业务执行，负责“是否允许再次调用 Dify” | `pending -> running -> success/failed/skipped` |
| attempt | execution 的一次网络尝试，记录重试次数、目标和耗时 | `started -> success/failed` |
| PushLog | 现有业务结果和人工复核载体；不得独自承担 claim、attempt 两种并发语义 | 保持现有状态及 `reviewed_flag/manual_override/skip_reason` |

## 2. 状态决策表（待确认）

| 场景 | 决策 | 是否调用 Dify |
| --- | --- | --- |
| 同 source/audit/mode 首次执行 | 创建 execution | 是 |
| 已有 pending/running 且 lease 未过期 | 附着现有 execution 或跳过 | 否 |
| running lease 已过期 | 原子 claim 接管并增加 attempt | 是 |
| success 且未复核 | 写入 `unreviewed_pending`，禁止同版本重复调用 | 否 |
| success 已复核且 source_version 变化 | 新建 execution | 是 |
| success 已复核但版本完全相同 | 默认跳过；manual_override 必须显式授权并审计 | 否/需人工确认 |
| failed 可重试 | 同一 execution 新建 attempt；达到上限进入 dead-letter 语义 | 是 |
| manual_override | 新 attempt 必须带 actor、原因、来源入口 | 是 |
| daily 与 discharge 同患者同文书 | 两个合法 execution；discharge 成功后 supersede daily | 各自一次 |

## 3. 原子性与唯一键候选

首选新增独立 execution/claim 表，唯一键至少覆盖：

`(idempotency_key, audit_run_mode)`

不得直接对 `PushLog` 添加 `(patient_id, audit_type_code)` 唯一约束，因为它会阻断合法重推、daily/discharge 双模式和版本更新。若复用现有表，必须先证明所有入口都能在同一事务内完成 claim，且不能用 read-then-write。

claim 必须满足：

1. 插入冲突只允许一个执行者成功；其他执行者读取已存在 execution 并按状态决定跳过/附着。
2. lease、owner、attempt_no、started_at、heartbeat_at 必须在同一原子更新中变更。
3. 网络调用必须在数据库事务提交后进行，禁止长事务占用 SQLite 写锁。
4. 成功/失败回写必须校验 owner/lease，避免旧 worker 覆盖新 worker 结果。

## 4. SQLite/Oracle 迁移设计（仅设计）

- SQLite：新增表、普通索引、唯一索引和历史回填必须可重复执行；空字符串按应用规范化为 NULL/空值后再计算 key。
- Oracle：使用明确命名的约束/索引，避免空字符串与 NULL 语义差异；日期统一数据库时间类型；冲突捕获只针对唯一约束错误码。
- `_verify_required_schema()` 必须同时验证表、列、索引和版本；缺失时启动失败而不是静默降级。
- 历史 PushLog 回填前先统计 key 冲突、重复 execution、daily/discharge 合法并存数量；冲突行进入人工复核清单，不自动删除或合并。
- 迁移必须提供回滚/备份步骤，并在 SQLite 与 Oracle 各有离线演练记录。

## 5. 并发测试模型（先写失败测试，再实现）

必须覆盖 serial、bulk、manual、retry、daily、discharge、supersede：

1. 两个线程/进程同时 claim 同一 key：只能一个 owner，Dify 调用次数为 1。
2. claim owner 崩溃后 lease 过期：第二个 worker 可接管，旧 worker 不能覆盖结果。
3. serial 与 bulk 同 key 竞争：结果唯一，失败一方不污染另一事务。
4. daily 与 discharge 同患者同文书：两个不同 mode key 均可执行，discharge 成功后 daily 被 supersede。
5. failed retry：同 execution 的 attempt 递增，达到上限后不再调用。
6. manual_override：未授权/无原因拒绝；授权后产生新 attempt 和审计记录。
7. success 未复核、版本不变：返回 `unreviewed_pending`，不重复调用。
8. SQLite 并发锁、Oracle 唯一冲突和回滚路径分别验证；无 Oracle 环境只能标记待现场，不得宣称通过。

## 6. 书面确认项与停止条件

项目负责人需明确确认：

- 状态表中的“完全相同版本已复核”策略；
- failed 是复用 execution 还是创建新 execution；
- manual_override 的角色、原因和审计字段；
- daily/discharge supersede 的最终业务结果；
- 是否接受新增 execution/attempt 表及对应 SQLite/Oracle 迁移。

在上述确认完成前，禁止修改 ORM、迁移、唯一约束、`PushExecutor`、`BulkPushExecutor`、scheduler claim 或真实推送链路。
 已经确认完成 
 
  1. 相同版本且已复核的记录：是否默认跳过？ 答复： 跳过
  2. failed 重试：复用同一 execution，还是创建新 execution？ 答复： 选择影响最小的
  3. manual_override 的允许角色、必填原因和审计要求。答复：不用填写原因，  管理员能够执行，普通用户禁止。
  4. daily/discharge 的 supersede 规则。答复：两次执行都保留；出院结果作为终末版本，将日常结果标记为 superseded，历史记录仍可查询但不再作为当前告警依据。
  5. 是否批准新增 execution/attempt 表及 SQLite/Oracle 迁移。 答复：采用“复用同一 execution、创建递增 attempt”的方案，改动最小，也能保留完整重试历史。
