# 数据与 Dify 契约

> 来源合并：`source_field_contract.md`、`audit_dimension_schema.md`、`dify_response_contract.md`、`migration_extra_json_columns.md`。

## 不变量

- Builder 和本地存储使用 `mr_text`；只有 `dify_pusher.py` 将其映射到 Dify 变量 `mr_txt`。
- 分组必填：`patient_id`、`visit_number`；缺失记录跳过并记录原因。
- 所有源归一为 `patient_id`、`visit_number`、`event_time`、`audit_date`、`record_id`、`record_name`、`content`。
- `audit_date` 统一为 `YYYY-MM-DD`；无法归一时使用 `invalid_audit_date`。

## 维度结果

`dimensions[]` 的核心字段：`dimension_code`、`dimension`、`severity`、`issue_summary`、`recommendation`、`confidence`。

- 旧病程/护理证据继续使用 `medical_evidence_json`、`nursing_evidence_json`。
- 类型专属证据使用 `extra`，持久化到 `AuditDimensionResult.extra_json`。
- `AuditConclusion.extra_json` 和 `AuditDimensionResult.extra_json` 为兼容扩展列；新增 ORM 字段必须同步 SQLite、Oracle 迁移与 schema 自检。

## Dify 输出

推荐顶层字段：`overall_conclusion`、`inconsistency`、`severity`、`risk_score`、`dimensions`。

默认 JSONPath：

```json
{
  "dimension_path": "$.dimensions",
  "conclusion_path": "$.overall_conclusion",
  "severity_path": "$.severity",
  "risk_score_path": "$.risk_score",
  "inconsistency_path": "$.inconsistency"
}
```

配置了 response paths 但全部不匹配时，必须保留原始响应并记录 `response_path_no_match`，不能静默落空维度。

---

## 增量修订（2026-08-29，031/T4-3，仅增量不重写）

- **024 语义降级开关**：高危严重度整改后，text_quality 硬门槛黑名单与语义降级配置开关
  落于 Dify 影子 V2 与后端 `audit_result_mapper` 路径（详见 024/025）；六类维度/JSONPath
  契约不变。
- **prearchive 数据面（新轨道，不进 Dify 主链路）**：`prearchive_service/` 独立采集
  （JHEMR/HIS/手麻/LIS + T8 新七源 + 无纸化 CDMS 元数据），规则 DSL 四判定器 +
  `doc_time_source: blws|file_index_topic`；其数据契约见 `prearchive_service/README.md`
  与 `docs/ACTIVE/030`（92 条评分项映射，待质控科签字）。
- **metrics 指标面**：`/api/metrics` 返回体 {requests{total,by_route[]},
  dify_latency{count/sum/min/max/avg/buckets}, scheduler_runs[]}——进程内存态。
