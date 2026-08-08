# Dify 质控提示词核查与修订建议（供外部 AI 复核）

> 状态：待外部 AI / 临床质控复核
> 建立日期：2026-07-13
> 复核对象：`docs/reference/` 下 5 份 `.txt` 提示词，以及 `109_DIFY_ADMISSION_FIRST_PROGRESS_REVIEW.md` 已完成的入院/首次病程复核包。
> 复核目标：在不改变各审计类型已有质控规则的前提下，统一高危口径、证据门槛、维度编码与 JSON Schema，使 Qwen3-30B-A3B-Instruct-2507 输出可被后端稳定解析，并杜绝"无证据/单侧证据/warn 却标高危"的误报。
> 隐私说明：本文不包含患者身份、病历正文或单条 Dify 返回内容。

---

## 0. 给复核方的核心要求（请逐条确认）

本文件由代码侧 AI 基于后端解析器与配置生成，**未修改任何提示词正文**。请你（复核方）重点确认以下事项，并以"确认 / 反对 / 建议"逐条回复：

1. 各审计类型的**高危（high/red）临床口径**是否过宽，是否会把"文书规范性问题"误判为高危。
2. 建议的高危硬门槛（见第 4 节）是否会误伤真正的直接安全风险冲突。
3. 受控 `dimension_code` 白名单（见第 3 节）是否覆盖临床实际需要的核查维度，有无遗漏。
4. 各类型"双方证据"的字段映射（admission_record→medical_evidence 等）是否与临床文书语义一致。
5. Qwen3-30B-A3B-Instruct-2507 在长上下文 + 严格 JSON 约束下的提示词结构是否合理（见第 6 节模型适配建议）。

---

## 1. 核查范围与文件清单

| 提示词文件（docs/reference/） | 对应核查类型 | 生产 audit_type code |
| --- | --- | --- |
| `109_DIFY_ADMISSION_FIRST_PROGRESS_REVIEW.md` | 入院记录 vs 首次病程 | `admission_vs_first_progress`（已复核，本文件不再重审） |
| `【首次病程记录】与【出院记录】 质控.txt` | 首次病程 vs 出院记录 | **⚠️ 生产 config 暂无对应项，见第 7 节** |
| `围手术前核查.txt` | 术前/手术/术后首次病程连贯性 | `surgery_chain`（围手术期） |
| `护理与病程一致性核查.txt` | 病程 vs 护理 | `progress_vs_nursing` |
| `检验检查与护理病程一致性核查.txt` | 检验检查 vs 病程护理 | `lab_exam_vs_progress_nursing` / `jyjc_vs_bcnursing`（同提示词两个类型） |
| `首页手术与首次病程核查.txt` | 病案首页手术诊断 vs 首次病程 | `frontpage_surgery_diagnosis_vs_first_progress`（调度侧记作 `surgery_chain`，见第 7 节） |

---

## 2. 后端解析契约（所有提示词必须满足的硬约束）

提示词输出的 JSON 必须能被 `app/dify_pusher.py:parse_dify_structured_output` 与 `app/services/dify_schema_parser.py` 正确解析。以下是后端**已经实现**的规则，提示词不得违反：

### 2.1 后端对高危的实际处理（关键差异）

| audit_type_code | 是否有后端高危门槛 | 说明 |
| --- | --- | --- |
| `admission_vs_first_progress` | ✅ 有（已实现） | 高危必须同时满足 `status=fail` + `confidence≥0.8` + `medical_evidence` 与 `nursing_evidence` 均非空；不满足则降级为 `unknown/low/gray/review_only`，并收敛顶层告警 |
| 其余所有类型（含 `surgery_chain`、`progress_vs_nursing`、`lab_exam_*`、`jyjc_vs_bcnursing`、`frontpage_*`） | ❌ **无任何后端门槛** | Dify 输出 `severity=high` 或 `alert_level=red` 的维度，会被 `_post_process_result` 直接抬升顶层严重度（见 `dify_schema_parser.py:526-541`）。这是日志里其他类型高危误报的根因 |

**这就是日志分析的核心结论**：入院/首次病程已有后端兜底，但其他类型完全依赖提示词自律。日志显示：

- `progress_vs_nursing`：6 个高危维度实际是 `warn`（被误标 high）
- `jyjc_vs_bcnursing`：38 个高危维度**无任何证据**
- `surgery_chain`：33 个高危维度仅单侧证据
- `syssvsscbc`：29 个高危维度仅单侧证据

### 2.2 后端字段归一化规则（`dify_result_normalizer.py`）

- `status`：合法值 `pass/warn/fail/unknown`；中文 `通过/一致→pass`、`风险→warn`、`不一致/失败→fail`、`无法判断→unknown` 会被归一。
- `severity`：合法值 `low/medium/high`；中文 `高/中/低` 会被归一，`severe/critical→high`。
- `alert_level`：合法值 `red/yellow/blue/gray`；`红/高危→red`、`不确定→gray`。
- `confidence`：会被 clamp 到 `[0.0, 1.0]`。
- `derive_severity_from_dimensions`：只要任意维度 `severity=high`，顶层就会被抬为 `high`——**这是后端放大问题的机制**。

### 2.3 后端证据字段映射（`audit_result_mapper.py`）

- `progress_vs_nursing` 是唯一的 **legacy 类型**：`medical_evidence`/`nursing_evidence` 写入 `medical_evidence_json`/`nursing_evidence_json` 专用列。
- 其余类型：`medical_evidence`/`nursing_evidence` 不写入专用列，而是**作为 `extra.medical_evidence_legacy` / `extra.nursing_evidence_legacy` 保留**，最终落到 `AuditDimensionResult.extra_json`。
- 因此非 legacy 类型的双方证据**语义不能假定是"病程/护理"**，109 文档第 8 节已强调：前端应按审计类型显示为"入院记录证据/首次病程记录证据"等，不能统一显示为"病程/护理"。

---

## 3. 受控维度编码（dimension_code 白名单）

各类型的 `dimension_code` **必须严格使用下方白名单**，后端不会自动收敛其他类型（仅 `admission_vs_first_progress` 有别名收敛）。

### 3.1 首次病程 vs 出院记录（建议白名单，提示词已给出）

```
patient_info_consistency
chief_complaint_consistency
admission_diagnosis_consistency
diagnosis_backfill_validity
new_discharge_diagnosis_evidence
treatment_course_completeness
discharge_advice_consistency
discharge_condition_consistency
text_quality
```

### 3.2 围手术期 surgery_chain（提示词已给出）

```
patient_info_consistency
timeline_consistency
preoperative_template_validity
diagnosis_consistency
operation_consistency
anesthesia_material_step_consistency
intraoperative_to_postoperative_consistency
postoperative_record_completeness
consent_subject_validity
text_quality
```

### 3.3 病程 vs 护理 progress_vs_nursing（legacy，固定 6 维度）

```
diagnosis_consistency
nursing_level_consistency
vital_sign_consistency
condition_consistency
treatment_measure_consistency
timeline_consistency
```

> ⚠️ 后端 `_dimension_code_from_name`（`dify_schema_parser.py:319`）只为这 6 个维度做了中文名→code 映射。若提示词输出中文名（如"诊断一致性"）会被映射到 `diagnosis_consistency`，但其他类型输出中文名会映射失败得到空 code。

### 3.4 检验检查 vs 病程护理（提示词已给出）

```
lab_abnormal_followup
exam_abnormal_followup
progress_result_consistency
nursing_recorded_consistency
high_risk_response_consistency
timeline_consistency
```

### 3.5 首页手术 vs 首次病程（提示词已给出）

```
diagnosis_consistency
operation_consistency
diagnosis_operation_match
timeline_consistency
```

---

## 4. ⚠️ 核心问题：高危口径不统一（必须修订）

这是本次核查发现的最严重问题，也是日志误报的直接原因。**5 份提示词对"高危（high/red）"的判定口径各不相同**：

### 4.1 现状对比表

| 提示词 | 高危触发条件 | confidence 门槛 | 证据要求 | warn 能否高危 |
| --- | --- | --- | --- | --- |
| 入院/首次病程（109，已修订） | 严重 + high_eligible + 双方证据 + 直接安全冲突 | ≥0.8 | ✅ 双方均非空 | ❌ 禁止 |
| 首次病程/出院（新） | "严重" → high/red，**无证据/置信度约束** | 无 | ❌ 仅存 `original_text` 单字段 | ❌ 禁止（但映射规则未约束证据） |
| 围手术期（新） | "严重" → high/red，**无证据/置信度约束** | 无 | ❌ 仅存 `original_text` 单字段 | ❌ 禁止 |
| 病程/护理（legacy） | `fail` → red，**无置信度/证据约束** | 无 | ⚠️ 提示词说"双方都有记录"但无强制 | ⚠️ 提示词说"warn 不等于 fail"，但 JSON 映射未禁止 warn→red |
| 检验检查（新） | `fail` → red，**无置信度约束** | <0.6 才降 unknown | ✅ 较好（要求异常明确+未处理） | ❌ 禁止（warn→yellow） |
| 首页手术（新） | `fail` + 高风险 → red，**无证据/置信度约束** | <0.6 才降 gray | ❌ 仅说"引用原文" | ❌ 禁止 |

### 4.2 问题根因

1. **"严重"等级语义模糊**：首次病程/出院和围手术期两份提示词，只说"严重→high/red"，没定义"严重"的临床硬门槛。Qwen3 可能会把"主诉部位左右写反"（文书问题）和"左右侧手术部位写反"（安全风险）都判成"严重"。
2. **缺少双方证据强制**：这两份提示词的 JSON 节点只把 `original_text`（单字段）存进 `medical_evidence`，**完全没有 nursing_evidence**，无法证明双方冲突。
3. **warn→high 漏洞**：病程/护理的 JSON 转换节点未明确禁止"warn 维度输出 high/red"，加上后端无门槛，导致日志里出现 6 个 warn 却标高危的维度。
4. **confidence 门槛缺失**：除检验检查和首页手术外，其余提示词没有 `confidence` 降级机制。

### 4.3 统一高危硬门槛建议（适用于所有类型）

请复核方确认：**任何维度的 `severity=high` / `alert_level=red` 必须同时满足以下全部条件，否则一律降为 `unknown/low/gray/review_only`**：

```
1. status = "fail"（明确冲突，warn 绝对禁止 high/red）
2. confidence >= 0.8
3. 存在冲突双方的直接原文证据（medical_evidence 与 nursing_evidence
   或对应类型的双方证据字段，均非空）
4. 证据来自不同文书/数据源，且构成直接、不可调和的矛盾
5. 矛盾可能影响患者身份识别、过敏禁忌、左右侧/病变部位、
   关键诊断依据、关键治疗措施或紧急患者安全
```

**绝对禁止高危的情形**（所有类型通用）：
- 一方未提及、另一方有记录
- 记录详略不同、同义表达、上下位关系、医学可兼容
- 仅有单侧原文证据
- 模板残留、错别字、重复、格式问题、文书规范性问题
- 一般性诊断依据不足、一般性信息遗漏
- 证据不足、无法确认、需人工判断的事项

---

## 5. ⚠️ 第二类问题：JSON Schema 字段不一致

5 份提示词的 JSON 输出结构存在差异，增加后端解析复杂度和出错风险。

### 5.1 字段差异对比

| 字段 | 入院/首次病程 | 首次病程/出院 | 围手术期 | 病程/护理 | 检验检查 | 首页手术 |
| --- | --- | --- | --- | --- | --- | --- |
| `audit_type.code` | ✅ | ❌ 空 | ❌ 空 | ❌ 无此字段 | ❌ 无此字段 | ❌ 无此字段 |
| `audit_type.name` | ✅ | ❌ 空 | ❌ 空 | ❌ 无 | ❌ 无 | ❌ 无 |
| `reasoning`（维度级） | ✅ | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 |
| `medical_evidence`/`nursing_evidence` | ✅ 双方 | ⚠️ 仅 medical（original_text） | ⚠️ 仅 medical | ✅ 双方 | ❌ 不输出 | ⚠️ 双方但语义混乱 |
| `raw_judgement` | ❌ 无 | ❌ 无 | ❌ 无 | ✅ 有 | ✅ 有 | ✅ 有 |
| 证据存入位置 | 维度级数组 | `extra.issues.original_text` | `extra.issues.original_text` | 维度级数组 | 不输出 | 维度级数组 |

### 5.2 关键问题

1. **首次病程/出院 和 围手术期 把证据存进 `extra.issues[].original_text`**，而后端 `map_dimension_row` 只把 `extra` 整体保留，**不解析 issues 里的 original_text**。后端判断"双方证据是否齐全"时只看维度级 `medical_evidence`/`nursing_evidence`——这两份提示词的 `nursing_evidence` 永远为空，即使将来给它们加后端门槛，也通不过。
2. **病程/护理、检验检查、首页手术 有 `raw_judgement` 字段**，入院/首次病程和出院/围手术期没有。后端 `_parse_new_schema` 会读取 `raw_judgement.reasoning_brief`（`dify_schema_parser.py:86`），缺失不报错但不统一。
3. **`audit_type.code` 大多为空**：后端不依赖此字段（code 来自 config），但缺失会让 Dify 原始返回难以人工辨认类型。

### 5.3 统一 Schema 建议

所有类型的 JSON 输出应统一为以下结构（与 109 文档第 6 节一致）：

```jsonc
{
  "version": "2.0",
  "audit_type": {"code": "<audit_type_code>", "name": "<类型中文名>"},
  "patient_summary": {
    "patient_id": "", "visit_number": "", "patient_name": "", "dept": "", "query_date": ""
  },
  "audit_summary": {
    "has_inconsistency": false, "severity": "low", "risk_score": 0, "alert_level": "blue",
    "closure_hours": 0, "push_strategy": "review_only", "outcome_bucket": "none",
    "overall_conclusion": "", "overall_qc_summary": "", "focus_items": [], "reasoning_brief": ""
  },
  "dimensions": [
    {
      "dimension_code": "", "dimension_name": "", "status": "pass", "severity": "low",
      "confidence": 0.9, "alert_level": "blue", "closure_hours": 0,
      "push_strategy": "review_only", "outcome_bucket": "none", "issue_summary": "",
      "medical_evidence": [], "nursing_evidence": [], "recommendation": "", "reasoning": "",
      "extra": {"issues": [], "manual_review": []}
    }
  ],
  "raw_judgement": {"consistency_label": "", "reasoning_brief": ""}
}
```

---

## 6. Qwen3-30B-A3B-Instruct-2507 适配建议

该模型为 30B 总参/A3B 激活、MoE 架构、Instruct 版（2507）。针对其特性给出提示词工程建议（请复核方确认是否适用实际部署）：

### 6.1 已知风险

1. **MoE 激活稀疏**：A3B 激活量相对较小，对超长、多规则叠加的提示词，规则遵循稳定性低于 Dense 大模型。日志显示 3 条 fallback 解析（非标准 JSON），可能与提示词过长、规则冲突导致 JSON 格式漂移有关。
2. **长上下文证据引用**：入院/首次病程、围手术期等需要同时引用两份文书原文证据，模型可能因上下文压缩而截断或编造证据。
3. **JSON 严格性**：30B 量级模型输出 JSON 时，常见问题是多余 Markdown 代码块（```json）、尾随逗号、中文引号。后端 `_load_json_with_tolerance` 有一定容错，但不能依赖。

### 6.2 提示词结构建议

1. **两节点架构保持不变**：节点一做事实提取（输出结构化事实），节点二做 JSON 转换。这种分工对 MoE 模型更稳定——节点一只需"找证据+定级"，节点二只需"格式转换"，降低单节点认知负荷。
2. **高危门槛写成显式检查清单**：不要用"严重"这种模糊词，改用"必须同时满足以下 5 个条件"的清单（如 109 文档第 5 节）。MoE 模型对显式清单的遵循度高于模糊语义。
3. **证据字段强制非空校验**：在提示词中明确"evidence_a 与 evidence_b 均不可为空；任一为空时不得判 high_eligible"，并要求模型在输出前自检。
4. **减少自由文本，增加枚举**：`dimension_code`、`issue_type`、`level` 全部用枚举白名单，禁止自由生成。这能避免"数百种维度名"的问题。
5. **JSON 输出前加一句强约束**：「只输出 JSON，不要 Markdown、解释、代码块，第一个字符必须是 `{`，最后一个字符必须是 `}`。」后端虽有容错，但强约束能降低 fallback 率。
6. **Few-shot 慎用**：30B 模型 few-shot 容易过拟合示例的特定表述。建议只在节点二（纯转换）给 1 个最小 schema 示例，节点一（需临床判断）不给 few-shot，避免模型模仿示例而非真实分析。

### 6.3 可观测性建议（后端已部分支持）

- 空输出：后端已标记 `empty_output` 解析告警（`dify_pusher.py:411`）。
- JSON 解析失败但非空：后端走 `_fallback_keyword_match`，标记 `fallback_keyword_match`。
- **建议补充**：空输出/解析失败时，在 `parse_warning` 记录 Dify `workflow_run_id` 与 outputs keys，便于定位是模型未输出还是输出被截断。日志显示有 2 条解析失败"未记录有效错误详情"，需要补这部分可观测性。

---

## 7. ⚠️ 第三类问题：审计类型 code 与配置错配（部署阻塞）

这是代码侧核查发现的**部署级问题**，必须在上线提示词前解决，否则提示词会被发给错误的 audit_type 工作流。

### 7.1 现状

| 提示词文件 | 提示词内 `audit_type.code` | config 实际定义的 code | scheduler 引用的 code |
| --- | --- | --- | --- |
| 入院/首次病程 | `admission_vs_first_progress` | 生产 config 有（template 无） | `scheduler_daily.audit_type_codes` 有 |
| 首次病程/出院 | （提示词未填 code） | **❌ 生产 config 无此项** | ❌ 无 |
| 围手术期 | （提示词未填 code） | ❌ 无 `surgery_chain`（仅代码引用） | `scheduler_daily` 有 `surgery_chain` |
| 病程/护理 | （提示词无 audit_type 字段） | `progress_vs_nursing` ✅ | 有 |
| 检验检查 | （提示词无 audit_type 字段） | `lab_exam_vs_progress_nursing` + `jyjc_vs_bcnursing` | `scheduler_daily` 有 `jyjc_vs_bcnursing` |
| 首页手术 | （提示词无 audit_type 字段） | `frontpage_surgery_diagnosis_vs_first_progress` | ❌ 调度用 `surgery_chain`（与围手术期重名冲突） |

### 7.2 需要确认的问题

1. **`surgery_chain` 到底是"围手术期"还是"首页手术"？** 调度里 `scheduler_daily.audit_type_codes` 含 `surgery_chain`，但有两份提示词（围手术前核查、首页手术与首次病程）都可能映射到它。代码 `payload_composer.py:357` 注册了 `surgery_chain` builder，`dify_schema_parser.py:26` 也专门处理 `surgery_chain` 的旧结构。**请确认 `surgery_chain` 对应哪份提示词**。
2. **首次病程/出院记录这份提示词，生产 config 里没有对应 audit_type**。是要新增一个 `discharge_vs_first_progress`（或类似）类型，还是挂到现有的 `discharge_vs_frontpage`（109 文档第 1 节提到这是 discharge_final 模式的类型之一）？
3. **检验检查两份 config（`lab_exam_vs_progress_nursing` 和 `jyjc_vs_bcnursing`）共用一份提示词**，但 builder 都是 `lab_exam_structured_progress_nursing`，需要确认是否要合并或区分提示词。

### 7.3 提示词必须补全 `audit_type.code`

每份提示词的 JSON 节点二应在 `audit_type.code` 填入与 config 完全一致的 code。建议：

| 提示词 | 建议 audit_type.code |
| --- | --- |
| 首次病程/出院 | `discharge_vs_first_progress`（待业务确认新建） |
| 围手术期 | `surgery_chain` |
| 病程/护理 | `progress_vs_nursing` |
| 检验检查 | `jyjc_vs_bcnursing`（生产启用项） |
| 首页手术 | `frontpage_surgery_diagnosis_vs_first_progress` |

---

## 8. 推送量与失败核查结论（已确认，无需复核）

来自日志分析与代码核验，结论稳定：

| 指标 | 数值 | 说明 |
| --- | ---: | --- |
| 统计窗口 10 天总推送 | 13,914 | 含成功/跳过/失败 |
| 成功 | 8,991 | — |
| 业务跳过 | 4,919 | 正常 |
| 超时失败 | 2 | 偶发 |
| 解析失败 | 2 | 未记录有效错误详情，需补可观测性（见 6.3） |
| 总异常率 | 0.029% | 极低 |
| 峰值 45 条/分钟、695 条/小时 | 0 失败 | 无负载致失败证据 |

**结论**：推送链路稳定，不存在"推送量过大导致失败多"。4 条异常均为偶发（超时/空输出），与高危质量问题无关。后续无需在推送侧改动，仅需补空输出/解析失败的详细错误原因记录。

---

## 9. 各类型逐份修订要点（请复核方逐条确认）

> 下表是代码侧基于后端契约给出的**必须修订项**，每项标注"影响解析"或"影响口径"。

### 9.1 首次病程 vs 出院记录（`discharge_vs_first_progress` 待建）

| # | 问题 | 修订建议 | 类别 |
| --- | --- | --- | --- |
| 1 | 节点一"严重"无临床硬门槛 | 增加 high_eligible 五条件清单（参照 109 第 5 节） | 口径 |
| 2 | 节点二 `original_text` 单字段，无双方证据 | 增设 `source_a/source_b`（first_progress_record / discharge_record）+ `evidence_a/evidence_b`，映射到 medical/nursing_evidence | 解析 |
| 3 | 严重→high/red 无 confidence/证据约束 | 增加：high/red 必须 fail+confidence≥0.8+双方证据非空，否则降 unknown/gray | 口径 |
| 4 | `audit_type.code` 空 | 填入确认后的 code | 解析 |
| 5 | 提示→warn→medium/yellow，但 confidence=0.6（提示等级）→ 输出未约束 warn 禁 red | 明确：warn 维度 severity 只能 medium/low，alert_level 只能 yellow/blue，禁止 red | 口径 |

### 9.2 围手术期 surgery_chain

| # | 问题 | 修订建议 | 类别 |
| --- | --- | --- | --- |
| 1 | "严重"无临床硬门槛 | 增加五条件清单；明确"术前模板未修改""术后记录不全"等属文书规范问题，不得 severe | 口径 |
| 2 | 三份文书（术前/手术/术后）但证据只存 original_text 单字段 | 增设 `source`（preop_record/operation_record/postop_record）+ 双侧证据，映射到 medical/nursing_evidence（术前→medical，术后→nursing，手术记录作为辅助） | 解析 |
| 3 | 严重→high/red 无约束 | 同 9.1 #3 | 口径 |
| 4 | `audit_type.code` 空 | 填 `surgery_chain`（若确认） | 解析 |
| 5 | 后端 `_normalize_parsed_root` 对 surgery_chain 旧结构（overall_status）有专门处理 | 确认新提示词是否还用 `overall_status`；若改用 `audit_summary`，则旧结构映射逻辑可逐步废弃 | 解析 |

### 9.3 病程 vs 护理 progress_vs_nursing（legacy）

| # | 问题 | 修订建议 | 类别 |
| --- | --- | --- | --- |
| 1 | fail→red 无 confidence/证据约束 | 增加：fail+red 必须 confidence≥0.8 + medical_evidence/nursing_evidence 双方非空；仅单侧证据或 confidence<0.6 降 unknown/gray | 口径 |
| 2 | JSON 节点未明确禁止 warn→red | 明确：warn 维度 alert_level 只能 yellow/blue，severity 只能 medium/low | 口径 |
| 3 | 节点一已明确"仅一方提及判 pass"（口径好），但 JSON 转换节点未强制执行 | 在转换节点补：若 evidence 仅单侧，禁止 fail/red | 口径 |
| 4 | 后端无门槛（除 admission 外） | **建议后端把 admission 的高危降级逻辑通用化**（见第 10 节），否则本类型完全靠提示词自律 | 后端 |

### 9.4 检验检查 vs 病程护理（`jyjc_vs_bcnursing`）

| # | 问题 | 修订建议 | 类别 |
| --- | --- | --- | --- |
| 1 | fail→red 无 confidence 门槛（仅 <0.6 降 unknown） | 增加：fail+red 必须 confidence≥0.8 | 口径 |
| 2 | 节点一明确"不输出证据数组"（合理），但节点二无法填 medical/nursing_evidence | 节点二仍需填双方证据（检验结果→medical_evidence，病程/护理记录→nursing_evidence），否则后端无法判双方冲突 | 解析 |
| 3 | 日志显示 38 个高危维度无证据 | 根因是 fail→red 无证据强制；修订后应消除 | 口径 |
| 4 | `audit_type.code` 无此字段 | 补 `audit_type.code` | 解析 |

### 9.5 首页手术 vs 首次病程（`frontpage_surgery_diagnosis_vs_first_progress`）

| # | 问题 | 修订建议 | 类别 |
| --- | --- | --- | --- |
| 1 | fail+高风险→red 无 confidence/证据约束 | 增加 confidence≥0.8 + 双方证据非空 | 口径 |
| 2 | 提示词证据字段语义混乱（首页诊断放 medical 还是 nursing？） | 明确：首页诊断/手术→medical_evidence，术后首次病程→nursing_evidence | 解析 |
| 3 | `audit_type.code` 无 | 补全 | 解析 |
| 4 | 日志显示 29 个高危维度仅单侧证据（来自 syssvsscbc，若本类型同源） | 同 9.4 | 口径 |

---

## 10. 后端门槛通用化建议（供项目负责人决策，非本提示词复核范围）

日志分析的结论之一是"不能只改提示词，还应增加后端门槛"。当前 `dify_schema_parser.py` 的高危降级逻辑被硬编码守卫在 `if audit_type_code == "admission_vs_first_progress"`（L521、L569）。

**建议方案（二选一，待项目负责人决定，本次不实施）**：

- **方案 A（最小风险）**：保持各类型提示词自律 + 后端通用守卫。在 `_post_process_result` 末尾增加一个通用守卫：**任何类型的维度，若 `severity=high` 且不满足（fail + confidence≥0.8 + 双方证据非空），一律降为 unknown/low/gray**。这相当于把 admission 的 `_downgrade_unqualified_admission_high_risk` 逻辑通用化，但保留 admission 的维度码收敛。
- **方案 B（保守）**：仅对日志显示问题严重的类型（jyjc_vs_bcnursing、surgery_chain、syssvsscbc）逐类型加守卫，与 admission 同模式。

**注意**：无论哪种方案，**都不能改变各类型已确立的质控规则**（如病程/护理的 6 维度、检验检查的"异常明确+未处理才 warn"等）。后端门槛只做"高危证据/置信度守门"，不重新定义什么是问题。

---

## 11. 复核方请回复的清单（汇总）

请复核方在阅读后，按以下编号逐条回复"确认 / 反对 / 建议"：

- [ ] Q1：第 4.3 节的统一高危硬门槛（5 条件 + 禁止情形）是否合理？是否遗漏某类直接安全风险？
- [ ] Q2：第 3 节各类型 dimension_code 白名单是否覆盖临床需求？
- [ ] Q3：第 5.3 节统一 JSON Schema 是否可接受？`raw_judgement` 是否所有类型都需要？
- [ ] Q4：第 7.2 节的 code 错配问题，`surgery_chain` 确认对应哪份提示词？首次病程/出院是否新建 `discharge_vs_first_progress`？
- [ ] Q5：第 6 节 Qwen3-30B-A3B 适配建议是否符合实际模型行为？
- [ ] Q6：第 9 节各类型逐项修订，是否有临床口径上的反对意见？
- [ ] Q7：第 10 节后端门槛方案 A/B，推荐哪个？是否担心改变现有质控规则？

---

## 附：本核查未改动的内容

本文件仅为核查与建议，**未修改任何提示词正文、未修改任何代码、未修改任何配置**。等待复核方回复后，再由代码侧统一实施修订。各审计类型已确立的质控规则（维度定义、pass/warn/fail 判定原则、legacy 证据列等）在本核查中均保持不变。
