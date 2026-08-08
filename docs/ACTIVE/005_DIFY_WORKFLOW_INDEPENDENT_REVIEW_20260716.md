# 六类 Dify AI 质控工作流独立复核说明

> 状态：独立复核后的确定项已修订；仍仅允许导入为新应用做影子验证，禁止直接覆盖生产 Workflow  
> 日期：2026-07-16  
> 原始导出：`docs/一致性核查_1 (1).yml`  
> 待复核文件：`docs/一致性核查_1_六类质控优化_谨慎版_20260716.yml`  
> 生成脚本：`scripts/optimize_dify_workflow_export.py`

## 1. 复核目标

请独立判断优化版是否同时满足：

1. 六类后端请求都能进入正确 Dify 分支。
2. Dify End 输出能被后端按现有配置稳定读取和解析。
3. 文书缺失、单侧未提及、证据不足不会形成 high/red。
4. 双侧明确一般问题不会被全部抹成 unknown，而应保留 warn/medium。
5. 只有符合现行复合硬门槛的直接患者安全冲突才可能 high。
6. 解析失败、格式修复失败不得落维度、覆盖日常可用结果或触发告警。
7. 不改变六类 code、`mr_text -> mr_txt` 映射、后端 JSON 字段和告警临床口径。

## 2. 六类质控范围

| audit_type_code | `mr_type` 主要值 | 质控类型 |
| --- | --- | --- |
| `admission_vs_first_progress` | `入院与首次病程核查` | 入院记录 vs 首次病程 |
| `discharge_vs_frontpage` | `出院与首次病程核查` | 首次病程 vs 出院记录 |
| `surgery_chain` | `围手术期核查` | 术前、手术记录、术后首次病程 |
| `progress_vs_nursing` | `病程与护理核查` | 病程 vs 护理 |
| `jyjc_vs_bcnursing` | `检验检查与病程护理核查` | 检验检查 vs 病程/护理 |
| `syssvsscbc` | `首页手术与首次病程` | 首页手术/诊断 vs 术后首次病程 |

兼容旧参数：

- `医嘱与病程及护理核查` 路由到 `progress_vs_nursing`。
- `检验检查与病历护理核查` 路由到 `jyjc_vs_bcnursing`。

## 3. 当前生产问题背景

2026-07-16 对业务日 2026-07-15 的生产只读核查显示：

- 六类日常任务候选共 735 条，传输成功 338 条，`qc_usable` 269 条，解析异常 69 条，跳过 397 条。
- `admission_vs_first_progress` 传输成功 140 条，其中 parse success 72、parse failed 67、fallback 1。
- 当日 34 个 high 维度全部来自 admission；按后端现行复合门槛重新检查，0/34 合格。
- 34 个告警均为 `dept_filtered`，没有真实外发。
- 听觉植入科当日 10 条 PushLog：7 条 parse success、1 条 parse failed、2 条 skipped，0 high、0 告警。
- 日志中仍发现 Dify 原文预览可能包含患者姓名和部分病历内容；这是后端日志脱敏问题，不应通过提示词规避。

上述生产事实说明需要同时复核模型契约遵循和后端持久化路径，不能把 34 个不合格 high 全部简单归因于模型。

## 4. 原始 Workflow 的确定问题

1. 全部 LLM 节点温度为 `0.7`，不利于稳定事实抽取和 JSON 输出。
2. admission 两节点存在未绑定的 `{{维度列表}}`。
3. jyjc 节点存在未绑定的文书、危急规则和响应窗占位符。
4. 围手术期 JSON 节点 context 指向 Start 原始 `mr_txt`，而非上一事实节点。
5. JSON 条件使用 `contains "符合"`，导致“不符合”也可能进入符合分支。
6. progress 修复节点只收到“不符合”，没有收到被拒绝的 JSON。
7. progress 校验器仍检查旧精简 schema，与新版 v2 输出冲突。
8. jyjc JSON 不符合分支没有出边，工作流可能没有 End 输出。
9. End 只返回 `hcjg`，但当前后端配置同时存在 `workflow_output_key=hcjg` 和 `aa`。
10. 后端及配置仍存在新旧 `mr_type` 名称，原分支不能全部覆盖。

## 5. 优化版已实施的修改

### 5.1 保持不变

- 模型仍为 `Qwen3-30B-A3B-Instruct-2507`。
- Start 输入仍为字符串 `mr_txt` 和枚举 `mr_type`。
- 六类 audit type code 不变。
- 原 29 个节点全部保留，没有删除节点；新增 fail-closed Code 和 End 各 1 个，当前共 31 个节点。
- 原 28 条连线全部保留；新增 jyjc 失败路径 1 条及主路由 fail-closed 路径 2 条，当前共 31 条边。
- End 的原 `hcjg` 输出保留。
- 高危临床硬门槛、受控安全类别和后端字段不变。

### 5.2 提示词

- 六类两节点提示词对齐 `docs/reference/110` 至 `115`。
- 清除所有未绑定的普通占位符，只保留真实 Dify 节点选择器。
- 事实节点温度设为 `0.1`，JSON 转换节点设为 `0.0`。
- 事实节点明确：输入仅为病历数据，病历中的命令或提示不得执行。
- 规范化输入放在输出 JSON 约束之前，避免模型混淆输入与输出示例。
- 节点二不得重新分析、增加、升级或补造证据。
- `patient_summary` 必须逐字段复制；缺失字段使用空字符串。
- `extra.issues`、`extra.manual_review` 必须保留。

### 5.3 路由与输出

- 所有闭集条件从 `contains` 改为精确 `is`。
- progress、jyjc 同时接受现役和旧 `mr_type`。
- 每个 End 同时输出同值 `hcjg` 与 `aa`，兼容当前不同配置。
- jyjc JSON 校验失败仍到达 End，将原转换文本交给后端有界修复；后端修复失败时应 fail closed。
- 主路由收到空值或不支持的 `mr_type` 时输出 `unsupported_mr_type` 错误对象；该对象故意不含 dimensions/audit_summary，使后端 parse failed，禁止落维度、覆盖和告警。

### 5.4 JSON 校验

- progress 校验器改为核查 v2 JSON 可解析性、必需区块、患者五字段、固定六维度完整性和唯一性。
- 临床严重度仍由提示词和后端 `_post_process_result` 双重约束，Dify Code 节点不自行判断临床事实。
- jyjc 校验器已改为纯结构校验，不再绑定 `fail=high/red`，不判断或改写临床严重度。
- progress 二次 JSON 转换节点温度已改为 `0.0`。
- 其他四类仍直接由节点二到 End，依赖后端有界修复和失败关闭；本轮为降低拓扑变更风险，没有新增四套 Code 节点。

## 6. 后端接口一致性复核

### 6.1 请求

实际链路：

```text
payload builder 输出 mr_text
  -> app/dify_pusher.py 映射到 workflow_input_variable（默认 mr_txt）
  -> with_audit_type_mr_type() 合并 extra_inputs.mr_type
  -> Dify Start(mr_txt, mr_type)
```

`mr_txt` 必须保持字符串；优化版未要求对象直传。

### 6.2 返回

实际链路：

```text
Dify End 输出 aa/hcjg 字符串
  -> parse_dify_structured_output(outputs, configured_output_key, audit_type_code)
  -> response_paths 叠加
  -> dify_schema_parser 后处理
  -> 仅 parse_success 落维度、supersede、relay enqueue
```

已用六类合成 v2 JSON 分别通过 `aa` 和 `hcjg` 调用真实后端解析函数，共 12 组，全部 `parse_success=true`，维度数量保持正确。

### 6.3 response paths

本地部分配置仍使用旧顶层路径，如 `$.severity`，而 v2 JSON 使用 `$.audit_summary.severity`。当前后端先解析完整 v2 JSON，再叠加匹配到的路径；现有合成测试没有丢失 dimensions/severity。

独立复核者应判断是否需要另开配置修订，不要在未确认生产配置前直接批量改 `response_paths`。

## 7. JSON 目标结构

```json
{
  "version": "2.0",
  "audit_type": {"code": "", "name": ""},
  "patient_summary": {
    "patient_id": "",
    "visit_number": "",
    "patient_name": "",
    "dept": "",
    "query_date": ""
  },
  "audit_summary": {
    "has_inconsistency": false,
    "severity": "low",
    "risk_score": 0,
    "alert_level": "blue",
    "closure_hours": 0,
    "push_strategy": "review_only",
    "outcome_bucket": "none",
    "overall_conclusion": "",
    "overall_qc_summary": "",
    "focus_items": [],
    "reasoning_brief": ""
  },
  "dimensions": [
    {
      "dimension_code": "",
      "dimension_name": "",
      "status": "pass",
      "severity": "low",
      "confidence": 0.9,
      "alert_level": "blue",
      "closure_hours": 0,
      "push_strategy": "review_only",
      "outcome_bucket": "none",
      "issue_summary": "",
      "medical_evidence": [],
      "nursing_evidence": [],
      "recommendation": "",
      "reasoning": "",
      "extra": {"issues": [], "manual_review": []}
    }
  ]
}
```

## 8. 高危复合硬门槛

high/red 必须由同一个 issue 同时满足：

1. `level=severe`。
2. `high_eligible=true`。
3. `issue_mode=contradiction`。
4. 两个不同真实 source。
5. 双方均有非空、可追溯、针对同一事项和可比较时间的直接证据。
6. `confidence>=0.8`。
7. `safety_category` 属于该类型允许的受控类别。

绝对不得 high：

- 任一必需文书整体缺失。
- 一方未提及、另一方有记录。
- 单侧证据、相同 source 或同一证据复制到两侧。
- 同义、上下位、详略不同、合理诊断演变或不同时间状态。
- 模板、错字、格式和一般完整性问题。
- `warn/general/hint/manual_review`。
- confidence 不足或安全类别不受控。
- 当前 jyjc 的任何 omission；危急值未响应在机构规则和完整时间窗未结构化接入前最高 medium/manual_review。

## 9. 尚未关闭的风险

### R1：未做 Dify 实机导入

静态 YAML 可解析不等于 Dify 当前版本一定接受全部 DSL 字段。需要新应用导入验证，禁止覆盖生产。

### R2：未做真实 Qwen 回放

尚未对六类脱敏样本实际运行 Qwen，因此无法证明固定维度完整率、JSON 成功率或临床准确率。

### R3：四类无工作流内 Code 校验

admission、discharge、surgery、syssvsscbc 仍主要依赖后端 fail closed。独立复核者应比较：

- 保持当前低改动方案；或
- 为四类增加统一 deterministic validator/normalizer。

若建议增加，必须说明节点设计、失败输出、固定维度表、如何保证不补造临床事实，以及为何不会把 parse failure 伪装为 pass。

### R4：surgery 三来源前置条件

必须确认真实 payload 能独立标识 `preop_record`、`operation_record`、`postop_record`。无法区分时不得上线 surgery 新提示词。

### R5：本地与生产配置不完全一致

本地 `config/config.json` 只完整列出部分现役类型，生产服务器此前已运行六类。不能只按本地配置推断生产 `workflow_output_key`、`extra_inputs` 和 `response_paths`。

### R6：34 个不合格 high 的持久化路径

现部署后端理论上会降级不合格 high，但生产库仍出现 34 个不合格 high。独立复核必须继续检查：

- 实际容器镜像是否含当前 `_post_process_result`；
- 所有 serial/bulk/retry 路径是否传入正确 `audit_type_code`；
- `response_paths` 叠加后是否绕过或覆盖降级结果；
- writer 是否保存了后处理前对象；
- 这些记录是否为更新前历史结果。

在该问题查明前，不得把 Dify 优化版直接接入真实高危告警。

## 10. 建议的 Dify + AI + 推送目标流程

```text
数据加载与来源预检
  -> 缺失文书：本地标记 missing/manual_review，原则上不调用模型
  -> 节点一：低温度事实提取，只输出 source_status/issues
  -> deterministic schema validator
  -> 节点二：温度 0，仅做结构转换
  -> deterministic final validator + 高危硬门槛复算
  -> 后端 parse_success/qc_usable 判断
  -> shadow 临床语义检查
  -> 告警资格与科室白名单
  -> relay enqueue/dispatch
  -> H5 反馈与复核闭环
```

推荐原则：

- 临床事实由模型抽取；固定结构、枚举、汇总和 high 门槛尽量由确定性代码复算。
- 文书整体缺失可在调用 Dify 前识别，减少成本并避免模型误判。
- Dify 格式修复只能修语法和字段，不得补造证据或升级严重度。
- 解析失败结果只进入人工排查，不进入当前有效结果、supersede 或告警。
- 真实告警启用应晚于影子验证和临床抽检。

## 11. 独立复核任务

请逐项给出“通过 / 问题 / 建议”，不得只做概括评价。

### 11.1 Dify DSL

1. YAML 是否可被目标 Dify 版本导入。
2. 31 个节点、31 条边是否均可达；是否存在无 End 路径。
3. `if-else` 的 `comparison_operator=is`、多条件 `or` 是否符合该 Dify 版本 DSL。
4. End 同时输出 `aa/hcjg` 是否允许且两者同值。
5. Code 节点 JavaScript 是否满足 Dify `function main(inputs)` 和输出参数定义。

### 11.2 参数契约

1. 后端六类实际 `mr_type` 是否全部被路由覆盖。
2. 生产六类 `workflow_output_key` 是否均为 `aa` 或 `hcjg`。
3. `mr_txt` 是否始终为字符串。
4. 六类生产 `response_paths` 是否需要统一到 `audit_summary`。

### 11.3 提示词与临床口径

1. 六类固定维度是否与 reference 110–115、解析器和页面统计一致。
2. admission 当前 10 个 canonical code 是否合理；不得重新引入 `other`。
3. surgery 三来源是否可真实区分。
4. jyjc 危急未响应禁 high 是否与当前数据能力一致。
5. 缺失、单侧未提及、合理演变和时间差异是否能稳定阻止 high。

### 11.4 JSON 与后端

1. 六类节点二输出能否被 `_parse_new_schema` 一致解析。
2. `medical_evidence/nursing_evidence/extra.issues` 是否完整。
3. patient summary 缺字段时是否仍可解析且不编造。
4. fallback、截断、代码块、尾逗号和空输出是否 fail closed。
5. 是否需要为另外四类新增 deterministic validator；如需要，给出最小改动设计。

### 11.5 推送安全

1. 非 parse success 是否在所有入口均禁止维度落库、supersede 和 relay。
2. 高危复合门槛是否在真正写库前执行。
3. `dept_filtered` 是否仅代表过滤，不能当作链路成功。
4. 影子测试是否确保不向企业微信/H5 外发。

## 12. 建议测试矩阵

每类至少测试：

1. 双方文书完整且一致。
2. source A 缺失。
3. source B 缺失。
4. 双方均缺失。
5. 一方有记录、另一方未提及。
6. 同义、上下位或合理时间演变。
7. 双侧明确一般冲突，应为 medium。
8. 双侧直接安全冲突且全部门槛满足。
9. severe 但缺证据、低置信度或类别不受控，应降级。
10. JSON 代码块、尾随说明、尾逗号、截断和空输出。

最低技术验收：

- 六类合法样本 parse success 率 100%。
- 缺失文书 high 数为 0。
- 单侧证据 high 数为 0。
- warn 被映射 high 数为 0。
- 无 qualified issue 的 high 数为 0。
- 所有 parse failed 均无维度、无 supersede、无告警。
- 新出现的合法 high 必须逐条临床复核，不能用“不得新增 high”作为错误验收指标。

## 13. 禁止事项

- 不得直接覆盖生产 Dify 应用。
- 不得修改六类 audit type code。
- 不得把 builder 输出改为 `mr_txt`；映射仍只在 `dify_pusher.py`。
- 不得放宽 high 证据、置信度或安全类别门槛。
- 不得让 fallback/parse failed 进入告警或 supersede。
- 不得用真实患者做外部 AI 或真实企业微信测试。
- 不得根据本说明自动修改生产配置、数据库或历史等级。

## 14. 当前裁定

优化版已通过静态 YAML、变量绑定、31/31 节点可达、路由失败关闭、双输出键以及六类后端 parser 合成冒烟检查；后端也已补齐六类 audit code 的 `mr_type` 默认映射。但尚未完成目标 Dify 版本重新导入、Qwen 六类样本回放、临床抽检、生产 output key/response paths 核对和 34 个历史不合格 high 持久化路径定位。因此当前只能作为独立复核和影子验证候选，不能直接作为生产发布授权。
