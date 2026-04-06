# Task 1 — 预警分级字段契约规格表

## 1. 四灯模型定义

| alert_level | 中文 | 语义 | closure_hours | push_strategy | outcome_bucket |
|---|---|---|---|---|---|
| `red` | 红灯 | 高风险，危及安全 | 24 | `immediate` | `primary` |
| `yellow` | 黄灯 | 中度风险，影响质量 | 72 | `batch` | `secondary` |
| `blue` | 蓝灯 | 低风险/规范性问题 | 0 | `shift_summary` | `none` |
| `gray` | 灰灯 | 不确定/置信度低 | 0 | `review_only` | `none` |

## 2. alert_level ↔ severity 兼容映射

| alert_level | → severity（自动派生） | 说明 |
|---|---|---|
| `red` | `high` | 1:1 |
| `yellow` | `medium` | 1:1 |
| `blue` | `low` | blue 属规范性/低风险 |
| `gray` | `low` | gray 无法确认风险，安全降级为 low |

**映射规则**：
- 当 Dify 输出包含 `alert_level` 时，`severity` 由映射自动派生（但 Dify 原始 severity 优先保留）
- 当 Dify 输出不包含 `alert_level`（v1 旧版），`severity` 维持原逻辑不变
- `alert_level` 与 `severity` 并存，**不替换**

## 3. 新增字段规格

### 3.1 audit_summary 级别（总体）

| 字段名 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `alert_level` | string | 否 | `""` | 总体最高预警灯号：red/yellow/blue/gray |
| `closure_hours` | int | 否 | `0` | 总体闭环时限（小时） |
| `push_strategy` | string | 否 | `""` | 总体推送策略：immediate/batch/shift_summary/review_only |
| `outcome_bucket` | string | 否 | `""` | 总体结局分桶：primary/secondary/none |
| `overall_qc_summary` | string | 否 | `""` | 整体病历质控结果描述（中文叙述） |

### 3.2 dimensions[] 级别（每维度）

| 字段名 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `alert_level` | string | 否 | `""` | 该维度预警灯号：red/yellow/blue/gray |
| `closure_hours` | int | 否 | `0` | 该维度闭环时限（小时） |
| `push_strategy` | string | 否 | `""` | 该维度推送策略 |
| `outcome_bucket` | string | 否 | `""` | 该维度结局分桶 |

### 3.3 固定 6 维度编码

| dimension_code | dimension_name |
|---|---|
| `diagnosis_consistency` | 诊断一致性 |
| `nursing_level_consistency` | 护理级别执行 |
| `vital_sign_consistency` | 生命体征交叉 |
| `condition_consistency` | 病情描述一致性 |
| `treatment_measure_consistency` | 诊疗措施执行 |
| `timeline_consistency` | 时间合理性 |

## 4. 数据库新增字段映射

### PushLog 表
| 新字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `alert_level` | VARCHAR(10) | `""` | 总体预警灯号 |

### AuditDimensionResult 表
| 新字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `alert_level` | VARCHAR(10) | `""` | 维度预警灯号 |
| `closure_hours` | INTEGER | `0` | 闭环时限 |
| `push_strategy` | VARCHAR(20) | `""` | 推送策略 |
| `outcome_bucket` | VARCHAR(20) | `""` | 结局分桶 |

### AuditConclusion 表
| 新字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `alert_level` | VARCHAR(10) | `""` | 总体预警灯号 |
| `closure_hours` | INTEGER | `0` | 闭环时限 |
| `push_strategy` | VARCHAR(20) | `""` | 推送策略 |
| `outcome_bucket` | VARCHAR(20) | `""` | 结局分桶 |
| `overall_qc_summary` | TEXT | `""` | 整体质控结果描述 |

## 5. 枚举值约束

- `alert_level`: `red | yellow | blue | gray | ""`（空字符串 = 未知/缺失）
- `push_strategy`: `immediate | batch | shift_summary | review_only | ""`
- `outcome_bucket`: `primary | secondary | none | ""`
- `closure_hours`: 非负整数（0 = 无闭环要求）
