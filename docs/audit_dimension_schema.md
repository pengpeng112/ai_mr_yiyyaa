# ADR-2: 审计维度数组项子字段映射协议

## 决策：方案 A（统一核心字段 + extra 扩展）

### 核心字段（所有 audit type 通用）

维度数组每项必须包含以下核心字段：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| dimension_code | string | 维度编码，如 "lab_consistency" |
| dimension | string | 维度名称，如 "检验一致性" |
| severity | string | 严重程度：high / medium / low / info |
| issue_summary | string | 问题摘要 |
| recommendation | string | 整改建议 |
| confidence | float | 置信度 0-1 |

### 扩展字段（类型专属证据）

所有非核心字段统一放入 `extra` 对象，由 `_save_audit_results` 序列化到 `AuditDimensionResult.extra_json`。

示例：

```json
{
  "dimension_code": "lab_abnormal_not_documented",
  "dimension": "异常检验未在病程记录",
  "severity": "high",
  "issue_summary": "白细胞 15.2×10⁹/L 异常升高，病程记录未提及",
  "recommendation": "补充记录感染相关评估及处理措施",
  "confidence": 0.92,
  "extra": {
    "evidence_lab": {
      "test_no": "T20250425001",
      "item_name": "白细胞计数",
      "result": "15.2",
      "units": "10^9/L",
      "abnormal_indicator": "H"
    },
    "evidence_progress": {
      "mrid": "49557032X-00001834-2-7-0-13",
      "record_date": "2025-10-14",
      "has_mention": false
    }
  }
}
```

## 三类 Audit Type 的落库对照表

### 1. progress_vs_nursing（旧类型，兼容）

Dify Response 示例：
```json
{
  "dimensions": [
    {
      "dimension_code": "diagnosis_consistency",
      "dimension": "诊断一致性",
      "severity": "medium",
      "issue_summary": "病程记录与护理记录诊断名称不一致",
      "recommendation": "统一使用标准诊断名称",
      "confidence": 0.85,
      "medical_evidence": [{"mrid": "mr-001", "content": "冠心病"}],
      "nursing_evidence": [{"record_id": "nr-001", "content": "冠状动脉粥样硬化性心脏病"}]
    }
  ]
}
```

落库结果：
- `medical_evidence_json` = `[{"mrid": "mr-001", "content": "冠心病"}]`
- `nursing_evidence_json` = `[{"record_id": "nr-001", "content": "冠状动脉粥样硬化性心脏病"}]`
- `extra_json` = `"{}"`（无 extra 字段时为空对象）

### 2. lab_exam_vs_progress_nursing（新类型）

Dify Response 示例：
```json
{
  "dimensions": [
    {
      "dimension_code": "lab_abnormal_omission",
      "dimension": "异常检验项遗漏",
      "severity": "high",
      "issue_summary": "血红蛋白 85g/L 降低，病程未记录贫血评估",
      "recommendation": "补充贫血原因分析及处理计划",
      "confidence": 0.95,
      "extra": {
        "evidence_lab": {
          "test_no": "T001",
          "item_name": "血红蛋白",
          "result": "85",
          "abnormal_indicator": "L"
        },
        "evidence_progress": {
          "mrid": "mr-001",
          "has_mention": false
        }
      }
    }
  ]
}
```

落库结果：
- `medical_evidence_json` = `"[]"`（新类型不走此字段）
- `nursing_evidence_json` = `"[]"`（新类型不走此字段）
- `extra_json` = `'{"evidence_lab": {...}, "evidence_progress": {...}}'`

### 3. frontpage_surgery_diagnosis_vs_first_progress（新类型）

Dify Response 示例：
```json
{
  "dimensions": [
    {
      "dimension_code": "operation_name_mismatch",
      "dimension": "手术名称不一致",
      "severity": "medium",
      "issue_summary": "首页记录"完壁式乳突改良根治术"，首次病程简写为"乳突手术"",
      "recommendation": "统一使用标准手术名称",
      "confidence": 0.88,
      "extra": {
        "evidence_frontpage": {
          "operation_name": "完壁式乳突改良根治术",
          "operation_code": "20.4900x009",
          "operation_date": "2026-02-11"
        },
        "evidence_first_progress": {
          "mrid": "49557032X-00004963-2-3-0-13",
          "description": "行乳突手术"
        }
      }
    }
  ]
}
```

落库结果：
- `medical_evidence_json` = `"[]"`
- `nursing_evidence_json` = `"[]"`
- `extra_json` = `'{"evidence_frontpage": {...}, "evidence_first_progress": {...}}'`

## 向后兼容性

- 旧 `progress_vs_nursing` 的 `medical_evidence` / `nursing_evidence` 仍走原字段，保持不变
- 新类型专属证据统一走 `extra_json`，不污染旧字段
- `_save_audit_results` 对未知字段记录 warning 日志，不崩溃

## 文件变更

- `app/services/audit_type_registry.py`: 顶部 docstring 写入协议说明
- `app/services/push_executor.py`: `_save_audit_results` 支持 extra 字段，增加未知字段检测
- `docs/audit_dimension_schema.md`: 本文档
