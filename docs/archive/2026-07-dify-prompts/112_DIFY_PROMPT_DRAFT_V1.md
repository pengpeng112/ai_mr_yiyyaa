# Dify 质控提示词方案 V2（独立复核修订版）

> 状态：方案稿，禁止直接复制到生产 Dify
> 建立日期：2026-07-13
> 最近修订：2026-07-13 — 修复高危遗漏型风险、伪 source、问题降级丢失、危急规则不明确和 manual review 无闭环等问题。
> 适用模型：Qwen3-30B-A3B-Instruct-2507（内网部署）。
> 上线前提：完成 `111_DIFY_PROMPT_REVISION_DETAILED_PLAN.md` 的口径冻结、配置/code 确认、影子验证和页面证据展示。

## 0. 使用说明

本版不再宣称“可直接复制上线”。推荐工作流为：

1. 数据预处理：提供患者摘要、真实文书 source、文书 ID/时间；jyjc 额外提供机构危急规则匹配和程序化时间窗检查。
2. 节点一 LLM：只提取受控 issue/manual review，不生成最终告警等级。
3. 节点二 Code：按本文件规则确定性生成系统 JSON，执行白名单、唯一性和高危门槛校验。
4. JSON Schema 检测：失败进入修复或技术异常队列；失败结果不得告警。

如 Dify 暂时只能使用第二个 LLM 做转换，第二个 LLM 输出仍必须再经过 Code 节点校验，不能直接入库。

## 1. 统一事实 Schema

节点一使用以下结构。`evidence[]` 每项必须对应输入中的真实文书，不得伪造 source、文书 ID、时间或引文。

```json
{
  "schema_version": "2.1",
  "conclusion": "pass|issue|manual_review",
  "issues": [
    {
      "dimension_code": "",
      "issue_type": "",
      "issue_mode": "contradiction|omission|timeline|text_quality",
      "level": "severe|general|hint",
      "high_eligible": false,
      "safety_category": "",
      "confidence": 0.0,
      "evidence": [
        {
          "source_type": "",
          "document_id": "",
          "document_time": "",
          "quote": ""
        }
      ],
      "critical_rule_match": {},
      "absence_check": {},
      "explanation": "",
      "recommendation": ""
    }
  ],
  "manual_reviews": [
    {
      "dimension_code": "",
      "review_type": "",
      "source_type": "",
      "document_id": "",
      "document_time": "",
      "quote": "",
      "reason": "",
      "suggestion": "",
      "confidence": 0.0
    }
  ]
}
```

### 1.1 issue_mode 约束

- `contradiction`：必须至少有两条来自不同 source 的非空直接引文。
- `omission`：允许只有触发侧引文；不得编造“未记录”引文。需要保存预期文书、覆盖时间窗和程序化 absence check。
- `timeline`：必须引用相关时间字段；无法排除补记/延迟签署时进入 manual review。
- `text_quality`：纯文本问题不得 high。若文本错误实际造成错患者、错侧、错药、错剂量或错术式，应改归相应 contradiction 安全类别。

### 1.2 安全类别白名单

`safety_category` 仅允许：

- 空字符串：非高危问题；
- `patient_identity`；
- `allergy_medication`；
- `wrong_site_or_side`；
- `wrong_procedure_or_implant`；
- `critical_diagnosis_basis`；
- `current_vital_or_life_support`；
- `critical_result_unhandled`。

## 2. 统一高危与降级规则

### 2.1 矛盾型 high

同一个 issue 同时满足下列全部条件才可 high/red：

1. `issue_mode="contradiction"`、`level="severe"`、`high_eligible=true`。
2. `confidence>=0.8`。
3. 至少两条证据来自不同真实文书，且引文均非空、不是“无/未记录/不详”等占位词。
4. 证据针对同一患者、住院次、事项和可比较时间窗，含义直接相反且不可调和。
5. `safety_category` 属于受控安全类别。

### 2.2 危急结果未响应型 high

仅当输入已经由系统提供机构规则和程序检查时允许：

1. `issue_mode="omission"`、`level="severe"`、`high_eligible=true`、`safety_category="critical_result_unhandled"`。
2. `critical_rule_match.matched=true`，且含机构规则 code、结果、单位、时间和适用人群。
3. `absence_check.coverage_complete=true`，响应窗已结束，程序确认规定来源内无通知、评估、处置或复查。
4. `confidence>=0.8`。

模型不得自行生成危急阈值、规则 code、coverage_complete 或“未响应”结论。缺少任一系统字段时严禁 high。

### 2.3 非 high 处理

- 问题明确成立但不满足 high：保留为 `warn/medium/yellow`，不得改成 unknown。
- 明确文本质量问题：`warn/low/blue`。
- 是否存在问题本身无法确认：`unknown/low/gray`，confidence 最大 0.59，写入 manual review。
- 一方未提及、详略不同、同义/上下位、合理诊断演变、时间窗不可比：不得判 contradiction。
- fallback、解析失败、code 错配：不得生成 high。

## 3. 节点一通用系统提示词

```text
你是病历质控事实提取助手。只根据输入文书和系统提供的结构化字段提取问题，不生成最终系统告警等级。

必须遵守：
1. 不评价治疗方案，不使用输入外医学事实，不补造文书内容。
2. 不因详略、同义、上下位、合理病程变化或单方未提及判直接冲突。
3. evidence 中的 source_type、document_id、document_time、quote 必须来自输入；不得把一种文书标成另一种文书。
4. contradiction 必须有不同 source 的双方直接引文；omission 不得编造第二侧引文。
5. 模型不得自行定义危急值或生成 critical_rule_match、absence_check。
6. 只有满足提示词全部高危条件时，才可 level=severe 且 high_eligible=true。
7. 明确一般问题使用 general；纯文本问题使用 hint；问题本身不能确认时写入 manual_reviews。
8. dimension_code 和 source_type 只能来自当前类型白名单。
9. 只输出符合统一事实 Schema 的 JSON；第一个字符必须是 {，最后一个字符必须是 }，不要 Markdown 或解释。

当前核查类型：{{audit_type_name}}
维度白名单：{{dimension_whitelist}}
source 白名单：{{source_whitelist}}
类型专属核查规则：{{type_specific_rules}}
系统危急规则匹配：{{critical_rule_match}}
系统时间窗检查：{{absence_check}}
病历输入：{{mr_txt}}
```

## 4. 节点二确定性转换规则

节点二推荐使用 Code 节点，不再依赖 LLM自由转换。系统输出保持现有解析器兼容字段：

```json
{
  "version": "2.1",
  "audit_type": {"code": "", "name": ""},
  "patient_summary": {
    "patient_id": "", "visit_number": "", "patient_name": "", "dept": "", "query_date": ""
  },
  "audit_summary": {
    "has_inconsistency": false,
    "needs_manual_review": false,
    "manual_review_count": 0,
    "severity": "low",
    "risk_score": 0,
    "alert_level": "blue",
    "closure_hours": 0,
    "push_strategy": "review_only",
    "outcome_bucket": "none",
    "overall_conclusion": "",
    "overall_qc_summary": "",
    "focus_items": [],
    "reasoning_brief": ""
  },
  "dimensions": [
    {
      "dimension_code": "",
      "dimension_name": "",
      "status": "pass",
      "severity": "low",
      "confidence": 0.9,
      "alert_level": "blue",
      "closure_hours": 0,
      "push_strategy": "review_only",
      "outcome_bucket": "none",
      "issue_summary": "未见明确问题",
      "medical_evidence": [],
      "nursing_evidence": [],
      "recommendation": "无需修改",
      "reasoning": "",
      "extra": {"issues": [], "manual_review": [], "evidence_sources": []}
    }
  ]
}
```

### 4.1 确定性映射

1. 输出维度白名单中的全部维度，顺序固定、code 唯一；白名单外 issue 隔离并记录校验错误，不映射到 `other`。
2. 对每个 issue 单独执行第 2 节门槛，禁止跨 issue 拼接证据。
3. 合格矛盾型或危急未响应型 high：`fail/high/red/90/immediate/primary`。
4. 明确 general：`warn/medium/yellow/60/batch/secondary`。
5. hint：`warn/low/blue/20/review_only/none`。
6. 不能确认：`unknown/low/gray/0/review_only/none`，confidence 不高于 0.59。
7. 仅 manual review 时 `has_inconsistency=false`，但 `needs_manual_review=true` 且数量准确。
8. medical/nursing 只是兼容字段；真实来源对象完整保存在 `extra.evidence_sources` 和 `extra.issues`。页面必须按 audit type 展示真实标签。
9. patient_summary 必须由输入变量/后端透传，不允许模型推断。
10. `audit_type.code` 必须与调用方一致；不一致时禁止 high 并进入技术复核。

### 4.2 证据兼容映射

| audit type | medical_evidence | nursing_evidence | 真实 source |
| --- | --- | --- | --- |
| 首次病程 vs 出院 | 首次病程引文 | 出院记录引文 | first_progress_record / discharge_record |
| surgery_chain | 参与比较的第一来源引文 | 第二来源引文 | preop_record / operation_record / postop_record，真实 source 以 extra 为准 |
| progress_vs_nursing | 病程引文 | 护理引文 | progress_record / nursing_record |
| jyjc | 检验检查引文 | 病程或护理引文 | lab_exam_report / progress_record / nursing_record |
| syssvsscbc | 首页引文 | 术后首次病程引文 | frontpage / first_progress_record |

## 5. 类型一：首次病程 vs 出院记录

> 建议 code：`discharge_vs_first_progress`。当前 `discharge_vs_frontpage` 无活配置且名称错误，未完成 code 决策前不得部署。

### 5.1 source 白名单

`first_progress_record`、`discharge_record`

### 5.2 维度白名单

`patient_info_consistency`、`chief_complaint_consistency`、`admission_diagnosis_consistency`、`diagnosis_backfill_validity`、`new_discharge_diagnosis_evidence`、`treatment_course_completeness`、`discharge_advice_consistency`、`discharge_condition_consistency`、`text_quality`

### 5.3 类型规则

- 患者身份应包含患者 ID/住院次等可用标识，不只比较姓名、年龄。
- 首次病程是初步判断，出院记录是最终结果；合理诊断演变不判冲突。
- `diagnosis_backfill_validity`：仅凭两份文书和最终诊断变化通常不能证明倒填；证据不足时 manual review。
- `new_discharge_diagnosis_evidence`、`treatment_course_completeness` 属 omission；允许只有触发侧证据，不得虚构“未记录”的引文。
- 出院医嘱、出院情况只有与住院经过存在明确相反信息时才按 contradiction；单纯未提及按 omission/general/manual review。
- 纯模板、重复、普通错字只能 hint；若造成错患者、错侧或过敏用药冲突，改归相应安全类别。

## 6. 类型二：surgery_chain

> code：`surgery_chain`。当前无活配置，完成三来源 payload/config 校验前不得部署。

### 6.1 source 白名单

`preop_record`、`operation_record`、`postop_record`

### 6.2 维度白名单

首轮保留：`patient_info_consistency`、`timeline_consistency`、`preoperative_template_validity`、`diagnosis_consistency`、`operation_consistency`、`anesthesia_material_step_consistency`、`intraoperative_to_postoperative_consistency`、`postoperative_record_completeness`、`consent_subject_validity`、`text_quality`。

麻醉、植入物/材料、关键步骤是否拆维度，需临床确认后在第二阶段处理。

### 6.3 类型规则

- 手术记录证据必须标 `operation_record`，不得伪装成 preop/postop。
- 拟行与实际手术只在名称、部位、侧别、单/双侧或术式明确不可兼容时判 contradiction；简称、全称和可兼容表述不判错。
- 术前记录在手术前写“拟行/明日手术”正常。只有相同文字出现在术后文书，或术前文书签署时间明确晚于手术完成时间，才可能判模板问题。
- 手术记录与术后记录的麻醉、植入物、重要步骤或并发情况直接相反时可判问题；术后未复述通常不算冲突。
- `postoperative_record_completeness` 属 omission，一般为 general/hint，不得仅因缺项 high。
- 错患者、错侧、错部位、错术式或错植入物可进入高危候选；必须满足同一 issue 的双来源门槛。

## 7. 类型三：progress_vs_nursing

> code：`progress_vs_nursing`。保留 legacy 落库列，但新版输出不豁免高危守门。

### 7.1 source 与维度白名单

- source：`progress_record`、`nursing_record`
- 维度：`diagnosis_consistency`、`nursing_level_consistency`、`vital_sign_consistency`、`condition_consistency`、`treatment_measure_consistency`、`timeline_consistency`

### 7.2 类型规则

- 只有同一事项、可比较时间窗、双方均有记录且含义直接相反时才判 contradiction。
- “同一天即可”删除；同日内生命体征、护理级别、氧疗和病情可发生变化，必须结合记录时间或事件时间。
- 病程诊断更多、护理较简略通常 pass；单方提及通常 pass，不得机械加入 manual review。
- 可明确高危候选的场景限于：过敏/用药禁忌直接冲突、当前危及生命生命体征直接冲突、关键生命支持措施状态直接冲突。普通护理级别差异不得自动 high。
- 现有 `diagnosis_consistency` 暂兼容过敏史；后续是否拆分过敏维度需临床确认和历史统计迁移方案。

## 8. 类型四：jyjc_vs_bcnursing

> code：`jyjc_vs_bcnursing`

### 8.1 source 与维度白名单

- source：`lab_exam_report`、`progress_record`、`nursing_record`
- 维度：`lab_abnormal_followup`、`exam_abnormal_followup`、`progress_result_consistency`、`nursing_recorded_consistency`、`high_risk_response_consistency`、`timeline_consistency`

### 8.2 类型规则

- `lab_abnormal_followup`、`exam_abnormal_followup`：处理普通有临床意义异常的关注/解释/处置/复查；明确遗漏通常为 general，不得自动 high。
- `progress_result_consistency`：病程已经引用了结果，但数值、阳阴性、部位或结论与报告直接相反。
- `nursing_recorded_consistency`：护理已经记录相关结果且与报告直接相反；护理未提及结果不判问题。
- `high_risk_response_consistency`：只承载本院 `critical_rule_match` 命中的危急结果，避免与前两个 followup 维度重复输出同一问题。
- `timeline_consistency`：记录提前引用尚未产生的结果时可判 timeline；结果晚于当前记录时不能判遗漏。
- 轻微异常、既往稳定异常或与本次诊疗无明确关系时，模型不得自行提升风险。
- 危急未响应 high 必须使用系统提供的机构规则和完整 `absence_check`；没有这些字段时最高 general/manual review。

### 8.3 同一异常的归属

- 普通异常关注不足：只进入对应 lab/exam followup。
- 报告与文书写法相反：进入 progress 或 nursing consistency。
- 机构危急规则命中且程序确认超时未响应：只进入 high_risk_response_consistency。
- 同一事实不得在多个维度重复生成独立告警。

## 9. 类型五：syssvsscbc

> 当前 code：`syssvsscbc`。保留兼容，后续迁移语义化 code。

### 9.1 source 与维度白名单

- source：`frontpage`、`first_progress_record`
- 维度：`diagnosis_consistency`、`operation_consistency`、`diagnosis_operation_match`、`timeline_consistency`

### 9.2 类型规则

- 只做首页与术后首次病程的一致性核查，不做病程完整性、手术指征、病理依据或治疗合理性评价。
- 一方缺失、MRID 为空、病程未写全诊断/手术、未写指征或术前评估，不判 warn/fail。
- 同义、简称、可解释上下位及语义仍清楚的笔误判 pass。
- `operation_consistency` 中明确错侧、错部位、错术式可进入高危候选。
- `diagnosis_operation_match` 若判断依赖外部医学知识，只能 manual review；不得仅根据首页内部诊断与手术关系伪造 frontpage/first_progress 双侧证据。
- 时间任一侧缺失时 pass/unknown；明确倒置且排除补记/签署延迟后才输出 timeline 问题。

## 10. 绝对禁止事项

1. 不得把不同患者、不同住院次或不同事件的证据拼为一个 issue。
2. 不得把同一 source 的两段文字伪装成双来源。
3. 不得以“未记录”“无相关内容”作为直接引文。
4. 不得把 general/hint/manual review 升为 high。
5. 不得因模型 confidence 高而替代临床安全类别、机构规则或证据门槛。
6. 不得让解析失败、JSON 修复失败、code 错配或白名单外维度进入高危告警。
7. 不得把 risk_score 当作临床概率；90/60/20/0 仅为系统枚举映射。
8. “立即通知”和“24 小时关闭”必须区分；紧急临床响应时限由本院制度确定。

## 11. 部署前校验清单

- [ ] 五类 source 均能从实际 payload 获取真实 document_id/time。
- [ ] surgery_chain 已支持 operation_record 独立来源。
- [ ] jyjc 已接入本院危急规则和程序化 absence check；否则 omission high 保持关闭。
- [ ] 节点二采用 Code/Schema 校验，或第二 LLM 后另有 Code 终检。
- [ ] dimensions 数量、顺序、唯一性和白名单校验通过。
- [ ] audit_type.code 与调用方一致。
- [ ] response JSONPath 已与新 schema 对齐：总结字段使用 `$.audit_summary.*`，不再读取旧根字段；不一致字段使用 `has_inconsistency`。
- [ ] fallback/parse_failed/空 code 均无法触发 high。
- [ ] progress_vs_nursing 新 schema 未被 legacy 豁免。
- [ ] 非 legacy evidence 和 manual review 在 logs、feedback、patient_qc 可见。
- [ ] 已完成影子样本临床抽检、灰度和回滚演练。

## 12. 待临床确认项

1. 本院危急检验、危急影像规则、适用人群、单位和响应时间窗。
2. `current_vital_or_life_support` 的具体受控场景，避免普通生命体征差异被高危化。
3. 围手术期麻醉、植入物/材料、关键步骤是否拆分维度。
4. 是否为病程护理单独增加过敏、管路/氧疗等维度；首轮为降低回归风险暂不扩容。
5. 首次病程/出院是否增加重大并发症、不良事件和关键用药连续性维度；首轮暂保留原 9 维度。
6. high 的临床响应时限与行政关闭时限。

## 13. 模型运行约束

- 不以“A3B/MoE”架构本身推断模型一定更差或更稳；以本地量化方式、上下文上限、采样参数和真实病例回归结果为准。
- 输入超出本地服务实际上下文或发生 payload 截断时必须技术失败，不能让模型基于残缺文书给出 high。
- 临床事实提取使用低随机性配置，并固定模型版本、提示词版本和工作流版本，便于回放。
- 节点一不给会诱导临床结论的特定病例 few-shot；如需示例，只提供字段格式和反例边界。
- 输出 token 必须覆盖全部维度和证据对象；输出被截断时不得进入关键词 fallback 告警。
