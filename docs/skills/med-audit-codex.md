# Skill Card: med-audit-codex

> 用途：医疗记录一致性审计系统的“防回归执行基线”。
> 适用：Oracle 抽取、Dify 推送、调度、日志、质控反馈改造。

---

## A. 执行前必查

1. 是否 Oracle 模式（`APP_DB_TYPE=oracle`）
2. 是否单 worker（避免 APScheduler 重复执行）
3. 是否存在历史脏数据（NULL）会影响 schema 校验
4. 是否涉及 `push/logs/scheduler/qc_feedback` 联动字段

---

## B. 不可回退的功能基线（必须保持）

### B1. 推送链路

- Dify 主输入变量（`mr_txt`）必须传字符串
- 批量推送必须有事务隔离（单条失败不污染整批）
- 推送日志必须落地 `skip_reason`（至少区分）：
  - `unreviewed_pending`
  - `rectified_suppressed`

### B2. 推送标记策略

- `pushed_flag/reviewed_flag/manual_override/skip_reason` 必须可用
- “已推送未复核且未覆盖”默认下次跳过
- 手工标记接口必须受管理员权限控制

### B3. 调度

- 支持 `every_10m/every_30m/daily/cron`
- 保存调度配置时必须验证 cron 合法性
- 状态接口必须输出诊断信息（`diagnostics`）

### B4. 日志

- `/api/logs` 必须对 NULL 字段健壮
- 列表与 CSV 导出必须支持：
  - `reviewed_flag`
  - `manual_override`
  - `skip_reason`
- 必须保留筛选选项接口：`/api/logs/filters/options`

### B5. 质控反馈界面

- 严重度/状态英文枚举需中文显示
- 质控详情必须展示病程记录与护理记录内容
- 文本展示需保留换行以提升核查可读性

---

## C. Oracle 约束清单

1. 布尔 SQL 比较使用 `== True/False`（避免 `.is_(True/False)`）
2. GROUP BY 与 SELECT 表达式对象一致（Oracle 严格）
3. 执行前清理 SQL 尾部分隔符（`;` / `；` / `/`）
4. 迁移新增字段需在 `database.py` 同步补齐（SQLite + Oracle）

---

## D. 标准回归命令

```bash
python -m py_compile app/**/*.py
python scripts/test_api.py
python scripts/quick_start.py
```

至少补充人工核验：

- `GET /api/logs?page=1&limit=20`
- `GET /api/scheduler/status`
- `POST /api/push/manual`
- `GET /api/qc/feedback/cases/{log_id}`

---

## E. 常见回归信号 -> 快速定位

1. 日志菜单 500（Pydantic string type on None）
   - 首查：`app/routers/logs.py` 的序列化兜底

2. 调度设置成功但不执行
   - 首查：`/api/scheduler/status` 的 `diagnostics`、`env_enabled`、`job_exists`

3. 查询 14 条但推送少于预期
   - 首查：推送漏斗日志 + `skip_reason_counts`

4. 质控页面显示英文枚举
   - 首查：`static/scripts/app.js` 映射函数是否被模板调用

---

## F. Dify 检验检查核查工作流基线

### F1. 推荐节点流程

适用于 `mr_type=检验检查与病历护理核查` 的 Dify 分支。后端主输入仍必须是字符串变量 `mr_txt`，不可改为对象直传。

1. Start 节点接收：
   - `mr_txt`：字符串，内容可以是结构化 JSON 字符串
   - `mr_type`：核查类型，例如 `检验检查与病历护理核查`
2. 根条件分支按 `mr_type` 做互斥判断：
   - `检验检查与病历护理核查` -> 检验检查分支
   - `医嘱与病程及护理核查` -> 医嘱分支
   - 不要用多个单选值 `and` 判断同一 `mr_type`
3. 检验检查分支节点顺序：
   - `检验检查与护理病程json过滤器`：解析 `mr_txt`，整理为可读文本，输出 `result`
   - `llm检验检查与护理病程一致性核查`：输入必须引用过滤器输出 `{{#过滤器节点.result#}}`
   - `llm检验检查与护理病程json格式转换`：把中文核查结论转为标准 JSON
   - `检验检查与护理病程json检测`：校验 JSON 结构，仅输出 `result`
   - `判断json标准化`：`result == "符合"` 走结束；`result == "不符合"` 走修复分支
   - `llm 核查及json格式的转换`：修复不合格 JSON，修复后建议再次进入 JSON 检测
4. End 节点必须输出：
   - 输出变量名：`aa`
   - 输出值：通过校验前的标准 JSON 文本，通常取 JSON 转换 LLM 的原始 JSON 输出

### F2. 节点输入输出约定

- `检验检查与护理病程json过滤器` 必须包含 `function main(inputs)`，返回 `{ result: "..." }`。
- 过滤器应兼容新结构和旧结构：
  - 新结构：`患者信息`、`检验检查.检验报告信息`、`检验检查.检查报告`、`病程.病程记录`、`护理.护理记录`
  - 旧结构：`patient_info`、`abnormal_labs`、`abnormal_exams`、`progress_context`、`nursing_context`
- 质控 LLM 不要再引用 Start 原始 `mr_txt`，应引用过滤器输出，避免绕过清洗和格式整理。
- JSON 转换 LLM 只输出 JSON，不要 Markdown，不要额外说明。
- JSON 检测 Code 节点输出参数只配置一个 String：`result`。
- `result` 只允许两个值：`符合`、`不符合`。
- 符合分支 End 输出 `aa = JSON 转换 LLM 的原始 JSON 输出`；不符合分支进入修复 LLM。

### F3. 标准 JSON 字段基线

JSON 转换提示词与 JSON 检测代码必须使用同一套字段名和枚举，禁止一边改字段另一边不改校验。

- 顶层字段：
  - `version`
  - `patient_summary`
  - `audit_summary`
  - `dimensions`
  - `raw_judgement`
- `patient_summary` 字段：
  - `patient_id`
  - `visit_number`
  - `patient_name`
  - `dept`
  - `query_date`
- 固定 6 个维度编码：
  - `lab_abnormal_followup`：异常检验结果在病程记录中的关注与处置
  - `exam_abnormal_followup`：异常检查结果在病程记录中的关注与处置
  - `progress_result_consistency`：检验检查结果与病程记录内容一致性
  - `nursing_recorded_consistency`：护理已记录内容与检验检查结果一致性
  - `high_risk_response_consistency`：高风险异常结果的病程响应
  - `timeline_consistency`：检验检查结果与病程/护理记录时间合理性
- 维度字段使用：
  - `dimension_code`
  - `dimension_name`
  - `status`
  - `severity`
  - `confidence`
  - `alert_level`
  - `closure_hours`
  - `push_strategy`
  - `outcome_bucket`
  - `issue_summary`
  - `medical_evidence`
  - `nursing_evidence`
  - `recommendation`
- 枚举映射：
  - 通过：`pass / blue / low`
  - 预警：`warn / yellow / medium`
  - 不通过：`fail / red / high`
  - 无法判断：`unknown / gray / low`
  - `confidence < 0.6` 时必须为 `unknown / gray / low`
- 汇总映射：
  - `risk_score`：`red=90`、`yellow=60`、`blue=20`、`gray=0`
  - `push_strategy`：`red=immediate`、`yellow=batch`、`blue=shift_summary`、`gray=review_only`
  - `outcome_bucket`：`red/yellow=primary`、`blue=secondary`、`gray=none`
  - `closure_hours`：`red=24`、`yellow=48`、`blue=72`、`gray=0`

### F4. 常见 Dify 故障定位

1. `ReferenceError: main is not defined`
   - Code 节点缺少 `function main(inputs)`；只粘贴辅助函数或业务函数会失败。
2. 后端日志 `output_keys=[]`、`未找到 output_key='aa'`
   - End 节点没有输出 `aa`，或流程进入了 `outputs: []` 的结束节点。
3. JSON 检测报 `Not all output parameters are validated.`
   - Dify Code 节点输出参数配置和 `return` 字段不一致；若采用简化检测节点，输出参数只保留 `result`，所有路径都返回 `{ result: "符合" }` 或 `{ result: "不符合" }`。
4. JSON 一直“不符合”
   - 首查 JSON 转换提示词和检测代码字段是否一致，例如 `dimension_code` vs `code`、`dept` vs `dept_name`、`push_strategy` 枚举是否一致。
5. AI 输出患者信息为空
   - 首查 JSON 转换 LLM 输入变量是否引用了真实上一节点输出，不要保留 `{{#上一个核查节点输出变量#}}` 这类占位。
6. 时间维度误判
   - 检验/检查结果时间晚于病程/护理时间时，不能要求早期记录提前体现未来结果，应按时间合理性维度判断。
