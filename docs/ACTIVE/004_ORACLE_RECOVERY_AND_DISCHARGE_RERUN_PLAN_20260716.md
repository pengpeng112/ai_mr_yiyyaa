# Oracle 调度连接恢复与 2026-07-15 出院终末补跑计划

> 状态：待独立复核；只授权本地开发与测试，不授权生产部署或补跑  
> 建立日期：2026-07-16  
> 生产事件：2026-07-16 11:44 的 `discharge_push` 在获取运行锁前因 `DPI-1080/ORA-3135` 与 `ORA-12541` 失败，六类 `discharge_final` 均未启动，未写 SchedulerHistory。  
> 目标范围：仅修复 Oracle 应用库连接恢复、锁前失败可观测性，以及经书面批准后补跑 `query_date=2026-07-15` 的六类 `discharge_final`。  
> 非目标：不修改六类 code、Dify 提示词/输入输出、高危门槛、科室白名单、ORM 字段、数据库迁移、PushLog 幂等模型或告警协议。

与其他计划的关系：本文是 `ACTIVE/003` 的事件专项子计划。对于“2026-07-16 Oracle 连接事件修复”和“2026-07-15 六类 discharge_final 补跑”，以本文 A→B→C→D 和停止点为唯一顺序；003 的其他生产整改仍按 003 执行，本文不授权绕过 001 安全门或 002 幂等门。两份计划出现范围冲突时停止并报告，不得自行合并工作包。

## 1. 已核实事实

### 1.1 今日任务

- `daily_increment` 已完成四类，处理业务日期 `2026-07-15`。
- `discharge_final` 配置每天 11:44，包含六类：
  - `progress_vs_nursing`
  - `syssvsscbc`
  - `jyjc_vs_bcnursing`
  - `admission_vs_first_progress`
  - `surgery_chain`
  - `discharge_vs_frontpage`
- 2026-07-16 11:44 调度进入 `_daily_push_job_v2()`，在 `acquire_scheduler_run_lock("discharge_push")` 查询应用库时失败。
- 异常链为：连接池旧连接关闭报 `DPI-1080: connection was closed by ORA-3135`，随后新连接报 `ORA-12541: TNS: 无监听程序`。
- 失败发生在 `_daily_push_job_v2_unlocked()` 之前，因此没有逐类型 PushLog，也没有 SchedulerHistory 失败终态。
- 当前应用库连接已经恢复；这只证明监听后来恢复，不代表当天终末任务自动补跑。

### 1.2 代码现状

- `app/database.py` 的 Oracle engine 已配置：`QueuePool`、`pool_pre_ping=True`、`pool_recycle=1800`、`pool_timeout=10`。
- 因此本计划不得把“新增 pool_pre_ping”当作修复，也不得仅增大 timeout。
- `scheduler_lock_service.acquire_scheduler_run_lock()` 对 DB 异常不分类、不恢复、不重试，异常直接穿透 APScheduler。
- `_daily_push_job_v2()` 在加锁前没有异常边界；只有成功进入 `_daily_push_job_v2_unlocked()` 后才会写逐类型历史。
- `write_scheduler_history_safe()` 依赖同一应用库；数据库持续不可用时不可能立即写表，必须有持久化兜底并在恢复后回放。
- `/api/scheduler/directed-retry` 当前只是 `dry_run=true` 参数校验桩，禁止把它假装成已实现的生产补跑接口。

## 2. 冻结决策

1. 连接恢复采用“有限次数、仅瞬态连接错误、指数退避、连接池失效后重建”的策略；不做无限重试。
2. 非连接类错误（SQL、权限、schema、编程错误）不重试，立即失败并保留原异常。
3. 对数据库 commit 返回异常的操作，不允许盲目重放；先用新连接核对提交结果。
4. 正常锁竞争与数据库故障分开：
   - `lock_busy`：另一个合法任务持锁，不视为 Oracle 故障，不启动第二个任务。
   - `lock_db_unavailable`：连接错误，进入恢复流程；耗尽后记录类型级 failed。
5. 加锁前失败按本次配置的六个 `audit_type_code` 分别生成失败 SchedulerHistory，使运行汇总能识别整类未启动；不新建父 run 表。
6. 数据库持续不可用时，将不含患者信息/密钥的失败事件写入持久化 JSONL spool；数据库恢复后幂等回放 SchedulerHistory。
7. 补跑默认受 ACTIVE/002 门禁约束。002 未完成时，只能走本文的应急特批轨；没有书面批准不得执行生产补跑。
8. 历史补跑期间默认禁止真实告警外发；补跑结果先落库和临床核查，是否补发告警另行审批。

## 3. 严格执行顺序

必须按工作包 A → 停止点 A → B → 停止点 B → C → 停止点 C → D 的顺序。不得把代码修复、部署和生产补跑合并执行。

## 4. 工作包 A：Oracle 连接恢复（仅本地代码）

### 4.1 允许修改文件

- `app/database.py`
- 新增 `app/services/app_db_recovery.py`（推荐）
- `app/services/scheduler_lock_service.py`
- `app/scheduler.py`
- 对应 `tests/` 文件

发现必须修改其他文件时先停止并报告，不得顺手扩大范围。

### 4.2 瞬态错误分类

在 `app_db_recovery.py` 建立纯函数，沿异常链检查 SQLAlchemy `DBAPIError`、cx_Oracle 异常文本/代码。第一版只允许识别已验证的连接类错误：

- `ORA-12541`：无监听程序
- `ORA-03135` / 日志中的 `ORA-3135` 文本：连接丢失
- `DPI-1080`：连接已关闭
- SQLAlchemy `DBAPIError.connection_invalidated == True`

可纳入同类 Oracle 网络错误时必须新增测试并在交付报告列明；不得使用“所有 DatabaseError 都重试”的宽泛条件。

### 4.3 连接池恢复

提供调度入口专用恢复函数，不把任意业务事务包装成通用自动重试：

1. 首次连接类异常后 rollback/close 当前 session。
2. 调用全局 `engine.dispose()` 使池中旧连接失效；不得重建第二个全局 engine 或替换 `SessionLocal.bind`。
3. 退避建议为 1、3、8 秒并加入小幅 jitter，总尝试次数最多 4 次；数值做常量并可单元测试，不开放成任意配置。
4. 每次重试创建全新 Session。
5. 日志只记录 error_code、attempt、lock_name、run_mode、query_date；不得记录 DSN 密码、患者信息或 SQL 正文。
6. 连接恢复成功后记录一次聚合 INFO；同一事件不要刷每 30 秒堆栈。

### 4.4 加锁事务的未知提交结果

`acquire_scheduler_run_lock()` 的 owner_id 必须在重试周期外生成并保持不变。若 `db.commit()` 抛出连接丢失：

1. 不立即再次 INSERT/UPDATE。
2. 恢复连接后按 `lock_name + owner_id + status=running` 回查。
3. 已持有：返回 acquired，继续任务。
4. 未持有且没有其他 running owner：才允许再次尝试获取。
5. 已被其他 owner 持有：返回 `lock_busy`，不得并发启动。

这样避免“提交实际成功但客户端未收到响应”造成重复锁操作。

### 4.5 调度入口异常边界

调整 `_daily_push_job_v2()`：

1. 在加锁前从文件配置解析 `query_date`、`audit_run_mode`、`lock_name`、configured codes；不得访问业务数据库。
2. 使用恢复包装调用加锁服务。
3. 区分 acquired、lock_busy、lock_db_unavailable、unexpected_error。
4. acquired 后保持现有心跳、执行、finally release 行为。
5. lock_busy 只记录明确的跳过/取消语义，不创建“业务失败”PushLog。
6. lock_db_unavailable 或 unexpected_error 在逐类型任务未启动时调用工作包 B 的失败历史记录器，然后正常向 APScheduler 抛出或返回明确失败；不得显示“executed successfully”。

### 4.6 A 包测试

新增聚焦测试，至少覆盖：

- engine 仍保留现有 `pool_pre_ping/pool_recycle`，没有重复 engine。
- 第一次 DPI-1080、第二次成功：dispose 一次，最终只执行一次任务。
- ORA-12541 连续失败后恢复：按 1/3/8 退避，成功后获取锁。
- 非瞬态 SQL/权限错误：0 次重试。
- commit 报连接丢失但锁实际已写入：回查 owner 后成功，不二次执行。
- commit 未生效：回查后仅重试一次获取流程。
- 其他 owner 已持锁：返回 lock_busy，不 dispose、不启动任务。
- SQLite 路径行为不变，不启用 Oracle 专属恢复。
- 心跳/释放仍只针对原 owner；恢复失败不遗留伪 running 锁。

### 停止点 A

执行 `compileall`、命名检查、聚焦 pytest、全量 pytest。提交修改文件、完整结果和 diff，停止等待确认；不得部署。

## 5. 工作包 B：加锁前失败写 SchedulerHistory

### 5.0 允许修改文件

- 新增 `app/services/scheduler_failure_recorder.py`（推荐）
- `app/services/scheduler_history_service.py`
- `app/scheduler.py`
- `app/main.py`（仅用于启动后安全 drain；不得改变路由、鉴权或启动失败门槛）
- `app/routers/scheduler.py`、`app/schemas.py`（仅当展示 spool backlog 必需；可不实现则优先不改）
- 对应 `tests/` 文件

不得修改 ORM、`app/database.py` 手工迁移、PushLog/执行器、Dify 或告警代码。发现需要其他文件先停止并报告。

### 5.1 失败事件模型（不迁移数据库）

不新增 ORM 字段。内部失败事件至少包含：

- `event_id`：UUID
- `occurred_at`：原始失败时间
- `query_date`
- `audit_run_mode`
- `lock_name`
- `audit_type_codes`
- `error_code`：受控枚举，如 `app_db_listener_unavailable`
- `attempt_count`
- `status=failed`

不得包含异常完整连接串、密码、患者标识、病历、SQL 正文。

### 5.2 直接写历史

连接在有限重试后恢复、但本次任务已放弃时，对配置中的每个 code 写一条 SchedulerHistory：

- `run_time=occurred_at`
- `trigger_type=auto`
- `query_date` 为本次业务日
- `audit_type_code` 为真实六类 code，不使用不存在的新质控 code
- `total_records=0`
- `success_count=0`
- `failed_count=0`
- `duration_seconds` 为加锁/恢复总耗时
- `status=failed`

这是“类型未启动”的历史，不得伪造 failed_count=候选数。

### 5.3 数据库仍不可用时的持久化 spool

1. 写入挂载卷 `/app/data/scheduler_failure_spool.jsonl`，使用文件锁、追加写、flush+fsync；文件权限仅容器用户可读写。
2. 每次应用启动成功后、每次调度开始前，尝试 drain；drain 失败不阻塞 liveness，也不触发任务。
3. 回放幂等键使用 `event_id`，但 SchedulerHistory 当前无 event_id 字段，因此采用以下最小方案：
   - `run_time` 使用事件原始时间并保持微秒；
   - 写前按 `run_time + query_date + audit_type_code + trigger_type + status` 查重；
   - 单事务写入该事件的全部类型历史；
   - commit 成功后将事件移动到 `.processed` 归档，不直接删除。
4. 若发生“DB commit 成功、归档前进程退出”，下次由上述查重阻止重复行。
5. JSONL 损坏行隔离到 `.invalid` 并报警，不得吞掉或阻塞其他有效事件。
6. spool 大小、未回放事件数进入授权 scheduler 状态/日志聚合；本包不要求新增数据库列。

### 5.4 B 包测试

- 加锁前 DB 故障但历史库恢复：六类各一条 failed history。
- DB 持续不可用：只写 spool，不声称已写 SchedulerHistory。
- spool 回放成功：六条历史且归档事件。
- commit 后模拟崩溃再回放：不重复历史。
- 两线程 drain：文件锁保证不重复。
- 损坏 JSONL：隔离并可见，不影响有效事件。
- lock_busy 与用户取消不得错误写成 DB 故障 failed。
- Scheduler run-summary 能显示六类 type-level failure，无 PushLog 也标记运行不完整。
- spool 中无患者、密码、DSN、病历正文。

### 停止点 B

完成全部测试和本地故障演练后停止。由技术负责人复核“DB 不可用时先落 spool、恢复后回放”的事实表述，不得宣称数据库完全不可用时可以同步写表。

## 6. 工作包 C：部署与现场只读验证

### 6.1 进入门

- A、B 代码独立复核通过。
- 全量测试、SQLite 测试、Oracle mock/现场只读测试通过。
- 记录当前 git commit、镜像 digest `3ddfa325…`、配置 SHA-256、数据库 schema、备份与回滚命令。
- 不包含 ORM/迁移、六类 code、Dify、高危、alert_dept_filter 改动。
- 用户书面批准“部署连接恢复代码”；这不等于批准补跑。

### 6.2 发布步骤

1. 构建新镜像，不使用仅容器热更新作为最终交付。
2. 备份 `/opt/med-audit-docker/config`、Compose、当前镜像标签和必要应用库元数据。
3. 单 worker 启动；验证 `/api/health/live` 不访问 Oracle。
4. 授权执行 `/ready` 或容器内 `SELECT 1`，连续 3 次成功，间隔至少 10 秒。
5. 验证 scheduler 两个 job 的 next_run、锁 idle、spool backlog 和最近 history。
6. 用 mock/隔离手段演练连接失效；不得为了测试主动中断生产 Oracle 监听。
7. 观察至少到下一次 daily/discharge 周期；若必须当天补跑，先进入 D 的独立审批。

### 6.3 回滚触发

- 容器不健康、连接池耗尽、重复任务、锁残留、history 重复、SQLite 回归、错误日志泄密。
- 触发后回滚镜像和配置；spool/历史只追加保留，不删除审计证据。

### 停止点 C

提交部署和只读验收报告后停止。未取得 D 的书面补跑批准，不得调用任务入口。

## 7. 工作包 D：2026-07-15 六类 discharge_final 定向补跑

### 7.1 补跑审批门

默认推荐轨：ACTIVE/002 execution/attempt、原子 claim、所有入口覆盖和并发测试已完成。

若 002 尚未完成，只允许应急轨，并必须同时取得：

- 项目/技术负责人书面批准
- 运维/DBA 书面批准
- 业务负责人书面批准补跑日期、六类范围和历史告警不自动外发
- 明确维护窗口、操作者、回滚负责人

当前“请生成计划”不构成上述批准。

### 7.2 补跑前只读对账

使用生产只读脚本固定输出并留档：

1. `query_date=2026-07-15`、`audit_run_mode=discharge_final` 六类现有 PushLog/History 数量。
2. V_QYBR 当日出院患者聚合和六类候选数。
3. 同 patient_id+visit_number+audit_type 是否已有成功可用终末结果。
4. 当日日常可用结果及将被 supersede 的预计数量。
5. 当前 pending/failed/success/dept_filtered 告警数量。
6. Oracle 连通性连续 15 分钟稳定；至少 3 次受控连接测试成功。
7. `discharge_push` 锁 idle，daily/manual/retry 没有处理同一日期与类型。

任一类型已经存在成功可用终末记录时，默认跳过该记录；不得使用 `manual_override` 强推。

### 7.3 告警与配置保护

1. 备份 `config/config.json` 及 SHA-256。
2. 历史补跑默认关闭真实 relay dispatch 和普通 notifier；不得修改 `alert_dept_filter=["听觉植入科"]`。
3. 关闭方式必须使用现有受控配置并记录 before/after；不得改代码硬编码 bypass。
4. 补跑完成后先核查 high，是否恢复外发配置由业务负责人确认；不得把历史高危自动补发给医生。
5. 配置恢复后再次计算 SHA-256 并核对除批准字段外完全一致。

### 7.4 执行策略

应急轨必须保持单 worker、独占 `discharge_push` 锁、无并发。六类按单类型、串行、逐个停止点执行，不一次性黑盒跑完：

1. 根据 dry-run 候选数从最小非零类型选择 canary。
2. 执行参数固定：`query_date=2026-07-15`、`audit_run_mode=discharge_final`、单个批准 code。
3. 每类完成后核对 SchedulerHistory、PushLog、status、parse_status、qc_usable、supersede 和告警未外发。
4. 任一类出现类型级失败、parse success 异常下降、重复 PushLog、错误 supersede 或连接恢复重试耗尽，立即停止剩余类型。
5. 前一类验收通过后才进入下一类，直至六类完成。

不得直接开放当前 `/directed-retry?dry_run=false` 桩。生产执行入口必须二选一并在实施前写死：

- 推荐：完成 002 后实现受 RBAC、execution/attempt 和审计保护的 directed retry。
- 应急：运维在容器内调用现有 `_daily_push_job_v2(query_date_override=..., audit_type_codes_override=[code], audit_run_mode_override="discharge_final", lock_name="discharge_push")`，命令、操作者和输出全程留档。

应急调用不得启动并发线程包裹任务，不得绕过函数内部锁，不得修改数据库状态伪造完成。

### 7.5 补跑后验收

逐类及合计输出：

- 候选、成功、跳过及原因、失败
- parse_success、fallback、parse_failed、qc_usable
- high/red 顶层与维度数，并按现役六类提示词和后端复合门槛复核
- superseded 数；仅 parse_success 终末可以覆盖日常
- 告警 pending/success/failed/suppressed/dept_filtered，证明没有真实外发
- 听觉植入科候选、可用结果、高危和告警状态
- 重复键和重复 Dify 调用检查

至少观察下一次完整 daily_increment 和 discharge_final 周期，确认自动连接恢复没有制造重复任务。

### 7.6 数据回滚边界

- 镜像/配置异常：回滚镜像与配置。
- 补跑已产生的 PushLog/维度/结论不得直接批量删除；先生成精确 ID、关联告警、supersede before/after 的回滚方案并另行批准。
- 已有日常结果和历史告警事实不得覆盖或删除。

### 停止点 D

六类对账、临床高危复核、配置恢复、无外发证明和完整测试报告经签字后，才可标记补跑完成。

## 8. 执行者必须运行的测试

```text
python -m compileall app tests scripts
python scripts/check_naming_convention.py
python -m pytest <新增连接恢复/调度锁/历史spool测试> -q
python -m pytest tests/test_scheduler.py tests/test_scheduler_run_summary.py -q
python -m pytest -q
```

禁止删除失败测试、放宽断言、添加无条件 skip、吞异常，或用生产运行成功代替自动化测试。

## 9. 每包交付模板

```markdown
### 工作包 X 交付报告
- 实施范围：
- 未实施内容：
- 修改文件与函数：
- 数据库/配置变化：
- Oracle 错误分类与重试次数：
- 未知 commit 结果如何核对：
- SchedulerHistory/spool 结果：
- 测试命令与完整结果：
- 生产连接/写入/Dify/relay 是否发生：
- 备份、镜像、配置 SHA-256：
- 回滚方法：
- 仍需人工确认：
- 是否到达停止点：

#### 禁止项检查
- 是否改六类 code、Dify 契约或高危门槛：
- 是否新增 ORM、迁移、唯一约束或 claim：
- 是否对非瞬态 DB 错误重试：
- 是否在未知 commit 状态下盲目重放：
- 是否未经批准部署或补跑：
- 是否真实发送企微/H5/普通通知：
- 是否清理或回滚他人工作区改动：
```

## 10. 给执行 AI 的启动提示词

```text
严格执行 docs/ACTIVE/004_ORACLE_RECOVERY_AND_DISCHARGE_RERUN_PLAN_20260716.md。

完整阅读 AGENTS.md、docs/INDEX.md、101 功能基线、med-audit-codex、ACTIVE/001、002、003 和 004。
当前只实施工作包 A：Oracle 调度连接恢复的本地代码与测试。不得实施 B/C/D，不得连接或修改生产，
不得触发调度、Dify、relay、企微，不得修改六类 code、提示词、mr_text/mr_txt、JSON、高危门槛、
ORM、迁移、唯一约束、PushLog 幂等模型或 alert_dept_filter。

先保存 git status/diff/HEAD 和既有测试基线，不清理、覆盖或回滚他人修改。注意 Oracle engine 已有
pool_pre_ping 和 pool_recycle，修复重点是瞬态连接错误分类、engine.dispose、有限退避、锁 commit
未知结果回查和调度入口异常边界。非连接类错误不得重试。

A 完成后按第 9 节模板提交修改、完整测试和禁止项检查，然后停止等待书面批准进入 B。
```
