# Dify 质控提示词修订详细计划（独立复核修订版）

> 状态：方案已复核修订，禁止直接上线；待临床口径、配置命名和灰度方案确认
> 建立日期：2026-07-13
> 最近修订：2026-07-13 — 撤销 legacy 类型豁免，改为双通道高危、问题与风险解耦、确定性结构转换及分阶段灰度。
> 配套文档：`109_DIFY_ADMISSION_FIRST_PROGRESS_REVIEW.md`、`110_DIFY_PROMPT_AUDIT_AND_REVISION_PLAN.md`、`112_DIFY_PROMPT_DRAFT_V1.md`。
> 本文只定义后续实施方案；本次不修改代码、配置、测试或 Dify 工作流。

## 0. 上线边界

原方案“统一提示词 + 后端守门”的方向保留，但以下设计不得继续实施：

1. 不得把所有不合格 high 一律改成 `unknown/gray`；明确成立但不够高危的问题应保留为 `warn/medium`。
2. 不得按 `audit_type_code` 永久豁免 `progress_vs_nursing`。新版 JSON 会走 `_parse_new_schema`，不会触发旧 schema 的 `confidence=0`。
3. 不得只凭维度级两个 evidence 数组放行 high；必须校验同一个 issue 的等级、资格、来源和证据。
4. 不得把手术记录证据伪装成术前或术后记录。
5. 不得让 JSON fallback、bulk 兼容回退或结论级兜底绕过高危门槛。
6. 不得让模型自行定义危急值或危急影像标准。

上线必须依次经过“口径冻结、提示词与后端影子验证、有限灰度、告警灰度”。

## 1. 修订后的设计决策

| # | 决策 | 修订后口径 |
| --- | --- | --- |
| D1 | 节点分工 | 节点一由 LLM 提取受控事实；节点二优先改为确定性 Code/JSON Schema 转换。若暂时保留第二个 LLM，仍必须经过 Code 节点终检。 |
| D2 | 问题与风险解耦 | `issue_mode` 判断问题类型，`level` 判断严重程度，`high_eligible` 只表示高危资格。高危资格不满足不等于问题不存在。 |
| D3 | 双通道高危 | 分为“直接矛盾型”和“危急结果未响应型”。前者要求不同来源的双侧直接证据；后者要求机构规则命中、完整时间窗和程序化未响应检查。 |
| D4 | 不按类型豁免 | 所有新 schema 类型执行相同守门；旧 schema 按实际解析路径兼容，旧 schema high 默认不触发即时告警。 |
| D5 | 真实证据来源 | 暂继续输出 `medical_evidence`/`nursing_evidence` 兼容解析器，同时在 `extra.issues[]` 保存真实 source、文书 ID、时间和引文；禁止伪造 source。 |
| D6 | 人工复核闭环 | manual review 不等于 inconsistency，也不触发高危，但必须有独立标记、数量、队列状态和关闭记录。 |
| D7 | code/config 先决条件 | 无活配置或命名未确认的类型只能保留方案，不得部署。输出 code 必须与调用方 code 一致。 |
| D8 | 失败安全 | 解析失败、fallback、schema/code 缺失时，最高只能为 `low/gray/manual_review` 或技术失败，绝不能触发外部高危告警。 |

### 1.1 类型映射

| 业务 | 当前 code | 当前状态 | 处理 |
| --- | --- | --- | --- |
| 首次病程 vs 出院记录 | `discharge_vs_frontpage` | 无活配置且名称不准确 | 建议改为 `discharge_vs_first_progress`；建立兼容映射前不得启用 |
| 围手术期 | `surgery_chain` | 无活配置 | 完成三来源 payload/config 验证后才能影子运行 |
| 病程 vs 护理 | `progress_vs_nursing` | 活配置 | 首轮保留 6 维度；取消后端豁免 |
| 检验检查 vs 病程护理 | `jyjc_vs_bcnursing` | 活配置 | 接入本院危急规则后才允许 omission high |
| 首页手术 vs 术后首次病程 | `syssvsscbc` | 活配置，命名不透明 | 首轮兼容旧 code，另行迁移语义化 code |

## 2. 临床判定模型

### 2.1 问题类型

- `contradiction`：不同文书对同一事项、相容时间窗给出不可调和的相反信息。
- `omission`：已有明确触发信息，但规定文书或时间窗内缺少必须记录的响应；不得用虚构引文证明“未记录”。
- `timeline`：事件时间明确倒置，且不能由补记或签署延迟解释。
- `text_quality`：模板、重复、错字、格式或表述问题。

### 2.2 矛盾型高危门槛

同一个 issue 必须同时满足：

1. `issue_mode="contradiction"`、`level="severe"`、`high_eligible=true`。
2. `status="fail"`、`confidence>=0.8`。
3. 至少两条直接引文来自不同真实 source，且均非空。
4. 证据针对同一患者、住院次、事项和可比较时间窗，并构成不可调和矛盾。
5. `safety_category` 属于：`patient_identity`、`allergy_medication`、`wrong_site_or_side`、`wrong_procedure_or_implant`、`critical_diagnosis_basis`、`current_vital_or_life_support`。
6. 不属于详略差异、同义/上下位表达、一般遗漏或纯文本质量问题。

### 2.3 危急结果未响应型高危门槛

仅适用于已经接入机构规则的类型：

1. `issue_mode="omission"`、`level="severe"`、`high_eligible=true`。
2. 输入含系统提供的 `critical_rule_match`：本院规则 code、项目/结果/单位、结果时间和适用人群。
3. 输入含程序计算的 `absence_check`，且 `coverage_complete=true`、响应窗已结束、规定来源中未找到通知/评估/处置/复查记录。
4. `confidence>=0.8`；模型不得自行把普通异常提升为危急结果。
5. 规则和时限已经本院检验、影像及临床专家批准。

缺少系统规则或完整时间窗时，只能 general/manual review，严禁 high。

### 2.4 非 high 的处理

| 情形 | 处理 |
| --- | --- |
| 问题明确，只是不满足 high | 保留 `warn/medium/yellow`，不得改 unknown |
| 纯文本质量问题 | `warn/low/blue` |
| 问题本身无法确认或证据/时间窗不足 | `unknown/low/gray`、`confidence<=0.59`，进入 manual review |
| JSON/schema/code 解析失败 | 技术失败或 `unknown/gray`，禁止告警 |

纯模板或错字不得 high；若内容实际造成错患者、错侧、错药、错剂量或错术式，应归入相应安全维度重新判断。

## 3. 后端实施方案（后续任务，本次不执行）

### 3.1 先影子判定

先新增纯函数计算守门结果，只写影子日志/字段，不覆盖生产严重度、不触发告警。完成临床抽检后才能切换。

### 3.2 以 issue 为单位守门

1. 遍历 `extra.issues[]`，校验 `issue_mode/level/high_eligible/safety_category/confidence`。
2. 校验同一 issue 的真实来源，禁止相同引文或占位词凑双侧证据。
3. omission high 只接受系统产生的 `critical_rule_match` 和 `absence_check`。
4. 至少一个 issue 完整通过，维度 high 才能保留；不得跨 issue 拼接证据。

### 3.3 取消类型豁免

- 新 schema：所有类型执行相同守门。
- 旧 schema：按解析路径识别；因缺少可靠 confidence/high_eligible，最高进入人工复核，不即时告警。
- `_canonicalize_admission_dimension_code` 仍仅用于 admission，避免污染其他类型编码。

### 3.4 降级与汇总

- 明确问题：`fail/high` 降为 `warn/medium/yellow`，保留问题与证据，写 `high_risk_rejected_reason`。
- 不确定问题：降为 `unknown/low/gray`，设置 `confidence=min(original, 0.59)`，写入 manual review。
- 汇总必须从守门后的维度重新计算。

### 3.5 关闭绕过路径

1. fallback 不得生成 high；parse_failed 不得触发 `__conclusion__` 高危告警。
2. bulk 兼容回退不得用空 audit type 跳过守门；移除回退或用真实 code 再后处理。
3. code 缺失/错配时禁止 high。
4. 运行时校验维度白名单、数量和唯一性。

### 3.6 manual review 闭环

新增或透传 `needs_manual_review`、`manual_review_count`、`manual_review_reasons`。日志、反馈、patient_qc 必须展示真实来源和证据，并支持筛选、认领、结论和关闭。

## 4. 五类提示词修订要点

### 4.1 首次病程 vs 出院记录

- 首轮保留原 9 维度。
- 倒填、新增诊断依据、诊疗经过完整性属于 omission，不强制虚构第二侧引文。
- 仅凭两份文书无法确认“倒填”时进入 manual review。
- code/config 完成前不得启用。

### 4.2 surgery_chain

- source 必须含 `preop_record`、`operation_record`、`postop_record`。
- 术前记录在术前写“拟行手术”是正常内容；只有其出现在术后文书，或术前文书签署时间明确晚于手术完成时间，才可能判模板问题。
- 术后完整性属 omission，一般不得 high。
- 麻醉、植入物/材料、关键步骤是否拆维度留待临床确认，避免一次扩大回归面。

### 4.3 progress_vs_nursing

- 首轮保持固定 6 维度。
- “同一天即可”改为同一事件或可比较时间窗；同日状态变化不得判冲突。
- 单方提及通常 pass；只有确有复核价值且无法确认时才 manual review。
- 不再后端豁免。

### 4.4 jyjc_vs_bcnursing

- source 拆为 `lab_exam_report`、`progress_record`、`nursing_record`。
- 普通异常关注不足与危急结果未响应分开。
- `high_risk_response_consistency` 只承载本院规则命中的危急结果，避免重复告警。
- 护理未提及结果不作为问题；只有明确记录相反事实时才作为冲突证据。

### 4.5 syssvsscbc

- 首轮保留 4 维度。
- `diagnosis_operation_match` 若依赖外部医学知识，最多 manual review；只有两份来源直接冲突才输出明确问题。
- 信息缺失、MRID 为空、未写指征或病理不判 warn/fail。

## 5. 技术债分级

| 债项 | 结论 |
| --- | --- |
| T1 ADR-2 与证据方案冲突 | 上线前必做 |
| T2 logs/feedback 专属证据展示 | 上线前必做 |
| T3 patient_qc 不输出 extra | 上线前必做 |
| T4 两个类型 config 缺失 | 启用相应类型前必做 |
| T5 code 命名漂移 | 上线前完成正式决策和兼容映射 |
| T6 builder 重复 sort | 非阻断，单独修复 |
| 新 T7 fallback 可生成高危 | 上线前必做 |
| 新 T8 运行时白名单/唯一性缺失 | 上线前必做 |
| 新 T9 manual review 无队列 | 上线前必做 |
| 新 T10 response JSONPath 仍指向旧根字段 | 上线前按 `$.audit_summary.*` 和 `has_inconsistency` 统一校正并测试 |

## 6. 回归与临床验证

自动化必须覆盖：新 schema progress confidence 保留；旧 schema 不告警；明确 general 被误标 high 时降 medium；真正不确定才降 unknown 且 confidence<=0.59；surgery 三 source；禁止跨 issue 拼证据；jyjc 无机构规则/完整时间窗不得 high；fallback、空 code、bulk 回退均不得 high；维度白名单/唯一性；manual review 完整闭环。

每类型匿名样本至少覆盖：真实双侧高危、一般冲突、单侧提及、同义/合理演变、时间窗不可比、文本质量、人工复核。jyjc 另含危急规则命中后已响应、未响应、响应窗未结束三类。所有 high 样本需由对应专业临床专家确认。

正式启用前必须满足：无证据/伪双侧 high=0；warn→high=0；fallback high=0；所有 high 页面证据可见；人工抽检未发现关键安全风险系统性漏报。观察周期和最低样本量由项目负责人、临床与运维共同确认。

## 7. 分阶段实施与回滚

1. **口径冻结**：确认危急规则、source、code、维度白名单和闭环时限，不改生产。
2. **影子运行**：新提示词与新守门只保存影子结果，不影响告警。
3. **单类型有限灰度**：新结果落库但高危告警关闭，由质控人员抽检；无活配置类型不得首轮灰度。
4. **告警灰度**：先只开放通过全部门槛的 contradiction high；omission high 等机构规则和程序化 absence check 上线后再启用。

出现无证据 high、fallback 告警、source 错配、证据不可见、临床安全风险系统性漏判或 manual review 丢失时立即回滚工作流版本并关闭新告警。影子结果保留用于追溯，不做删除。

## 8. 待确认事项

1. 本院危急检验/影像规则及响应时限。
2. 临床响应时间与行政关闭时间是否拆分。
3. `discharge_vs_first_progress` 最终 code 与兼容策略。
4. `syssvsscbc` 的语义化新 code。
5. 围手术期麻醉、植入物、关键步骤是否在第二阶段拆维度。
6. manual review 的责任角色、时限和关闭条件。
