# Task 2 — 四类数据源字段映射与日期归一契约

## 统一核心字段

所有 source 在进入聚合/builder 前，统一补齐 canonical 字段：

- `patient_id`
- `visit_number`
- `event_time`
- `audit_date`（`YYYY-MM-DD`）
- `record_id`
- `record_name`
- `content`

其中 `patient_id`、`visit_number` 为分组必需字段，缺失时该记录跳过并记录 reason。

## 各 source 扩展字段

### lab

- `test_no`
- `result_time`
- `specimen`
- `item_name`
- `report_item_code`
- `result`
- `units`
- `abnormal_indicator`
- `print_context`

### exam

- `exam_no`
- `exam_time`
- `exam_class`
- `description`
- `impression`
- `recommendation`
- `is_abnormal`

### progress / nursing

- 基于核心字段：`event_time`、`record_id`、`record_name`、`content`

## 日期归一规则

- 目标格式：`YYYY-MM-DD`
- 允许输入：`datetime/date` 对象、`YYYY-MM-DD`、`YYYY/MM/DD`、`YYYY.MM.DD`、`YYYY-MM-DD HH:MM(:SS)`、`YYYYMMDD`、`YYYYMMDDHHMMSS`、中文日期（如 `2026年04月26日`）
- 解析优先级：
  - `lab`: `result_time` → `event_time`
  - `exam`: `exam_time` → `event_time`
  - `progress/nursing/first_progress`: `event_time`
  - `frontpage`: `event_time` → `discharge_date` → `admission_date`
  - 全部失败时回退 `query_date`
- 若仍无法得到合法日期，记录 skip reason：`invalid_audit_date`

## 跳过策略（可诊断）

- `missing_group_fields:patient_id,visit_number`：分组必需字段缺失
- `invalid_audit_date`：`audit_date` 无法归一

跳过记录不会抛 `KeyError`，由 loader 记录 info 日志并继续处理后续数据。

## progress follow-up window（Task 5）

- 当 `group_key` 包含 `audit_date` 且配置 `progress_followup_days > 0` 时：
  - `progress` 记录若 `record.audit_date` 在 `query_date + [1, progress_followup_days]` 范围内
  - 会并入 `query_date` 对应 bundle（仅作为上下文补充）
  - 原始记录 `audit_date` 保留，并标记 `is_followup_progress=true`
- 该策略不改变 lab/exam 的主 `audit_date` 分组。

## 代码落点

- `app/services/source_field_contract.py`
  - `normalize_date_to_ymd`
  - `normalize_source_record`
- `app/services/data_source_loader.py`
  - 每条记录先做 contract normalize，再入 bundle
