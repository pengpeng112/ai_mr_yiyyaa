# Dify 预警分级提示词与落库扩展计划

## TL;DR

> **Quick Summary**: 为病历文书/护理记录一致性质控重构两份 Dify 提示词，并同步规划 JSON 扩展、解析兼容、数据库落库与通知展示适配。
>
> **Deliverables**:
> - 两份新版提示词（质控判定 + JSON 输出）
> - 扩展后的 JSON 字段方案（含整体质控描述、维度级预警灯号）
> - 后端解析/落库/API/通知适配实施任务清单
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 2 waves
> **Critical Path**: 字段契约 → 数据模型/迁移 → 解析器 → 落库/API → 提示词定稿

---

## Context

### Original Request
用户提供了当前两段 Dify 提示词，希望重写为支持红/黄/蓝/灰分级预警的新版提示词，并要求：
- 每个维度输出预警灯号；
- 增加整体病历质控结果描述；
- 该整体描述可落库；
- 允许扩展 JSON 字段；
- 允许新增数据库字段。

### Interview Summary
**Key Discussions**:
- 现有提示词分两段：一段负责质控分析，一段负责 JSON 输出。
- 新规则引入四类预警：红灯/黄灯/灰灯/蓝灯。
- 预警灯号按维度输出，不只是总体结果。
- 整体病历质控结果描述需要可以保存到数据库。
- 用户允许新增 JSON 字段与新增数据库字段。

**Research Findings**:
- 当前解析链已支持 `patient_summary / audit_summary / dimensions / raw_judgement`。
- 当前系统仅原生理解 `severity=high|medium|low`，不原生理解 `alert_level=red|yellow|blue|gray`。
- 当前已有维度级结构化表，但缺少预警灯号、闭环时限、推送策略等字段。

### Metis Review
**Identified Gaps** (addressed):
- 现有三档 `severity` 与四灯模型语义不一致：计划中采用“并存”策略，新增 `alert_level` 而不替换 `severity`。
- 当前通知逻辑仅支持“发现不一致即通知”：本计划仅落库并展示 `push_strategy` 元数据，不直接改造批量/班次推送机制。
- 现有解析/落库路径不止一处：计划中明确覆盖解析器、执行器、重推路径、响应 schema。

---

## Work Objectives

### Core Objective
形成一套可执行的重构方案，使 Dify 提示词、结构化 JSON、数据库字段与后端解析链能够共同支持“整体质控描述 + 维度级红黄蓝灰灯预警”。

### Concrete Deliverables
- 两份新版提示词文稿
- 扩展 JSON 契约说明
- 数据表新增字段方案
- 解析/落库/API/通知改造任务清单

### Definition of Done
- [ ] 计划中明确提示词目标、JSON 契约、数据库新增字段、解析落库路径与验证方式
- [ ] 计划中所有任务都有具体引用、验收标准与 QA 场景

### Must Have
- 保留现有兼容字段 `status` 与 `severity`
- 新增 `alert_level` 及整体质控描述承载方案
- 维度级输出包含灯号与处置元数据
- 保持对旧版 Dify 输出的解析兼容

### Must NOT Have (Guardrails)
- 不直接替换或删除现有 `severity`
- 不把本次范围膨胀为前端改造
- 不把本次范围膨胀为完整消息调度系统重构
- 不要求人工验证作为唯一验收方式

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — 所有验证均需由执行代理通过脚本、接口或解析测试完成。

### Test Decision
- **Infrastructure exists**: YES（项目无 pytest，但已有 `scripts/` 手工验证脚本）
- **Automated tests**: Tests-after
- **Framework**: Python 脚本 + 现有 API/解析调用

### QA Policy
每个任务必须至少提供：
- 1 个 happy path 场景
- 1 个 failure/compatibility 场景
- 证据保存到 `.sisyphus/evidence/`

---

## Execution Strategy

### Parallel Execution Waves

```text
Wave 1 (可立即开始 — 契约/字段/文稿基础):
├── Task 1: 预警模型与字段契约定义
├── Task 2: 数据库字段与迁移方案设计
├── Task 3: 解析器兼容策略设计
├── Task 4: API/Schema 暴露面盘点
└── Task 5: 两份提示词草案重构

Wave 2 (在 Wave 1 基础上并行推进 — 落库/通知/验证):
├── Task 6: 落库路径与重推路径同步改造
├── Task 7: 通知内容与预警展示策略适配
├── Task 8: 解析兼容验证脚本与样例固化
├── Task 9: 提示词定稿与输出示例固化
└── Task 10: 文档化部署与回滚说明

Wave FINAL:
├── Task F1: Plan compliance audit
├── Task F2: Code quality review
├── Task F3: Real manual QA scenario execution
└── Task F4: Scope fidelity check
```

### Dependency Matrix
- **1**: — — 2,3,5,6,7,8,9
- **2**: 1 — 6,10
- **3**: 1 — 6,8,9
- **4**: 1 — 6,7,10
- **5**: 1 — 9
- **6**: 2,3,4 — 7,8,10
- **7**: 1,4,6 — 10
- **8**: 1,3,6 — 10
- **9**: 1,3,5 — 10
- **10**: 2,4,6,7,8,9 — FINAL

### Agent Dispatch Summary
- **Wave 1**: T1/T2/T4 → `quick`，T3 → `deep`，T5 → `writing`
- **Wave 2**: T6 → `unspecified-high`，T7 → `writing`，T8 → `quick`，T9 → `writing`，T10 → `writing`
- **FINAL**: F1 → `oracle`，F2 → `unspecified-high`，F3 → `unspecified-high`，F4 → `deep`

---

## TODOs

- [ ] 1. 定义预警分级与 JSON 契约

  **What to do**:
  - 明确四灯模型与现有 `status/severity` 的并存关系：保留 `status`、`severity`，新增 `alert_level`。
  - 在 `audit_summary` 中定义整体质控描述与总体预警字段，如 `overall_qc_summary`、`alert_level`、`closure_hours`、`push_strategy`、`outcome_bucket`。
  - 在 `dimensions[]` 中定义维度级字段：`alert_level`、`closure_hours`、`push_strategy`、`outcome_bucket`。

  **Must NOT do**:
  - 不删除现有 `severity`
  - 不把四灯直接硬映射成仅三档而丢失灰/蓝语义

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 契约梳理是高确定性的结构设计工作。
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: 2,3,5,6,7,8,9
  - **Blocked By**: None

  **References**:
  - `app/dify_pusher.py:190-207` - 当前解析结果标准字段基线
  - `app/dify_pusher.py:420-459` - 新 schema 维度解析入口
  - `app/services/push_executor.py:301-330` - 当前落库消费字段集合

  **Acceptance Criteria**:
  - [ ] 产出一份明确字段契约，列出新增字段名、类型、层级、含义
  - [ ] 说明 `alert_level` 与 `severity` 的兼容映射规则

  **QA Scenarios**:
  ```text
  Scenario: 契约完整覆盖新需求
    Tool: Bash (python)
    Preconditions: 已整理字段清单
    Steps:
      1. 用脚本读取字段契约样例 JSON
      2. 校验同时包含 patient_summary/audit_summary/dimensions 新老字段
      3. 断言 dimensions 中包含 alert_level
    Expected Result: 字段契约样例可被 json.loads 成功解析
    Evidence: .sisyphus/evidence/task-1-contract.json

  Scenario: 兼容字段未丢失
    Tool: Bash (python)
    Preconditions: 已生成扩展样例 JSON
    Steps:
      1. 校验 status 与 severity 字段仍存在
      2. 若缺失则脚本返回非零退出码
    Expected Result: 脚本通过
    Evidence: .sisyphus/evidence/task-1-compat.txt
  ```

- [ ] 2. 设计数据库新增字段与迁移方案

  **What to do**:
  - 为 `PushLog`、`AuditDimensionResult`、`AuditConclusion` 规划新增字段。
  - 明确整体质控描述的主落库位置，优先放入 `AuditConclusion` 的新增字段。
  - 设计 SQLite/Oracle 双模式下的迁移策略与默认值策略。

  **Must NOT do**:
  - 不重命名旧列
  - 不要求回填历史数据为四色灯号

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 字段设计与迁移方案边界明确。
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: 6,10
  - **Blocked By**: 1

  **References**:
  - `app/models.py` - 现有 ORM 表结构
  - `app/database.py` - 现有手工迁移模式
  - `app/services/push_executor.py:319-330` - 当前总结表落库字段

  **Acceptance Criteria**:
  - [ ] 列出每张表新增字段、类型、默认值、兼容策略
  - [ ] 明确 Oracle/SQLite 迁移注意事项

  **QA Scenarios**:
  ```text
  Scenario: 迁移方案可执行
    Tool: Bash (python)
    Preconditions: 已更新数据库迁移设计
    Steps:
      1. 执行初始化/迁移命令
      2. 检查新列存在
    Expected Result: 初始化成功且可见新增列
    Evidence: .sisyphus/evidence/task-2-migration.txt

  Scenario: 历史数据兼容
    Tool: Bash (python)
    Preconditions: 旧数据存在且无新列值
    Steps:
      1. 查询旧记录
      2. 断言读取不报错
    Expected Result: 旧记录在新 schema 下可正常读取
    Evidence: .sisyphus/evidence/task-2-backward.txt
  ```

- [ ] 3. 设计解析器向后兼容扩展

  **What to do**:
  - 扩展 `parse_dify_structured_output()` 支持新增总体字段与维度级预警字段。
  - 设计当新字段缺失时的降级逻辑。
  - 明确 `gray` 与 `unknown`、`blue` 与 `low severity` 的关系。

  **Must NOT do**:
  - 不破坏旧版输出解析
  - 不把灰灯自动等同于失败告警

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要处理新旧 schema 共存与语义映射。
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: 6,8,9
  - **Blocked By**: 1

  **References**:
  - `app/dify_pusher.py:168-271` - 结构化解析主流程
  - `app/dify_pusher.py:383-413` - root 归一化逻辑
  - `app/dify_pusher.py:638-674` - 后处理与自动补全逻辑

  **Acceptance Criteria**:
  - [ ] 明确新字段解析入口与默认值规则
  - [ ] 定义旧版 JSON 回退逻辑

  **QA Scenarios**:
  ```text
  Scenario: 新版 JSON 可解析
    Tool: Bash (python)
    Preconditions: 有 v2 样例 JSON
    Steps:
      1. 调用 parse_dify_structured_output
      2. 断言 audit_summary 与 dimensions 中都解析出 alert_level
    Expected Result: parse_success=True
    Evidence: .sisyphus/evidence/task-3-v2.txt

  Scenario: 旧版 JSON 不回归
    Tool: Bash (python)
    Preconditions: 有 v1 样例 JSON
    Steps:
      1. 调用同一解析入口
      2. 断言无异常且保留原 severity/inconsistency 行为
    Expected Result: 兼容通过
    Evidence: .sisyphus/evidence/task-3-v1.txt
  ```

- [ ] 4. 盘点 API / Schema / 报表暴露面

  **What to do**:
  - 识别所有返回审计结果的 API 与 schema。
  - 规划哪些响应需要新增总体质控描述、维度级灯号与处置元数据。
  - 识别哪些统计逻辑暂不改动，避免范围蔓延。

  **Must NOT do**:
  - 不顺手扩展前端需求
  - 不重做统计口径

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 主要是接口暴露面梳理。
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: 6,7,10
  - **Blocked By**: 1

  **References**:
  - `app/schemas.py` - 当前响应模型
  - `app/routers/report.py` - 报表读取与回退解析路径
  - `app/routers/logs.py` - 日志详情/重推路径

  **Acceptance Criteria**:
  - [ ] 输出受影响 API / schema 清单
  - [ ] 明确 in-scope 与 out-of-scope 接口

  **QA Scenarios**:
  ```text
  Scenario: API 暴露面清单完整
    Tool: Bash (python)
    Preconditions: 已完成接口梳理
    Steps:
      1. 运行脚本扫描 schema/routers 引用
      2. 输出受影响文件清单
    Expected Result: 清单包含 logs/report 关键路径
    Evidence: .sisyphus/evidence/task-4-api-scan.txt

  Scenario: 统计逻辑未被误纳入
    Tool: Bash (python)
    Preconditions: 已定义范围边界
    Steps:
      1. 比对计划任务与统计模块
      2. 确认无新增统计改造任务
    Expected Result: 范围边界明确
    Evidence: .sisyphus/evidence/task-4-scope.txt
  ```

- [ ] 5. 重构两份提示词草案

  **What to do**:
  - 重写“质控判定提示词”，纳入四灯定义、维度判定标准、整体质控总结要求。
  - 重写“JSON 输出提示词”，纳入新增字段、每维灯号、整体质控描述、闭环时限与推送策略元数据。
  - 给出示例输出，确保字段命名与后端契约一致。

  **Must NOT do**:
  - 不输出与契约不一致的字段名
  - 不遗漏固定 6 个维度编码

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: 以高约束的结构化提示词设计为主。
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: 9
  - **Blocked By**: 1

  **References**:
  - 用户现有提示词全文 - 作为重构基线
  - `app/dify_pusher.py:420-459` - 当前新 schema 维度命名兼容逻辑
  - `app/services/push_executor.py:301-330` - 当前落库消费字段

  **Acceptance Criteria**:
  - [ ] 两份提示词都明确输出要求且无 Markdown 包装要求冲突
  - [ ] 样例输出字段与契约一致

  **QA Scenarios**:
  ```text
  Scenario: 提示词字段名一致
    Tool: Bash (python)
    Preconditions: 已产出提示词与示例 JSON
    Steps:
      1. 用脚本提取示例 JSON 键
      2. 与契约清单比对
    Expected Result: 无缺失、无多余关键字段
    Evidence: .sisyphus/evidence/task-5-prompt-schema.txt

  Scenario: 固定 6 维度编码完整
    Tool: Bash (python)
    Preconditions: 已产出 JSON 示例
    Steps:
      1. 校验 dimension_code 集合
      2. 缺任一编码则失败
    Expected Result: 六个编码齐全
    Evidence: .sisyphus/evidence/task-5-dimensions.txt
  ```

- [ ] 6. 统一落库路径与重推路径改造

  **What to do**:
  - 在主推送落库路径中持久化新增总体字段与维度字段。
  - 检查重推、报表回退解析等二级路径，避免只改一处。
  - 明确整体质控描述的最终存储位置与读取位置。

  **Must NOT do**:
  - 不只改 `push_executor` 而遗漏重推/报表路径
  - 不把提示词字段落到不合适的旧字段中造成语义混乱

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 涉及多落库路径一致性控制。
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: 7,8,10
  - **Blocked By**: 2,3,4

  **References**:
  - `app/services/push_executor.py:288-331` - 主落库逻辑
  - `app/routers/logs.py` - 重推与日志详情相关逻辑
  - `app/routers/report.py` - 历史结果读取与回退解析路径

  **Acceptance Criteria**:
  - [ ] 新字段在主推送与重推结果中都能保存
  - [ ] 整体质控描述可从数据库读取而非仅存在临时内存结构

  **QA Scenarios**:
  ```text
  Scenario: 主推送落库成功
    Tool: Bash (curl)
    Preconditions: 服务启动，存在可推送数据
    Steps:
      1. 触发一次推送
      2. 查询对应日志详情
      3. 断言返回包含 overall_qc_summary / dimensions[].alert_level
    Expected Result: 新字段存在且不为空（若提示词产出）
    Evidence: .sisyphus/evidence/task-6-push.json

  Scenario: 重推路径不遗漏新字段
    Tool: Bash (curl)
    Preconditions: 已有一条可重推日志
    Steps:
      1. 执行重推
      2. 再次读取日志详情
      3. 断言新字段仍存在
    Expected Result: 重推后新字段完整
    Evidence: .sisyphus/evidence/task-6-retry.json
  ```

- [ ] 7. 适配通知展示与预警元数据

  **What to do**:
  - 明确通知内容如何展示维度级灯号与整体最高级别。
  - 仅把 `push_strategy` 作为元数据保存/展示，不在本次实现批量调度。
  - 约束红黄蓝灰在通知文案中的 emoji/文案映射。

  **Must NOT do**:
  - 不扩展为完整批处理通知系统
  - 不引入新的人工审批流

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: 重点是输出展示规范与边界约束。
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: 10
  - **Blocked By**: 1,4,6

  **References**:
  - `app/notifier.py` - 当前通知文案生成逻辑
  - 用户给出的预警等级/闭环时限/推送策略表 - 作为业务规则基线

  **Acceptance Criteria**:
  - [ ] 明确四灯对应展示符号与文案
  - [ ] 明确本次只存储/展示，不改造调度发送机制

  **QA Scenarios**:
  ```text
  Scenario: 通知文案展示最高级别
    Tool: Bash (python)
    Preconditions: 准备包含 red/yellow/blue/gray 的示例数据
    Steps:
      1. 调用通知内容生成逻辑
      2. 断言输出包含对应灯号标识
    Expected Result: 红黄蓝灰映射正确
    Evidence: .sisyphus/evidence/task-7-notify.txt

  Scenario: 未误实现批处理机制
    Tool: Bash (python)
    Preconditions: 已完成通知方案设计
    Steps:
      1. 审查新增配置与调用链
      2. 断言未新增 scheduler/batch dispatcher 改造
    Expected Result: 范围受控
    Evidence: .sisyphus/evidence/task-7-scope.txt
  ```

- [ ] 8. 固化解析兼容验证脚本与样例

  **What to do**:
  - 新增 v1/v2 Dify 输出样例 JSON。
  - 编写解析验证脚本，分别断言旧版兼容与新版新增字段解析成功。
  - 覆盖灰灯、蓝灯、红灯混合场景。

  **Must NOT do**:
  - 不只测新版不测旧版
  - 不用模糊断言替代字段级断言

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 以测试样例与脚本固化为主。
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: 10
  - **Blocked By**: 1,3,6

  **References**:
  - `app/dify_pusher.py` - 解析入口
  - 用户现有 JSON 结构约束 - 作为 fixture 基线

  **Acceptance Criteria**:
  - [ ] 至少有 1 份 v1 fixture、1 份 v2 fixture、1 份 mixed fixture
  - [ ] 验证脚本断言新旧 schema 都通过

  **QA Scenarios**:
  ```text
  Scenario: v2 fixture 解析通过
    Tool: Bash (python)
    Preconditions: 已准备 v2 fixture
    Steps:
      1. 执行解析测试脚本
      2. 断言 alert_level / overall_qc_summary 成功提取
    Expected Result: 测试通过
    Evidence: .sisyphus/evidence/task-8-v2.txt

  Scenario: v1 fixture 无回归
    Tool: Bash (python)
    Preconditions: 已准备 v1 fixture
    Steps:
      1. 执行同一脚本
      2. 断言 parse_success=True 且原有字段语义不变
    Expected Result: 测试通过
    Evidence: .sisyphus/evidence/task-8-v1.txt
  ```

- [ ] 9. 定稿提示词与输出示例

  **What to do**:
  - 在 Wave 1 草案基础上，生成最终两份提示词。
  - 补充完整 JSON 输出示例，体现整体描述与每维灯号。
  - 给出字段释义，方便后续 Dify 配置与联调。

  **Must NOT do**:
  - 不保留自相矛盾的字段命名
  - 不遗漏落库所需字段

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: 文稿打磨与联调说明整理。
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: 10
  - **Blocked By**: 1,3,5

  **References**:
  - Task 1 字段契约输出
  - Task 3 解析兼容规则
  - 用户现有原始提示词全文

  **Acceptance Criteria**:
  - [ ] 两份提示词与 JSON 示例彼此一致
  - [ ] 可直接交由执行代理落地到 Dify/代码库

  **QA Scenarios**:
  ```text
  Scenario: 提示词与 JSON 示例一致
    Tool: Bash (python)
    Preconditions: 已定稿文档与示例 JSON
    Steps:
      1. 提取示例 JSON 字段
      2. 比对字段契约与定稿说明
    Expected Result: 一致性通过
    Evidence: .sisyphus/evidence/task-9-consistency.txt

  Scenario: 整体描述可落库
    Tool: Bash (python)
    Preconditions: 已定义数据库字段与 JSON 示例
    Steps:
      1. 读取 JSON 示例中的 overall_qc_summary
      2. 校验其可序列化为数据库目标字段
    Expected Result: 可序列化、可持久化
    Evidence: .sisyphus/evidence/task-9-storage.txt
  ```

- [ ] 10. 输出部署、回滚与联调说明

  **What to do**:
  - 说明提示词切换顺序、数据库迁移顺序、回滚策略。
  - 说明旧 prompt 与新 prompt 并存期间的兼容策略。
  - 说明如何验证 Dify 平台上的实际输出符合计划契约。

  **Must NOT do**:
  - 不假设一次切换即可完全无风险
  - 不遗漏回滚说明

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: 需要形成清晰的执行/回滚手册。
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: FINAL
  - **Blocked By**: 2,4,6,7,8,9

  **References**:
  - `DEPLOY.md` - 当前部署说明风格
  - `app/dify_pusher.py` - 解析 fallback 逻辑
  - 用户业务规则 - 闭环时限与推送策略定义

  **Acceptance Criteria**:
  - [ ] 说明切换、验证、回滚三部分步骤
  - [ ] 明确旧版并存时的兼容策略

  **QA Scenarios**:
  ```text
  Scenario: 回滚说明可执行
    Tool: Bash (python)
    Preconditions: 已编写回滚步骤
    Steps:
      1. 检查是否包含 prompt 回退、解析兼容、字段保留三项
      2. 缺失任一项则失败
    Expected Result: 回滚说明完整
    Evidence: .sisyphus/evidence/task-10-rollback.txt

  Scenario: 联调说明可验证实际输出
    Tool: Bash (curl)
    Preconditions: 服务可访问
    Steps:
      1. 调用实际接口获取一条审计结果
      2. 对照联调说明检查字段
    Expected Result: 联调说明覆盖关键字段校验
    Evidence: .sisyphus/evidence/task-10-validation.json
  ```

---

## Final Verification Wave

- [ ] F1. **Plan Compliance Audit** — `oracle`
  校验计划中的新增字段、解析路径、落库位置、提示词产物、验证脚本是否全部覆盖。

- [ ] F2. **Code Quality Review** — `unspecified-high`
  检查模型、解析器、落库代码、schema、脚本是否存在遗漏引用、兼容性破坏或重复实现。

- [ ] F3. **Real Manual QA** — `unspecified-high`
  运行解析脚本、接口脚本、重推场景，验证旧版 JSON 与新版 JSON 都可被正确消费。

- [ ] F4. **Scope Fidelity Check** — `deep`
  确认工作未越界到前端、复杂调度系统或新的人工流程设计。

---

## Commit Strategy

- **1**: `feat(db): add alert metadata fields for audit results`
- **2**: `feat(parser): support alert-level qc output schema`
- **3**: `feat(api): expose qc summary and alert metadata`
- **4**: `docs(prompts): add v2 dify qc prompt templates`

---

## Success Criteria

### Verification Commands
```bash
python -c "from app.dify_pusher import parse_dify_structured_output; print('ok')"
python scripts/test_parser_v2.py
curl http://localhost:8000/api/logs
```

### Final Checklist
- [ ] 整体质控描述有明确落库字段承载
- [ ] 每个维度可输出红/黄/蓝/灰灯号
- [ ] 旧版 JSON 解析不回归
- [ ] 新版 JSON 新增字段可解析、可落库、可对外返回
