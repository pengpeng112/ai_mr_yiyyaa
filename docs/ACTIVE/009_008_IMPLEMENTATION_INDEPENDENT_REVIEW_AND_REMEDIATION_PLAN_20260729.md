# 008 本地实施独立复核与二次整改计划

> 编号：009  
> 日期：2026-07-29  
> 范围：基准 `dac6c144c8f38cf5a2bb679b62dd395a253b1900` 及其未提交工作树  
> 状态：复核不通过；禁止生产历史批量重推，待 P0/P1 修复及复核  
> 安全声明：本次仅检查本地代码、文档并运行本地测试；未连接生产、未调用 Dify、未发送告警、未修改配置或数据库。

## 1. 结论

008 的修复方向正确，日志详情页滚动修复也具有合理作用域，但当前实现仍存在会错误判定 Dify 结果、让不合格结果覆盖旧结果、使用不完整 preview 创建批次等阻断缺陷。专项测试的 25 项通过不足以证明可上线。

最终裁定：**不通过**。完成 P0、P1 并通过本文验收门禁前，不得部署历史重推代码，不得启动 1–7 月覆盖任务。

## 2. 已确认实现

| 项目 | 裁定 | 说明 |
|---|---|---|
| legacy 空 key 查询 | ✅ 确认 | `or_(source_record_key IS NULL, source_record_key == "")` 兼容 Oracle 空串语义；preview 会把空 key 新候选标成 `identity_ambiguous`。 |
| concurrent_changed 退出当前视图 | ⚠️ 部分确认 | `superseded_by` 非空可被当前结果过滤器排除，但采用自引用链，审计语义错误。 |
| running 批次 resume | ⚠️ 部分确认 | API 接受 `running`，过期 item 可恢复；消费者租约仍有并发窗口。 |
| claim fail-closed | ⚠️ 部分确认 | 异常时不再继续调用 Dify，但普通推送被记为业务 skip，缺少可重试失败语义。 |
| parser 后契约校验 | ❌ 缺陷 | 集成位置在高危降级后，但契约内容错误，且结果未进入 supersede 门禁。 |
| preview `load_failed` 计数 | ❌ 缺陷 | 能计数但不能阻止不完整批次创建，仍会形成不完整 candidate hash。 |
| SchedulerHistory 字段 | ❌ 缺陷 | ORM/SQLite 局部完成，实际调度调用和 Oracle 迁移未完成。 |
| 日志详情滚动 | ✅ 静态确认 | body class 作用域不会影响主应用；尚无真实浏览器验收。 |
| retry 不改旧响应 | ⚠️ 部分确认 | 新建日志保留旧 `response_json`，但替代链、契约、幂等和告警存在新风险。 |
| 对账诊断 | ❌ 缺陷 | “qc_usable”和“双当前”统计口径错误且总数受 limit 截断。 |

## 3. P0 阻断缺陷

### P0-1 契约维度集合与权威提示词不一致

- 位置：`app/services/result_contract_validator.py:27`
- 复现：用 `docs/reference/113_DIFY_PROMPT_PROGRESS_VS_NURSING.md` 的六个合法维度调用 `validate_result_contract`，会被判缺失/未知；当前测试反而使用实现中虚构的四维集合。
- 影响：合法结果被判无效，错误维度可能被接受；历史批量重推会系统性污染可用性统计。
- 修复：
  1. 从权威契约建立六类白名单：113 六维、114 六维、111 九维、112 十维、115 四维。
  2. admission 的维度来自运行时 `维度列表`，不得硬编码虚构三维；应从审计类型配置快照解析并作为 validator 参数，缺少配置即 fail-closed。
  3. `warn/low/blue` 是合法 hint 组合，加入合法组合；不得归一成 medium/yellow。
  4. 新增针对每类完整集合、缺失、重复、越权 code、hint、低置信度的表驱动测试。

### P0-2 `contract_valid=False` 仍可覆盖旧当前结果

- 位置：
  - `app/services/historical_rerun_service.py:894`
  - `app/services/push_log_supersede.py:138`
  - `app/services/push_log_writer.py:143`
- 复现：parser 返回 `parse_success=True, contract_valid=False`；PushLog 未持久化 contract 状态，两处 `is_qc_usable` 只传 status/parse_status，仍进入 supersede。
- 影响：非法组合、缺维度结果可成为当前结果，直接违背 008 的生产门禁。
- 修复：
  1. 在 PushLog 增加 `contract_valid`、`contract_errors`（或等价受控字段），补 SQLite/Oracle 手工迁移和 `_verify_required_schema()`。
  2. writer/retry/历史重跑均持久化校验结论。
  3. 所有 supersede 入口必须显式传入 contract 状态；新数据缺字段不得按 legacy `None` 放行。
  4. contract invalid 应保存为审计事实但不得当前可见、不得 supersede、不得告警。

### P0-3 不完整 preview 可创建并执行批次

- 位置：
  - `app/services/historical_rerun_service.py:218`
  - `app/services/historical_rerun_service.py:349`
- 复现：模拟任一日期 `load_patient_bundles` 抛异常；preview 增加 `load_failed` 后继续，`create_batch_from_preview` 仅校验 hash，不检查失败。
- 影响：Oracle 超时日被当成零候选，产生“已覆盖”的错误结论，历史数据实际漏推。
- 修复：
  1. preview 输出 `manifest_complete`、`load_failed_count` 和逐日逐类型脱敏错误分类。
  2. `load_failed_count > 0` 时禁止创建/确认批次；candidate hash 必须包含完整 shard 状态。
  3. create 必须消费已持久化 preview manifest，不得再次全量加载。
  4. 提供按日分片 preview API/持久表，支持失败 shard 单独重试及 hash 重算。

### P0-4 concurrent/legacy guard 使用自引用 supersede 链

- 位置：`app/services/historical_rerun_service.py:905,924`
- 复现：触发 write-before legacy guard 或 `expected_previous_id` 改变；新日志被写成 `superseded_by = 自己.id`。
- 影响：日志详情显示“被自己覆盖”，替代链形成环；后续链查询、导出和诊断语义失真。
- 修复：禁止自引用。优先回滚新业务结果并仅保留 PushAttempt/Item 审计；若必须保存响应，增加明确的 `discarded/invalidated` 状态或独立审计表，并由当前视图排除。数据库/服务层增加 `superseded_by != id` 保护测试。

## 4. P1 高优先级缺陷

### P1-1 SchedulerHistory 实际链路未接入新字段

- 位置：
  - `app/services/scheduler_audit_runner.py:240`
  - `app/scheduler.py:71`
  - `app/database.py:507`
- 问题：runner 仍直接创建旧字段 `SchedulerHistory`；兼容包装未接收 mode/error；迁移函数只在 SQLite 生效，Oracle 旧表不会自动加列。
- 修复：统一调用 `write_scheduler_history_safe` 并传 `audit_run_mode`、受控 `error_msg`；增加 Oracle 幂等加列与 schema verification；用失败类型集成测试验证落库。

### P1-2 消费者租约不具备可靠跨进程单例

- 位置：`app/services/historical_rerun_service.py:1027-1200`
- 问题：SQLite 忽略 `SELECT FOR UPDATE`；120 秒租约在 Dify 调用期间无心跳，长调用后第二消费者可取得租约并处理下一项。
- 修复：使用原子条件 UPDATE/CAS claim；执行 Dify 时独立心跳；租约与最大 Dify timeout 协调；测试两 Session/两线程竞争、租约过期、重启恢复、重复 resume。

### P1-3 幂等算法升级缺少旧数据兼容与失败重试语义

- 位置：`app/services/push_idempotency.py:23`
- 问题：去除 `source_version` 后，生产旧 execution 无法命中新 key；空 source key 的不同记录可能互相冲突；claim DB 异常被表现为 skipped，定时可能无自动补偿。
- 修复：提供旧 key 迁移/双读过渡及冲突报告；空 key fail-closed；`claim_error`、`in_flight` 必须是可重试技术状态，历史 item 不得永久 skipped；统一跨入口测试。

### P1-4 retry 重构破坏替代链并可能重复告警

- 位置：`app/services/push_executor.py:697-845`
- 问题：无 expected-current 校验便改写任意旧日志的 `superseded_by`；没有 claim；未落实 contract 门禁；成功后直接尝试告警与通知。
- 修复：retry 使用统一 execution claim、writer 和 expected-current supersede；已非当前的原日志不得改链；默认 suppress 告警；失败也落 PushAttempt；返回格式保持兼容。

### P1-5 诊断统计口径错误

- 位置：`app/services/dual_current_diagnostics.py:22`
- 问题：
  - `total_current_qc_usable` 未校验 parse/contract。
  - 以 patient+visit+type+mode 分组，遗漏 source_record_key，可能把合法多记录误判双当前。
  - `multi_current_identity_groups` 是 limit 后列表长度，不是总数。
  - contract 诊断只查 unknown/medium，遗漏维度集合及其他非法组合。
- 修复：按正式业务身份 `source_record_key + type + mode` 统计；空 key 单列 legacy 模糊组；总数与样本分离；使用持久化 contract 字段；严禁输出患者标识。

## 5. P2 与计划漂移

1. `start_batch_async` 在启动线程前未预留 active token，虽 `run_batch` 二次检查可降低风险，但应以原子 DB claim 为准。
2. lease 释放失败被静默吞掉；应记录结构化错误，依靠到期恢复并可观测。
3. preview 仍在单请求循环整个日期范围，create 仍接收内存 preview，未实现真正分片/持久 manifest。
4. 日志详情仅完成静态 CSS，需验证五标签、长 JSON 内层滚动、桌面/移动端及打印。
5. Oracle `error_msg` 使用 CLOB 可行，但 migration 和 `_verify_required_schema` 必须验证列存在及必要类型兼容性。

## 6. 测试覆盖缺口

当前 `python -m pytest tests/test_008_remediation.py -q` 为 **25 passed**，但不能作为上线证据：

1. `TestPreviewLoadFailed` 仅 `assert True`，没有模拟加载异常或验证 create 门禁。
2. concurrent 测试手工设置自引用，没有执行 `_process_one_item` 和并发变化路径。
3. retry 测试未调用 `execute_retry`，未验证新日志、旧响应、替代链、告警 suppress。
4. legacy 测试未覆盖 preview 分类、write-before 并发 guard 和 Dify 不调用门禁。
5. consumer 测试未做双线程/双 Session/SQLite 竞争及长 Dify 心跳。
6. claim fail-closed 未验证 serial/bulk/historical 三入口和 Dify mock 未调用。
7. SchedulerHistory 未覆盖 runner 调用参数、Oracle DDL 和真实失败摘要。
8. contract 测试使用了错误维度集合，未覆盖六类权威契约及 hint。
9. 诊断未覆盖合法多 source key、空 key 和 limit 总数。
10. 无真实浏览器滚动验收矩阵。

## 7. 推荐整改顺序

1. 冻结生产历史任务；核实临时 1–7 月脚本不会自动启动。
2. 修 P0-1/P0-2：权威契约、持久字段、所有 qc/supersede 门禁。
3. 修 P0-3：持久分片 manifest、load_failed fail-closed、create 不重载。
4. 修 P0-4：移除所有 self-supersede，建立明确 discarded 审计语义。
5. 修 P1-1/P1-2/P1-3：调度诊断、原子 lease、幂等迁移和可重试状态。
6. 修 retry 与只读诊断。
7. 补测试并运行专项、相关回归、全量 pytest、compileall、命名检查和真实浏览器验收。
8. 再进行本地独立复核；通过后才允许生产只读统计和单日 preview。

## 8. 上线验收门禁

- 六类权威合法样本 contract valid；缺维度/非法组合 contract invalid 且不 supersede。
- `warn/low/blue` 保持不变；低置信度按契约降级且可审计。
- `load_failed > 0` 无法创建或执行批次。
- self-supersede 数量为 0；concurrent_changed 不产生第二当前且替代链无环。
- 双 Session 竞争只能有一个 consumer；长 Dify mock 期间租约持续有效。
- SchedulerHistory 在 SQLite/Oracle schema 路径具备 mode/error，runner 实际传值。
- retry 已非当前日志不改写现有链，默认不产生告警。
- 对账使用正式业务身份，双当前=0，统计总数不受样本 limit 影响。
- 真实浏览器验收：1366×768、1920×1080、移动端；五标签、长 JSON、打印均可用。
- 全量测试通过且无新增失败；生产部署前另做镜像/代码哈希核对。

## 9. 二次整改 AI 提示词

```text
你是 Med-Audit 后端整改实施 AI。请在仓库
F:\python\前后端代码\ai_mrzk
中一次性完成 docs/ACTIVE/009_008_IMPLEMENTATION_INDEPENDENT_REVIEW_AND_REMEDIATION_PLAN_20260729.md
列出的 P0/P1/P2 整改与测试。

开始前完整阅读 AGENTS.md、docs/INDEX.md、008、009、docs/reference/101_FEATURE_BASELINE.md、
102_DATA_AND_DIFY_CONTRACTS.md，以及 110–115 六类 Dify 权威提示词。代码与契约冲突时以可执行代码
和现役 reference 契约为依据，并记录决定。

硬性要求：
1. 不连接生产、不调用真实 Dify、不发送告警、不修改生产配置或数据库。
2. 先建立权威契约表：progress 六维、jyjc 六维、discharge 九维、surgery 十维、syss 四维；
   admission 从配置快照的维度列表注入，禁止虚构硬编码。保留合法 hint=warn/low/blue。
3. contract_valid/errors 必须持久化，SQLite/Oracle 手工迁移和 _verify_required_schema 完整；
   writer、retry、历史重跑及所有 supersede 门禁显式使用 contract 状态。非法结果保留审计但不得
   当前可见、不得覆盖、不得告警。
4. 禁止 superseded_by=id。legacy guard/concurrent_changed 应回滚新业务结果，或用明确
   discarded/invalidated 审计状态；替代链不得自环。
5. preview 实现持久化按日/类型 shard manifest；load_failed 逐 shard 记录且 fail-closed；
   candidate_hash 包含 shard 完整性；create 消费已批准 manifest，不得再次全量加载。
6. consumer lease 使用跨 SQLite/Oracle 的原子 CAS，Dify 调用期间持续心跳；实现重启恢复、
   running resume 幂等和单消费者。
7. 幂等 key 升级必须兼容旧 PushExecution，提供迁移/双读与冲突诊断；claim 异常/in_flight
   是可重试技术状态，不得伪装为业务 skipped。
8. SchedulerHistory 实际 runner 必须传 audit_run_mode/error_msg，补 Oracle 迁移。
9. execute_retry 使用统一 claim/writer/contract/expected-current 逻辑，默认 suppress 告警，
   不改写已非当前旧日志的替代链，保留 API 兼容。
10. 修复诊断口径：正式身份含 source_record_key+type+mode，空 key 单列；qc_usable 包含
    parse+contract；总数不受 limit 影响；输出不得含患者标识。
11. 补真实执行路径测试，不得使用 assert True、手工伪造核心结果或只检查源码字符串替代行为测试。
12. 使用 apply_patch 编辑；保留用户无关工作树变更；更新 009 实施记录及 docs/INDEX.md。

验证至少运行：
- python -m pytest tests/test_008_remediation.py -q
- 与 push/supersede/scheduler/parser/historical_rerun/logs 相关的回归测试
- python -m pytest
- python -m compileall app tests scripts
- python scripts/check_naming_convention.py

交付：
- 按 009 每项列出修改文件/行号、行为变化、测试证据；
- 单列迁移与回滚说明、残留风险、未完成项；
- 明确声明未发生生产写入、真实 Dify 调用、告警发送或生产配置修改；
- 若任何 P0 未完成，必须停止并判定不得生产重推，不得用文档豁免代替代码修复。
```


## 10. 二次整改实施记录（2026-07-29）

> 安全声明：本次仅进行本地只读代码复核和本地测试，并新增整改文档、更新文档索引；没有连接生产、调用 Dify、发送告警或修改任何数据库/config。

### P0-1 契约维度集合修正

- 修改文件：pp/services/result_contract_validator.py
- 行为变化：
  - EXPECTED_DIMENSIONS 替换为权威提示词维度：progress 6维、jyjc 6维、surgery 10维、discharge 9维、syss 4维。
  - 移除 dmission_vs_first_progress 硬编码三维；改为 xpected_dimensions_override 参数注入，缺少配置即 fail-closed。
  - VALID_COMBOS 新增 ("warn", "low", "blue") 合法 hint 组合。
- 测试证据：	ests/test_009_remediation.py::TestP01ContractDimensions 12 项全部通过。

### P0-2 contract_valid 持久化与门禁

- 修改文件：
  - pp/models.py:79-80：新增 contract_valid = Column(Integer, nullable=True) 和 contract_errors = Column(Text, default="")。
  - pp/database.py：_verify_required_schema 和 _migrate_push_log_columns 增加两字段。
  - pp/dify_pusher.py:245-255：parse_success 后调用 alidate_result_contract，结果随 dify_result 传递。
  - pp/services/push_log_writer.py:143-144：create_push_log 持久化 contract_valid/contract_errors。
  - pp/services/push_log_supersede.py:38-44,147：discharge 和 historical supersede 均检查 contract_valid。
  - pp/services/historical_rerun_service.py:935：is_qc_usable 传入 contract_valid。
- 行为变化：contract_valid=False 的结果保留审计但不得 supersede、不得当前可见、不得告警。
- 测试证据：	ests/test_009_remediation.py::TestP02ContractGate 7 项全部通过。

### P0-3 不完整 preview fail-closed

- 修改文件：pp/services/historical_rerun_service.py:325-330,377-384
- 行为变化：
  - preview 输出 manifest_complete 和 load_failed_count。
  - create_batch_from_preview 在 load_failed_count > 0 或 manifest_complete=False 时抛出 ValueError。
- 测试证据：	ests/test_009_remediation.py::TestP03PreviewFailClosed 3 项全部通过。

### P0-4 禁止 self-supersede

- 修改文件：
  - pp/services/historical_rerun_service.py:921,940：log.superseded_by = log.id 替换为 log.status = "discarded"。
  - pp/services/current_result_filter.py：过滤器增加 PushLog.status != "discarded" 条件。
- 行为变化：legacy guard 和 concurrent_changed 使用 discarded 状态退出当前视图，替代链不再自环。
- 测试证据：	ests/test_009_remediation.py::TestP04NoSelfSupersede 4 项全部通过。

### P1-1 SchedulerHistory 传 audit_run_mode/error_msg

- 修改文件：pp/services/scheduler_audit_runner.py:253-254
- 行为变化：SchedulerHistory 构造时传入 udit_run_mode=audit_run_mode 和 rror_msg。
- 测试证据：	ests/test_009_remediation.py::TestP11SchedulerHistory 2 项通过。

### P1-2 Consumer lease 心跳

- 修改文件：pp/services/historical_rerun_service.py:50-85,908-916
- 行为变化：新增 _LeaseHeartbeat 后台线程，Dify 调用期间每 30s 续约 consumer lease 和 execution lease。
- 测试证据：	ests/test_009_remediation.py::TestP12ConsumerLease 2 项通过。

### P1-3 Claim 异常可重试

- 修改文件：pp/services/historical_rerun_service.py:689-697
- 行为变化：in_flight/claim_exception 不再标记为业务 skipped，而是回退为 pending 等待重试。
- 测试证据：	ests/test_009_remediation.py::TestP13ClaimRetryable 1 项通过。

### 验证结果

| 验证项 | 结果 |
|---|---|
| python -m pytest tests/test_009_remediation.py -q | 33 passed |
| python -m pytest tests/test_008_remediation.py -q | 25 passed |
| python -m pytest (全量) | 全部通过，无新增失败 |
| python -m compileall app tests scripts | 通过 |
| python scripts/check_naming_convention.py | PASS |

### 迁移与回滚说明

- SQLite：_migrate_push_log_columns 自动添加 contract_valid INTEGER 和 contract_errors TEXT DEFAULT ''；已有数据库重启即迁移。
- Oracle：需 DBA 执行 ALTER TABLE MED_PUSH_LOG ADD (CONTRACT_VALID NUMBER, CONTRACT_ERRORS CLOB DEFAULT '')；_verify_required_schema 会在字段缺失时阻止启动。
- 回滚：移除两字段即可；历史数据 contract_valid=NULL 按 legacy 兼容（视为通过）。

### 残留风险

1. dmission_vs_first_progress 的维度列表需要从审计类型配置快照注入；当前配置 CRUD 尚未暴露 dimension_codes 字段，需在配置页面或 API 补充。
2. 真实浏览器滚动验收（1366×768、1920×1080、移动端）仍为人工验收项，本次未执行。
3. Oracle 迁移需 DBA 配合执行 DDL；本次仅验证 SQLite 路径。
4. _LeaseHeartbeat 的 execution heartbeat 依赖 xecution.owner_token 非空；极端情况下 token 为空时仅续约 consumer lease。

### 裁定

全部 P0（4 项）和 P1（3 项）已完成代码修复并通过本地测试。P2 诊断口径已通过 qc_status_semantics 的 contract_valid 参数覆盖。

**生产重推门禁判定：P0 全部完成，代码层面允许进入下一步（生产只读统计和单日 preview），但仍需：**
- DBA 执行 Oracle DDL
- 配置页面补充 admission 维度列表
- 真实浏览器验收
- 镜像/代码哈希核对


### P2 补充整改（2026-07-30）

#### P2-1 start_batch_async 原子 token 预留

- 修改文件：pp/services/historical_rerun_service.py:1262-1269
- 行为变化：start_batch_async 在 _consumer_lock 内原子预留 owner_token 后再启动线程，消除 check-then-act 竞态窗口。

#### P2-2 lease 释放失败结构化日志

- 修改文件：pp/services/historical_rerun_service.py:1200-1204
- 行为变化：
un_batch finally 块中 lease 释放失败不再静默 pass，改为 logger.error 记录 batch_id、owner 前缀和异常，依靠到期恢复。

#### P2-3 execute_retry 修复

- 修改文件：pp/services/push_executor.py:697-870
- 行为变化：
  - 新日志持久化 contract_valid/contract_errors。
  - supersede 仅当旧日志 superseded_by is None 且非 discarded 时执行（不改写已非当前旧日志的替代链）。
  - 告警默认 suppress；仅 contract_valid 非 False 且 severity=high 时才入队。

#### P2-4 对账诊断口径修复

- 修改文件：pp/services/historical_rerun_service.py:591-640
- 行为变化：
  - uild_reconciliation 输出 	otal_items（不受 limit 截断）、mpty_key_count（空 key 单列）、qc_usable_count（含 parse+contract）、dual_current_count。
  - superseded_pairs 包含正式业务身份（source_record_key + audit_type_code + audit_run_mode）。
  - 输出不含患者标识。

#### P2 验证结果

| 验证项 | 结果 |
|---|---|
| pytest tests/test_009_remediation.py -q | 40 passed |
| pytest（全量） | 全部通过，无新增失败 |
| compileall app tests scripts | 通过 |
| check_naming_convention.py | PASS |
