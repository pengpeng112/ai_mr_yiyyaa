# 015 整合整改执行计划（基于 014 交叉核查 + 当前代码核查）

> 文档编号：015
> 日期：2026-08-07（Asia/Shanghai）
> **状态：执行完成（A1–A4 / B1–B3 / C1）** — 2026-08-07
> 性质：整合执行计划；执行中曾获用户书面授权做 C1 生产只读核查与多当前清理 + 函数唯一索引
> 输入：014 交叉核查总报告（G1-G11 / 011 / 012 / 007-008 四轮核查）+ 2026-08-07 当前工作区代码核查
> 分支约束：当前工作分支 `fix/ora-12609-p4-error-code`；默认禁止 git 提交/push/建分支（除非用户另行授权）

## 0. 执行完成摘要（2026-08-07）

| 任务 | 结果 |
| --- | --- |
| A2 删 `_daily_push_job` | 已完成；仅保留 v2 |
| A4 relay 吞错补日志 | 已完成；查询/close 静默点改 warning |
| A3 historical_rerun detail 收口 | 已完成；`public_error_message` |
| A1 fanout 超时 | 已完成；复用 `_apply_query_timeout` + 2 测例 |
| B1/B2/B3 文档 | 011 force=False / 007 002 事实 / 116 复合 high 门槛 |
| C1 PushLog 当前唯一 | 生产：多当前 38857 行标 superseded（不删历史）；`duplicate_groups=0`；`uq_push_log_current_identity` 已建；本地迁移 + `scripts/remediate_pushlog_multi_current.py` |
| pytest | 901 passed（基线 891 未减少） |

本计划 **§1.2 开放项已全部关闭**。§1.3 本轮不执行项（011/P5 观察、012 双源、007/008 生产补跑、116 P1-01~03 等）**仍不在本计划授权内**，须按 013 主线与对应专项计划另批。

---

## 1. 关键前提：014 快照已过时，必须以当前代码为准

014 报告基于旧快照。**2026-08-07 对当前工作区逐项 grep 核查后**，014 中大部分安全项已修复。执行 AI 必须先按下表逐项验证当前代码状态，禁止按 014 描述盲目修改已修复代码。

### 1.1 已修复项（禁止重复修改）

| 014 项 | 当前状态 | 证据 |
| --- | --- | --- |
| G1 JWT 环境变量架空 | 已修复 | `app/auth.py:29-38` 统一 ENVIRONMENT/APP_ENV，冲突即 RuntimeError；生产门禁硬校验 |
| G2 默认管理员后门 | 已修复 | 全 `app/` 树 grep `_ensure_debug_admin_for_login` / `Admin123456` 零命中；`app/routers/users.py` 登录路径无重建逻辑 |
| G3 多 worker 防护 | 已修复 | `app/scheduler.py:131-136` 检测 workers>1 即禁用进程内调度器 |
| G6 匿名 notify/test SSRF | 已修复 | `app/routers/notify.py:28` 已加 `require_permission("manage_config")` + 开关函数 |
| G7 SQL 字面量绕过 | 已修复 | `app/db_client_base.py:42-44` 已剥离字符串字面量与 hint 注释再校验 |
| G8 health 无鉴权 | 已缓解 | `app/routers/health.py` 新增匿名 `/live` 轻探针（:38）+ 授权 `/ready`（:176，require_permission("view_scheduler")）；根路径匿名但走缓存（:165-172） |
| G10 report 漏 audit_type_code | 已修复 | `app/routers/report.py:60` 已传 |
| P1-04 配置接口明文 Key | 已修复 | `app/routers/config.py:410-422` `_mask_dify_targets_for_response` 脱敏 |
| P1-05 反馈越权 | 已修复 | `app/routers/qc_feedback.py:51` 非 admin 且 dept_id 不匹配即拦截 |
| P1-06 病历正文进日志 | 已修复 | `app/services/dify_log_utils.py` 指纹化（`_fingerprint_for_log`）+ 截断 + `_is_full_debug_log_enabled` 开关 |
| 007-S2 独立 supersede 策略 | 已实现 | `app/services/push_log_supersede.py:127` `mark_historical_reaudit_superseded`，已被 push_executor/bulk_push_executor/historical_rerun_service 调用 |

### 1.2 仍开放项（本计划执行范围）

| 编号 | 问题 | 位置 | 处置 |
| --- | --- | --- | --- |
| 011-CODE-1 | fanout worker 绕过 `_apply_query_timeout`，驼峰直写 `conn.callTimeout` 且 except 吞错 | `app/services/data_source_loader.py:455-459` | 任务 A1 |
| G11 | `_daily_push_job` 死代码（引用未定义 `db`，无调用方） | `app/scheduler.py:400` 起 | 任务 A2 |
| G5 残留 | `historical_rerun.py` 11 处 `detail=str(exc)` | `app/routers/historical_rerun.py:41,79,105,108,184,186,200,202,217,219,232` | 任务 A3 |
| G9 | relay_alert_service except 静默吞错 | `app/services/relay_alert_service.py:38-39`（已知一处，需全文 grep 确认） | 任务 A4 |
| 011-DOC-1 | 011 文档 force=True 过期描述（代码实际 force=False） | `docs/ACTIVE/011_*.md` S-08/A.7 | 任务 B1 |
| 007-M1/M2/M3 | 007 文档与代码事实不符 | `docs/ACTIVE/007_*.md` §3.1/§6.1/§4.2 | 任务 B2 |
| BLOCK-02 | 116 报告"依赖 extra.issues"表述不准确（漏维度级证据门槛） | `docs/reference/116_*.md` §3.2 | 任务 B3 |
| G4 | PushLog 无 (source_record_key, audit_type_code, audit_run_mode) 唯一约束 | `app/models.py:51`（仅普通索引） | 任务 C1（先核查后决定） |

### 1.3 本轮不执行项

| 项 | 原因 |
| --- | --- |
| 011/P5 连续调度观察、011/P1 镜像核对 | 生产运维项，本地不可执行 |
| 012/P0 配置冻结 + 乱码修复、012/P1 DBA 执行计划 | 需生产 SSH / DBA |
| 012/P2-P7 双源切换代码 | 独立大计划，依赖 012 P0/P1 门禁通过 |
| 116 P1-01/P1-02/P1-03 | 当前状态未核实，见 §5 不确定项 6 |
| 007/008 历史补跑本身 | 需书面批准 + 全部门禁通过 |

---

## 2. 绝对红线（违反即任务失败）

### 2.1 Dify 推送内容冻结（保证 Dify 可解析）

以下文件/逻辑**禁止任何修改**，推送入参必须与现状逐字节一致：

- `app/services/payload_composer.py` 全部（builder 调度 + text_template 渲染）
- `app/services/payload_builder.py` 全部（legacy builder、中英文字段别名映射）
- `app/dify_pusher.py:99-116, 318`（`workflow_input_variable` → `mr_txt` 映射，默认变量名 `mr_txt`）
- `config/config.json` 中任何 `audit_types[].payload.text_template` 内容
- 命名红线：builder 输出键只用 `mr_text`；禁止直写 `payload["mr_txt"]`；可运行 `python scripts/check_naming_convention.py` 自查

### 2.2 文书关联条件冻结

以下逻辑**禁止任何修改**：

- `app/services/record_identity.py` 全部：`get_record_source_key`（mrid:: 前缀 + 五字段 legacy 键：患者ID/次数/所在科室名称/病历完成时间/护理记录时间）、`get_bundle_source_key`（legacy 无前缀 / 新类型 `code::` 前缀）、`_apply_run_mode_scope`（`mode::` 前缀）
- `app/services/data_source_loader.py`：`(patient_id, visit_number)` 分组键、`_build_fanout_params` 参数模板（:420-436）、fanout records 的 `record.setdefault` 补充字段逻辑（:478-482）
- 任何审计 SQL 的 join/关联条件
- 012 §6.2 已冻结口径：mr_class 三值（'EMR10.00.03','EMR10.00.02','EMR10.00.01'）、`caption_date_time`、护理模板 572/709、护理双时间（form_time/created_date）、operation_date、同日窗口、required/anchor

### 2.3 操作红线

- 禁止 git 提交、push、建分支、reset
- 禁止生产数据库 DDL/DML；核查 SQL 只输出不执行
- 禁止调用 Dify、触发推送、发送真实告警
- 每个任务完成后运行 `pytest tests/ -v`，基线 891 passed 不得减少
- 代码注释、日志消息、Swagger 描述用中文；HTTP 错误 detail 用英文（遵循 CLAUDE.md）

---

## 3. 执行任务

### 任务 A1：修复 fanout 超时缺口（011-CODE-1）

位置：`app/services/data_source_loader.py:439-499`（`_oracle_fanout_worker`）

问题：:455-459 直写驼峰 `conn.callTimeout` 且 except 仅 debug 吞错，与主路径 `app/oracle_client.py` 的 `_apply_query_timeout` 行为不一致。

要求：
1. 先读 `app/oracle_client.py` 中 `_apply_query_timeout` 的实现、签名与恢复逻辑
2. fanout worker 改为复用同一函数设置/恢复超时；except 降级分支保留但升级为 warning 日志
3. **禁止**改动：fanout SQL、`_build_fanout_params`、records 处理、:478-482 的 setdefault 补充字段
4. 新增/更新测试验证超时设置函数被调用且异常时不中断 fanout

### 任务 A2：删除死代码（G11）

位置：`app/scheduler.py:400` 起的 `_daily_push_job`（注意：`_daily_push_job_v2`（:592）是活代码，禁止动）

要求：
1. grep 确认 `_daily_push_job`（无 `_v2` 后缀）无任何调用方
2. 删除整个函数及其专属辅助代码；:399 附近注释同步更新
3. 跑全量 pytest 确认无回归

### 任务 A3：错误详情泄露收口（G5 残留）

位置：`app/routers/historical_rerun.py` 11 处 `raise HTTPException(..., detail=str(exc))`

要求：
1. 先 grep 找到 `public_error_message` 定义（参照 `app/routers/patients.py:47` 用法），复用而非新造
2. 逐处改造为 `public_error_message(exc, "中文提示")` 模式
3. 例外：若某处 exc 确认为纯业务 ValueError 且无内部细节（SQL/堆栈/路径），可保留原文但必须加注释说明理由
4. HTTP detail 对外语义保持英文/业务化，不得泄露内部异常原文

### 任务 A4：relay_alert_service 吞错补日志（G9）

位置：`app/services/relay_alert_service.py` 全文（先 `grep -n "except" ` 找全所有静默点，已知 :38-39 一处）

要求：仅增加 `logger.warning`（含 exc 类型 + 截断消息），**不得改变返回行为**（该服务走池化路径，连接 acquire 阶段已设超时，属可观测性补强而非行为修复）。

### 任务 B1：修订 011 文档 force=True 过期描述

文件：`docs/ACTIVE/011_ORACLE_12609_PROGRESS_NURSING_REMEDIATION_PLAN_20260803.md`

事实依据：代码为 `force=False`（`app/oracle_client.py:590`），守护测试 `test_reset_oracle_pool_does_not_force_close`（`tests/test_oracle_client.py`）。若按旧文档"修复"成 force=True 反而引入新风险。

要求：删除/订正 S-08/A.7 中关于 `pool.close(force=True)` 中断在飞查询的描述，改写为与代码一致。

### 任务 B2：修订 007 文档三处不一致

文件：`docs/ACTIVE/007_HISTORICAL_MANUAL_RERUN_AND_CURRENT_RESULT_PLAN_20260728.md`

- M1：§3.1 把"断点续推"列为已有能力 → 改为"仅有幂等跳过已完成项（skip_already_succeeded），无持久化批次断点"
- M2：§6.1"复用 ACTIVE/002" → 改为"002 已落地为 push_execution/push_attempt 表（含 uq_push_execution_key_mode 唯一索引），直接复用其幂等机制"
- M3：§4.2 身份键依赖 `source_version`/`clinical_source_fingerprint` → **先读代码**：`app/models.py:424` push_execution 表已有 `source_version` 列，确认其语义是否满足 007 需求后据实改写；若满足则改写文档，若不满足则在 §6.2 补迁移清单。禁止臆断

### 任务 B3：修订 116 报告 BLOCK-02 表述

文件：`docs/reference/116_SYSTEM_FUNCTION_UI_PUSH_REVIEW_20260714.md` §3.2

事实依据：high 判定是复合门槛——维度级 `medical_evidence`+`nursing_evidence` 双方有意义（`app/services/dify_schema_parser.py:480-485`）**且** `extra.issues` 每条满足 severe+high_eligible+contradiction+双方证据+confidence≥0.8+受控安全类别（`:488-507`）。

要求：把"后端 high 依赖 extra.issues"改写为上述复合门槛描述。

### 任务 C1：PushLog 唯一约束（G4，先核查后决定）

1. 编写只读核查 SQL 并**交给用户在库中执行，禁止自行执行**：
   ```sql
   SELECT source_record_key, audit_type_code, audit_run_mode, COUNT(*) AS cnt
   FROM push_log
   WHERE superseded_by IS NULL AND source_record_key != ''
   GROUP BY source_record_key, audit_type_code, audit_run_mode
   HAVING COUNT(*) > 1;
   ```
   （Oracle 生产库表名可能带前缀，以 `app/models.py` `_table_name()` 实际映射为准）
2. 仅当用户书面确认无重复（或重复已清理）后：
   - 在 `app/models.py` PushLog `__table_args__` 增加部分唯一索引
   - 在 `app/database.py` 增加对应 `_migrate_xxx_columns()` 迁移（遵循无 Alembic 手动迁移约定）
   - 注意 002 的 push_execution 表幂等键（idempotency_key+audit_run_mode）与本约束语义不同，二者并存不冲突，但需在迁移注释中说明
3. 若用户未确认，跳过本任务并在交付报告标注"待数据核查"

---

## 4. 执行顺序与验收

| 顺序 | 任务 | 类型 | 验收 |
| --- | --- | --- | --- |
| 1 | A2 删死代码 | 代码 | pytest 全量通过 |
| 2 | A4 relay 补日志 | 代码 | pytest 通过 + 行为不变 |
| 3 | A3 detail 收口 | 代码 | pytest 通过 + 无 detail=str(exc) 残留 |
| 4 | A1 fanout 超时 | 代码 | pytest 通过 + 新增超时测试 |
| 5 | B1/B2/B3 文档 | 文档 | 与代码事实逐条一致 |
| 6 | C1 唯一约束 | 待定 | 用户确认核查结果后执行 |

每完成一个任务立即跑 `pytest tests/ -v`；任何任务失败不得带着失败进入下一任务。

## 5. 不确定项（遇到即停止并报告，不得自行决策）

1. **G4 存量重复**：push_log 现有数据在目标键上是否有重复行——未核查，必须等 C1 只读 SQL 结果
2. **007-M3 语义**：`push_execution.source_version`（002 落地）是否等同 007 §4.2 要求的身份键字段——需执行 AI 重读 007 原文 + models.py 后判定，可能只需文档改写
3. **historical_rerun.py detail 语义**：11 处均为 4xx 校验类错误，exc 多为业务 ValueError；是否构成泄露需逐一确认异常来源（任务 A3 第 3 条已含此判断要求）
4. **G8 根路径暴露面**：匿名 `/api/health` 根路径仍返回缓存的组件状态，是否需进一步收口属部署方安全决策，本计划不动
5. **relay G9 全量位置**：014 称"多处"，当前仅核实 :38 一处，执行前需全文 grep 确认
6. **116 P1-01/P1-02/P1-03**（健康 readiness、模板六类、配置校验）：本次未逐一核实当前代码状态；若用户要求纳入，执行 AI 需先对照 116 原文核查现状再决定是否仍开放
7. **任何需要改动 §2 红线文件才能完成的"修复"**：一律不做，记录到交付报告

## 6. 交付物要求

1. 每个任务的变更说明 + pytest 全量输出末尾（passed 数）
2. 交付报告：已完成项 / 跳过项及原因 / 新发现问题 / 触碰文件清单
3. 红线自查声明：确认 payload 组装、mr_txt 映射、record identity、SQL 关联条件、text_template 零改动，附 grep 证据

---

## 附：执行提示词（供粘贴给执行 AI）

```markdown
# 任务：按 docs/ACTIVE/015 执行 Med-Audit 整合整改

## 第一步：阅读
1. `docs/INDEX.md`（文档规则）
2. `docs/ACTIVE/015_CONSOLIDATED_REMEDIATION_EXECUTION_PLAN_20260807.md`（本计划，你的唯一执行依据）
3. `docs/ACTIVE/014_CROSS_REVIEW_REPORT_20260807.md`（核查背景）
4. `CLAUDE.md`（项目规范，特别是 mr_text/mr_txt 命名红线）

## 执行规则
- 严格按 015 §3 的任务 A2 → A4 → A3 → A1 → B1/B2/B3 顺序执行；C1 只做第 1 步（输出核查 SQL），等用户确认后再继续
- 严格遵守 015 §2 红线：payload_composer.py / payload_builder.py / dify_pusher.py 的 mr_txt 映射 / record_identity.py / data_source_loader.py 的关联逻辑 / text_template 一律禁止修改
- 014 报告基于旧快照，015 §1.1 所列已修复项禁止重复修改；动手前先 grep 验证当前代码状态
- 每完成一个任务运行 `pytest tests/ -v`，基线 891 passed 不得减少
- 禁止 git 提交/push/建分支；禁止生产 DDL/DML；禁止调用 Dify/触发推送
- 遇到 015 §5 不确定项立即停止该任务并报告，不得自行决策

## 交付
按 015 §6 输出交付报告（含红线自查 grep 证据）。
```
