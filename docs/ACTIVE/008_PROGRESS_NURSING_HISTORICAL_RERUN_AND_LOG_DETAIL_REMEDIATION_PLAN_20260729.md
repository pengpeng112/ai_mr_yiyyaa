# 病程护理历史重推、定时防漏与推送日志详情整改执行计划

> 编号：008  
> 日期：2026-07-29  
> 状态：外部独立复核后有条件通过（2026-07-29）；确认 3 个 P0 实现冲突，修复并验证前禁止任何生产历史批量重推  
> 环境：Med-Audit 生产 `10.10.8.84:8000`，容器 `med-audit`，Oracle 应用库/业务库，Dify 5 节点  
> 核心范围：`progress_vs_nursing` 历史 1–7 月重推与安全覆盖、定时漏推对账、非法结果组合整改、`log_detail.html` 桌面滚动修复  
> 关联：`002_PUSHLOG_IDEMPOTENCY_DESIGN_GATE.md`、`007_HISTORICAL_MANUAL_RERUN_AND_CURRENT_RESULT_PLAN_20260728.md`、`docs/reference/101_FEATURE_BASELINE.md`、`docs/skills/med-audit-codex.md`

## 1. 目标

本计划解决四个相互关联的问题：

1. 病程记录与护理记录能够按历史日期重新加载、重新推送，并在新结果可用时安全替代旧当前结果。
2. 历史补跑和日常/出院定时任务都能与实际 Oracle 文书逐日对应，形成可解释的漏斗和漏推清单。
3. 修复质控维度中 `unknown|medium` 等违反现役枚举契约的组合，避免“解析成功但结果不可用”。
4. 修复独立推送日志详情页在桌面端无法向下滚动的问题。

本计划不授权：

- 直接删除历史 PushLog、Dify 原始响应、维度、结论、告警或医生反馈；
- 无 preview、无候选哈希地连续补跑 1–7 月；
- 按 `patient_id + visit_number` 宽泛覆盖同一次住院的全部结果；
- 把 fallback、parse failed 或非法维度组合视为可替代旧结果；
- 在未批准前停止、续跑或重建生产任务；
- 修改高危门槛、提示词、告警科室白名单或真实发送告警。

## 1.1 外部独立复核裁定与本计划修订结论

外部 AI 对首版计划裁定为“有条件通过”。本地逐项对照当前可执行代码后确认：

### 已确认的 P0 阻断

1. **空 `source_record_key` 历史会形成双当前结果。**
   - preview 使用新 bundle 的非空 key 查当前结果，无法发现同患者/访次/类型/模式下旧 key 为空的当前 success。
   - 执行阶段又要求同 key supersede，旧空 key 永不命中。
   - 当前实现会把新结果记为 `success_no_previous` 并提交，导致新旧结果的 `superseded_by` 都为空。
   - 本计划原先描述了 `legacy_resolvable`，但当前代码尚未实现该分类和执行门禁。
2. **`concurrent_changed` 会形成双当前结果。**
   - `mark_historical_reaudit_superseded()` 返回 `-1` 后，当前执行器仍提交 status=success 的新 PushLog。
   - 新结果没有被 supersede，也没有退出当前视图，违背 007 的“不能出现两个当前结果”约束。
3. **持久批次目前不具备容器重启后的自动恢复能力。**
   - 批次消费者是进程内线程。
   - 重启后 batch/item 可停留在 running。
   - resume 不接受 running batch，claim 只领取 pending item。
   - 没有消费者单例锁和 stale running item 回收，因此批次可能永久卡住或被重复启动。

### 已确认的 P1 风险

- serial/bulk 的 `claim_execution` 异常使用 `claim_error_fallback` 继续调用 Dify，属于幂等 fail-open。
- `force=True` 会绕过未过期 in-flight lease。
- `source_version` 参与幂等键；普通、手推覆盖、历史批次使用不同 version，跨入口互斥不可见。
- preview 在单个 HTTP 请求内循环完整日期范围，创建批次又重新执行一次完整 preview。
- preview 遇到加载异常时 `continue`，失败日期会从候选集中消失，无法区分“0 文书”和“加载失败”。
- `qc_usable` 只检查 transport success + parse success；当前没有固定维度集合及 status/severity/alert_level 组合的完整可用性门槛。
- SchedulerHistory 没有 `error_msg`、`audit_run_mode` 字段，类型级加载错误只能依赖文件日志。

### 已确认的 P2 文档/实现差异

- 历史批次当前为串行消费者，`parallel_workers=2` 对该执行路径不生效。
- 当前出院模式代码已包含通用 `{dept_filter}` fallback，不能继续使用“仅三类有转换”作为当前代码结论；仍须逐类型验证实际 SQL 是否含可注入锚点。
- ORA-12609 风险主要来自长日期逐日加载与定时窗口重叠，不能简单归因于“6 路并发查询业务库”；Dify 并发仍会增加整体资源竞争。
- `execute_retry` 会就地改写原 PushLog 的 `response_json`，与本计划“原始响应永不改写”不一致，须单独整改或书面列为受限 legacy 例外。

### 修订后的硬结论

在 P0-1、P0-2、P0-3 完成并通过测试前：

- 禁止启动 H1 批量任务；
- 禁止用持久批次执行生产 canary；
- 禁止把 `success_no_previous` 视为历史覆盖成功；
- 禁止对 running batch 直接人工改库后续跑；
- 页面滚动修复可以独立开发和发布，但不构成重推授权。

## 2. 已确认的生产事实

### 2.1 运行环境

- 容器唯一且 healthy。
- Uvicorn 为单 worker。
- 应用库为 Oracle。
- 健康接口可用。
- Dify 节点池为 5 个节点，策略为 `round_robin`。
- `daily_push`、`discharge_push` 使用分离的数据库运行锁。

### 2.2 调度配置

日常任务：

```text
时间：09:00
模式：daily_increment
类型：
  progress_vs_nursing
  jyjc_vs_bcnursing
  admission_vs_first_progress
  surgery_chain
```

出院终末任务：

```text
时间：11:44
模式：discharge_final
类型：
  progress_vs_nursing
  syssvsscbc
  jyjc_vs_bcnursing
  admission_vs_first_progress
  surgery_chain
  discharge_vs_frontpage
```

近 14 天调度历史共 84 条类型级记录，确认 3 次 `total=0` 失败：

- 2026-07-27 `progress_vs_nursing`
- 2026-07-27 `syssvsscbc`
- 2026-07-28 `progress_vs_nursing`

这些记录符合业务库加载阶段失败/超时特征，不能因为 `PushLog.failed=0` 判断为没有问题。

### 2.3 当前临时历史任务

生产存在两个宿主机临时任务：

- `/tmp/july_remain_push.sh`
- `/tmp/h1_replace_push.sh`

7 月脚本的已核实参数：

```text
日期：2026-07-23 ～ 2026-07-28
类型：六类
date_dimension=record_create_date
existing_result_policy=replace_current
alert_policy=suppress
allow_rectified=false
skip_already_succeeded=false
parallel_workers=6
target_strategy=round_robin
```

1–6 月脚本等待 7 月脚本结束后自动启动。

生产 `HistoricalRerunBatch`、`HistoricalRerunItem` 当前均为 0 条。因此上述任务不是持久化历史重跑批次，只是 Shell 脚本调用普通手推 API，存在以下缺口：

- 没有数据库批次级断点；
- 没有冻结候选集和 `candidate_hash`；
- 没有逐条 `previous_current_push_log_id`；
- 页面无法可靠展示完整任务进度；
- 容器/主机重启后的恢复语义不明确；
- 6 worker 可能与定时任务竞争 Oracle/Dify 资源。

### 2.4 高危与告警只读基线

- 顶层 high/red PushLog：706。
- high/red 维度：1093。
- `admission_vs_first_progress` 高危 PushLog：704。
- `surgery_chain` 高危 PushLog：2。
- 其余类型高危：0。
- 上述高危 PushLog 全部 `reviewed_flag=0`。
- 关联告警 `dept_filtered`：570。
- 形式门槛不合格高危维度：20，均涉及 `dimension_code=other` 等不合格条件。

该基线只用于说明当前数据质量风险；本计划不自动修改高危等级。历史高危整改仍须遵守 `med-audit-history-remediation` 技能的逐阶段审批。

### 2.5 日志 138724

该记录只读结果：

```text
audit_type_code=jyjc_vs_bcnursing
audit_run_mode=daily_increment
query_date=2026-07-23
status=success
parse_status=success
pushed_flag=true
manual_override=true
severity=medium
superseded_by=NULL
dimension_count=6
```

维度组合：

```text
unknown|medium = 3
unknown|low    = 2
warn|medium   = 1
```

`unknown|medium` 不符合现役契约：unknown 应映射为 `unknown/low/gray`；若事实达到中危，应使用 `warn/medium/yellow`。这说明 `parse_status=success` 尚不足以证明结果契约完全可用。

### 2.6 日志详情页滚动根因

生产静态资产仍包含：

```css
#app {
  height: 100vh;
  overflow: hidden;
}
```

主系统通过 `.content { overflow-y:auto }` 提供滚动，但独立 `log_detail.html` 没有 `.content` 容器。桌面端内容超过一屏时被 `#app` 裁剪；移动端媒体查询把高度改回 auto，因此问题主要在桌面宽度出现。

## 3. 必须冻结的业务口径

### 3.1 历史覆盖含义

“覆盖历史结果”定义为：

1. 新结果成为业务当前结果。
2. 旧结果通过 `superseded_by/superseded_at` 退出默认业务视图。
3. 旧结果、原始响应、维度、结论、告警和反馈仍保留审计。
4. 失败的新结果不影响旧当前结果。
5. 不物理删除旧结果，不改写旧 `response_json`。

### 3.2 新结果可替代门槛

必须全部满足：

- `status=success`
- `pushed_flag=1`
- `parse_status=success`
- `qc_usable=true`
- 固定维度集合完整
- 维度 status/severity/alert_level 组合合法
- patient_id、visit_number、audit_type_code、audit_run_mode 一致
- source identity 唯一且可证明
- 新 PushLog、维度、结论在同一事务完整落库
- 写入前旧当前结果仍等于 preview 的 `previous_current_push_log_id`

任一不满足：

- 新记录标记为 failed、skipped 或 concurrent_changed；
- 旧结果继续保持当前；
- 不得建立 supersede；
- 不得发送历史告警。

### 3.3 业务身份分类

#### exact_match

以下字段完全一致，可自动替代：

```text
source_record_key
+ audit_type_code
+ audit_run_mode
+ patient_id
+ visit_number
```

#### legacy_resolvable

旧记录 `source_record_key` 为空，但可使用以下组合唯一证明新旧来源一致：

```text
patient_id
+ visit_number
+ audit_type_code
+ audit_run_mode
+ query_date
+ 文书来源日期/稳定来源指纹
```

必须先生成精确 ID 映射清单、dry-run 和哈希，经批准后处理。

**当前实现状态：未实现，属于 P0。** 当前 preview 会把此类旧当前结果误判为 `has_current=false`，执行后可能形成 `success_no_previous` 双当前。在实现以下门禁前，所有“新 key 非空、同患者/访次/类型/模式存在空 key 旧当前”的候选必须降为 `identity_ambiguous`，不得调用 Dify：

1. preview 反查同 patient_id + visit_number + audit_type_code + audit_run_mode 的空 key、未 supersede、qc_usable 旧结果；
2. 输出 `legacy_empty_key_current_count` 和精确旧 ID 的内网映射；
3. 能唯一证明来源一致时才进入 `legacy_resolvable`；
4. 不能唯一证明时保持 `identity_ambiguous`；
5. 写入前再次执行相同 guard，发现空 key 旧当前时禁止 `success_no_previous` 提交；
6. 不允许通过关闭 `require_same_source_key` 宽泛解决。

#### identity_ambiguous

以下情况不得自动替代：

- 同一住院存在多个可能旧当前结果；
- 缺少 query_date 或来源日期；
- 新旧文书版本无法证明一致；
- patient_id/visit_number 缺失；
- 不同 audit_run_mode 混在一起；
- 来源键发生碰撞。

禁止为了提高覆盖率而退化为只按 `patient_id + visit_number` 覆盖。

## 4. 总体执行顺序

```text
生产任务状态冻结
  → 本地修复详情页
  → 结果契约校验
  → 病程护理只读 preview
  → 实际文书/当前结果逐日对账
  → 候选身份分类
  → 单日最多 100 条 canary
  → supersede 与页面验收
  → 观察 daily/discharge
  → 按日扩展历史范围
  → 六类后续复核
```

任何阶段失败都停止，不跳过门禁进入下一阶段。

## 5. 工作包 A：当前临时任务收口

### A1. 写入前提

停止、暂停、修改两个 Shell 任务属于生产状态变更，必须取得书面批准。

### A2. 建议动作

1. 允许当前 7 月正在处理的单类型安全收口。
2. 阻止 `h1_replace_push.sh` 自动进入 1–6 月循环。
3. 保存：
   - 脚本 SHA-256；
   - 日志 SHA-256；
   - 当前 PID；
   - 完成到的日期和类型；
   - 每个日期/类型的 total/success/failed/skipped。
4. 不删除已产生的新 PushLog。
5. 不恢复或改写已建立的 supersede。
6. 确认 `daily_push`、`discharge_push` 锁恢复 idle。

### A3. 验收

- 没有同范围历史任务仍调用 Dify；
- 1–6 月任务未自动开始；
- 已完成项目可从日志重建；
- 定时任务不受影响；
- 生产配置和 Dify 节点池未被改写。

## 6. 工作包 B：日志详情页滚动修复

### B1. 建议实现

给独立页面增加专用 class：

```html
<body class="log-detail-page">
```

增加作用域样式：

```css
.log-detail-page {
  margin: 0;
  min-height: 100vh;
  min-height: 100dvh;
  overflow-y: auto;
}

.log-detail-page #app {
  display: block;
  width: 100%;
  height: auto;
  min-height: 100vh;
  min-height: 100dvh;
  overflow: visible;
}
```

禁止直接删除全局 `#app overflow:hidden`，否则可能破坏主应用侧栏和内容区布局。

同步更新：

- `static/log_detail.html`
- `static/styles/pages/log_detail.css`
- HTML/CSS 缓存版本号
- 静态前端测试

### B2. 浏览器验收矩阵

- Chrome/Edge
- 1366×768
- 1920×1080
- 900px 临界宽度
- 手机宽度
- 鼠标滚轮、触摸板、PageDown、Home/End
- AI 结果、证据原文、结构化输出、落库维度、类型区块
- JSON 内部局部滚动
- sticky 顶栏
- 打印模式

以生产日志 138724 作为长内容样本，但测试输出不得保存患者信息或病历正文。

### B3. 验收标准

- 页面可滚动到最后一个内容块；
- 切换标签后仍可滚动；
- 顶栏不遮挡内容；
- 不产生双滚动条导致的滚轮失效；
- 主应用其他页面滚动无回归；
- 浏览器强制刷新后获取新版本资源。

## 7. 工作包 C：结果契约校验

### C1. 确定性规则

至少校验：

```text
pass    → low    → blue
warn    → medium → yellow
fail    → high   → red
unknown → low    → gray
```

补充：

- `confidence < 0.6` 必须为 unknown/low/gray；
- parse failed/fallback 不得 qc_usable；
- 高危必须通过现行后端复合门槛；
- 维度固定集合缺失不得 qc_usable；
- 非法组合不能只记录 warning 后继续替代旧结果。

### C1.1 固定实现落点

契约校验必须落在 `app.services.dify_schema_parser._post_process_result` 的解析后处理阶段，并在任何 writer/mapper 和 `qc_usable` 判定之前完成：

1. status 归一；
2. confidence 门槛；
3. status/severity/alert_level 三元组校验；
4. 按 `audit_type_code` 校验该类型的预期维度 code 集合，不能用一套全局维度集合；
5. 生成明确的 `contract_valid`、`contract_errors` 或等价受控结果；
6. contract invalid 时 parse 不可用，禁止 save/supersede；
7. `qc_status_semantics.is_qc_usable` 必须把 contract validity 纳入判断，不能继续只看 transport + parse。

当前代码没有上述完整校验，日志 138724 的 `unknown|medium` 可穿透 parser、mapper、writer 并成为 qc_usable；该事实是生产重推前置阻断。

### C2. 处理策略

1. Dify 原始响应永不改写。
2. 在解析完成、落库前执行 schema validation。
3. 可确定归一化的枚举在结构化对象中修正，并记录 reason code。
4. 无法确定的组合标记 schema validation failed。
5. 历史非法组合先统计、再生成精确 ID dry-run；不得宽泛 UPDATE。

### C3. 测试

- `unknown|medium` 被拒绝或确定性转换；
- fallback 不覆盖旧结果；
- 固定维度缺失不覆盖；
- 合法 medium 使用 warn/medium/yellow；
- 合法 unknown 使用 unknown/low/gray；
- 原始 response_json 不变。

## 8. 工作包 D：病程护理历史只读 preview

### D1. 范围

首轮只处理：

```text
audit_type_code=progress_vs_nursing
date_from=2026-01-01
date_to=2026-07-29
date_dimension=record_create_date
audit_run_mode=daily_increment
alert_policy=suppress
allow_rectified=false
```

必须改为按自然日分片的 preview API/服务调用，不允许单个 HTTP 请求一次加载七个月正文。创建批次只能消费已冻结、仍在有效期内的 preview manifest，不能再次完整扫描 210 天。

每个日期分片必须有独立状态：

```text
pending | loading | completed | load_failed
```

任一日期/类型 `load_failed` 时：

- 写入受控错误类别和耗时；
- 不把该日期候选并入 candidate_hash；
- 整个 manifest 标记 incomplete；
- 禁止从 incomplete manifest 创建批次；
- 重新成功 preview 后才允许生成最终 candidate_hash。

### D2. 每日必须输出

- 业务库病程原始行数；
- 业务库护理原始行数；
- patient_id + visit_number 分组数；
- 双方均有文书的 bundle 数；
- 仅病程、仅护理、双方为空数；
- 可推送候选数；
- source_record_key 非空数、空值数、重复数；
- exact_match 数；
- legacy_resolvable 数；
- identity_ambiguous 数；
- rectified_suppressed 数；
- 已有当前 qc_usable 数；
- 缺失当前结果数；
- 预计 Dify 调用数；
- Oracle 错误与耗时。

对于 legacy `progress_vs_nursing`，主 SQL 的 INNER JOIN 只产生“同一分组下病程与护理双方均命中”的 bundle。`expected_bundle_count` 必须明确为“双侧均有且满足现有 SQL/日期口径的去重 bundle”，不能把单侧原始文书直接加入 expected 分母。单侧数据单独统计为诊断指标，不当作执行器可推送漏失。

### D3. 对账主键

优先：

```text
source_record_key + audit_type_code + audit_run_mode
```

业务辅助键：

```text
patient_id + visit_number + query_date + audit_type_code + audit_run_mode
```

不得使用未去重的 `success/bundles` 作为唯一覆盖率。

### D4. 性能门禁

- preview 默认只读；
- 避开 08:30–10:30、11:15–13:00；
- 不与历史重推同时运行；
- Oracle 超时立即停止当日后续类型；
- 不自动把加载异常解释为 0 候选。
- preview 与 batch create 不得重复执行同一全范围业务库查询。

## 9. 工作包 E：持久化历史重跑

### E0. P0 实现门禁

进入 canary 前必须先完成：

#### E0.1 legacy 空 key 防双当前

- preview 实现 `legacy_empty_key_current` 反查；
- 此类候选默认 identity_ambiguous；
- 明确批准的 legacy_resolvable 才能执行；
- 最终写入前再次检查；
- `success_no_previous` 仅允许在确认不存在任何同身份旧当前结果时出现。

#### E0.2 concurrent_changed 原子失败

`expected_previous_id` 不匹配时必须满足二选一，首选方案 A：

- A：回滚新 PushLog、维度、结论事务，仅在 execution/attempt/item 中记录 concurrent_changed；
- B：保留审计 PushLog，但必须在同一事务将其标记为非 qc_usable、非 current，且所有当前结果查询显式排除。

禁止保留 `status=success + parse_status=success + superseded_by=NULL` 的新记录。

#### E0.3 批次恢复和消费者单例

- 为 batch consumer 增加数据库级单例 claim/lease；
- 重启后只允许一个消费者接管同一 batch；
- 基于 item.updated_at + execution lease 识别 stale running；
- 只在确认原消费者租约过期后将 stale running item 重置为 pending；
- resume 支持可恢复的 running batch，但必须先完成恢复审计；
- 重复 resume/auto_start 不得启动第二消费者；
- 恢复动作记录操作者、时间、回收 item 数和原状态。

未完成 E0.1–E0.3 前，批次表“已建”不得表述为“具备可恢复执行能力”。

### E1. 必须使用

- `/api/push/historical-rerun/preview`
- `candidate_hash`
- `HistoricalRerunBatch`
- `HistoricalRerunItem`
- execution/attempt claim
- `previous_current_push_log_id`
- pause/resume/cancel/reconciliation

禁止继续以 Shell 循环普通 `/api/push/manual` 作为正式半年重跑方案。

### E2. Canary 参数

```text
类型：progress_vs_nursing
范围：单日
候选：最多 100
消费者：串行
existing_result_policy：replace_current
alert_policy：suppress
allow_rectified：false
```

当前历史批次执行器是串行实现，`parallel_workers` 对该路径不生效。首轮保持串行；未来若要并行，必须另做数据库 claim、Oracle/Dify 压测和消费者并发设计，不在本计划中直接开放。

### E3. 单条事务

1. claim execution；
2. 加载指定候选；
3. 事务外调用一个 Dify 节点；
4. 解析并跑契约校验；
5. 写入新 PushLog、维度、结论；
6. 校验旧当前 ID 未变化；
7. 建立 supersede；
8. 提交；
9. 只读回查；
10. 记录 attempt、target、耗时和原因。

补充硬门禁：

- claim 异常必须 fail-closed，记录批次失败，不得 `claim_error_fallback` 后继续 Dify；
- `force=True` 不得绕过另一个 owner 的未过期 in-flight lease；
- 跨普通定时、普通手推、手推覆盖、历史批次必须共享同一业务身份互斥层；
- `source_version` 可保留作审计字段，但不能使同一业务身份的 in-flight claim 相互不可见；
- `concurrent_changed` 和 legacy 空 key 冲突不得留下第二个当前结果。

### E4. 告警

- 默认 suppress；
- 不重发历史企微/H5；
- 不修改旧 success/sent；
- `dept_filtered` 不是发送成功；
- 本计划不启用 `new_high_only`。

## 10. 工作包 F：定时漏推对账

### F1. 漏斗

每次日常和出院任务必须形成：

```text
raw_rows
→ grouped_bundles
→ precheck_pushable
→ skipped_by_reason
→ Dify attempted
→ transport_success
→ parse_success
→ qc_usable
→ current_result
```

### F2. 跳过原因

至少分开：

- unreviewed_pending
- rectified_suppressed
- empty_progress_nursing
- empty_both_sides
- already_succeeded
- identity_ambiguous
- concurrent_changed
- cancelled

### F3. 加载失败

ORA-12609 或其他业务库加载异常必须：

- SchedulerHistory 记录 type-level failed；
- 保留错误类别、耗时、query_date、run_mode；
- 创建只读待补跑清单；
- 不把 `total=0` 当作真实无候选；
- 不自动与下一轮宽泛合并。

当前 SchedulerHistory 缺少 `error_msg` 和 `audit_run_mode`。实施上述要求必须同步：

- ORM 增加两个字段；
- SQLite/Oracle 手工迁移；
- `_verify_required_schema()` 增加必需列；
- 写历史服务填充受控错误摘要，不写患者信息或连接密钥；
- API/页面兼容历史 NULL；
- Oracle 查询、导出和聚合回归。

### F4. 模式对账

`daily_increment` 与 `discharge_final` 分开统计：

- daily：记录创建日期；
- discharge：出院日期，对该次住院加载完整文书；
- 不简单相加两个模式的成功数；
- 不允许跨模式误 supersede，除现有明确终末覆盖规则。

## 11. 工作包 G：生产发布

### G1. 发布前

- 保存 git status/diff/HEAD；
- 不清理既有工作区改动；
- 对容器内关键 Python/HTML/CSS 与拟发布仓库文件逐文件计算 SHA-256，区分生产热更新代码与本地未部署代码；
- 备份镜像 ID、config、`.env` 和应用库相关行；
- 确认 SECRET_KEY 备份；
- 记录两个历史脚本和日志 SHA-256；
- 确认无历史任务、定时任务占用相同范围。
- 生产只读按月统计当前 qc_usable 结果中 `source_record_key` 为空/非空的数量，并按 audit_type/run_mode 分组，量化 legacy P0 暴露面；
- 上线前运行双当前识别查询，基线化 `success_no_previous`、concurrent_changed 和同患者/访次/类型/模式多当前结果。

### G2. 发布顺序

1. 详情页滚动修复；
2. P0 legacy 空 key 防双当前；
3. P0 concurrent_changed 原子失败；
4. P0 批次恢复与消费者单例；
5. 结果契约校验；
6. claim fail-closed 与跨入口 in-flight 互斥；
7. 分片 preview/load_failed manifest；
8. SchedulerHistory 字段迁移；
9. 单日 100 条病程护理串行 canary；
10. supersede 与业务页面验收；
11. 观察一次 daily；
12. 观察一次 discharge；
13. 按日扩展；
14. 病程护理完成后才评估其他五类。

### G3. 回归命令

```powershell
python -m compileall app tests scripts
python scripts/check_naming_convention.py
python -m pytest tests/test_push_executor.py -q
python -m pytest tests/test_historical_rerun_batch.py -q
python -m pytest tests/test_historical_rerun_replacement.py -q
python -m pytest tests/test_manual_replace_current.py -q
python -m pytest tests/test_push_idempotency.py -q
python -m pytest tests/test_push_frontend_static.py -q
python -m pytest
```

必须补充真实浏览器测试，不能仅用静态字符串断言替代滚动验收。

新增强制失败测试：

1. `unknown|medium` 被拒绝或归一；
2. `confidence < 0.6` 强制 unknown/low/gray；
3. 非法组合和固定维度缺失均不 qc_usable、不 supersede；
4. 空 key 旧当前 + 新成功不产生双当前；
5. concurrent_changed 保持旧当前且新结果不进入当前视图；
6. stale running item 在租约过期后可恢复；
7. running batch 可安全 resume；
8. 重复 resume/auto_start 只启动一个消费者；
9. preview 加载异常产生 load_failed，manifest incomplete 且不可创建批次；
10. claim 异常 fail-closed；
11. force 不能绕过有效 in-flight；
12. 普通定时、手推覆盖、历史批次不能对同一身份并发双调 Dify；
13. 真实浏览器多分辨率、五标签、JSON 局部滚动和打印回归。

## 12. 验收指标

### 12.1 历史重推

- preview 候选哈希与执行哈希一致；
- preview manifest complete，load_failed=0；
- 100 条 canary 无重复 Dify 调用；
- 每个 qc_usable 新结果只有一个业务当前版本；
- 旧结果 superseded_by 指向新结果；
- 失败项旧结果保持当前；
- identity_ambiguous 未被覆盖；
- 告警新增数为 0；
- 结果契约非法组合新增数为 0。
- `success_no_previous` 中不存在 legacy 空 key 旧当前；
- concurrent_changed 新结果当前可见数为 0；
- stale running item 为 0；
- 同一 batch 活跃消费者不超过 1。

### 12.2 文书覆盖

按日输出：

```text
expected_bundle_count
current_qc_usable_count
missing_count
identity_ambiguous_count
load_failed_count
```

只有满足以下条件才可标记当天完成：

- 业务库加载成功；
- 双方文书候选已去重；
- 所有候选均落在 success、业务合理 skip、identity_ambiguous 或明确 failed 待重试中；
- 没有无法解释的数量差；
- failed 已形成精确重试清单。

### 12.3 页面

- 日志 138724 五个标签可滚动到底；
- 桌面和移动端均正常；
- 主应用滚动无回归；
- JSON 局部滚动正常；
- 打印输出完整。

## 13. 回滚

### 13.1 页面

回滚静态文件或镜像，不涉及数据库。

### 13.2 历史重推

- 失败结果不需回滚旧当前状态；
- 已成功替代结果不得直接删除；
- 恢复 supersede 必须基于同一 run_id 的 before 快照和精确 ID；
- 回滚仍需书面批准；
- 不修改旧告警、反馈和 Dify 原始响应。
- 上线前必须提供“双当前识别查询”，覆盖 legacy 空 key、success_no_previous 和 concurrent_changed；
- 发现双当前立即停止后续批次，不得用宽 UPDATE 修复；
- concurrent_changed 首选事务回滚新业务结果，仅保留 execution/attempt/item 审计；
- 已经形成的 success_no_previous 需按精确 ID 生成 before/after 处置清单并另行批准。

### 13.3 `execute_retry` legacy 例外

当前 `PushExecutor.execute_retry` 会就地改写原 PushLog 的 `response_json`。这与“Dify 原始响应永不改写”冲突。生产历史整改前必须二选一：

1. 改为创建新的 PushLog，并使用安全替代链；或
2. 书面声明该入口为受限 legacy 例外，禁止用于历史批量整改，并记录调用审计。

本计划推荐方案 1；在完成前，历史重推不得调用 `execute_retry`。

### 13.4 契约整改

- 新校验器异常时回滚代码；
- 已落库历史非法组合不自动批改；
- 任何历史改级按精确 ID、小批事务和 before/after 快照处理。

## 14. 停止点与批准

### 停止点 1

独立 AI 已完成首轮复核并给出有条件通过。本地已确认三个 P0。P0 修复设计、失败测试和迁移影响未复核通过前，不得进入生产 canary。

### 停止点 2

用户批准收口临时任务和阻止 H1 自动启动。

### 停止点 3

页面修复可独立部署。历史重推相关部署必须同时满足：P0-1/2/3、契约校验、claim fail-closed、跨入口互斥和分片 preview 测试通过，用户批准生产部署。

### 停止点 4

病程护理 1–7 月 preview 完成，用户批准精确候选哈希和单日 canary。

### 停止点 5

Canary 对账通过，用户逐批批准扩展日期。

## 15. 给外部 AI 的独立复核提示词

```text
你是 Med-Audit 医疗病历 AI 一致性质控系统的独立复核 AI。请只做代码、配置、数据库聚合和日志的只读复核，
不要修改生产、不要调用 Dify、不要启动/停止调度、不要发送告警、不要删除或覆盖任何历史记录。

仓库：F:\python\前后端代码\ai_mrzk
生产：10.10.8.84:8000，容器 med-audit，Oracle 应用库/业务库，Dify 5 节点。

开始前必须完整阅读：
1. AGENTS.md
2. docs/INDEX.md
3. docs/reference/101_FEATURE_BASELINE.md
4. docs/skills/med-audit-codex.md
5. docs/ACTIVE/002_PUSHLOG_IDEMPOTENCY_DESIGN_GATE.md
6. docs/ACTIVE/007_HISTORICAL_MANUAL_RERUN_AND_CURRENT_RESULT_PLAN_20260728.md
7. docs/ACTIVE/008_PROGRESS_NURSING_HISTORICAL_RERUN_AND_LOG_DETAIL_REMEDIATION_PLAN_20260729.md
8. .agents/skills/med-audit-history-remediation/SKILL.md
9. 该技能引用的 database-remediation-contract.md 和 connection-runbook.md

安全边界：
- 不输出姓名、患者号、住院号、身份证、手机号、病历正文、request_json、response_json 或密钥。
- 不把密码写入命令行、脚本、日志或报告。
- 不读取或外发完整 mr_text/mr_txt。
- 所有生产查询只输出聚合数和脱敏错误分类。
- 不以本地 SQLite 代替生产 Oracle 结论。
- 不清理、覆盖或回滚工作区已有改动。

请独立验证以下问题：

A. 历史重推能力
1. replace_current 是否确实绕过 unreviewed_pending。
2. 新结果失败、fallback、parse failed、维度不完整或枚举非法时是否会覆盖旧结果。
3. mark_historical_reaudit_superseded 的身份键和并发校验是否充分。
4. 空 source_record_key 历史记录是否会造成新结果成功但旧结果未 supersede。
5. HistoricalRerunBatch/Item、execution/attempt 是否真正接入生产执行，而不只是建表。
6. 当前 /tmp/july_remain_push.sh 和 /tmp/h1_replace_push.sh 是否绕过持久化批次。
7. 主机/容器重启后临时任务是否可恢复，是否可能重复调用 Dify。
8. 空 key 旧当前是否被 preview 误判并形成 success_no_previous 双当前。
9. concurrent_changed 是否仍提交可见 success 新结果。
10. stale running item、running batch resume 和消费者单例是否已真正实现。

B. 病程护理文书覆盖
1. 对 progress_vs_nursing 按 2026-01-01 至 2026-07-29、record_create_date 逐日只读加载。
2. 统计病程原始行、护理原始行、双方 bundle、单侧 bundle、空 bundle。
3. 按 source_record_key + audit_type + run_mode 去重。
4. 对空 source_record_key 单列，不能猜测匹配。
5. 将去重 bundle 与当前 qc_usable PushLog 对账，输出 missing、failed、skip、ambiguous。
6. 不使用未去重 success/bundles 作为覆盖率。
7. 若 ORA-12609，记录为 load_failed，不解释为 0 候选。

C. 定时任务
1. 核对 scheduler_daily 和 scheduler_discharge 的实际生产配置。
2. 核对 SchedulerHistory 最近 14 天的类型级 completed/failed。
3. 重点检查 progress_vs_nursing、syssvsscbc 的 total=0 日期。
4. 核对 daily_increment 与 discharge_final SQL转换、日期语义和覆盖关系。
5. 核查临时半年重跑是否与 09:00/11:44 调度争用 Oracle 和 Dify。

D. 结果契约
1. 复核日志 ID 138724，但不得输出患者标识或病历正文。
2. 确认是否存在 unknown|medium。
3. 对生产全库聚合非法 status/severity/alert_level 组合。
4. 核对 parser、mapper、writer 是否在 qc_usable 前强制契约。
5. 核对 Dify 原始响应是否保持不可变。
6. 给出最小修复点和失败测试，不要自动改历史等级。

E. 日志详情页
1. 核对生产 static/log_detail.html、styles/app.css、styles/pages/log_detail.css。
2. 验证桌面端 #app height:100vh + overflow:hidden 是否导致独立页面被裁剪。
3. 评估 scoped body class 修复是否会影响主应用。
4. 给出 Chrome/Edge、桌面/移动、标签切换、内部 JSON 滚动和打印验收矩阵。

F. 并发与资源
1. 评估长日期逐日加载、5 Dify 节点、临时任务与定时窗口重叠的风险，区分业务库加载串行度与 Dify 并发度。
2. 判断持久批次串行、单日最多 100 条是否合理。
3. 核对 execution claim、scheduler lock 和 historical batch 是否能阻止重复执行。
4. 核对 claim 异常是否 fail-closed、force 是否仍绕过有效租约、source_version 是否分裂跨入口互斥。

交付格式：
1. 先给结论：确认、部分确认、否定、无法验证。
2. 每项结论必须引用具体文件、函数、配置路径或生产聚合证据。
3. 单列“计划中的错误假设或遗漏”。
4. 单列 P0/P1/P2 整改项。
5. 给出分阶段执行顺序、停止点、验收指标和回滚方法。
6. 明确列出本次是否发生生产写入、Dify 调用、调度操作或告警发送。
7. 不要执行整改；复核完成后停止，等待人工批准。
```

## 16. 当前裁定

病程护理历史重推需求在设计方向上可实施，但当前代码不满足生产执行条件。正确路径是：

1. 先安全收口当前临时任务；
2. 修复三个 P0：legacy 空 key 双当前、concurrent_changed 双当前、批次恢复/消费者单例；
3. 修复结果契约、claim fail-open、force 租约绕过和跨入口互斥；
4. 将 preview 改为按日分片、显式 load_failed、complete manifest；
5. 修复详情页滚动；
6. 以实际 Oracle 双侧同日去重 bundle 为可推送分母逐日对账；
7. 对 exact_match 自动替代，对 legacy_resolvable 经批准处理，对 identity_ambiguous 保持人工；
8. 单日最多 100 条、串行 canary；
9. 双当前=0、告警新增=0、非法组合新增=0 后逐批扩展。

在独立复核和书面批准完成前，本计划不得解释为生产补跑、停任务、数据库修改或部署授权。


## 17. 本地开发实施记录（2026-07-29）

> 状态：全部 P0/P1/P2 本地开发完成，全量测试通过。禁止未批准生产部署。

### 已完成工作包

| 工作包 | 状态 | 关键文件 | 测试 |
| --- | --- | --- | --- |
| P0-1 legacy 空 key 防双当前 | 已完成 | pp/services/historical_rerun_service.py (_find_legacy_empty_key_current, preview 分类, write-before guard) | 	est_008_remediation.py::TestLegacyEmptyKeyGuard |
| P0-2 concurrent_changed 不产生第二当前 | 已完成 | pp/services/historical_rerun_service.py (自标记 superseded_by=log.id) | 	est_008_remediation.py::TestConcurrentChanged |
| P0-3 持久批次恢复与消费者单例 | 已完成 | pp/services/historical_rerun_service.py (consumer lease, 
ecover_stale_running_items, _active_consumers) | 	est_008_remediation.py::TestBatchRecovery |
| P1-4 结果契约校验 | 已完成 | pp/services/result_contract_validator.py, pp/services/dify_schema_parser.py, pp/services/qc_status_semantics.py | 	est_008_remediation.py::TestContractValidation |
| P1-5 claim fail-closed 与跨入口互斥 | 已完成 | pp/services/push_idempotency.py (source_version 不参与 key, force 不绕过 in-flight), push_executor.py, ulk_push_executor.py | 	est_008_remediation.py::TestClaimFailClosed, 	est_push_idempotency.py |
| P1-6 按日分片 preview/load_failed | 已完成 | pp/services/historical_rerun_service.py (load_failed 计数, stats bucket) | 	est_008_remediation.py::TestPreviewLoadFailed |
| P1-7 SchedulerHistory 可诊断字段 | 已完成 | pp/models.py, pp/database.py, pp/services/scheduler_history_service.py | 	est_008_remediation.py::TestSchedulerHistoryFields |
| P1-8 日志详情页桌面滚动修复 | 已完成 | static/log_detail.html (body.log-detail-page 作用域 CSS) | 	est_008_remediation.py::TestLogDetailScroll |
| P2-9 execute_retry 原始响应审计 | 已完成 | pp/services/push_executor.py (新 PushLog + supersede 链) | 	est_008_remediation.py::TestExecuteRetry |
| P2-10 双当前诊断 | 已完成 | pp/services/dual_current_diagnostics.py | 	est_008_remediation.py::TestDualCurrentDiagnostics |

### ORM / 迁移

- SchedulerHistory: 新增 udit_run_mode (String(32)), rror_msg (Text)
- HistoricalRerunBatch: 新增 consumer_owner (String(64)), consumer_lease_until (DateTime), consumer_heartbeat_at (DateTime)
- SQLite: _migrate_scheduler_history_columns() 已扩展
- Oracle: _migrate_oracle_alert_columns() 已扩展 MED_SCHEDULER_HISTORY 和 MED_HISTORICAL_RERUN_BATCH
- _verify_required_schema() 已同步更新

### 回归测试

`
python -m compileall app tests scripts  # PASS
python scripts/check_naming_convention.py  # PASS
python -m pytest  # 全量 PASS (exit code 0)
`

### 生产发布前置条件

1. 人工复核本实施记录并书面批准
2. 生产 Oracle 应用库执行 DDL（新字段）
3. 容器镜像重建并部署
4. 双当前诊断 ull_reconciliation_report() 确认 multi_current_identity_groups=0
5. 单日 canary 最多 100 条，串行执行
6. 告警新增=0、非法组合新增=0 后逐批扩展

### 回滚方法

- 代码回滚：git revert 本次变更或回退到 HEAD dac6c144
- 数据库回滚：新字段为 nullable/default，不影响旧代码运行
- 批次回滚：cancel batch + 手动清理 running items

### 声明

本次实施：
- 未连接生产服务器
- 未调用真实 Dify
- 未发送告警
- 未修改生产配置或数据库
- 未停止任何现有脚本
