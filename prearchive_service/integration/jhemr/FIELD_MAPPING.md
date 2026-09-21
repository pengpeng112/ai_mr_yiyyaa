# 字段对照表（JHEMR ↔ Med-Audit，046 T7）

对接时以本表冻结字段口径；未列字段不承诺。TEST 值仅用于本地 L1 演示。

| 主题 | JHEMR 侧 | Med-Audit 侧 | 说明 |
| --- | --- | --- | --- |
| 患者 | `patient_id` | `JHEMR.V_QYBR."患者ID"` → RunRow.patient_id | 字符串，保留前导零；TEST 前缀=TEST0001/2/3 |
| 就诊 | `visit_number` | `JHEMR.V_QYBR."次数"` → RunRow.visit_number | 锚点源按 (patient_id, visit_id) 回查；fixtures 中 visit_id=visit_number="1" |
| 提交动作 | `submission_id` | RunRow.submission_id | 幂等键：同值复用既有检查（仅 failed 重建） |
| 医生 | `operator.id/.name/.dept_code` | IssueActionRow.operator_id/name；审计 | 服务账号签名≠医生身份；医生身份全部来自 operator 并审计 |
| 文书引用 | `document_refs[].doc_id/revision` | 票据/审计与 issue.document_revision | 经确认的定位引用；Med-Audit 不猜嘉和打开文书的命令，未知时退化为本系统证据位置 |
| 检查任务 | `check_id` | RunRow.id（=run_id） | GET 路径直接使用 |
| 复检 | rechecks → `check_id` | 新 RunRow（trigger_type=manual_recheck，run_revision+1） | 原锚点未变也生成新 revision |
| 缺陷 | `issues[].issue_id` | IssueRow.id（issue_key=pid\|vid\|rule\|event 稳定） | 生命周期不换 ID；人工状态与引擎结论分离 |
| 评分项 | `issues[].fid` | COVERAGE_MAP（92 目录 FID） | null=非无纸化评分项关联规则 |
| 严重级 | `issues[].severity` | low/medium/high | 参考扣分分值≠高风险，不用于自动升级 |
| 状态 | `issues[].status` | open/viewed/rectifying/resolved/false_positive/manual_closed | `rectified` 动作→rectifying（待复检），不改判通过 |
| 检查结论 | `summary.status` | pass/fail/unknown/pending/not_run | 全排除/零规则=not_run，不显示"全部通过" |
| 提交策略 | `submission_policy` | 固定 notify_only | 提醒不阻断；临床强制拦截不在本期范围 |
| 触发类型 | — | emr_submit / manual_recheck / paperless_rpa | JHEMR 提交=emr_submit；整改复检=manual_recheck |
| 票据 | `ticket_nonce` | ViewTicketRow.nonce（一次性，默认 300s） | 绑定 patient+visit+operator+scope；过期/重放/换人拒绝 |

## 时间口径

- `submitted_at`/`checked_at`/`data_snapshot_at`：`YYYY-MM-DD HH:MM:SS`（Asia/Shanghai）；
- 签名 `X-Jhemr-Timestamp`：unix 秒，偏差窗 ±300s；
- 规则时限判定全部按 Asia/Shanghai 比较（046 §5.2）。
