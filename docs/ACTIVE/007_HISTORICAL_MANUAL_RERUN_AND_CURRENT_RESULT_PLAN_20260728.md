# 历史质控手工重跑、当前结果替代与日期批量推送改造计划

> 状态：本地开发已落地（002 幂等 + 007 批次/替代/当前结果投影/推送页）；禁止未批准生产补跑或删除历史数据  
> 日期：2026-07-28  
> 本地实施：2026-07-28（execution/attempt、historical_rerun API、mark_historical_reaudit_superseded、默认 hide_superseded、推送页历史重跑模式）  
> 关联计划：`002_PUSHLOG_IDEMPOTENCY_DESIGN_GATE.md`、`005_DIFY_WORKFLOW_INDEPENDENT_REVIEW_20260716.md`、`006_SCHEDULED_DIFY_MULTI_TARGET_CONFIGURATION_PLAN_20260716.md`  
> 目标：支持按日期范围对历史已质控记录进行可恢复的手工重新核查，新结果成功且结构化可用后成为业务当前结果；手动推送与定时推送复用同一套 Dify 多节点池。

## 1. 用户要求与本计划落点

| 用户要求 | 计划落点 |
| --- | --- |
| 对历史已经质控的数据重新手工推送 | 增加明确的“历史重新核查”运行目的，允许经授权绕过普通重复推送跳过规则 |
| 重新核查完成后覆盖之前的重复核查结果 | 新结果只有在 `transport success + parse_success + qc_usable` 后才替代旧当前结果 |
| 覆盖后不再保留重复数据 | 业务列表、患者质控、统计和默认导出只读取当前结果；旧记录退出业务当前视图 |
| 手动推送可以按日期批量推送 | 复用已有 `date_from/date_to/date_dimension`，补齐持久批次、按日分片、暂停/恢复、取消和对账 |
| 定时推送也能使用多个 Dify | 复用 006 已有持久化 Dify 节点池，手动与定时任务使用同一 resolver 和节点策略 |
| 在推送界面设置多个 Dify | 推送页继续作为节点池维护入口之一，与系统配置页读写同一个 `/api/config/dify/targets` 数据源 |
| 多 Dify 便于解析 | 增加逐节点 transport/empty/parse/qc_usable 指标；多节点用于负载和故障切换，不对同一患者 fan-out 后择优 |

## 2. 必须冻结的安全与审计语义

### 2.1 “覆盖且不保留”的准确含义

本计划将“覆盖且不保留”定义为：

1. 新结果成为唯一的业务当前结果。
2. 旧结果默认不再出现在患者质控、业务统计、风险列表和普通导出中。
3. 管理员可在“历史版本”中查看替代链，避免临床追溯断裂。
4. 不直接更新旧 PushLog 的 `response_json`、`request_json`、维度或结论来伪装成新结果。
5. 不物理删除历史成功记录、原始 Dify 响应、已发送告警、医生反馈和查看记录。

原因：历史成功结果、企微/H5 已发送事实和医生反馈属于审计事实。物理删除会导致告警、反馈、导出审计和临床追溯关系断裂，也无法证明重跑前后的差异。若医院另有数据留存期限，应通过现有 retention 机制和单独审批执行，不属于本计划。

### 2.2 替代成功门槛

只有新 PushLog 同时满足以下条件，才允许替代旧当前结果：

- `status=success`；
- `pushed_flag=1`；
- `parse_status=success`；
- 结构化结果通过当前 audit type schema；
- `qc_usable=true`；
- `audit_type_code`、患者、住院次数和来源身份与待替代记录一致；
- 新结果及维度、结论已在同一事务中完整落库。

以下结果绝不能替代旧当前结果：

- transport failed、timeout、empty output；
- parse failed、fallback；
- Dify 返回 unsupported audit type；
- 文书来源身份不一致；
- 任务取消、进程退出或数据库事务失败；
- 只有单侧证据却被模型输出为 high 的不合格结果。

### 2.3 告警与反馈

- 历史重跑默认 `alert_policy=suppress`，不自动重发企业微信/H5 告警。
- 若确需对重跑新高危发送告警，必须单独选择 `new_high_only` 并二次确认，且只对新结果中首次出现的合格 high 入队。
- 旧 `QCRecordAlertLog success/sent` 状态不改、不删、不重发。
- 旧 `QCFeedback`、医生查看记录和整改状态保留在旧版本；页面展示其来源版本。
- `suppress_ai_push=true` 的已整改患者默认仍禁止重跑；只有具备专门权限并填写理由才能纳入候选。

## 3. 当前代码事实与缺口

### 3.1 已有能力

- `ManualPushRequest` 已有 `query_date`、`date_from`、`date_to` 和 `date_dimension`。
- 手动推送页面已有单日/日期范围控件。
- `app/routers/push.py` 已能把日期范围拆成 `query_dates` 并逐日加载六类 bundle。
- 手动推送支持审计类型筛选、科室筛选、dry-run、异步和并发；另有 `skip_already_succeeded` **仅幂等跳过已成功项**，**不是**持久化批次断点续推。
- 手动推送和调度路径已经可以读取持久化 Dify targets。
- `PushLog` 已有 `superseded_by/superseded_at`，当前主要用于 `discharge_final` 替代 `daily_increment`；历史重跑另有 `mark_historical_reaudit_superseded`。
- 日志查询和导出已有 `hide_superseded`，业务默认列表/统计应优先使用当前结果过滤器。
- 006 已完成多 Dify 节点池、策略、熔断、系统配置 UI 和调度接线的本地开发。
- ACTIVE/002 的 `push_execution` / `push_attempt` 表与原子 claim 已落地（含 `uq_push_execution_key_mode` 唯一索引），serial/bulk/历史重跑已接线。

### 3.2 仍需解决

1. 普通手动推送会被 `unreviewed_pending` 和整改抑制规则拦截；历史重跑需走独立 `/api/push/historical-rerun/*` 授权语义（本地已实现，生产补跑仍须书面批准）。
2. 长周期补跑的批次恢复依赖 `HistoricalRerunBatch/Item` 持久化；生产全量补跑仍受门禁约束。
3. PushLog 层仍无 `(source_record_key, audit_type_code, audit_run_mode)` 部分唯一约束；“同一身份只有一个当前”主要靠应用层 `superseded_by IS NULL` + 002 claim（见 015/C1）。
4. 生产真实补跑、连续调度观察与临床抽检尚未完成。
5. 多 Dify 节点的 parse/qc_usable 指标仍需持续纳入批次结果观测，不能仅展示 transport success。

## 4. 目标业务模型

### 4.1 运行目的与结果策略

手动推送请求增加明确字段，不复用含义模糊的布尔开关：

```json
{
  "run_purpose": "standard|historical_reaudit",
  "existing_result_policy": "skip_success|replace_current",
  "reaudit_reason": "审批单或重跑原因",
  "alert_policy": "suppress|new_high_only",
  "confirm_candidate_hash": "dry-run候选集哈希"
}
```

规则：

- 普通手动推送默认 `standard + skip_success`，保持现有行为。
- 历史重新核查固定使用 `historical_reaudit + replace_current`。
- `historical_reaudit` 仅管理员或新增 `manage_historical_rerun` 权限可执行。
- `reaudit_reason` 必填，写入批次审计；禁止把密码、患者姓名或病历正文写入理由。
- `manual_override` 继续作为 PushLog 结果标记，不直接充当请求授权开关。
- 不提供“按日期先删除再推送”模式。

### 4.2 当前结果身份

新旧结果只有在同一业务身份下才能建立替代关系。首版优先身份为：

```text
source_record_key
+ audit_type_code
+ audit_run_mode
```

补充约束：

- `patient_id + visit_number` 必须一致，但二者不能单独作为覆盖键。
- 不同 audit type 绝不能互相替代。
- `daily_increment` 与 `discharge_final` 保持既有双模式语义；只有现有终末覆盖规则允许跨模式替代。
- **身份键不使用** `source_version` / `clinical_source_fingerprint`：
  - `PushLog` **没有**这两列；业务当前结果身份仍是 `source_record_key + audit_type_code + audit_run_mode`。
  - `push_execution.source_version`（002 已落地，`String(128)`）**仅作审计/入口标记**（如 `hist_rerun:{batch_id}`、`manual_replace`），**不参与** `make_idempotency_key` 计算（见 `push_idempotency.py` 注释 P1-5），因此**不能**充当 007 的临床来源指纹身份键。
  - `clinical_source_fingerprint` 在全代码库中仍不存在；若后续引入必须同时加 PushLog ORM、SQLite/Oracle 迁移和 `_verify_required_schema()`，并重新验证历史兼容性。
- `source_record_key` 必须由现有来源构造逻辑（`record_identity.py`）稳定生成。
- 历史 `source_record_key` 为空、无法证明稳定时，进入 `identity_ambiguous` 人工清单，不自动替代。
- 候选身份规范化后生成 SHA-256，用于 dry-run 确认和并发校验；哈希中不得包含姓名或病历正文。

### 4.3 替代链

- 旧当前 PushLog 的 `superseded_by` 指向新 PushLog，`superseded_at` 记录事务时间。
- 同一业务身份任意时刻只能有一个未被替代的成功可用结果。
- 当前 PushLog 没有数据库唯一约束；并发安全首版完全依赖 ACTIVE/002 的 execution claim 和替代事务校验。若后续增加数据库兜底，需先清理历史重复，并分别设计 SQLite 部分唯一索引与 Oracle function-based unique index，不能直接增加普通唯一约束。
- 再次重跑时只替代当前节点，不重写更早历史节点。
- 新结果失败时，旧当前结果继续有效。
- 替代事务失败时，新结果和替代关系一起回滚，不能出现“新结果成功但两个都是当前”的中间状态。
- 删除新当前结果不是常规回滚方式；回滚应基于 before 快照恢复原替代关系并保留失败审计。

## 5. 日期批量重跑设计

### 5.1 页面输入

推送页面增加“历史重新核查”模式，保留现有字段：

- 日期维度：记录创建日期、入院日期、出院日期、查询日期；
- 开始日期、结束日期；
- 六类质控多选；
- 科室范围；
- 单次 worker 数和审计类型并行开关；
- 使用系统 Dify 节点池或本次临时节点；
- 告警策略；
- 重跑原因。

执行按钮分为：

1. `预检候选`：只查数据，不调用 Dify、不写业务结果。
2. `确认并创建批次`：提交候选集哈希和二次确认。
3. `暂停/继续/取消`：只影响未开始分片，已进入单条事务的项目正常收口。

### 5.2 分片与规模控制

- 日期范围按自然日拆分，再按 audit type、科室和稳定业务键排序。
- 每个分片设置候选上限，默认建议 100 条；批次可以包含多个分片。
- 长日期范围不一次性把全部病历正文放入内存。
- dry-run 返回每天、每类型的候选数、已有当前结果数、身份不明数、已整改抑制数和预计 Dify 调用数。
- 候选数超过配置上限时只允许创建分批任务，不允许同步 HTTP 长连接执行。
- 批次记录持久化，容器重启后可以从未完成分片继续；已成功项目不重复调用。
- 取消任务不删除已完成的新结果，也不回滚已经成功的替代关系。

### 5.3 断点续跑与并发

- **直接复用** ACTIVE/002 已落地的 execution/attempt 原子 claim（`PushExecution`/`PushAttempt` + `uq_push_execution_key_mode`）；不得另造第二套幂等模型。
- 每条候选在调用 Dify 前取得 lease；同一业务身份已有运行中 lease 时跳过或附着，不重复调用。
- Dify 网络调用不长期占用数据库事务。
- 落库时重新校验 candidate hash、旧当前 PushLog ID 和原状态；任一变化则记为 `concurrent_changed`，不得强行覆盖。
- SQLite worker 最多 4；Oracle 使用公共 `effective_parallel_workers()` 计算。
- APScheduler 继续保持单进程/单 uvicorn worker，手动重跑不得绕过 daily/discharge 数据库锁语义。

## 6. 持久批次与数据结构

### 6.1 复用已落地的 ACTIVE/002

002 已落地为 `push_execution` / `push_attempt` 表（含 `uq_push_execution_key_mode` 唯一索引）及 claim/lease API（`app/services/push_idempotency.py`），并已接入 serial/bulk 与历史重跑路径。本计划**直接复用其幂等机制**，不得另造第二套幂等模型。execution 负责：

- 稳定幂等键（`idempotency_key + audit_run_mode`，由 `source_record_key + audit_type_code + audit_run_mode` 派生；`source_version` 不参与 key）；
- 原子 claim 和 lease；
- 同一次业务执行的网络 attempts；
- target、耗时和失败原因；
- 跨进程恢复（依赖 DB 状态，非进程内内存）。

### 6.2 新增重跑批次实体

在 ACTIVE/002 首次实施之外，建议新增最小批次表，名称最终按现有模型前缀确定：

```text
HistoricalRerunBatch
  id / status / actor / reason
  date_from / date_to / date_dimension
  audit_type_codes_json / dept_filter_json
  existing_result_policy / alert_policy
  candidate_hash / config_snapshot_hash
  candidate_count / processed / success / failed / skipped / superseded
  created_at / started_at / finished_at / cancelled_at

HistoricalRerunItem
  batch_id / business_identity_hash / execution_id
  previous_current_push_log_id / new_push_log_id
  status / reason_code / attempt_count
  created_at / updated_at
```

要求：

- Item 不存患者姓名和病历正文；业务明细仍在受权限控制的 PushLog。
- SQLite 和 Oracle 都需要手工迁移、索引、幂等建表和 `_verify_required_schema()` 校验。
- `business_identity_hash` 在同一批次唯一。
- 保存配置快照哈希，不保存明文 API Key。
- 如 ACTIVE/002 最终 execution 设计已能承载 item 状态，可合并 Item，但必须保留批次级查询和统计能力。

## 7. API 计划

建议新增独立 API，避免扩展 `/api/push/manual` 后误触历史覆盖：

```text
POST /api/push/historical-rerun/preview
POST /api/push/historical-rerun/batches
GET  /api/push/historical-rerun/batches/{batch_id}
GET  /api/push/historical-rerun/batches/{batch_id}/items
POST /api/push/historical-rerun/batches/{batch_id}/pause
POST /api/push/historical-rerun/batches/{batch_id}/resume
POST /api/push/historical-rerun/batches/{batch_id}/cancel
GET  /api/push/historical-rerun/batches/{batch_id}/reconciliation
```

API 契约：

- preview 不调用 Dify、不创建 PushLog、不触发告警。
- create 必须提交 preview 返回的 `candidate_hash`；候选变化返回 409 并要求重新预检。
- 所有写接口要求管理员/专门权限并记录 actor、来源 IP、筛选条件和批次 ID。
- items 接口默认不返回 `mr_text/request_json/response_json`。
- 批次状态使用闭集：`draft|confirmed|running|paused|completed|completed_with_errors|cancelled|failed`。
- 不能把部分失败的批次显示为纯 `completed`。

## 8. 当前结果查询与导出

新增共享查询函数，例如：

```python
apply_current_result_filter(query, include_superseded=False)
```

以下业务入口默认 `include_superseded=false`：

- 患者质控列表和详情默认结果；
- 风险/告警业务列表；
- 首页和统计报表；
- 推送日志普通列表；
- CSV/Excel 普通导出。

管理审计入口可以显式选择“包含历史版本”，并展示：

- 当前/历史状态；
- 替代它的新 PushLog ID；
- 替代时间；
- 重跑批次 ID；
- 旧结果关联的告警与反馈状态。

导出必须：

- 默认只导出当前结果，解决重复记录问题；
- 显式导出历史版本时增加 `is_current/superseded_by/rerun_batch_id` 列；
- 调用 `record_export_audit()`；
- 保持历史 NULL 容错和科室权限过滤。

## 9. 手动与定时 Dify 多节点

### 9.1 唯一配置源

- 继续使用全局 `config.dify.targets` 和 `/api/config/dify/targets`。
- 推送页与系统配置页只是同一配置源的两个 UI 入口，不复制配置。
- 保存后必须重新 GET，以服务端脱敏结果为准。
- 节点 Key 留空表示保留旧密钥，任何 GET、日志和批次快照不得返回明文或密文。

### 9.2 运行语义

- 手动普通推送、历史重跑、daily_increment、discharge_final 使用同一 `resolve_dify_target_pool()`。
- 每个患者的一次 execution 只选择一个 Dify 节点；禁止同时发给多个节点比较结果。
- transport error、timeout、empty output 可以在同一 execution 内有限切换节点重试。
- parse failed 是否跨节点重试默认关闭；只有完成六类脱敏回放、证明不会引入结果选择偏差后再开放，且最多一次。
- 多次 attempt 只允许一个最终 `qc_usable` 结果成为 PushLog 当前结果。
- 所有节点必须部署等价的六类 workflow 契约；混用不同维度集合、不同 output key 或不同高危门槛的节点禁止加入同一池。

### 9.3 解析可观测性

每个节点至少统计：

- selected；
- transport_success / transport_failed；
- empty_output；
- parse_success / parse_failed / fallback；
- qc_usable；
- latency p50/p95；
- circuit state。

批次完成后按 audit type 和 target 对账。节点连续出现 schema 不匹配或 parse failure 时应从新任务选择中隔离并报警，但不得自动采用另一个节点的“更高风险”结果。

## 10. 实施工作包

### 工作包 A：契约确认与失败测试

1. 冻结业务身份键、替代成功门槛、默认告警策略和权限。
2. 为普通手推、历史重跑、daily、discharge 建立入口矩阵。
3. 先补失败测试：失败/解析失败不得替代，身份不明不得替代，重复并发不得双调用。
4. 核对 006 当前代码与测试，禁止重写第二套 Dify target resolver。

停止点：设计复核通过，才允许迁移数据库。

### 工作包 B：ACTIVE/002 幂等基础

1. 实施 execution/attempt 原子 claim、lease 和唯一键。
2. 覆盖 serial、bulk、manual、scheduler、retry 路径。
3. 完成 SQLite/Oracle 迁移与并发测试。
4. 保持 PushLog 为业务结果，不让其独自承担 claim 与 attempt。

停止点：并发和崩溃恢复测试通过。

### 工作包 C：批次模型与预检 API

1. 新增 batch/item 模型及手工迁移。
2. 实现日期范围按日、类型、科室分片。
3. 实现候选身份、当前结果匹配和 candidate hash。
4. 输出 `pushable/identity_ambiguous/rectified_suppressed/already_running` 分类。
5. preview 保证只读。

停止点：使用合成数据完成 dry-run 对账。

### 工作包 D：历史重跑执行器

1. 从持久批次 claim item。
2. 复用现有 payload composer、Dify pusher、parser 和 writer。
3. 支持暂停、恢复、取消和容器重启续跑。
4. 记录节点 attempt 指标和失败原因。
5. 默认抑制外部告警。

停止点：mock Dify 故障、空输出、parse failed、进程中断全部可恢复。

### 工作包 E：当前结果替代服务

1. 将现有 discharge 专用逻辑保留为明确策略。
2. 新增独立的 `mark_historical_reaudit_superseded` 策略函数；不得复用或改写现有 `mark_daily_logs_superseded`，因为后者硬编码 `discharge_final` 前置条件。
3. 新结果完整可用后在同一事务建立 `superseded_by`。
4. 并发状态变化时拒绝覆盖。
5. 生成 batch 级 before/after 对账。

停止点：所有失败场景均证明旧当前结果未变化。

### 工作包 F：查询、统计和导出统一

1. 增加共享 current-result filter。
2. 业务页面、报表、统计和普通导出默认隐藏历史版本。
3. 管理员保留历史版本查看入口。
4. 检查历史 NULL、旧 audit type 空值和 Oracle 空字符串语义。

停止点：同一身份多次重跑后，普通列表/统计/导出均只出现一条当前结果。

### 工作包 G：推送页面

1. 增加“普通推送/历史重新核查”模式。
2. 增加预检结果、候选分类、重跑原因和二次确认。
3. 增加批次进度、暂停、恢复、取消和错误明细。
4. 节点池编辑继续写 006 的统一配置 API。
5. 明确提示节点池同时用于手动和定时推送。

### 工作包 H：调度与多节点回归

1. 验证 daily/discharge 都使用统一节点池。
2. 验证调度锁仍按 `daily_push/discharge_push` 分离。
3. 验证同一患者不 fan-out。
4. 验证节点故障切换、熔断和解析指标。
5. 不改变调度候选 SQL、Dify 目标选择语义之外的业务逻辑、告警门槛和科室白名单。

### 工作包 I：生产演练与分批发布

1. 备份应用库、配置、`.env` 和镜像 ID。
2. 先用合成数据和 mock Dify 完成全链路演练。
3. 生产只做只读 preview，输出候选数量和 candidate hash。
4. 取得书面批准后，先执行单类型、单日、最多 100 条试运行。
5. 对账 current/high/medium/low/parse/alert/feedback 数量。
6. 试运行通过后再按日扩展，禁止直接一次运行数月全量。

## 11. 测试矩阵

### 11.1 替代规则

- 同身份新结果 success + parse_success：旧结果被替代。
- 新结果 failed/empty/parse failed/fallback：旧结果保持当前。
- 不同 audit type、run mode 或 `source_record_key`：不替代。
- 历史 source key 为空：进入人工清单。
- 两个 worker 竞争同一 item：只调用一次 Dify，只产生一个当前结果。
- 替代事务中断：不存在两个当前结果。
- 新结果删除/回滚：按批准快照恢复关系，不删除旧响应。

### 11.2 日期批次

- 单日、跨月、月末和闰日范围。
- `date_from > date_to`、未来日期、超范围日期拒绝。
- 六类按日分片数量与数据源查询一致。
- 暂停、恢复、取消、容器重启后计数不重复。
- 断点续跑跳过已成功 item，失败 item 按上限重试。

### 11.3 当前结果投影

- 普通日志、患者质控、报表、Dashboard 和导出只统计当前结果。
- 管理审计查询可看到完整替代链。
- 旧告警和反馈仍能定位原 PushLog。
- 历史 NULL、空 audit type、Oracle 空字符串不导致 500 或漏掉当前结果。

### 11.4 多 Dify

- 0/1/2/10 个节点配置。
- round-robin 和 weighted-random。
- 单患者不 fan-out。
- transport/empty 有界切换节点。
- parse failed 默认不跨节点重跑。
- 节点 workflow 契约不一致时预检失败。
- 手动、历史重跑、daily、discharge 均复用同一 pool resolver。

### 11.5 建议验证命令

```bash
python -m compileall app tests scripts
python -m pytest tests/test_push_executor.py tests/test_bulk_push_executor.py -q
python -m pytest tests/test_push_skip_policy.py tests/test_push_log_supersede.py -q
python -m pytest tests/test_scheduler_audit_types.py tests/test_scheduler_safety.py -q
python -m pytest tests/test_dify_target_pool_resolver.py tests/test_scheduler_audit_runner_multi_target.py -q
python scripts/frontend_regression_check.py
python scripts/frontend_method_check.py
python scripts/check_naming_convention.py
python -m pytest
```

新增测试文件建议：

- `tests/test_historical_rerun_preview.py`
- `tests/test_historical_rerun_batch.py`
- `tests/test_historical_rerun_replacement.py`
- `tests/test_current_result_projection.py`
- `tests/test_historical_rerun_frontend_static.py`

## 12. 发布门禁与回滚

### 12.1 发布门禁

- 002 幂等 execution/attempt 已实施并通过并发测试。
- 006 多节点回归通过，所有节点 workflow 契约一致。
- SQLite 与 Oracle 迁移均完成离线验证。
- 生产容器 healthy，Oracle 连接基线稳定，uvicorn 为单 worker。
- 生产 preview 已生成，候选范围、identity ambiguous 和告警影响已确认。
- 临床/质控负责人批准精确日期、类型、科室、告警策略和首批上限。
- 首批执行前保存 before 快照和 SHA-256。

### 12.2 回滚

- 停止领取新的 batch item，等待运行中 item 收口。
- 禁用 `historical_rerun.enabled`，普通手动和定时推送继续运行。
- 按 batch before 快照恢复 `superseded_by/superseded_at` 关系。
- 新 PushLog 保留并标记批次回滚，不物理删除原始响应。
- Dify 节点池可停用新增节点并回退上一配置备份；不得更换 `SECRET_KEY`。

## 13. 明确不在本计划内

- 不按日期直接删除 PushLog、维度、结论、告警或反馈。
- 不覆盖旧 PushLog 的原始 Dify response。
- 不将同一患者发送给全部 Dify 节点后选择“最好”或“最高危”结果。
- 不修改六类 audit type code、维度白名单、高危硬门槛或临床统计口径。
- 不用真实患者数据测试外部 AI。
- 不在未批准情况下运行 2026 年 1 月至 7 月全量重跑。
- 不把生产 config、API Key、数据库密码或患者信息写入批次日志。

## 14. 验收标准

1. 管理员可在推送页面按日期范围、质控类型和科室预检历史候选。
2. 重跑必须经过 preview、候选哈希确认和原因填写。
3. 长批次可暂停、恢复、取消并在容器重启后继续。
4. 新结果失败或解析不可用时不影响旧当前结果。
5. 新结果成功可用后，普通页面、统计和导出只出现一个当前结果。
6. 管理审计仍可查看完整替代链、旧告警和旧反馈。
7. 手动、历史重跑和定时任务复用同一 Dify 节点池与 resolver。
8. 多节点不 fan-out，节点故障可有限切换，逐节点解析质量可观测。
9. SQLite、Oracle、前端静态检查和全量测试全部通过。
10. 生产首批最多 100 条完成 before/after 对账后，才允许扩展下一批。

## 15. 当前裁定

本需求可以实施，但不能采用“先删除历史、再重新推送”或“直接覆盖旧 response_json”的方式。正确实现是：**直接复用已落地的 ACTIVE/002**（`push_execution`/`push_attempt` 幂等 claim），再由持久化重跑批次（`HistoricalRerunBatch/Item`）负责日期范围和断点恢复；成功且可解析的新 PushLog 通过替代链成为唯一业务当前结果，旧记录仅保留为受权限控制的审计历史；手动和定时推送继续复用 006 的同一套 Dify 多节点池。
