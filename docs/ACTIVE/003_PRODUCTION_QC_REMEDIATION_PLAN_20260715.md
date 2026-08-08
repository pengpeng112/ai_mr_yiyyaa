# 生产质控完整性、解析质量与高危准确性整改计划（待独立复核）

> 文档状态：待独立复核，禁止直接实施  
> 编制日期：2026-07-15  
> 最近修订：2026-07-15（吸收独立复核意见并完成代码现状校正、依赖图和关键语义冻结）  
> 本地实施复核：2026-07-15（A/B/C/D-shadow/E/F 初版的阻断缺陷已修复并通过全量 pytest；生产、Dify、临床、002 与 G 仍未验收）  
> 服务器部署：2026-07-15 17:58（镜像 `sha256:3ddfa3255526600d62d8a795e9607a0e97439b9c95c1e117b5e6da74bf410003`；容器 healthy；未触发任务、Dify、告警或补跑，等待运行观察）  
> 证据日期：生产任务业务日期 `2026-07-14`  
> 适用系统：Med-Audit 六类质控、双模式调度、Dify 结果解析、告警与 H5 反馈  
> 操作约束：本计划不是上线授权。复核通过后仍须按工作包、停止点和审批门逐项执行，禁止合并工作包或跳过灰度。
> 唯一文件：本仓库不存在另一份 `AI-HMS` 命名的同内容计划；实施与复核只能引用本文件和 `docs/INDEX.md` 中的 003 条目。

## 1. 目标与边界

### 1.1 整改目标

1. 让“任务完成”同时反映审计类型是否实际执行、Dify 是否返回、结果是否可解析、结果是否可用于质控，而不是只看 PushLog 是否存在或 HTTP 是否成功。
2. 修复 `jyjc_vs_bcnursing` 终末任务因 Vastbase 全住院时间窗查询超时而整类无结果的问题，并支持安全、可审计的定向补跑。
3. 降低 `admission_vs_first_progress` 结构化输出不可用率，不改变六类质控 code、Dify 主输入变量、现役最终 JSON 契约和已经生效的高危硬门槛。
4. 在现有高危形式门槛之上补充证据语义质量控制，重点处理“相同证据声称冲突”“过短证据缺上下文”“宽泛维度承载高危”等风险。
5. 补齐任务完整性、解析质量、告警过滤/发送状态的页面与运维观测，并降低健康检查和日志对生产数据库及隐私的额外影响。
6. 对本次漏跑和解析失败数据进行可核对、可回滚、无重复告警的恢复。

### 1.2 明确不做

- 不重命名或新增六类质控 code；生产现有 `discharge_vs_frontpage` 保持不变。
- 不改变 `mr_text` 构建语义、Dify 默认输入变量 `mr_txt` 的映射位置或现役 JSON 字段名称。
- 不把“某类文书缺失、一方未提及、信息不足”升级为 high。
- 不以简单提高数据库超时作为唯一修复，不静默吞掉分批查询失败，不把部分结果伪装为完整成功。
- 不在缺少临床专家确认时直接启用新的高危临床规则。
- 不用真实患者数据做外部 Dify、企业微信或前置机测试；生产补跑必须另行书面批准。
- 不顺带实施 `ACTIVE/002_PUSHLOG_IDEMPOTENCY_DESIGN_GATE.md`。如本计划依赖其 execution/attempt 能力，须先确认 002 的实现状态并作为独立工作包验收。

### 1.3 与现役 001/002 的边界

1. `ACTIVE/001_PENDING_WORK_EXECUTION_PLAN.md` 管理认证、权限、SSRF、敏感日志、留存等安全债。003 可进行只读分析、本地开发和影子验证，但进入 E 的真实外发或 G 的任何生产写操作前，技术负责人和安全负责人必须确认 001 中以下门禁已关闭并提供测试证据：默认管理员兜底、JWT 生产环境/默认密钥、匿名 notify SSRF、反馈科室越权、病历正文日志。未关闭时不得扩大管理面或外发范围。
2. `ACTIVE/002_PUSHLOG_IDEMPOTENCY_DESIGN_GATE.md` 管理 execution/attempt、原子 claim 和并发重试。003 不重复实现这些表或事务语义；推荐轨要求 002 验收后才进入 G 的生产补跑。
3. 紧急补跑不是默认替代方案。只有医院书面认定漏跑造成的业务风险高于重复处理风险时，才可走 §4 G 的应急轨；实施 AI 无权自行启用。

## 2. 生产核查基线

### 2.1 推送与调度

业务日期 `2026-07-14` 自动任务共生成 1,362 条 PushLog：

| 状态 | 数量 | 说明 |
| --- | ---: | --- |
| success | 918 | 仅表示推送/持久化主流程成功，不等于结构化结果可用 |
| skipped | 444 | `unreviewed_pending` 241、`empty_lab_exam` 172、`insufficient_surgery_docs` 31 |
| failed | 0 | 不能据此认定六类全部成功，见下述“落库前整类失败” |

主要异常：

1. `discharge_final / jyjc_vs_bcnursing` 在 Vastbase `fetch_emr_documents_by_visits` 查询阶段触发 `psycopg2.errors.QueryCanceled: canceling statement due to statement timeout`，对应 SchedulerHistory 为 failed、总数 0，且没有生成 PushLog。
2. 该异常发生在逐患者 PushLog 之前，因此仅看 PushLog 失败数会得到“0 失败”的错误结论。
3. 同一终末调度中的其他类型随后继续执行，说明失败隔离存在，但缺少整次运行的“部分成功”汇总和醒目标识。

### 2.2 结构化解析质量

918 条 status=success 的 PushLog 中：

| parse_status | 数量 |
| --- | ---: |
| success | 754 |
| fallback | 2 |
| failed | 162 |

162 条解析失败全部来自 `admission_vs_first_progress`，占该类型 298 条传输成功记录的 54.4%。其中 158 条为 `parsed_json_missing_dimensions_and_conclusion`，4 条为 JSON 语法错误。原始响应并非空，因此根因更接近 Dify 节点输出契约遵循失败，而不是网络失败。

### 2.3 高危与告警

1. 共 42 条顶层 high PushLog、50 个 high 维度，全部来自 `admission_vs_first_progress`。
2. 复核脚本按现行后端复合门槛校验后，50 个维度均满足：维度 `status=fail`、双方有效证据、`confidence >= 0.8`，且至少一个 issue 同时满足 severe、high_eligible、contradiction、双方证据和受控安全类别。
3. 因此本次不能把问题描述为“后端高危硬门槛仍被绕过”。剩余风险是证据的临床语义质量：56 条 issue 中有 3 条双方证据文本完全相同；15 条至少一侧证据少于 12 个字符；`physical_examination` 与 `other` 合计承载 25/50 个 high 维度。
4. 50 个 high 维度均生成告警记录，但状态全部为 `dept_filtered`；当前科室白名单只允许“听觉植入科”，所以当天没有真实外发，不能据此证明企业微信送达和 H5 反馈链路可用。

### 2.4 其他观测

- Dify `patient_summary` 偶发缺 patient_id、patient_name、query_date 或 audit_date；PushLog 仍能依靠请求上下文关联患者，但模型输出完整性不足。
- `/api/health` 的深度检查被容器频繁调用时会连接 Oracle，造成无必要负载和连接成功日志噪音。
- 当天同业务日期查询未观察到 superseded 记录，但日志存在终末结果触发 supersede 的线索；在未完成跨日期/同住院号对账前，不判定为代码缺陷。
- 生产 Oracle Instant Client 11.2 缺少较新的 call timeout/连接池能力；升级属于独立基础设施事项，不与业务修复混发。

### 2.5 已有能力与真实缺口（实施者不得重复建设）

| 主题 | 当前代码已有能力 | 本计划真实缺口 |
| --- | --- | --- |
| 健康探针 | `GET /api/health/live` 已存在且不访问外部依赖；`GET /api/health/ready` 已存在并要求 `view_scheduler`；Compose 已使用 `/live` | `docker_deploy.sh`、`DEPLOY.md` 等仍调用深度 `/api/health`；深度检查缺少缓存/最小间隔；需盘点前端、监控和脚本调用方 |
| Vastbase 分批 | `fetch_emr_documents_by_visits` 已有 `batch_size`，默认 500、限制 1–5000，并按患者键串行分批 | 终末全住院期文书量、单批 SQL/索引、模板过滤、串行总耗时及 statement_timeout 的组合根因未定位 |
| 类型失败历史 | `scheduler_audit_runner` 异常路径已写 `SchedulerHistory(status=failed,total_records=0)` | 缺少同一次跨类型运行的汇总、run_mode/错误分类表达和 UI 醒目标识；PushLog 页面掩盖落库前失败 |
| 终末覆盖 | `push_log_supersede.py` 已按 discharge `status=success` 覆盖 daily | 当前没有检查 `parse_status`，解析失败/fallback 的终末记录仍可能错误覆盖日常可用结果 |

## 3. 总体整改原则

1. **状态分层**：区分 transport、parse、qc_usable、alert 四层状态；任何一层失败都不得被总览展示为“全部完成”。
2. **失败显式化**：审计类型在生成 PushLog 前失败，也必须在运行历史、接口和页面中可见。
3. **完整性优先**：分批查询可以重试，但任一批最终失败时整个审计类型标记 failed；不得把已取到的部分患者作为完整批次提交。
4. **兼容优先**：不直接改写历史 `PushLog.status` 语义；第一阶段以已有 `parse_status` 推导 qc_usable，待接口和页面完成兼容后再评估是否需要新增字段。
5. **高危保守**：既不因文书缺失报 high，也不因证据短就无条件降级。短证据只有在具备结构化断言、部位/侧别、极性、时间和上下文时才可参与高危。
6. **影子验证**：高危语义规则先只计算候选新等级和降级原因，不改变生产告警；完成临床复核后才允许切换。
7. **可恢复**：补跑按业务日期、run_mode、audit_type_code 精确限定；复用幂等/attempt 机制，禁止生成不可追溯的重复当前结果或重复告警。

### 3.1 已冻结的业务与工程语义

以下结论不再留给实施者自行选择：

1. 第一阶段 `qc_usable = PushLog.status == "success" AND PushLog.parse_status == "success"`。历史 fallback 从“传输成功”中保留，但从“质控可用成功”中排除，报表必须标注统计口径变更日期。
2. fallback 和 parse_failed 仅供排查/人工复核：不得抬升顶层风险、不得生成外发告警、不得成为当前有效结果、不得触发 supersede。
3. “出院结果为终末版本”解释为“**可用的出院终末结果优先**”。只有 discharge_final 且 qc_usable 的记录可以 supersede daily；不可用终末记录保留历史但不覆盖既有可用 daily。
4. 格式修复不得创造、补写或改写临床事实。修复后出现新的合法 high 不自动视为回归，必须单列数量并临床抽检真/假阳性。
5. SchedulerHistory 采用“方案 B”：优先复用现有 per-type history，由 API 按调度时间窗、query_date、trigger/run_mode 和配置类型集合派生整次汇总；第一阶段不建父 run 表。只有 run_mode、error_code、短 error_summary 无法可靠派生时，才提交最小加列设计并另行批准。
6. 查询失败 v1 采用整类原子：任何批最终失败，本类型不得产生“当前可用”的部分结果。若实测恢复成本不可接受，v2 只能引入 staging checkpoint，全部成功后原子 promote；失败的 staging 永远不得进入当前 PushLog/告警/supersede，且 v2 必须单独设计审批。

## 4. 依赖图、实施顺序与停止点

### 4.1 硬依赖 DAG

```text
P0 设计冻结与基线
├─ A 状态聚合与页面 ───────────────┐
├─ F 健康/日志调用方减负（可与 A 独立） ─┤
├─ B Vastbase 根因与可靠性 ──────────┤
├─ C 解析与 Dify 影子 ──┬─ D 临床规则 shadow ┤
│                       └─ E 告警观测/合成闭环 ┤
└─ 001 安全门 + 002 幂等门 ────────────┤
                                        └─ G 生产灰度、恢复与对账
```

依赖解释：

- P0 是所有工作包的前置条件。
- A、F、B、C 在 P0 后无代码硬依赖，可分别开发；D 依赖 C 的统一样本和解析口径；E 的状态观测依赖 A，合成链路可提前准备。
- G 必须等待 A、B、C、E 验收；F 的调用方减负必须在同轮生产发布前完成；D 可保持 shadow，不阻塞查询/解析恢复，但阻塞高危新语义正式切换。
- 一个实施 AI 仍须“一次只交付一个工作包、一个独立提交、到停止点即汇报”。允许并行是团队调度能力，不允许把 A+F 或其他包混成一次修改。
- 不得将数据库迁移、Dify 提示词切换、高危规则切换和生产补跑放在同一次发布中。

### P0：设计冻结与基线固化

**目的**：防止修复过程中丢失可比基线或误改契约。

实施步骤：

1. 导出脱敏聚合基线：六类、两种 run_mode 的 SchedulerHistory、PushLog status/parse_status/skip_reason、维度等级、告警状态；不得导出病历正文。
2. 固化 162 个解析失败的错误类别计数，并从已脱敏或合成数据生成最小失败 fixture；原始患者响应只允许在受控环境使用。
3. 为 42 条 high/50 个 high 维度生成临床复核清单，字段至少含 audit_type、dimension_code、双方证据、issue_mode、safety_category、confidence、告警过滤原因；姓名、患者 ID 等标识脱敏。
4. 对同一次 `2026-07-14 discharge_final` 做六类对账：配置是否包含、是否有 SchedulerHistory、候选是否为 0、是否有 PushLog、实际 SQL 是否使用出院日期。候选为 0 必须与 Oracle 出院患者枚举交叉核对，禁止直接解释为“当天无患者”。
5. 确认 `ACTIVE/002` 和 §1.3 所列 `ACTIVE/001` 安全门的实际代码、测试、部署状态，形成逐项证据表。
6. 创建可重复的只读聚合脚本设计，固定路径为 `scripts/qc_production_readonly_audit.py`：默认不接受病历正文、不调用 Dify/relay、不写数据库；输出 JSON/CSV 聚合和校验和。脚本实施属于 P0，必须有“只读 SQL/无 commit/无外部 HTTP”静态测试。
7. 采用 §3.1 已冻结语义，不再在 P0 重新投票；若业务方反对，必须先修订并重新复核本计划。

停止条件：提交基线脚本及测试、聚合结果、六类 discharge 对账、脱敏 fixture 清单、001/002 门禁状态表。任何数据无法复现则停止，不进入其他包。

### A：任务完整性和状态语义

**涉及代码（以实施时实际代码为准）**：

- `app/models.py`：`SchedulerHistory`、`PushLog`
- `app/scheduler.py`、`app/services/scheduler_audit_runner.py`
- `app/routers/scheduler.py`、`app/routers/logs.py`
- 调度/日志相关静态页面与 API schema
- `app/database.py`（仅当复核批准新增字段时）

实施步骤：

1. 不重复建设类型失败落库。复用现有 per-type SchedulerHistory，由汇总 API 派生一次调度的 `completed`、`partial`、`failed`、`running/unknown`；配置类型全部有终态且无 failed 才允许 completed，任一类型 failed 或缺少终态即为 partial/failed/unknown。
2. 每类显示：候选患者数、PushLog 成功/跳过/失败、transport success、parse success/fallback/failed、qc_usable、high 数、告警 pending/success/failed/dept_filtered。
3. 保留当前候选加载/多源查询异常仍写 SchedulerHistory 的行为并补测试；先从日志/配置派生 run_mode。只有无法稳定关联时，提交 `run_mode + error_code + 短 error_summary` 最小加列方案，不得直接创建父 run 表。
4. 错误摘要禁止包含 SQL 全文、数据库口令、病历正文和患者标识；原始异常只进受限服务日志并按现有脱敏规则处理。
5. 调度状态页增加“本次运行不完整”醒目标识；不得再由 PushLog failed=0 推导整体成功。
6. 日志列表保留历史 `status`，新增派生展示“传输成功/解析失败/质控可用”；CSV 同步新增字段并调用导出审计。
7. high/alert 等明细计数由 PushLog、维度和告警表聚合，不冗余写入 SchedulerHistory。若最小加列确有必要，先提交 SQLite/Oracle 双数据库迁移设计、回填默认值、`_verify_required_schema()` 变更及回滚 SQL，批准后才改 ORM。

测试要求：

- 类型在生成第一个 PushLog 前抛异常，整次运行必须 partial/failed。
- 一类失败后其他类型继续，汇总必须 partial。
- status=success + parse_status=failed 不计 qc_usable。
- 历史 NULL 字段、旧 SchedulerHistory、SQLite/Oracle 字段兼容。
- API 权限、CSV 字段和导出审计回归。

验收门：页面能准确复现当天 `jyjc_vs_bcnursing` 为类型级失败，且 162 条解析失败不再出现在“可用成功”内。完成后停止。

### B：Vastbase 终末查询可靠性

**涉及代码**：

- `app/emr_vastbase_client.py::fetch_emr_documents_by_visits`
- `app/services/data_source_loader.py` 的 discharge_final 多源加载路径
- `app/services/scheduler_audit_runner.py`
- `config/config.json.template` 及配置校验接口
- `tests/test_emr_vastbase_client.py` 和新增 loader/timeout 测试

实施步骤：

1. 先用阶段计时和错误码证明超时层级：Oracle 出院患者枚举、Vastbase 连接、患者键批查、具体 `document_kind`、payload 组装或 Dify；不得把所有 timeout 归为同一原因。
2. 对现有分批实现做基线而非重写：记录总键数、batch_size、批数、每批耗时/行数、最慢批和总耗时；日志只记数量与批号，不记患者键。
3. 在只读环境取得实际终末 SQL 的 `EXPLAIN`/执行耗时和返回行数分布，由 DBA 核查 `v_blws`、患者键连接、`progress_template_name`/模板过滤及相关索引。若无 DBA 权限，输出待执行 SQL 和证据，不擅自创建索引。
4. 对终末专用加载策略做三组对比：当前全住院期、按 document_kind 拆查、经临床批准的时间/文书数量裁剪。任何“最近 N 份”或时间窗裁剪都可能漏临床信息，未经临床签字只能测性能，不能启用。
5. 压测现有 batch_size 的多个档位，识别单批超时还是串行总耗时；默认值由结果确定。保留参数绑定、列名 `.lower()` 和现有模板过滤语义。
6. SQL/索引/加载策略确定后，再加稳定性保护：仅对 statement timeout、连接瞬断等明确瞬态错误做有限指数退避；语法、权限、字段错误不得重试；建立总截止时间和稳定错误码。
7. v1 保持整类原子。任一批最终失败时，本类型不得产生当前可用结果，SchedulerHistory 记 failed；已取得的内存结果丢弃。staging checkpoint 仅按 §3.1 第 6 条另案审批。
8. 配置项保存校验上下界；老配置采用安全默认值；配置页面不得显示密码。现有 batch_size 范围如需改变，须给出压测证据和兼容测试。
9. B 只完成管理员定向重试接口的设计、权限和参数校验测试桩；真正写操作必须进入 G，并复用 002 或获批应急轨。

测试要求：阶段错误分类、现有分批等价性、空键、单批/多批/边界批次、重复键、大写列名、特定 document_kind、第二批超时后重试成功、最终超时整类失败、非瞬态错误不重试、总截止时间、连接关闭/回滚、无部分 promote。

验收门：提交阶段定位、EXPLAIN/DBA 结论、batch_size 压测矩阵和终末加载策略对比；使用合成或脱敏同规模键集合连续三次完成且结果数一致；超时注入时状态可见且无伪成功。完成后停止。

### C：Dify 输出与解析可用性

**涉及代码/资产**：

- `docs/reference/109_DIFY_PROMPT_FINAL_IMPLEMENTATION_PLAN.md`
- `docs/reference/110_DIFY_PROMPT_ADMISSION_VS_FIRST_PROGRESS.md`
- 六类 Dify 两节点提示词（仅先改文档/影子工作流）
- `app/services/dify_schema_parser.py`
- `app/services/push_log_writer.py`、`app/services/push_executor.py`
- `app/dify_pusher.py`
- parser、writer、executor 的 fixture 回归测试

实施步骤：

1. 用 162 条失败分类定位是节点一缺事实、节点二未输出 JSON、JSONPath 配错还是模型格式漂移；不得只凭四条语法错误推断全部原因。
2. 节点二强化：首字符 `{`、尾字符 `}`、无 Markdown；必须输出 `dimensions` 和 `conclusion`，无问题时输出空数组和非高危结论，不允许省略字段；patient_summary 由输入确定性复制，不让模型自由编造。
3. 保持六类现有字段名和后端 parser 可识别证据字段；不得引入第三套证据命名。
4. parser 保留 raw response 的受控引用与明确 parse_error 分类；严禁在 JSON 缺关键结构时凭自然语言推断 high。
5. 按 §3.1 落实可用门槛。特别检查 `push_log_writer.py`、串行/批量/重试入口和 `push_log_supersede.py`，确保 fallback/parse_failed 不抬升风险、不外发、不成为当前有效结果、不 supersede；历史原始记录仍保留。
6. 评估一次有界“格式修复”机制：仅修复 JSON 语法/包装，不新增临床事实；修复前后原文和原因可审计。若需要再次调用模型，必须独立开关、最多一次、使用合成/脱敏验证并统计成本与误差。
7. Dify 先建影子版本，回放脱敏/获批样本；禁止直接覆盖生产工作流。对比 parse success、维度数、结论、高危差异和延迟。

测试要求：158 类缺 dimensions/conclusion、4 类 malformed JSON、Markdown 包裹、空输出、旧 schema、六类合法输出、patient_summary 缺失、fallback 不告警不 supersede、raw response 脱敏。

验收门：影子样本 parse success ≥ 99%，且所有失败均显式标记；现有六类合法 fixture 100% 兼容；格式修复没有创造临床事实。分别报告解析恢复数、恢复后新增 high 数及临床抽检的 true/false positive，不能以“新增 high=0”作为验收条件。完成后停止并由用户人工更新 Dify。

### D：高危临床语义质量（必须临床专家确认）

**原则**：现行后端复合硬门槛有效，本包是附加语义保护，不替代双方证据、confidence、issue_mode、high_eligible 和 safety_category 门槛。

候选规则：

1. 双方证据去空白、标点和格式标签后完全相同，不得作为 contradiction 的唯一依据；降为 manual_review/medium，并记录 `identical_evidence`。
2. 不以“少于 12 字”一刀切。短证据必须同时提供规范化主张，例如 `attribute=手术侧别`、`value_a=左`、`value_b=右`，并携带文书名和上下文；否则不得 high。
3. `dimension_code=other` 默认禁止 high。确有直接安全风险时必须映射到受控维度或新增维度设计，经临床和契约审批后实施。
4. `physical_examination` 只有在明确患者身份、手术部位/侧别、过敏用药或关键诊断依据冲突且存在直接安全后果时可 high；一般查体差异、详略差异、病程演变不得 high。
5. 一个维度包含多个 issue 时逐条验证；顶层 high 必须至少存在一个通过全部形式门槛和语义门槛的 issue。
6. 文书缺失、一方未提及、时间窗不完整继续绝对禁止 high；检验危急值未响应例外仍必须依赖本院规则、危急值本身、通知/处置完整时间窗。

临床复核方法：

- 对当天 42 条记录、50 个高危维度全量双人盲审，分歧由第三位临床专家裁决。
- 标注“真实直接安全风险/一般矛盾/病程演变/证据不足/文书缺失/模型误引”，同时评价证据是否能独立支持结论。
- 规则先运行 shadow，只写比较日志或离线报告，不影响等级、告警和当前记录。
- 上线标准：误报率达到院方目标；任何已确认真实直接安全风险被降级都必须分析并修正规则。具体阈值由医务/质控部门书面确认，本计划不擅自设定。

涉及代码预计为 `app/services/dify_schema_parser.py` 的高危资格判断、`audit_result_mapper`/writer、提示词和对应测试；具体函数应在实施前以当前代码定位，不按过期行号修改。

验收门：临床签字的规则表、50 维度复核结果、shadow 前后混淆矩阵和漏报清单齐全。没有临床书面确认不得切换。完成后停止。

### E：告警范围、送达和 H5 闭环

**涉及代码**：`app/services/relay_alert_service.py`、告警/H5 路由、配置接口和对应页面。

**进入门**：业务负责人必须先书面确认当前 `alert_dept_filter=["听觉植入科"]` 是有意限制还是配置遗漏。确认前只允许做状态可观测性和本地合成 relay，不得扩科室或真实外发。

实施步骤：

1. 页面分别显示 high eligible、已创建、dept_filtered、pending、success、failed，过滤状态不得显示成“发送成功”或“系统无高危”。
2. 展示当前 `alert_dept_filter` 及命中依据（dept_code/dept_name），但不暴露 secret。
3. 对空科室、科室回填失败、白名单拼写差异建立明确状态和聚合告警。
4. 使用纯合成患者和本地/测试 relay 验证签名、重试、幂等、detail_url、token、H5 查看和反馈；真实前置机测试须单独批准。
5. 若白名单被确认正确，保持原范围，只验证可观测性；若确认遗漏，另开配置变更单，列明新增科室、负责人和回滚值。生产灰度只使用已批准科室的一条合成告警；不得用当天患者补发测试。

验收门：告警状态账实一致，过滤原因可解释，测试 relay 与 H5 闭环通过。完成后停止。

### F：健康检查、日志和基础设施减负

实施步骤：

1. 不重复创建探针：验证现有 `/api/health/live` 不访问外部依赖、现有 `/api/health/ready` 继续要求 `view_scheduler`、Compose 继续使用 `/live`，并补防回退测试。
2. 盘点 `docker_deploy.sh`、`DEPLOY.md`、前端、监控、运维脚本中所有 `/api/health` 调用；探活改 `/live`，部署后的授权深检改 `/ready`。更新文档时同步 INDEX 规则，保留兼容路径但标记不得用于高频 probe。
3. 对兼容 `/api/health` 深检增加短时缓存/请求合并或最小探测间隔，避免并发重复连接业务库；不得缓存或返回口令、SQL、患者信息。缓存 TTL 和失败策略必须测试。
4. `patient_summary` 缺字段、parse_error 和查询超时改为聚合计数加抽样日志；日志不得包含病历正文和患者标识。
5. 验证 `audit_detail.log` 级别、轮转和留存策略；生产默认不得记录正文预览。
6. Oracle Instant Client 19c 升级另建运维变更单，验证加密配置可解密、Oracle 驱动兼容和回滚镜像后实施，不与应用功能发布捆绑。

测试要求：liveness 不调用任何外部依赖；readiness 超时隔离；容器健康状态稳定；日志脱敏和轮转测试；旧监控调用兼容或同步更新。

验收门：24 小时健康探测不产生业务库连接风暴，日志无病历正文。完成后停止。

### G：生产灰度、定向恢复与对账

**共同前置条件**：A、B、C、E 验收；F 的生产调用方减负完成；001 安全门关闭；D 保持 shadow 或已获临床签字；用户书面批准生产变更和补跑窗口。

**推荐轨（默认唯一允许轨）**：002 的 execution/attempt、原子 claim、所有推送入口覆盖及 SQLite/Oracle 并发测试通过。复用同一 execution，失败重试创建递增 attempt。

**应急轨（默认禁用）**：002 未就绪时原则上不做生产补跑。只有医院业务负责人、技术负责人、运维负责人共同书面特批，才可在单 worker、停用同类自动调度、独占 run lock、先 dry-run 对账、relay 外发关闭、单日期+单 run_mode+单 audit_type、全程操作审计和可回滚备份条件下执行一次。应急轨不得新增临时 ORM/唯一约束，不得使用 manual_override 绕过已复核记录，不得并发，不得扩大到 admission 重调 Dify。任一前置条件不满足立即停止。

实施顺序：

1. 备份镜像、配置和应用数据库；记录镜像 digest、配置校验和、数据库 schema 版本和回滚命令。
2. 先部署不改变临床等级的 A/B/C/F 代码，保持 D 高危语义规则 shadow、告警配置不变。
3. 选择非生产数据集或批准的小日期范围做 canary，核对 SchedulerHistory、PushLog、parse_status、维度、supersede、告警状态。
4. 先用 P0 脚本对 `2026-07-14 discharge_final` 六类全部做只读对账，确认每类的配置、history、候选、PushLog 与出院日期 SQL。只允许把已证明的漏跑加入补跑清单；当前已知写操作范围锁死为 `query_date=2026-07-14`、`run_mode=discharge_final`、`audit_type_code=jyjc_vs_bcnursing`，其他类型发现疑点只能另报审批。
5. 对 162 条 admission 解析失败：能从已存 raw response 确定性重新解析的先离线重解析；需要重新调用 Dify 的记录另列清单并审批。重处理不得覆盖原始响应、不得重复企业微信告警。
6. 执行终末覆盖对账：同 patient_id + visit_number + audit_type 下，日常与终末均保留；终末可用结果将日常标记 superseded；parse_failed/fallback 的终末结果不得 supersede 日常可用结果。
7. 输出完整性报表：配置类型数、类型历史终态、候选数、成功、跳过及原因、失败、parse success/fallback/failed、qc_usable、high、alert 各状态、superseded 数和差异原因。
8. 连续观察至少一个完整 daily_increment 和一个完整 discharge_final 周期，逐类核对“候选为 0”不是 SQL 转换或配置错误，再决定是否启用 D 的新语义规则。

回滚触发：任何类型整类缺失、parse success 明显下降、真实高危被错误降级、重复当前记录/重复告警、supersede 错标、H5 无法访问、数据库迁移校验失败。触发后停止任务、回滚镜像/配置；数据修复使用审计脚本，不删除原始 execution/attempt/PushLog。

验收门：六类均有明确终态；`jyjc_vs_bcnursing` 漏跑完成对账；解析不可用不再计入可用成功；无重复告警；临床抽检完成。验收报告签字后方可关闭计划。

## 5. 数据库与兼容性决策

1. 优先复用现有 `PushLog.parse_status` 和 SchedulerHistory，避免为状态展示立即改写 PushLog.status。
2. A 包固定采用 API 派生汇总，禁止第一步创建父 run 表或把 parse/high/alert 计数冗余写进 SchedulerHistory。仅当 P0 证明 run_mode 和错误原因无法可靠关联时，允许提出 `run_mode`、`error_code`、短 `error_summary` 最小加列，且不得在未批准时实施。
3. 获批的最小加列必须同步：
   - SQLAlchemy ORM；
   - SQLite 手工迁移；
   - Oracle 手工迁移，字段类型/默认值/空字符串语义兼容；
   - `app/database.py::_verify_required_schema()`；
   - 老数据回填策略和只增不删的回滚方案；
   - API schema、CSV 和页面 NULL 容错测试。
4. 任何新增唯一约束、execution/attempt 表或 claim 流程均归 `ACTIVE/002` 管理，本计划不得重复设计或绕过其审批门。
5. 推荐轨补跑使用同一 execution 的递增 attempt；相同版本且已复核记录默认跳过；manual_override 仅管理员可执行且普通用户禁止。若无需填写原因，系统仍必须自动记录操作者、时间、参数、来源 IP/请求 ID 和前后状态。

## 6. 必须新增或强化的自动化测试

| 测试组 | 必测场景 |
| --- | --- |
| 调度完整性 | 加载前失败、类型级失败后继续、部分成功汇总、缺少类型终态、并发 run lock |
| Vastbase | 分批等价性、超时重试、最终失败无部分提交、列名小写、模板过滤、连接回收 |
| Parser | 六类合法 schema、缺 dimensions/conclusion、malformed JSON、Markdown、旧 schema、空输出 |
| 风险门槛 | 单侧/无证据、相同证据、短证据有/无结构化上下文、other、physical_examination、fallback 禁 high |
| 持久化 | parse_failed 不写高危维度、不告警、不 supersede；历史 NULL 兼容；事务失败隔离 |
| 告警 | dept_code/name 白名单、dept_filtered、pending/success/failed、幂等、H5 token/反馈权限 |
| API/UI | qc_usable 统计、类型级失败可见、CSV 导出审计、权限与敏感字段脱敏 |
| 双数据库 | SQLite/Oracle 初始化、迁移、schema verify、日期/布尔/空字符串兼容 |
| 只读对账脚本 | 静态证明无写 SQL/commit/外部 HTTP；六类/双模式聚合；脱敏；候选 0 交叉核对 |

执行最低命令：

```text
python -m compileall app tests scripts
python scripts/check_naming_convention.py
python -m pytest
```

还必须执行针对上述新增测试的 focused pytest；禁止删除失败测试、放宽断言、无条件 skip 或吞异常。真实 Dify/数据库/relay 联调结果不能替代单元与集成测试。

## 7. 发布单元（与 DAG 一致）

1. **提交/发布 A**：整次 run 聚合 API、页面和三层状态展示；不得夹带 F。
2. **提交/发布 F**：现有健康探针调用方治理、深检减负和日志聚合；可在 A 后或由另一团队并行，但独立提交、独立验收。
3. **提交/发布 B**：Vastbase 根因修复与可靠性保护；定向重试只保留接口设计/测试桩，不执行生产补跑。
4. **提交/发布 C**：后端可用性门槛与 Dify 影子版本；提示词由用户人工更新。
5. **提交/发布 D**：高危规则保持 shadow；临床签字后另一次发布才允许切换。
6. **提交/发布 E**：告警状态观测与本地合成 relay；真实企微属于独立变更单。
7. **生产 G**：不是普通代码包；只部署已分别验收的版本并执行获批 canary、补跑和对账。

每次发布均记录 git commit、镜像 digest、配置校验和、迁移版本、测试报告、canary 参数、回滚命令。禁止依赖仅存在于容器内且未固化到镜像的热更新。

## 8. 实施 AI 每包交付模板

```markdown
### 工作包 X 交付报告

- 实施范围：
- 未实施内容：
- 修改文件与函数：
- 数据库/配置变化：
- 兼容性说明：
- 测试命令与逐项结果：
- 失败测试及原因（不得隐藏）：
- 安全/隐私检查：
- 灰度或影子结果：
- 回滚方法：
- 与基线差异：
- 仍需人工确认：
- 是否满足停止点：是/否

#### 禁止项检查表（逐项回答是/否并给证据）
- 是否改动六类 code、mr_text/mr_txt 或 JSON 字段契约：
- 是否改动现行高危门槛或启用未签字临床规则：
- 是否修改 002 管理的 ORM/迁移/唯一约束/claim：
- 是否连接生产、调用真实 Dify/relay 或写入患者数据：
- 是否扩大 alert_dept_filter、管理面或网络暴露：
- 是否删除/覆盖/回滚工作区其他人的修改：
- 是否存在未列出的修改文件：
- 契约未变证明（测试/差异）：
- 本包明确未改文件清单：
```

## 9. 治理、签字与仍需人工决定的事项

### 9.1 RACI 和签字

| 角色 | 责任 | 必须签字的停止点 |
| --- | --- | --- |
| 项目/技术负责人 | 范围、架构、兼容性、提交和回滚 | P0、A、B、C、E、G |
| 临床质控负责人 | 样本标注、高危语义、时间窗/文书裁剪 | B 的任何临床裁剪、D、C 恢复后新增 high 抽检 |
| 运维/DBA | EXPLAIN/索引、备份、部署、监控、补跑窗口 | B、F、G |
| 安全负责人 | 001 安全门、权限、日志、外发边界 | E 真实链路、G |
| 业务负责人 | 科室白名单、终末优先、补跑范围 | E 进入门、G |

计划只定义依赖和质量门，不虚构人员姓名或固定工期。P0 交付时由项目负责人填写姓名、联系方式、计划开始/结束日期和每包工作量；未填写不得进入生产相关包。建议 SLA：P0/A/F 各 1–2 个工作日评审，B/C 各 2–5 个工作日，临床 50 维双审在样本交付后 3 个工作日内完成；实际 SLA 以院方书面安排为准。

### 9.2 已冻结、不再提问

- qc_usable 排除 fallback；fallback/parse_failed 禁止告警、current 和 supersede。
- 采用“可用终末结果优先”，不是“任意终末结果优先”。
- SchedulerHistory 先 API 派生、后最小加列，不建父 run 表。
- v1 整类原子；checkpoint 只能 staging 后原子 promote。
- admission 默认先离线重解析 raw；再次调用 Dify 必须单列预算、范围和审批。

### 9.3 仍需书面决定

1. 临床：相同证据、短证据、`other`、`physical_examination` 的候选规则及可接受误报/漏报阈值。阈值未定不妨碍 shadow 报表，但禁止正式切换。
2. 业务：`alert_dept_filter=["听觉植入科"]` 是有意范围还是遗漏。
3. DBA/临床：终末全住院期文书是否允许按 document_kind/时间/数量裁剪；未签字保持全量语义。
4. 管理层：002 未就绪且业务要求立即补跑时，是否特批应急轨。

## 10. 完成定义

只有同时满足以下条件才可将本计划标记完成并归档：

- 六类 daily/discharge 配置范围内的任务均有可见、准确的类型级终态；
- 不再出现“PushLog 0 failed 但整类漏跑未提示”；
- admission 影子/生产 parse success 达到批准阈值，解析不可用结果不抬高风险、不告警、不 supersede；
- `jyjc_vs_bcnursing` 终末查询稳定并完成获批日期的定向对账；
- 高危语义规则经临床专家签字，shadow 证明未造成不可接受漏报；
- 告警过滤、发送、H5 反馈状态账实一致；
- SQLite/Oracle、六类契约、调度、日志、反馈和权限回归全部通过；
- 生产至少观察一个完整双模式周期，无整类遗漏、重复当前结果或重复告警；
- 结论合并回现役基线/契约文档，并同步更新 `docs/INDEX.md` 后再归档本计划。

## 11. 计划复核通过门槛

在以下项目全部勾选前，本文件继续保持“待独立复核，禁止直接实施”：

- [x] 文档路径与 `docs/INDEX.md` 唯一对应，仓库内无第二份 AI-HMS 同内容计划。
- [x] 已按代码现状修订 live/ready/Compose、Vastbase 已分批、SchedulerHistory 已记录类型失败。
- [x] 已使用 DAG 消除实施顺序与发布拆分冲突，且仍要求一个工作包一个提交和停止点。
- [x] 已冻结 qc_usable、fallback、parse_failed、current 和 supersede 语义。
- [x] 已选择 SchedulerHistory API 派生优先、必要时最小加列的低迁移方案。
- [x] 已明确 001 安全门、002 推荐轨及严格受控的应急轨。
- [x] 已增加六类 discharge 对账、Vastbase 分层根因和 staging checkpoint 边界。
- [x] 已删除 C 的“无新增高危”错误验收条件。
- [x] 已增加 alert_dept_filter 业务确认进入门。
- [x] 已指定角色级 RACI、签字停止点、只读基线脚本路径和禁止项检查表。
- [ ] 项目/技术负责人已实名确认范围和工作量。
- [ ] 临床质控负责人已确认 D 的标注组织与签字流程。
- [ ] 运维/DBA 已确认 B 的只读 EXPLAIN 条件和 G 的备份/窗口条件。
- [ ] 安全负责人已确认 001 安全门判定方法。
- [ ] 业务负责人已确认科室白名单及“可用终末优先”语义。

## 12. 给实施 AI 的启动指令

本节仅在 §11 的人工项目门完成、用户书面说“开始 P0”后使用。首次只允许执行 P0，不允许提前实现 A-G：

```text
严格执行 docs/ACTIVE/003_PRODUCTION_QC_REMEDIATION_PLAN_20260715.md。

开始前完整阅读 AGENTS.md、docs/INDEX.md、docs/reference/101_FEATURE_BASELINE.md、
docs/skills/med-audit-codex.md、docs/ACTIVE/001_PENDING_WORK_EXECUTION_PLAN.md、
docs/ACTIVE/002_PUSHLOG_IDEMPOTENCY_DESIGN_GATE.md 和 003 全文。

本轮只执行 003 的 P0，不实施 A-G，不修改生产，不调用真实 Dify/relay/企业微信，
不写业务数据库，不修改六类 code、mr_text/mr_txt、JSON 契约、高危门槛、ORM、迁移、
唯一约束或推送执行器。不得清理、覆盖或回滚工作区其他人的修改。

先盘点工作区和当前代码，建立 scripts/qc_production_readonly_audit.py 及测试时，必须保证：
只读 SQL、无 commit/flush、无外部 HTTP、无病历正文输出、患者标识脱敏；完成六类双模式
聚合和 2026-07-14 discharge_final 六类对账。生产连接只在我另行明确授权时允许；未授权时
使用本地 fixture 完成脚本与测试。

P0 完成后按 §8 模板提交：修改文件、未改文件、基线/对账结果、001/002 门禁状态、所有测试
命令和完整结果、禁止项检查表、回滚方法。然后停止，等待书面批准进入指定的下一个工作包。
任何不确定、证据不一致或测试失败都必须如实报告，不得自行扩大范围、删除测试、放宽断言、
添加无条件 skip 或吞异常。
```

## 13. 2026-07-15 本地代码复核修复记录

> 2026-07-16 事件专项说明：当日 11:44 的 `discharge_push` 因 Oracle `DPI-1080/ORA-12541` 在加锁前失败，未产生六类终末历史。该连接恢复和 `query_date=2026-07-15` 六类补跑的唯一执行顺序见 `ACTIVE/004_ORACLE_RECOVERY_AND_DISCHARGE_RERUN_PLAN_20260716.md`；不得把本计划 G 与 004 合并执行。003 的其他范围继续以本文为准。

本节只记录本地代码状态，不构成生产发布或 G 包授权。

1. 调度汇总不再把同日 daily/discharge 的 SchedulerHistory 直接混用：使用对应 run_mode PushLog 时间窗保守归属；无可靠锚点或窗口重叠返回 `unknown/ambiguous`，不猜测 completed；daily/discharge 分别读取 `daily_push`/`discharge_push` 锁。
2. 高危语义规则硬锁为 shadow，环境变量不能启用实际降级；`physical_examination` 安全类别与现行受控类别统一。
3. 单条重推解析失败时保留原有可用日志、维度和结论，不再写入失败结果或先删除旧结果；解析成功才使用统一 writer 原子替换并触发 supersede。
4. 匿名 `/api/health` 即使传 `force_refresh=true` 也不能绕过深检缓存；授权 `/ready` 保留强制刷新。
5. 告警账实报告改为数据库聚合，消除逐 PushLog 查询高危维度的 N+1。
6. Vastbase visits 查询达到 `max_records` 或总截止时间时显式失败并清除内存部分结果，不再把截断结果当完整成功；按日 visits 路径同样拒绝截断成功。
7. 全量回归命令均通过：
   - `python -m compileall -q app scripts tests`
   - `python scripts/check_naming_convention.py`
   - `python -m pytest -q`

仍未完成：生产只读真基线、Vastbase EXPLAIN/索引/真实性能、六类 Dify 影子、临床双审、科室白名单书面确认、真实 relay/H5、002 execution/attempt、G 补跑和双模式完整周期观察。因此 §11 的人工门仍不得勾选，003 不得归档。

服务器部署留痕：旧镜像标签 `med-audit:backup-20260715-175613`；容器文件备份 `/opt/med-audit-docker/backups/pre-003-20260715-175613.tar.gz`；Compose 备份 `/opt/med-audit-docker/backups/docker-compose-pre-live-20260715-175916.yml`。服务器 Compose 健康探针已由深度 `/api/health` 改为 `/api/health/live`。
