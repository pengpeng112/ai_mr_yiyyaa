# 数据库整改契约

## 1. 先发现实际 schema

执行前从 SQLAlchemy metadata/数据库字典只读确认表名、前缀、字段和约束。不得假设开发环境的 SQLite 名称等于生产 Oracle 名称。

核心实体：

- `PushLog`：患者、访次、顶层严重度、告警级别、解析状态、`dept`、请求/响应 JSON。
- `AuditDimensionResult`：维度级状态、严重度、告警级别、置信度和双方证据。
- `AuditConclusion`：汇总结论、严重度、风险分和告警级别。
- `QCRecordAlertLog` / 反馈相关表：已发送/待发送/科室过滤告警的历史事实。

### 1.1 证据字段落库现实（整改必须知道）

当前 `map_dimension_row` 对 **非 legacy** 审计类型会把：

- `medical_evidence_json` / `nursing_evidence_json` 写成 `[]`；
- 实际文本进 `medical_content` / `nursing_content`；
- 结构化 issue 进 `extra_json`（含 `issues[]` 的 evidence_a/b、safety_category 等）。

因此：

- 只读/复核时必须读 content + extra，不能只看 evidence 数组列。
- dry-run/回写前若需重算硬门槛，优先从 **未改动的** `PushLog.response_json` 重解析，或从 content/extra 还原证据，不得因数组列为 `[]` 误判“无证据”。
- 本技能默认**不**借整改顺带改 mapper 或补写历史 evidence 数组；若要修落库契约，须另开开发任务与批准。

不得修改 Dify 原始响应。`request_json` 仅允许补充缺失的 `patient_info` 科室字段，并必须保留其他键和值。

## 2. 严重度一致性

对批准降级的维度，目标枚举必须保持内部一致：

- 正常且有一致性证据：`status=pass`, `severity=low`, `alert_level=blue`。
- 证据不足/无法判定：`status=unknown`, `severity=low`, `alert_level=gray`，并保留 manual-review 语义。
- 中危：使用现役契约认可的 `warn/medium/yellow` 组合。

不要把“证据不足”改成 `pass/blue`。更新维度后，调用或复用生产聚合逻辑重算结论和 PushLog；禁止用手写常量跳过聚合。

如果历史 schema 还包含 `closure_hours`、`push_strategy`、`outcome_bucket`、`risk_score`，必须按现役映射一并重算，不能留下 `low + red`、`pass + immediate` 等矛盾组合。

### 2.1 从库行还原 dim 以跑形式门槛

非 legacy 类型常见 `medical_evidence_json`/`nursing_evidence_json` 为 `[]`。跑 `_qualified_high_risk_issue` 前必须：

1. `medical_evidence` ← 非空 evidence 数组，否则用 `medical_content` 作为单元素列表；
2. `nursing_evidence` 同理；
3. `extra` ← `extra_json`（含 `issues[]`）。

优先路径仍是未改动的 `PushLog.response_json` 完整重解析；库行还原用于批量只读基线与无 response 场景。

### 2.2 默认不触碰的字段

除非批准清单逐字段写明，否则禁止修改：

- `PushLog.reviewed_flag` / `manual_override` / `skip_reason`
- `PushLog.response_json` / 原始 Dify 原文类字段
- 医生反馈、`QCAlertFeedback`、已成功告警的发送事实字段

降级只更新：获批维度的 status/severity/alert_level/派生策略字段 + 重算后的 conclusion 与 PushLog 顶层等级相关字段 + 可选的审计化 suppression（若服务支持）。

## 3. 告警历史处理

- 已发送成功的告警（如 `success`/`sent`）：永久保留发送记录，不修改成未发送，不删除 payload 审计事实。
- 待发送或失败且对应结果已获准降级：仅在确认现有服务支持审计化 suppression 时标记抑制；否则停止并提交设计。
- **`dept_filtered`**：科室白名单过滤，**不是发送成功**，也不是“待补发”。对应 high 若获准降级，一般只改质控等级；不创建真实外发、不把 filtered 改成 success。
- 不得触发真实企微、H5、Dify 或患者通知作为测试。
- 不得因为历史结果降级而自动撤回医生已提交的反馈。

## 4. 科室字段映射

业务视图使用 `JHEMR.V_QYBR`，精确键为：

```text
PushLog.patient_id    <-> V_QYBR."患者ID"
PushLog.visit_number  <-> V_QYBR."次数"
```

用户说的 `visit_id` 必须先证明就是该 `visit_number/次数`；无法证明时停止。

字段映射：

```text
patient_info.inpatient_dept_code  <- "所在科室编码"
patient_info.inpatient_dept_name  <- "所在科室名称"
patient_info.discharge_dept_code  <- "出院科室编码"
patient_info.discharge_dept_name  <- "出院科室名称"
patient_info.admission_dept_name  <- "入院科室名称"
PushLog.dept                      <- "所在科室名称"，为空时才回退到"出院科室名称"
patient_info.dept/department      <- 与 PushLog.dept 相同的规范名称
patient_info.dept_code            <- "所在科室编码"，为空时才回退到"出院科室编码"
```

Oracle 空字符串等同 NULL。只填补空/缺失字段：

- 目标非空且与视图相同：跳过，计为 already_complete。
- 目标非空但与视图不同：不覆盖，计为 conflict。
- 视图无匹配：不更新，计为 no_match。
- 复合键存在多条且无法确定唯一有效行：不更新，计为 ambiguous。
- patient_id 或 visit_number 缺失：不更新，计为 invalid_key。

优先复用 `app.utils.patient_dept_query.query_patient_dept()`。不要引用不存在的“在院科室”列；真实列名是“所在科室”。

注意：该函数在复合键命中多行时按“出院日期、入院日期”倒序取第一行。单条在线补全可以沿用这一既有行为；历史批量整改必须先统计重复复合键。重复记录是否确属同一有效住院行需业务库负责人确认，在确认前归入 `ambiguous`，不得自动回填。

## 5. 事务、幂等与审计

- dry-run 必须是默认模式。
- 所有写入按批准的主键清单执行，不能重新运行一个可能变化的宽泛 WHERE 条件。
- 写前使用 optimistic check：当前值必须等于快照 before 值。
- 每批最多 100 条维度或 PushLog；每批独立提交和验证。
- 重复运行同一批准清单应产生 0 个新增修改并报告 already_applied。
- before/after 快照、批准清单、错误清单和执行日志写入宿主机持久化备份目录，权限最小化，并计算 SHA-256。
- 回滚脚本只能从相同 run_id 的 before 快照生成；执行回滚仍需书面批准。
