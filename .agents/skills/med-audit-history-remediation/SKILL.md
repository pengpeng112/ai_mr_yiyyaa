---
name: med-audit-history-remediation
description: 安全核查 Med-Audit 历史高危质控结果，并通过脱敏离线包引入外部 AI 复核；经人工批准后分批降级不符合高危硬门槛的记录，同时按 patient_id + visit_number（业务视图“患者ID”+“次数”）补齐缺失的在院/出院科室信息。适用于生产服务器、Oracle 应用库、JHEMR.V_QYBR 业务视图、PushLog/AuditDimensionResult/AuditConclusion 历史整改。涉及历史高危、红色告警、科室回填、生产数据库修订、外部 AI 复核时必须使用。
---

# 历史高危与科室数据安全整改

## 1. 目标与强制边界

本技能只处理两类任务：

1. 复核历史 `high/red` 质控结果，把不满足现行高危硬门槛的结果降为经批准的非高危等级。
2. 对历史记录中缺失的在院科室、出院科室信息，按同一次就诊的复合键精确回填。

必须遵守：

- 外部 AI 只能处理脱敏、最小化的离线复核包；严禁上传姓名、患者号、住院号、身份证号、手机号、原始病历、完整 `mr_text/mr_txt`、`request_json` 或 `response_json`。
- 外部 AI 的意见不是数据库写入授权。它只能生成候选决定，必须经过本地规则校验和院方临床/质控授权。
- 禁止执行无条件的 `UPDATE ... SET severity='low'`、按颜色批量改级、按关键词批量降级。
- 禁止仅按 `patient_id` 回填。用户口中的 `visit_id` 在本系统必须核实并映射为 `PushLog.visit_number`，对应 `JHEMR.V_QYBR."次数"`。
- 禁止覆盖非空且相互冲突的科室字段；冲突进入人工清单。
- 禁止删除已发送的企微/H5 告警历史或修改原始 Dify 响应。历史发送事实必须保留。
- 禁止在生产容器中直接访问公网 AI。
- 所有写入必须先备份、dry-run、生成精确清单、取得书面批准，然后小批量事务执行并可回滚。

本任务的字段口径已经代码核实并冻结：

- 本系统没有独立 ORM 字段 `visit_id`。
- 用户所称 `visit_id` 在本任务中只允许解释为 `PushLog.visit_number`（住院次数）。
- 业务视图连接键固定为 `PushLog.patient_id + PushLog.visit_number` 对应 `JHEMR.V_QYBR."患者ID" + "次数"`。
- 如果来源文件或外部系统中的 `visit_id` 无法证明等于该住院次数，必须停止该批回填，不得按名称猜测。
- 当前持久化目标是既有 `PushLog.dept` 和 `request_json.patient_info` 内的科室键；本技能不授权新增 ORM 列或数据库迁移。

开始前完整阅读：

- `AGENTS.md`
- `docs/INDEX.md`
- `docs/reference/101_FEATURE_BASELINE.md`
- `docs/skills/med-audit-codex.md`
- 当前 `docs/ACTIVE/` 中与安全、幂等、生产整改相关的计划
- 本技能的 [数据库整改契约](references/database-remediation-contract.md)
- 本技能的 [服务器与数据库操作手册](references/connection-runbook.md)
- 进入高危逐条复核前，必须阅读 [六类提示词路由与判定规则](references/prompt-routing-and-adjudication.md)，并按记录的 `audit_type_code` 只加载对应的技能内提示词快照。

## 2. 固定执行阶段与停止点

每次只能推进一个阶段。每一阶段完成后输出报告并停止，除非用户在同一条书面指令中明确批准了后续指定阶段。

### 阶段 0：本地与生产只读预检

1. 检查 `git status`，不得清理、覆盖或回滚他人改动。
2. 确认应用库类型、表前缀、容器、镜像、单 worker、健康状态和当前配置；不得打印密钥。
   - 容器不是 `healthy`、健康接口超时或 worker 数无法确认时，记录基线后停止；不得进入任何写入阶段。
3. 生产连接可用时，必须以生产容器内应用库的只读统计作为基线；本地 SQLite 只能验证 schema/脚本，不能替代生产结论。
   - 优先运行 `scripts/production_readonly_baseline.py`（技能目录内；拒绝 `--apply`）。
   - 默认输出：high 并集计数、按类型/解析/复核、告警 status、**证据路径盘点**、**形式门槛聚合**、`push_time`/`query_date` 范围。
   - 可选：`--include-semantic-shadow` 对 formally_qualified 再聚合并发 shadow 候选降级原因（仍只读）；`--skip-formal-gate` / `--skip-request-json` 用于慢库应急。
   - 可通过标准输入临时在容器执行，禁止借此把未批准代码持久化到生产镜像。
4. 只读统计历史高危数量、涉及时间范围、六类 `audit_type_code`、解析状态、复核状态和告警发送状态。
5. 高危候选集合取“PushLog 顶层 high/red”与“维度层 high/red”的并集，并分别统计，避免顶层聚合异常导致漏查。
6. **证据字段路径盘点（生产 2026-07 起强制）**：对 high/red 维度分别统计
   - `medical_evidence_json` / `nursing_evidence_json` 为空、但 `medical_content`/`nursing_content` 非空的比例；
   - `extra_json.issues[]` 是否含 `evidence_a`/`evidence_b`/`safety_category`/`high_eligible`；
   - 禁止只把 `*_evidence_json` 当“有无证据”的唯一来源（v2 落库会把 evidence 数组写成 `[]`，证据多在 content/extra）。
7. **双重门槛基线**：对候选 high 维度从库行还原 dim（content/extra 补证据）后跑现行 `_qualified_high_risk_issue`（只输出数量，不输出病历）。
   - 优先用基线脚本的 `formal_gate` 段；若需与历史 Dify 输出逐字对齐，可另批从**未改动**的 `response_json` 重解析核对，但不得把 response 原文外发。
   - `formally_qualified`：过后端复合门槛；
   - `formally_unqualified`：不过门槛（应优先进入待批准降级候选，绝不自动写库）；
   - **不得**把 `formally_qualified` 直接等同于“临床必须 keep_high”。
   - 可选对照 `app.services.high_risk_semantic_shadow.evaluate_semantic_high_risk_dim` 的 shadow 原因计数（生产 shadow 默认不改级；整改里仅作本地辅助，不可单独写库）。
8. 只读统计科室缺失位置：`PushLog.dept`、`request_json.patient_info` 内的在院/出院字段；不得假设存在独立 ORM 列。
9. 对 V_QYBR 的 `患者ID+次数` 做重复键统计。现有查询函数会按出院/入院日期取第一行，但批量整改不得把这一行为自动等同于业务唯一性。
10. Oracle 应用库按日筛选优先用 `push_time` 范围；`query_date` 绑日期时可能触发 ORA-01861，不得硬猜格式。基线报告同时给出 `push_time_min/max` 与 `query_date_min/max`。
11. 输出基线、拟处理范围、排除范围、风险和所需批准。此阶段不得修改数据库。

停止点：用户确认候选范围和脱敏方案。

### 阶段 1：生成高危复核包

1. 按 [六类提示词路由与判定规则](references/prompt-routing-and-adjudication.md) 校验 `audit_type_code`。没有匹配提示词、code 为空或 code 与文书来源不一致的记录不得交给 AI 自动判定，转人工复核。
2. 在内网生成本地映射清单：随机 `review_token -> push_log_id/dimension_id/conclusion_id`。映射清单不得离开内网。
3. **组装最小双方证据**时按优先级取字段（均需再脱敏，且截断到可判断该矛盾的最短片段）：
   1. `extra_json.issues[]` 中对应 issue 的 `evidence_a` / `evidence_b`（首选，结构化）；
   2. 否则 `medical_content` / `nursing_content`；
   3. 否则 `medical_evidence_json` / `nursing_evidence_json`（legacy 或已修复落库时）；
   4. **禁止**把完整 `response_json`/`mr_text` 打进外部包。
4. 生成外部复核包，仅包含：`review_token`、质控类型、维度编码、当前等级、置信度、已脱敏且足以判断该维度的最小双方证据片段、高危硬门槛布尔项、`safety_category`（若有）、解析状态、`formally_qualified`（本地重算）。不得只给脱离语境的模型摘要；若脱敏后证据不足以判断，则转内网人工复核。
5. 外部 AI 的系统指令必须附带对应类型的完整技能内提示词快照，不得只附统一高危五条件，也不得把六类提示词混在一个病例上下文中。
6. 证据摘要仍可能构成健康信息；使用既有脱敏器并进行人工抽检。无法可靠脱敏的记录禁止外发，改为内网人工复核。
7. 对文件计算 SHA-256，记录生成时间、查询条件、行数、脱敏版本和所用提示词文件 SHA-256。

停止点：用户批准该复核包可交给外部 AI。

### 阶段 2：校验外部 AI 返回结果

外部 AI 只允许返回以下决定：

- `keep_high`：维持高危。
- `downgrade_medium`：建议中危，仍需人工确认。
- `downgrade_low`：建议低危/正常，仍需人工确认。
- `manual_review`：证据不足、冲突或不确定。

每条返回还必须包含受控 `reason_code` 和简短说明。拒绝未知 token、重复 token、缺字段、自由文本等级、提高等级、修改证据或置信度的返回。

**本地二次裁决（强制，顺序固定）：**

1. 重新运行后端复合门槛（`_qualified_high_risk_issue` 同类逻辑；库行须先按契约还原证据字段）。  
   - **不满足硬门槛** → 不得 `keep_high`；进入降级候选（默认倾向 `downgrade_medium` 或 `unknown` 映射，最终等级仍须批准）。  
   - **满足硬门槛** → **仍不得自动 keep_high**；仅表示“技术上可高危”，必须再过提示词临床语义。
2. 本地确定性语义辅助（可选但推荐）：对 form 通过项调用 `evaluate_semantic_high_risk_dim`；`should_demote=true` 的不得因外部 AI 单独 keep_high，至少进 `manual_review` 或降级候选。
3. 用对应类型提示词规则做临床语义复核（见第 3 节与 `prompt-routing`）。重点拦截：
   - 详略/同义/上下位/合理时间演变被标 contradiction；
   - `safety_category` 与事实不符（例如一般时间差却标 `critical_diagnosis_basis`）；
   - 单侧未提及、缺文书、格式问题；
   - `dimension_code=other` 或白名单外 code。
4. 仅当 **后端门槛 +（shadow 未强制 demote）+ 提示词临床规则 + 外部 AI 建议 keep_high** 一致，才进入“可批准 keep_high 清单”；任一不一致进人工。
5. 生成“可批准 keep_high / 可批准降级 / 必须人工 / 拒绝”四张清单（相对旧三张，把 keep 与降级拆开）。

停止点：临床质控负责人批准精确的 token/ID、目标等级和理由代码。

### 阶段 3：高危整改 dry-run

1. 先制作应用库一致性备份和待修改行的 before 快照。
2. 为每条批准记录计算所有关联层的 before/after，不写库。
3. 维度层调整后重新聚合 `AuditConclusion` 和 `PushLog`；不得直接把顶层统一设为 low。  
   - 同步重算：`closure_hours` / `push_strategy` / `outcome_bucket` / `risk_score`（若列存在），避免 `low+red`、`pass+immediate`。
4. 若同一 PushLog 仍有任何**批准保留**的 high 维度，顶层必须保持 high/red。
5. 统计对告警的影响（按 `QCRecordAlertLog.status` 分类）：
   - `success`/`sent`：已发送事实不改、不删、不重发；
   - `pending`/`failed`：可单列“抑制待发”审批；
   - **`dept_filtered`**：表示科室白名单过滤，**不是发送成功**；降级后一般无需外发，也不得当作“应补发”。
6. 不得触发真实企微/H5/Dify 测试。

停止点：用户核对 dry-run 总数和逐条哈希清单，并书面批准写入批次。

### 阶段 4：分批执行高危整改

1. 仅执行批准清单，默认每批不超过 100 条维度记录。
2. 每批一个事务；写前再次校验原值与 before 快照一致，否则该条跳过并报告并发冲突。
3. 每批提交后只读回查关联维度、结论、PushLog 和告警状态。
4. 生成追加式审计文件：操作者、时间、run_id、批准单、记录 ID、before/after、理由代码、AI 建议、规则判定和事务结果。
5. 任一批出现数量不符、顶层聚合不符或异常，立即停止后续批次；不得吞异常。

停止点：用户确认高危整改结果后才可进入科室回填。

### 阶段 5：科室回填 dry-run 与执行

1. 复用 `app.utils.patient_dept_query.query_patient_dept()` 的业务语义。
2. 精确连接：`PushLog.patient_id = V_QYBR."患者ID"` 且 `PushLog.visit_number = V_QYBR."次数"`。
3. 回填规则见数据库整改契约。只补空值，不覆盖冲突值。
4. 先输出命中、无命中、多义、冲突、可更新数量；经批准后按小批事务执行。
5. 每批回查 `PushLog.dept` 与 `request_json.patient_info`，保留 JSON 其他字段原样。

停止点：用户确认回填和冲突清单。

### 阶段 6：验收与回滚演练

1. 对账处理前后 high/red、medium/yellow、low/blue、unknown/gray 数量。
2. 对账每个 PushLog 的顶层等级与维度最大有效等级。
3. 对账告警历史，确认没有重发、漏删历史或新建真实患者告警。
4. 对账科室字段完整率、无命中率、冲突率；抽样核对复合键。
5. 用 before 快照在隔离环境验证反向恢复脚本。生产是否回滚仍需单独批准。

## 3. 高危复核的确定性规则

不得仅相信外部 AI 的自然语言判断。允许 **keep_high** 至少同时满足：

### 3.1 后端复合门槛（技术上限，代码为准）

以 `app/services/dify_schema_parser.py` 中 `_qualified_high_risk_issue` 及同类逻辑为准（执行前对照当前代码）：

- 维度 `status=fail`（或契约认可的明确 fail 语义），不是 `unknown`/缺文书/单侧未提及。
- 维度 `confidence >= 0.8`（以代码阈值为准）。
- **维度级** `medical_evidence` 与 `nursing_evidence` 均有意义（若库内数组为空，必须从 content / issues 证据还原后再判；不得因数组列空直接当“无证据高危”或直接当“有证据”）。
- 同一条 `extra.issues[]` 同时满足：`level=severe`、`high_eligible=true`、`issue_mode=contradiction`、source_a≠source_b 且均非空、evidence_a/b 有意义、issue confidence 达标、`safety_category` 属于该 `audit_type_code` 白名单。
- 不是相同证据复制、短占位文本、`dimension_code=other`、解析失败或 fallback 结果。

### 3.2 提示词临床规则（语义下限）

后端门槛通过后，仍须用对应类型提示词拦截“形式上像高危、临床上不是”的情况，尤其：

- 详略、同义、上下位、合理诊断演变、不同时间状态变化；
- 主诉/病程**时间表述差异** alone（除非同时构成可证明的关键事实冲突）；
- 查体措辞差异 alone 被抬到 `critical_diagnosis_basis`；
- `safety_category` 与证据事实明显不符（过宽贴标签）。

**生产观察（2026-07-17）**：当日 high 几乎全部集中在 `admission_vs_first_progress`；形式门槛可全部通过，但临床仍有大量“应降级/应人工”候选。整改时默认按 **admission 优先、先形式不合格、再临床过宽** 排序。

### 3.3 自动整改边界

- 自动整改只允许“降级”，不允许借本技能提升历史等级。
- 以下默认进入降级候选或人工复核，不直接判定为正常 pass：
  - 一类文书缺失、一方未提及或只有单侧证据；
  - JSON 解析失败、fallback、证据字段错位或来源无法确认；
  - 双方证据相同、模板化、过短或不能证明直接矛盾；
  - 缺少受控安全类别或高危资格字段；
  - **形式门槛通过但临床语义过宽**（须 `manual_review` 或批准后的 medium）。
- “正常级别”映射：有充分一致性证据 → `pass/low/blue`；仅证据不足 → `unknown/low/gray/manual_review`，不得伪造 pass。
- 在用户或临床负责人未逐条批准目标映射前，不得自行把“非高危”统一改成 medium 或 low。
- **本技能默认不改** `reviewed_flag`、`manual_override`、`skip_reason`、医生反馈表；降级不等于改复核状态或删除反馈。若业务要求同步改 flag，须在批准清单中单列字段与目标值。
- **本技能不提供生产一键写库脚本**；阶段 3–4 必须基于批准 ID 清单手写/生成受控 SQL 或临时脚本，dry-run 后再执行。禁止宽 WHERE 重扫。

六类提示词是临床语义判定依据，后端复合门槛是 high/red 的技术上限。两者必须同时通过；任一不通过都不得维持 keep_high。提示词快照不能替代历史生产 Workflow 版本：若无法取得历史版本，报告必须标注“按当前 110–115 标准复核，不代表复原历史模型判定”。

## 4. 交付报告模板

每个阶段必须报告：

- 阶段、run_id、环境、镜像/版本、操作者。
- 实际执行的只读或写入命令（隐藏密码和 token）。
- 查询范围、候选数、排除数、错误数及分类。
- 修改文件/数据库表/字段；未修改项。
- 备份路径、快照 SHA-256、外部复核包 SHA-256。
- 测试和对账结果。
- 下一阶段所需的明确批准。

任何不确定医学判断标记“需临床专家确认”；任何数据库结构或字段不一致立即停止，不得猜测。
