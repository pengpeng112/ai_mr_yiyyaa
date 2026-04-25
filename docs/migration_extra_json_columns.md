# ADR-1: AuditDimensionResult / AuditConclusion extra_json 列迁移

## 背景

当前 `AuditDimensionResult` 与 `AuditConclusion` 均无 `extra_json` 列；`AuditDimensionResult` 仅有 `medical_evidence_json` / `nursing_evidence_json` 两个病程护理硬编码列，对 lab/exam、frontpage/first_progress 语义错位。

## 决策

- 新增通用列 `extra_json TEXT DEFAULT '{}'`（`AuditDimensionResult` 与 `AuditConclusion` 各加一列）。
- 旧 `medical_*` / `nursing_*` 列对新类型 **置空不复用**，避免误读。
- `database.py._migrate_xxx_columns` 加 ALTER TABLE，覆盖 SQLite/Oracle/PostgreSQL 三库。
- `_save_audit_results` 对无 `extra_json` 列时降级为 try/except，向下兼容回滚。

## 影响范围

- `app/models.py`: `AuditDimensionResult.extra_json`, `AuditConclusion.extra_json`
- `app/database.py`: `_migrate_audit_dimension_result_columns`, `_migrate_audit_conclusion_columns`, `_verify_required_schema`
- `app/services/push_executor.py`: `_save_audit_results` 写入逻辑 + 降级 try/except
- `app/schemas.py`: `AuditDimensionItem.extra_json`

## 回滚策略

若需回滚到旧版本：
1. 旧代码不感知 `extra_json` 列，读取时忽略，不影响。
2. 若旧代码写入同一行，会覆盖 `extra_json` 为默认值 `{}`，数据不丢失（因为旧字段仍独立存在）。
3. 降级测试已覆盖：`_save_audit_results` 中 try/except 会在旧库无列时静默跳过。

## 验证

- `tests/test_audit_dimension_extra_json.py` 通过
- SQLite 二次启动幂等（不重复 ALTER 报错）
- 旧 audit type `progress_vs_nursing` 落库行为不变
