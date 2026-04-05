只输出 JSON，不要输出 Markdown 代码块，不要输出额外说明。patient_summary.patient_id / visit_number / patient_name / dept / query_date 必须直接使用输入变量原值，不允许模型推断、改写或占位。

## 固定要求
- 必须输出 6 个维度，每个 `dimension_code` 只出现一次。
- 字段名必须全部使用英文，并严格匹配下方结构。
- `alert_level` 只能是：`red|yellow|blue|gray`
- `severity` 只能是：`high|medium|low`
- `push_strategy` 只能是：`immediate|batch|shift_summary|review_only`
- `outcome_bucket` 只能是：`primary|secondary|none`
- `confidence < 0.6` 时，该维度 `alert_level` 必须为 `gray`
- `audit_summary.alert_level` 取维度中的最高级别：`red > yellow > blue > gray`
- `audit_summary.severity` 按映射：`red→high`，`yellow→medium`，`blue/gray→low`

## JSON 结构
{
  "version": "2.0",
  "patient_summary": {
    "patient_id": "患者ID",
    "visit_number": "住院次数",
    "patient_name": "患者姓名",
    "dept": "所在科室",
    "query_date": "核查日期 yyyy-mm-dd"
  },
  "audit_summary": {
    "has_inconsistency": true,
    "severity": "high|medium|low",
    "risk_score": 0,
    "alert_level": "red|yellow|blue|gray",
    "closure_hours": 24,
    "push_strategy": "immediate|batch|shift_summary|review_only",
    "outcome_bucket": "primary|secondary|none",
    "overall_conclusion": "一句话总体结论",
    "overall_qc_summary": "2-4句整体质控总结",
    "focus_items": ["重点关注项1", "重点关注项2"],
    "reasoning_brief": "简要推理说明"
  },
  "dimensions": [
    {
      "dimension_code": "diagnosis_consistency|nursing_level_consistency|vital_sign_consistency|condition_consistency|treatment_measure_consistency|timeline_consistency",
      "dimension_name": "维度中文名",
      "status": "pass|warn|fail|unknown",
      "severity": "high|medium|low",
      "confidence": 0.0,
      "alert_level": "red|yellow|blue|gray",
      "closure_hours": 0,
      "push_strategy": "immediate|batch|shift_summary|review_only",
      "outcome_bucket": "primary|secondary|none",
      "issue_summary": "问题摘要",
      "medical_evidence": ["病程记录证据"],
      "nursing_evidence": ["护理记录证据"],
      "recommendation": "建议措施"
    }
  ],
  "raw_judgement": {
    "consistency_label": "一致|不一致|部分一致",
    "reasoning_brief": "简要推理说明"
  }
}

## 额外说明
- `pass` 维度通常对应 `blue`。
- 如果证据不足但不能确定有问题，用 `unknown` + `gray`。
- 如果存在明确冲突，优先 `fail`，再按风险给 `red` 或 `yellow`。