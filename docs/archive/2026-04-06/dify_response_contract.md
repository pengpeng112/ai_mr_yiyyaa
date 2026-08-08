# Task 3 — 多核查类型 Dify 输入/输出契约

## 输入命名约定

- Builder 输出字段固定为：`mr_text`
- Dify Workflow 入参变量默认：`mr_txt`
- 二者通过 `workflow_input_variable` 映射，不在 builder 层混用命名

## `lab_exam_vs_progress_nursing` 的 `mr_text` 推荐结构

```text
[patient_info]
- patient_id: ...
- visit_number: ...
- patient_name: ...
- dept: ...

[audit_date]
- audit_date: YYYY-MM-DD

[abnormal_labs]
- ...

[abnormal_exams]
- ...

[progress_notes]
- ...

[nursing_records]
- ...

[check_rules]
- ...
```

## `frontpage_surgery_diagnosis_vs_first_progress` 的 `mr_text` 推荐结构

```text
[patient_info]
- patient_id: ...
- visit_number: ...
- patient_name: ...

[admission_discharge_info]
- ...

[diagnoses]
- ...

[surgeries]
- ...

[selected_first_progress]
- ...

[check_rules]
- ...

[warnings]
- ...
```

## 推荐 AI 输出 JSON

```json
{
  "overall_conclusion": "...",
  "inconsistency": true,
  "severity": "high",
  "risk_score": 80,
  "dimensions": [
    {
      "dimension_code": "diagnosis_consistency",
      "dimension": "诊断一致性",
      "severity": "high",
      "issue_summary": "...",
      "recommendation": "...",
      "confidence": 0.92,
      "extra": {
        "evidence_lab": [],
        "evidence_exam": [],
        "evidence_progress": [],
        "evidence_nursing": [],
        "evidence_frontpage": [],
        "evidence_first_progress": []
      }
    }
  ]
}
```

> ADR-2 决议：`dimensions[]` 只保留核心字段，专属证据统一放 `extra`。

## response_paths 默认 JSONPath

```json
{
  "dimension_path": "$.dimensions",
  "conclusion_path": "$.overall_conclusion",
  "severity_path": "$.severity",
  "risk_score_path": "$.risk_score",
  "inconsistency_path": "$.inconsistency"
}
```

## 配置异常降级规则

- 当配置了 response_paths 但全部无匹配时：`parse_warning = "response_path_no_match"`
- 系统不得沉默落库空 dimensions，应可观测告警并保留 raw response
