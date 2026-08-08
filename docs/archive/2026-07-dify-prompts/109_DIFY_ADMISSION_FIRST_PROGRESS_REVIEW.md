# 入院记录与首次病程 Dify 质控复核包

> 状态：待外部 AI / 临床质控复核
> 建立日期：2026-07-13
> 范围：`admission_vs_first_progress` 两节点 Dify 工作流、生产日志汇总与本地后端兼容改动。
> 隐私说明：本文不包含患者身份、病历正文或单条 Dify 返回内容。

## 1. 复核目标

请独立核查以下问题：

1. 高危 (`high` / `red`) 的临床口径是否过宽，是否会将文书规范性问题误判为高危。
2. 第一节点的自然语言质控结果能否被第二节点稳定转换为系统 JSON。
3. 建议提示词是否会降低无证据或单侧证据的高危误报，同时保留真正的直接安全风险冲突。
4. 本地后端兜底逻辑是否符合 Dify 输出契约，是否会引入不符合业务预期的降级。

## 2. 生产日志核查摘要

### 2.1 高危结果结构审查

统计窗口：2026-07-03 14:08 至 2026-07-13 14:08；生产库只读查询。

| 指标 | 数量 | 说明 |
| --- | ---: | --- |
| 高危 PushLog | 571 | `PushLog.severity = high` |
| 高危维度 | 1,190 | 同一 PushLog 可有多个维度 |
| 原始文书缺失 | 0 | `mr_text` 均存在 |
| `fail` 高危维度 | 1,184 | 99.5% |
| `warn` 高危维度 | 6 | 不满足“明确冲突”口径，需复核 |
| 顶层高危但无 `red/high` 维度 | 6 条 | 顶层与维度不一致 |
| 顶层高危但总结非 `high/red` | 3 条 | 顶层与总结不一致 |
| 非标准 fallback 解析 | 3 条 | 需核对 Dify 原始输出 |
| 红色高危维度无任何返回证据 | 43 | 无法仅根据返回结果证明高危 |
| 红色高危维度仅单侧证据 | 1,109 | 无法完成双文书直接冲突证明 |

按审计类型的主要结构问题：

| 审计类型 | 高危 PushLog | 主要异常 |
| --- | ---: | --- |
| `admission_vs_first_progress` | 463 | 1,047 个高危维度仅单侧证据，5 个无证据，3 条无红色维度/顶层不一致/fallback |
| `jyjc_vs_bcnursing` | 38 | 38 个高危维度无证据，1 条无红色维度 |
| `progress_vs_nursing` | 33 | 6 个高危维度为 `warn` 却标高危 |
| `syssvsscbc` | 27 | 29 个高危维度仅单侧证据，2 条无红色维度 |
| `surgery_chain` | 10 | 33 个高危维度仅单侧证据 |

判定：推送成功不等于高危结论临床正确。至少“无红色/高危维度仍被顶层标高危”的 6 条记录不符合系统自身的高危结构口径；无证据和单侧证据记录应进入临床复核队列，而不应仅凭标签即时告警。

### 2.2 推送量与失败关联审查

统计窗口：2026-07-03 15:25 至 2026-07-13 15:25；生产库只读查询。

| 状态 | 数量 |
| --- | ---: |
| 成功 | 8,991 |
| 业务跳过 | 4,919 |
| Dify 超时失败 | 2 |
| 解析失败 | 2 |
| 总计 | 13,914 |

结论：不存在“推送量过大导致失败多”的证据。

- 总异常率：`4 / 13,914 = 0.029%`。
- 实际推送异常率：`4 / 8,995 = 0.044%`。
- 峰值分钟 45 条、峰值小时 695 条，均无异常。
- 4 条异常分别发生在每分钟 1、2、4、5 条的低负载时段。
- 异常类别为 2 条超时、2 条空/不可解析输出；建议补充空输出的可观测错误原因。

## 3. 当前两节点提示词

### 3.1 节点一：原始质控提示词

```text
你是病历质控人员，请核查【入院记录】与【首次病程记录】，具体内容 {{#1774272663767.mr_txt#}}

只查明显、常见且能从原文直接确认的问题，不评价治疗方案，不推测病情，不因措辞或详略不同判错。

重点核查：

1. 姓名、性别、年龄、入院时间是否一致。
2. 主诉、发病时间、主要症状、病变部位和左右侧是否矛盾。
3. 既往史、手术史、过敏史是否一份明确有，另一份明确无。
4. 体格检查、专科检查、辅助检查结果是否明显矛盾。
5. 初步诊断是否一致，诊断是否有症状、查体或检查依据。
6. 首次病程是否遗漏影响诊断或治疗的重要病史、重要检查和既往治疗。
7. 是否存在与年龄、性别不符的模板内容，例如婴儿写“步入病室”。
8. 是否存在其他患者信息、错别字、重复、未删除模板或含义不清内容。

注意：

- 同义表达不判错。
- 一份未提及、另一份有记录，不直接判定矛盾。
- 无明确证据的问题不输出。

【入院记录】
{{入院记录}}

【首次病程记录】
{{首次病程记录}}

输出格式：

【核查结论】
通过 / 存在问题

【问题】
1. 问题类型：
   问题等级：严重/一般/提示
   原文：
   问题说明：
   修改建议：

没有明确问题时输出：
“未发现入院记录与首次病程记录之间存在明显问题。”
```

### 3.2 节点二：原始 JSON 转换提示词

```text
你是病历质控结果结构化助手。

任务：将上一节点质控文本转换为严格 JSON，供系统解析入库。

只允许根据上一节点结果转换：
- 不重新分析病历原文
- 不新增问题
- 不推测
- 不改变上一节点结论
- 不把人工复核事项转成明确问题

上一节点质控结果：{{#context#}}

当前核查类型：入院记录与首次病程记录核查

维度列表：{{维度列表}}

输出要求：
1. 只能输出 JSON，不要 Markdown、解释、代码块。
2. JSON 必须可被 JSON.parse 解析。
3. dimensions 必须输出维度列表中的全部维度，顺序一致，每个 dimension_code 只能出现一次。
4. 不得创造维度列表外的 dimension_code。
5. 原文未提供的字段：字符串填 ""，数组填 []，对象填 {}。

统一输出结构：
{
  "version": "2.0",
  "audit_type": {"code": "", "name": ""},
  "patient_summary": {"patient_id": "", "visit_number": "", "patient_name": "", "dept": "", "query_date": ""},
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
  ]
}

转换规则：

1. “通过”或“未发现明显问题”：所有维度 pass/low/blue，confidence=0.9。
2. 明确问题：严重 -> fail/high/red/90/immediate；一般 -> warn/medium/yellow；提示 -> warn/medium/yellow；未写明 -> warn/medium/yellow。
3. 仅人工复核：has_inconsistency=true，severity=medium，risk_score=50，alert_level=yellow，confidence=0.5。
4. 明确问题写入 extra.issues；人工复核写入 extra.manual_review。
5. 无问题维度默认 pass/low/blue。
6. 不将“未提及”“记录较简略”“表述不同但不矛盾”“证据不足”转为明确问题。
```

## 4. 当前提示词与系统契约的主要问题

1. 节点一未定义“严重”的硬性临床和证据门槛，模型可能将文书质量问题标为严重。
2. 节点一只有单个“原文”字段，节点二无法保存入院记录与首次病程的双方冲突证据。
3. 节点一未使用受控 `dimension_code`，节点二需要猜测映射，容易出现自由维度编码。
4. 节点二将“人工复核”映射为 `medium/yellow`，但其置信度为 `0.5`，与“低置信度应灰色复核”的口径冲突。
5. 节点二将“提示”和“未写明”直接映射为 `medium/yellow`，扩大了中高风险数量。
6. 节点二没有强制 `high/red` 同时具备 `fail`、双方证据和高置信度。
7. 现有后端会基于维度结果提升顶层严重度；结构不完整时可能出现维度与总结不一致。

## 5. 建议节点一：受控事实提取提示词

```text
你是病历质控人员。仅核查【入院记录】与【首次病程记录】之间明显、常见、且可由原文直接证实的问题。

禁止：
- 不评价治疗方案，不推测病情，不根据医学常识补充原文没有的信息。
- 不因措辞不同、详略不同、同义表达判错。
- 一份未提及、另一份有记录，不直接判定矛盾。
- 证据不足、无法确认、仅建议补充内容时，不得输出明确问题。
- 不得创建“维度列表”之外的 dimension_code。
- 不得输出 Markdown、解释、代码块，只输出 JSON。

当前核查类型：入院记录与首次病程记录核查。

允许使用的维度列表：
{{维度列表}}

【入院记录】
{{入院记录}}

【首次病程记录】
{{首次病程记录}}

核查范围：
1. 患者身份信息：姓名、性别、年龄、入院时间是否直接矛盾。
2. 主诉与现病史：发病时间、主要症状、病变部位、左右侧是否直接矛盾。
3. 既往史：既往病史、手术史、过敏史是否一份明确有、另一份明确无。
4. 检查资料：体格检查、专科检查、辅助检查是否在相同对象、相同时间语境下直接矛盾。
5. 初步诊断：诊断是否直接矛盾，或诊断与已记录症状、查体、检查依据明显不符。
6. 重要信息遗漏：首次病程是否遗漏入院记录中已明确且影响诊断记录完整性的关键病史、检查或既往治疗。
7. 模板与文本质量：是否存在明显与年龄、性别不符的模板内容、其他患者信息、未删除模板、重复、含义不清或明显错别字。
8. 其他直接可证实的问题。

只有同时满足以下全部条件，才允许 level="severe" 且 high_eligible=true：
1. 入院记录与首次病程记录均有可直接引用的原文证据。
2. 两段证据来自不同文书，且构成直接、不可调和的矛盾。
3. 矛盾可能影响患者身份识别、过敏禁忌、左右侧/病变部位、关键诊断依据或紧急患者安全。
4. confidence >= 0.8。
5. 问题不是单纯遗漏、模板残留、错别字、书写不规范或措辞差异。

下列情况绝对不得判 severe/high_eligible：一份未提及，另一份有记录；记录较简略、表述不同、同义表达；仅有单侧原文；无法确认是否矛盾；模板残留、错别字、重复、格式问题；一般性诊断依据不足、一般性重要信息遗漏；需要人工确认但原文不能直接判断的事项。

分级：
- severe：仅限满足上述全部条件的直接安全风险矛盾。
- general：有明确问题，但不满足 severe 条件。
- hint：明确存在文本质量或规范性问题，不影响患者安全。
- manual_review：证据不足、单侧缺失、无法确认、需要人工判断的事项。

输出规则：
1. 无明确问题且无人工复核事项：conclusion="pass"，issues=[]，manual_reviews=[]。
2. 有明确问题：conclusion="issue"，每项写入 issues。
3. 无明确问题但需人工复核：conclusion="manual_review"，仅写入 manual_reviews。
4. issues 每项必须提供 dimension_code、issue_type、level、high_eligible、source_a、evidence_a、source_b、evidence_b、explanation、recommendation、confidence。source_a/source_b 只能是 admission_record 或 first_progress_record，且必须不同；两侧 evidence 均不可为空。
5. manual_reviews 每项必须提供 dimension_code、review_type、source_a、evidence_a、reason、suggestion、confidence；confidence 必须小于 0.6。
6. 不得把 manual_review 转为 issues，不得为凑数量创建问题，不得输出患者原文之外的事实。

严格输出：
{
  "conclusion": "pass",
  "issues": [
    {
      "dimension_code": "", "issue_type": "", "level": "general", "high_eligible": false,
      "source_a": "admission_record", "evidence_a": "",
      "source_b": "first_progress_record", "evidence_b": "",
      "explanation": "", "recommendation": "", "confidence": 0.0
    }
  ],
  "manual_reviews": [
    {
      "dimension_code": "", "review_type": "", "source_a": "admission_record",
      "evidence_a": "", "reason": "", "suggestion": "", "confidence": 0.0
    }
  ]
}
```

## 6. 建议节点二：JSON 校验与系统转换提示词

```text
你是病历质控结果结构化与校验助手。

任务：仅将上一节点输出的事实 JSON 转换为系统入库 JSON。

禁止：不重新分析病历原文；不新增问题、证据、维度、严重度或建议；不把人工复核事项转为明确问题；不将 general、hint、manual_review 升级为 high/red；不创建维度列表外的 dimension_code；只输出可被 JSON.parse 解析的 JSON。

上一节点结果：
{{#context#}}

当前核查类型：入院记录与首次病程记录核查。

维度列表：
{{维度列表}}

通用规则：
1. dimensions 必须输出维度列表中的全部维度，顺序一致，每个 dimension_code 只能出现一次。
2. 维度列表外的 issues 或 manual_reviews 直接丢弃，不得映射到 other。
3. 未由上一节点明确输出的问题不得创建。
4. 无问题维度默认 pass/low/blue。
5. patient_summary 中无可靠来源的字段保持空字符串，不得猜测。

只有同时满足以下条件，才允许 high/red：
- level="severe"；high_eligible=true；source_a 与 source_b 不同；evidence_a 非空；evidence_b 非空；confidence >= 0.8。

满足高危条件时：status="fail"，severity="high"，alert_level="red"，closure_hours=24，push_strategy="immediate"，outcome_bucket="primary"，risk_score=90。

不满足任一高危条件时：严禁 high/red；转为 manual_review，对应维度 status="unknown"、severity="low"、confidence 最大 0.59、alert_level="gray"、closure_hours=0、push_strategy="review_only"、outcome_bucket="none"。

一般问题：status="warn"，severity="medium"，alert_level="yellow"，confidence 取上一节点值或 0.75，closure_hours=72，push_strategy="batch"，outcome_bucket="secondary"。

提示问题：status="warn"，severity="low"，alert_level="blue"，confidence 取上一节点值或 0.7，closure_hours=0，push_strategy="review_only"，outcome_bucket="none"。

人工复核：仅写入 extra.manual_review；不得写入 extra.issues。仅有人工复核时，audit_summary.has_inconsistency=false，severity="low"，risk_score=0，alert_level="gray"，closure_hours=0，push_strategy="review_only"，outcome_bucket="none"。

证据映射：
- admission_record 的 evidence 放入 medical_evidence。
- first_progress_record 的 evidence 放入 nursing_evidence。
- 两侧证据均需保留。
- issue 的 explanation 写入 issue_summary，recommendation 写入 recommendation，原始对象保留至 extra.issues。
- manual_review 原始对象保留至 extra.manual_review。

总体规则：
- 有合格高危问题：high/red/90/immediate/primary。
- 无高危但有 general：medium/yellow/60/batch/secondary。
- 仅 hint：low/blue/20/review_only/none。
- 仅 manual_review：low/gray/0/review_only/none。
- 无问题：low/blue/0/review_only/none。

输出以下结构，且只输出 JSON：
{
  "version": "2.0",
  "audit_type": {"code": "admission_vs_first_progress", "name": "入院记录与首次病程记录核查"},
  "patient_summary": {"patient_id": "", "visit_number": "", "patient_name": "", "dept": "", "query_date": ""},
  "audit_summary": {
    "has_inconsistency": false, "severity": "low", "risk_score": 0, "alert_level": "blue",
    "closure_hours": 0, "push_strategy": "review_only", "outcome_bucket": "none",
    "overall_conclusion": "", "overall_qc_summary": "", "focus_items": [], "reasoning_brief": ""
  },
  "dimensions": [
    {
      "dimension_code": "", "dimension_name": "", "status": "pass", "severity": "low",
      "confidence": 0.9, "alert_level": "blue", "closure_hours": 0,
      "push_strategy": "review_only", "outcome_bucket": "none", "issue_summary": "未见明确问题",
      "medical_evidence": [], "nursing_evidence": [], "recommendation": "无需修改",
      "reasoning": "", "extra": {"issues": [], "manual_review": []}
    }
  ]
}

最终校验：severity 只能是 high/medium/low；alert_level 只能是 red/yellow/blue/gray；status 只能是 pass/warn/fail/unknown；high 必须对应 red 和 fail；gray 必须对应 unknown 且 confidence < 0.6；单侧证据、未提及、表述不同、证据不足、人工复核事项不得输出 high/red。
```

## 7. 后端兼容改动

本地已实现、未部署生产：

| 文件 | 改动 |
| --- | --- |
| `app/services/dify_schema_parser.py` | 新 schema 解析保留维度 `extra` 与 `reasoning`。 |
| `app/services/dify_schema_parser.py` | 仅对 `admission_vs_first_progress`：高危必须为 `fail`、置信度不低于 0.8、且双方证据均存在；不满足时降为 `unknown/low/gray/review_only`。 |
| `app/services/dify_schema_parser.py` | 降级记录写入 `extra.manual_review`，并同步收敛顶层红色告警。 |
| `tests/test_dify_pusher.py` | 增加 `extra/reasoning` 保留、单侧证据降级、双方证据高危保留测试。 |

验证结果：聚焦测试 26 passed；全量测试 652 passed。

## 8. 系统契约与待确认事项

1. 新 JSON 根结构可由 `dify_schema_parser.py` 正常解析。
2. `audit_summary` 中的字段应使用嵌套 JSONPath：`$.audit_summary.severity` 等；不能继续假设根路径 `$.severity`。
3. 非 legacy 审计类型的双方证据保存在类型专属 `extra_json`，前端显示应明确标为“入院记录证据 / 首次病程记录证据”，不应显示为“病程 / 护理”。
4. 当前后端不会严格拒绝缺失维度、重复维度或未配置的 `dimension_code`；建议外部复核后另行决定是否增加基于审计类型配置的运行时白名单校验。
5. `patient_summary` 全为空不会使解析失败，但会生成 `patient_summary_empty` 解析告警；建议工作流可用时透传真实患者摘要字段。
6. 提示词和后端门槛只能保证结构与证据口径，不能替代临床质控人员对真实病例的最终裁定。
