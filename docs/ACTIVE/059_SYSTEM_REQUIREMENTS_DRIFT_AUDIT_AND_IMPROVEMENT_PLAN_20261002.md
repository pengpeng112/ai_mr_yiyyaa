# 059 — 系统现状、历史要求偏差核查与改进执行计划

> 版本：v1.3；编制日期：2026-10-02；复核修订：2026-10-03（v1.1，R01–R12）；执行修订：2026-10-04（v1.2，round-8 修复计划 R0–R7）；执行完成：2026-10-04（v1.3，A0–A9 本地核查与整改模式执行，run_id=system-audit-20261004-r1）；编制/修订者：Codex / GPT-6（会话系统标识）；v1.2/v1.3 执行者：ZCode / GLM-5.3。
> 状态：A0–A9 已按本地核查与整改模式执行完成（§11 执行记录）；生产部署与业务/临床验收未开始（授权外）。执行新增 3+1 修复（FIX-A1/A2/A3 组装层 + FIX-C1 文档），残留全部为外部阻塞或用户裁定项（§11 known findings）。
> 定位：023 综合业务主线的核查与改进专项，不替代 023，不重新启动已交付计划。后续以执行时最新要求和证据更新本文件。
> 后续任务：[060 改进后详细测试计划](060_POST_IMPROVEMENT_FRONTEND_BACKEND_AND_QC_ACCURACY_TEST_PLAN_20261002.md)。先明确要求、查清偏差、完成获授权改进，再以实际交付版本执行060。

## 1. 任务目标与交付边界

回答以下问题，并给出逐条证据和可执行改进，而不是只给宏观建议：

1. 当前代码、配置模板、部署形态和用户实际业务流程分别是什么？哪些已经实现、部署、启用、验收？
2. 之前对话要求、任务文档、最新勘误与当前实现是否一致？有无漏做、多做、误做、提前启用或文档误标完成？
3. 已有缺陷是否真正关闭？已关闭项是否回归？仍开放项是代码缺陷、数据问题、资源阻塞、产品暂缓还是验收不足？
4. 架构、可靠性、权限、前端可用性、质控准确性和运维是否仍有完善空间？每项收益、成本、风险和依赖是什么？
5. 哪些改进可以在本地明确授权范围内完成，哪些需要生产、临床或外部系统另行批准？
6. 每条要求和改进如何交给060验证，避免“修了代码但没有验收标准”？

本计划有两种执行范围，启动时必须在检查点写明：

| 模式 | 执行包 | 可产生的修改 | 完成口径 |
| --- | --- | --- | --- |
| 核查模式 | A0–A5、A8文档部分、A9 | 仅审计证据、计划内结论、必要文档勘误和登记 | 核查交付完成；改进候选未实施 |
| 本地核查与整改模式 | A0–A9 | 现时需求明确、归属清楚的本地P0/P1缺陷修复及必要测试；常规可逆文档补正 | 获授权本地改进完成；生产与临床验收分别列状态 |

仅说“执行核查”时采用核查模式；明确说“执行059并完成本地整改”或复制§12.2提示词才采用第二种模式。文档中的未来步骤、旧APPROVED、已完成报告不自行扩展授权。

## 2. 证据来源、最新要求与冲突裁决

### 2.1 固定启动和审查顺序

1. `AGENTS.md` → `开发起步包/README.md` → `开发起步包/00_AI协作规则.md` → `01_统一修改记录.md`末10行。
2. 读取`02_协作任务板.md`、`docs/INDEX.md`；执行`git status --short`、`git diff --stat`、只读HEAD核对；认领本次文件范围。
3. 读取023最新阶段行及§9.1、101功能基线、102数据/Dify契约、103Relay/H5契约、105对应`docs/skills/med-audit-codex.md`、119协作指南。
4. 按主题配对读取“原始要求→执行计划→交付→后续更正→现时代码/测试”：031/032/034、035/036、037/038、039/040、041/042、043/044、046/047、048/049、050/051、052/053/054/055/056、057/058。
5. 048/050/057等已归档计划按INDEX新路径仅作历史追溯；035等留在ACTIVE不等于当前待执行。024/025仅按准确性、历史整改边界读取，不启动历史整改。
6. 读取109–115六类质控口径、116患者质控任务包、[WP0前端基线夹具](../reference/wp0_frontend_baseline_fixtures/README.md)等相关现役资料。夹具在INDEX登记为逻辑编号117，实际文件没有117前缀；900–906也是索引编号，不能按编号猜文件名。
7. 在本地受控环境盘点可用对话索引。已知`review/conversations-export-20260906/INDEX.md`登记13份导出，截至09-04，含未脱敏敏感串；本轮编制仅核对其索引，不宣称已逐份审阅。执行时先筛选用户消息与日期，再受控提取需求，不能把全文或密钥送入公网模型/终端输出。
8. 对09-04以后的要求从当前会话、01、最新交付与检查点交叉追溯。重点读取01的09-23生产升级/启用两行、09-24目标库纠正行、09-27密钥修复、09-29/09-30补跑记录，以及054§4.1质控科答复、§15.3测试设施实证、§16目标库勘误和056/058接续证据。01/交付中的用户转述应标“有出处的转述”，不冒称原始聊天一手消息。未保存的客户端历史不可假装可访问；登记缺口，只有会实质改变目标、验收、范围或授权的缺失信息才请求用户补充。

### 2.2 两条独立证据链

- **应当怎样**：当前用户明确要求 → 同一事项后续用户修订/批准 → 有出处的现役业务契约/裁定 → 未被替代的任务要求。新要求覆盖旧要求必须限定在同一事项及其范围，不能跨任务迁移授权。
- **实际上怎样**：现时源码、配置与构建证据 → 现时运行/只读核查证据 → 带日期的交付报告 → 历史计划或描述。代码可以证明现状，不能证明偏离用户要求是合理的。

发生冲突，建立`CONFLICT-*`记录，逐条比较用户消息发生时间、原话位置、作用范围、后续确认与实现证据。文件名日期、mtime、文档最后一段和AI总结均不能单独证明“最新要求”。同一天先后不明、原始消息缺失或业务解释不唯一时标`待裁定`，不自动选对自己实现有利的一方。

原始要求不能静默改写。新增勘误说明“旧口径→新口径→来源日期→被替代范围”，01只追加，历史测试数字和历史报告事实保留。

### 2.3 必建追溯表

| 表 | 必填字段 | 验收要求 |
| --- | --- | --- |
| 要求台账`requirements.csv` | REQ-ID、主题、要求摘要、用户消息/文档路径及位置、发生时间、来源可信度、替代关系、适用环境、验收标准、授权边界 | 每条要求可溯源；事实描述与期望行为分开；缺口明确 |
| 冲突表`conflicts.csv` | CONFLICT-ID、旧/新REQ-ID、双方来源时间、冲突范围、裁决依据、现行口径、未决问题、受影响文件 | 有新要求证据才核销；无证据不伪造决定 |
| 系统完成度表`system-state.csv` | 模块、REQ-ID、代码/测试入口、本地实现、构建发布、生产部署、开关启用、业务验收、证据时间、限制 | 至少六个状态独立填写；历史证据不当现时结论 |
| 偏差/缺陷表`findings.csv` | AUD-ID、REQ-ID、复现、期望/实际、证据、影响、根因、级别、类别、改进包、负责方、060用例 | 每个结论有证据；建议与已证实缺陷分开 |

建议状态：`符合/偏离/部分符合/待核实/外部阻塞/产品暂缓/不适用`。统计必须给分母、排除理由与未验证项，不用“总体已完成”掩盖生产或业务缺口。

## 3. 编制时已知的重点核对线索

以下是带日期的历史线索，不能直接作为执行时生产结论，也不自动作为本轮整改任务。

| 线索 | 历史来源与冲突 | 执行时核对动作 |
| --- | --- | --- |
| 真正完成时点提醒与过渡RPA锚点 | 031§9目标为完成时提示、不走CDSS；§11/§12接受约出院后5天RPA过渡；旧正文又残留179完成锚点建议，后续已纠正 | 区分最终目标、允许的过渡方案、实际触发配置与提示发生时间；过渡接受不等于最终目标已经验收 |
| 护理数据和缺项判定 | 031§12 Q1经无纸化数据面，不直连护理库；后续T8-1/R3修订禁止用RPTCOUNT判护理缺项 | RPTCOUNT仅总量对账；数据面不足必须显示不可判断，不能报护理缺项或伪称全源覆盖 |
| JHEMR目标库 | 054/055旧179 Oracle路径冻结，056更正177:5432/jhemr；058记录账号仅能见部分视图和现时对账阻塞 | 检查目标身份、权限与SQL方言；旧179写入批准不能迁移177；不执行旧驱动器 |
| 09-23生产升级与预检启用 | 01先记录代码升级至564e276阶段、18表到位且开关未动，后记录compose适配ac699b5、med-prearchive启用与BFF四env/复验200；V_QYBR只读修复验证、六类871组补推=665成功/2失败/204跳过；rule_registry=file、result_delivery=false、业务sources全disabled | 区分镜像/代码升级、进程/BFF可达、业务源就绪与结果外发四层；不能把“启用sidecar”写成全源规则业务启用，也不能套用更早“BFF关闭”摘要。09-27另有BFF200记录；执行时只读复核现值，不能断言10-03现时开关 |
| 密钥事故和补跑 | 01的09-27记录75/75解密恢复；09-29记录7窗补推；后补的09-30行记录daily q=09-23、discharge q=09-22两窗也已完成，另保留q=09-24 jyjc残留及10-01同类超时复发线索 | 按事项发生时间和后续更正核销两窗旧待办，不能按01物理行序当事件先后；不重复列“待修密钥”。核现时错误码和类型/窗口缺口，不能自动补跑或提高超时 |
| 09-30判断组装疑点 | 01后补09-30行记录103条样本、62条深读及status语义翻转/解释占位/conclusion字面量/聚合不稳定线索 | 属历史复核发现，尚非本轮已复现结论或临床金标准；在A4定位组装层并交060 B08/B09、Q12/Q16独立反例，不把“真阳性率良好”当准确性验收 |
| D-J1终态竞态 | 049待修由051关闭；051更正L1稳定态4条为6条，要求first==stable==expected | 核对代码、故障注入与首次读取完整性；不重复实现；回归则另建AUD-ID |
| W10与签字 | 031§12/T8-4、00/105与033说明系统推送类豁免签字、等待用户清单；049旧表仍写待签 | 以最新用户裁定核销旧签字阻塞，规则清单缺失仍开放，不造规则 |
| 两条规则产品线 | 预检规则中心已实现不等于主服务004C/023 WP8落地；WP8产品暂缓 | 分开盘点，不把框架、预检侧边车或92项快照当全量主服务规则引擎 |
| 门禁覆盖不足 | 058记录52 passed+47环境类skip，legacy规则中心no-demo跳过；锚仍指09-21历史基线 | 正式绿表、专项实跑、现场验收三者分开；缺环境的必测项交给060补齐 |
| 文档与部署漂移 | 058留ARCHITECTURE/DEPLOY等补正欠账，10-02导航治理已交付 | 重新查当前差异，不重复归档；核对BFF开启/关闭等不同日期状态 |
| 归属未明现场 | 056§6.6登记问题；规则`.bak`既有删除归属未知 | 留原状，查归属证据；需要依赖或修改该内容才请求裁定，继续无关任务 |

## 4. 全系统核查矩阵

每行至少检查：用户要求、入口、数据/配置、权限、异常、可观测性、已有测试、实际部署证据、缺口及060验收用例。

| 领域 | 检查内容与必须追问的问题 | 实现证据入口 |
| --- | --- | --- |
| 总体架构 | 主服务/独立预检/前端/业务源/应用库/Dify/Relay边界；进程拓扑与单worker；依赖方向、事务边界、配置漂移和失效传播 | `app/main.py`、`app/database.py`、`ARCHITECTURE.md`、compose、预检README |
| 用户与RBAC | 四角色实际权限集合、科室数据范围、对象越权、菜单与接口权限一致、Cookie/Bearer/CSRF、H5 token边界 | auth/permissions、users/roles/menu、security_middleware、相关tests |
| 数据接入 | 应用库与业务源分离；Oracle/Vastbase/PostgreSQL及预检多源；真实来源/列型/身份键/时间/水位；disabled与BLOCKED | loader、DB客户端、102、058源台账、模板、预检gateways |
| 就诊和数据完整性 | patient_id+visit_number、防跨次/跨科室、空键与稳定ID、重复行、日期边界、源缺失、截断是否破坏证据 | patient/canonical record、join/fanout、EMR批量查询、预检context |
| 质控类型和配置 | 六类与其他扩展类型逐条核对，SQL/JSONPath/字段映射/Dify池、required和display paths；模板与生产差异；部分保存 | AuditTypeRegistry、config、payload_composer、audit_types API/UI |
| 手动/批量/重推 | 串行与并行语义一致，skip标记、事务隔离、幂等键、当前结果、取消、熔断/重试/降级、漏斗分母 | push_executor、bulk_push_executor、push_log_writer、push/historical_rerun |
| 双模式调度 | enabled决策、legacy忽略条件、独立DB锁、手动路径实际锁名、cron、误触发、历史窗口和六类终末覆盖 | scheduler、scheduler_run_modes、history与相关tests |
| AI质控判断 | 提示词与工作流实际版本；数据到模型、JSON、解析校验、维度/结论与告警全链；不合格high兜底与真实high保留 | 109–115、prompts、dify_pusher、parser/validator/mapper、models |
| 日志、患者质控和报表 | NULL兼容、筛选分页、current/superseded、颜色/严重度一致、跨页面统计口径、导出审计与隐私 | logs、patient_qc、stats/report、ExportAuditLog、前端契约 |
| 告警和闭环 | Relay/HMAC、enqueue/dispatch、科室编码/名称、接收人去向、反馈抑制、结论fallback、防重发、H5反馈 | 103、relay_alert_service、mobile_qc、QCFeedback与QCAlertFeedback |
| 预检与规则中心 | 零双向import、四锚点、五态引擎、两轨规则/FID、规则发布回退、coverage ledger、AI匹配人工审阅、trial副作用 | prearchive_service、prearchive_admin BFF、规则中心双前端 |
| JHEMR和外部对接 | L1本地协议、L2真实联调、L3现场体验分别验收；签名/版本/幂等/整改复检；FILEVERIFY冻结范围 | integration包、jhemr接口、047/051/056最新材料 |
| 两套前端 | legacy默认入口、UI Next迁移完整度；页面和17页历史矩阵对账；加载/空/错/权限态、长文本、移动端、刷新深链 | `static/`源码、`frontend/src/`、路由清单、`docs/reference/wp0_frontend_baseline_fixtures/README.md`、既有E2E |
| 性能可靠性 | ORA-12609、Vastbase超时、查询计划、连接回收、N+1、无界分页、任务竞态、Outbox重试与恢复 | 当前分支只读差异、048/049/051、metrics、性能日志 |
| 部署与运维 | 源码/镜像/静态产物一致、密钥稳定、配置备份、驱动打包、存储挂载、迁移自检、恢复、监控和依赖锁 | Dockerfile/compose/entrypoint、DEPLOY、requirements/lock、run_gates |
| 文档与协作 | INDEX编号/状态/路径、入站引用、旧要求勘误、统一记录与任务板、归档完整性、测试/部署状态不夸大 | check_documentation、119、01/02、INDEX、相关检查点 |

## 5. 执行包A0–A9

### A0 — 接管、环境边界与可复现基线

**输入**：§2启动资料、当前工作树及最新授权。**步骤**：

1. 保存HEAD、分支、tracked/untracked/deleted全量dirty清单、逐文件修改前哈希和副本、INDEX/01/02快照；untracked不能被git diff遗漏，deleted保留状态与原始来源。持久化到受控证据目录，不reset/clean/stash，不恢复未知删除。
2. 在`review/system-audit-<执行日期>-<run_id>/`记录环境清单、只读生产核查允许范围、使用模式和负责文件；运行命令均先核副作用。
3. 清点Python/Node/数据库驱动/浏览器/测试账号；不打印.env、生产配置原文或密码；核验测试环境隔离守卫。
4. 使用med-audit-gates执行quick并保存Markdown表；已有失败独立登记，不默认归因本任务。需要完整基线时按隔离栈条件跑full，不能在未审查环境启动app.main。
5. 禁止只读数据库调查导入app.main或调用init_db；可用经审查的独立只读连接/工具，明确查询预算和回滚关闭。
6. 已核截至2026-10-03本地HEAD仍ac699b5（09-23），dirty混有09-24/09-28/10-02等批次，不把全部归为10-02。建议独立准备按归属分批提交清单，未知`.bak`删除等保留；只有当前任务明确批准commit后才提交，不继承旧授权。**提交不是A0或只读核查的强制前置**：无批准时用HEAD+全文件manifest+前镜像冻结；每会话比对漂移，只阻塞依赖归属不明文件的修改。

**产出**：`baseline.json`、`before-manifest.json`、`exec-log.md`、模式与授权清单。**完成条件**：现场归属及保护措施明确，能够区分新旧改动；失败项有恢复点。

### A1 — 全文档盘点与历史用户要求重建

1. 从INDEX登记全部现役计划/交付/参考，按主题建立配对图；全仓Markdown先做路径、标题、状态和日期盘点，启动/契约/业务任务正文按关联逐份阅读。
2. 排除vendor/cache、无关工具内部资料、未授权敏感附件；记录排除路径、数量和理由。历史archive仅为解释冲突回溯，不作为当前实施依据。
3. 对可用本地对话按时间提取用户角色消息、回答和条件；区分用户原话、AI建议、实际批准，保留文件位置/消息时间；不把AI“已完成”当验收。
4. 按领域给每条需求分配REQ-ID，补齐目标、约束、验收和来源；合并重复要求但保留全部来源和版本链。
5. 标注无法访问的聊天时段、遗失批准证据与来源可信度；不得为了“全量分析”盲目导出客户端隐私数据库。
6. 台账按领域分期追加：先推送/调度/高危判断/权限P0域，再数据接入/预检闭环/前端，最后运维与文档。每批登记“相关文档总数、全文已读、仅元数据盘点、被替代/排除、未读/无法取得”及需求分母、稳定REQ-ID/版本；P0要求与批准证据逐条核证，不能用抽样替代。非P0抽样必须说明选择方法、抽样比例和遗漏风险。
7. 某领域A1/A2已闭合后，可在依赖明确的范围推进该领域A3–A5；不必等所有领域读完才做任何核验。已冻结范围之外持续留NOT_REVIEWED；只有全部纳入范围资料完成处置才关闭全局A1/A2，禁止以P0分期交付宣称全系统覆盖。

**产出**：`document-inventory.csv`、`requirements.csv`、需求版本链与覆盖分母。**完成条件**：所有相关已登记文档有“已读/追溯/被替代/不相关/无法取得”状态，无凭空需求。

### A2 — 逐项冲突裁决与完成度核销

1. 先逐条核对§3线索，再扫描新冲突；每项对照“旧要求—用户后续要求—实现—交付—勘误”。
2. 将同一问题的多份计划归为一个AUD-ID，避免重复修复和重复完成计数；旧缺陷已关闭但回归时建立新ID并关联旧ID。
3. 对状态矛盾分辨：业务要求变化、文档漂移、实现偏离、部署欠账、测试不足、资源阻塞、授权不足、归属不明。
4. 最新要求能确定的自行落实文档解释；要求改变临床裁定/验收/生产范围且证据不足的请求用户明确裁定，并继续其他领域。

**产出**：`conflicts.csv`、状态核销表。**完成条件**：每个冲突有结论或有具体缺失信息，不能以“最新文档优先”一笔带过。

### A3 — 当前系统架构与关键链路核验

1. 按§4从真实入口跟踪配置、鉴权、数据抽取、身份分组、payload、Dify、解析校验、落库、日志、告警、反馈与复检。
2. 给出组件/信任边界、依赖、部署拓扑和事务关系；可在本文件用Mermaid或文字表，图必须与实现核对。
3. 对主链路和预检两条轨道分别建立“输入→关键处理→输出→失败处理→状态持久化→可恢复性”契约表。
4. 用隔离合成数据做必要定向验证；Mock结果只能证明工程链路，不证明真实Oracle方言、生产部署或临床判断。
5. 生产只读可用时核配置脱敏摘要、镜像/进程/开关、聚合漏斗与错误码；不可用就标部署未知，不能用本地结果替代。
6. 特别检查手动调度与真实job锁策略、不同run mode幂等、current结果版本和结论fallback，不按文档口号推断代码行为。

**产出**：`system-state.csv`、架构边界图、关键链路证据。**完成条件**：§4每领域有结论和可定位证据，未核实项单列。

### A4 — 系统分析、偏差复现与根因确认

1. 对每条偏差记录最小复现数据、调用步骤、期望/实际、源码位置、影响到的页面/接口/配置/统计/告警。
2. 做反例检查，避免把合法skip、授权不足、资料不全、合理临床变化或未启用的可选能力误判缺陷。
3. 检查遗漏需求与超范围实现；解释对医生/护士/质控员实际流程的影响，不只看HTTP是否200。
4. 可靠性问题以错误码、查询计划、资源回收、时间预算和故障注入证明根因；不得仅扩大超时、重试或吞异常。
5. 架构改进列备选方案和取舍：沿用现架构最小修复优先；大规模重构、WP8立项、护理新直连、外部客户端改造另列建议，不默认实现。
6. 判断准确性问题先分“源数据/身份/时间错误、模型事实提取、转换/校验、映射/显示、临床标准缺失”，临床未裁定不由AI代定。

**产出**：`findings.csv`与根因证据。**完成条件**：证实的缺陷、待核实风险、改进建议、外部待办四类清晰。

### A5 — 改进分级、任务拆包与060验收绑定

分级：P0=患者/数据串次、越权、泄密、非法high、关键链路不可用；P1=需求偏离、结果丢失/重复、核心页面失败、持续性能问题；P2=效率、体验和可维护性建议。项目既有评级不同则记录映射，不能静默改变旧标准。

每个改进包`FIX-*`填写：关联REQ/AUD、目标行为、允许环境、白名单文件、影响分析、具体步骤、测试输入、独立期望、失败/回退条件、依赖、负责方、估算与060 TC-ID。未知原因不得直接进入开发。

建立四个队列：明确本地可修、需业务裁定、需生产/外部批准、资源阻塞/产品暂缓。核查模式到此不执行业务代码修改；整改模式继续A6。不得为了提高“完成率”删除开放项或降低验收标准。

**完成条件**：所有P0/P1有动作或有明确阻塞；每个FIX有验收；已完成不重复列施工。

### A6 — 获授权本地整改，小批闭环

1. 按依赖处理P0再P1；每包修改前检查任务板和归属，更新本次实际文件范围。可逆细节按现约定推进，不反复确认。
2. 对高风险行为先用已有测试或最小故障复现固定期望，再修实现；新增测试必须能揭示真实风险，不写只镜像实现的测试。
3. 行为变更同时核API/schema、数据库手动迁移及_verify_required_schema、Oracle/SQLite、legacy/UI Next、模型映射与统计。
4. 不直接手改static/ui-next构建产物，改frontend源码后按构建流程同步；不改真实配置密文、生产开关、Dify工作流或患者历史结果。
5. 批后做定向回归与quick，保存diff、检查点和01批次登记；失败先定位，在授权范围内修复并复验，不跳门。
6. 凡需修改目标、放宽临床阈值/高危规则、新增源/产品能力或扩大环境，先产出具体方案再走已有批准要求，暂停依赖步骤并继续无关包。

**产出**：本地FIX结果表、逐包验证、回退依据。**完成条件**：所有获授权包通过对应验收；未实施包如实列明。

### A7 — 改进后的工程回归与发布准备

1. 依据实际变更选择关联单元/集成/前端测试，复查所有P0/P1修复、相邻业务链和文档一致性。
2. 涉demo/sidecar按med-audit-demo-stack管理；正式回归按med-audit-gates执行full+锚，不用定向测试替代正式汇总。
3. full前仅启动隔离demo主服务供聚合脚本管理sidecar；不得预占sidecar导致降级轮无法运行。必测skip不算成功。
4. 验证构建产物、配置变更清单、迁移dry-run、回退点和部署说明；不部署、不commit/tag/push/PR，除非当前会话另有精确授权。
5. 工程全绿只是进入060的证据；不能宣称临床判断准确、真实四角色验收或连续观察已经完成。

**完成条件**：Markdown门禁表可复核、必测项结果明确；修复和待上线范围清楚。

### A8 — 文档勘误与060输入冻结

1. 把现时结论补入相应现役契约/计划，保留带日期历史事实；小范围修正文档漂移，不再次启动全面归档。
2. 更新本文件§11执行记录：需求/冲突/缺陷分母、已修/未修、部署与验收状态、每包证据、未决裁定。
3. 为060生成`handoff-060.json`，严格遵守下方v1契约：HEAD+含untracked/deleted的文件manifest、REQ/冲突版本、配置模板/SQL/规则/prompt hash、FIX列表、环境限制、回退、必测TC-ID与已知缺陷。
4. 向060传入全部P0/P1、已修缺陷、受影响页面/API和准确性疑点；测试期望引用业务要求，不复制实现返回值。
5. 核查模式未改代码也生成交接，明确“无整改版本、060只能做现状基线；改进后正式验收待整改交付”。

**完成条件**：060能够独立启动和核对版本，无口头遗留；INDEX/01/02同步。

#### A8交接JSON v1契约（两计划共用）

文件落本次审计证据目录，060启动时校验。以下顶层键全部必需；未来新增可选字段须说明兼容性，未知schema_version不接受。

| 字段 | 类型/固定含义 | 校验要求 |
| --- | --- | --- |
| schema_version | integer，固定1 | 不接受字符串或未知版本 |
| run_id / generated_at | 非空string / 带时区ISO时间 | 对应实际任务；禁止假时间 |
| execution_mode / delivery_kind | audit或local_remediation / audit_baseline、verified_no_fix或remediated | 没改进交付只能audit_baseline或verified_no_fix；不能冒充remediated；verified_no_fix须满足零必要FIX核证条件（见下方补充规则，R5） |
| baseline | object | head为40位小写hex；branch为string；manifest_path与manifest_sha256、runtime_manifest_sha256、session_diff_path齐；路径和哈希按下述规则核验 |
| requirements / conflicts | object | version、path、sha256齐；记录冻结范围，不凭一个版本号省略原件 |
| file_manifest | array of object | 每项path（仓库相对路径）、status（present/deleted）、sha256（存在为64位小写hex，删除为null）、kind（code/test/document/config_template/sql/rule/prompt/build）齐；路径唯一，原字节哈希；可选布尔append_only（默认false，仅登记类文档允许true，三类校验规则见下，R5） |
| artifacts | array of object | 每项kind、path、sha256、availability（available/not_available/not_applicable）、reason齐；不可得项hash为null且reason非空，不能省略未配置workflow |
| fixes | array of object | 每项fix_id、requirement_ids、finding_ids、status（fixed/open/blocked/not_authorized）、changed_paths、must_test_ids、evidence_paths、rollback齐 |
| known_findings | array of object | 每项finding_id、severity、status、reason、next_step齐；闭环之外残留也必须列 |
| must_test_ids | 去重string array | 引用060真实ID或T1追加登记的子ID；fix.must_test_ids为其子集；无业务变更时仍列核查后必须验证项 |
| environments | array of object | 每项level（E0–E4）、status（ready/blocked/not_authorized）、evidence_paths、limitations、next_step齐 |
| authorizations | array of object | 每项action、scope、status（approved/not_approved）、reference齐；approved有当前动作出处；不能含密钥/token/患者标识 |
| rollback | object | before_manifest_path、instructions_path、limitations齐；只有本批对象，不跨会话整体回退 |
| limitations | string array | 文档/对话覆盖差额、源权限、未部署/临床未验等如实保留 |

manifest_path指完整file_manifest原件；manifest_sha256为原件原字节SHA-256。runtime_manifest_sha256对kind≠document的子集按path排序、UTF-8 JSON规范序列化（ensure_ascii=false、sort_keys=true、separators=(',', ':')）后计算。这样纯登记文档追加与真正被测代码变化可以分辨；若规则/prompt修改则必须重锁相应测试。所有路径从仓库根解析、禁止越界；生产运行实例配置只留脱敏摘要/版本证据，不放明文、密文秘密或PHI。

**三类文件校验规则（R5，2026-10-04，生产者与消费者使用同一规则）**：

1. **不可变交付快照**——requirements/conflicts 原件、handoff 原件与 manifest 原件本身：校验**原件原字节 SHA-256**，任一失配即交接校验失败。
2. **被测运行文件**——file_manifest 中 kind∈{code,test,config_template,sql,rule,prompt,build} 的条目：校验 **runtime_manifest_sha256**（runtime 子集）；失配=被测版本漂移，阻塞依赖该版本的测试并要求重新锁定/重跑，不得在漂移版本上沿用旧结论。
3. **可追加执行记录**——登记类文档（`开发起步包/01_统一修改记录.md`、`02_协作任务板.md`、本文件§11与060§13执行记录、INDEX 状态行）：manifest 条目标 `append_only: true`；消费者发现其 hash 变化时**登记漂移摘要，不判交接失败**（合法的收尾登记必然追加行），但此类文件的**新增/删除仍判失败**、且漂移内容不得包含对既有快照/运行文件结论的改写。非登记类 document（如 reference 契约）不得标 append_only，失配须解释。

**最终冻结时点**：handoff 的生成与冻结发生在**A9 收尾登记（01/02/INDEX）完成之后**——即先把执行事实登记进 append_only 文档，再冻结快照；此后 01/02 的后续追加属第 3 类漂移，不再使交接失效。代码/规则/prompt/config_template 在冻结后的任何变更都必须走新版本交接（更新 runtime 哈希并重锁受影响测试），不适用漂移容忍。

每个fix.rollback是object，必含before_paths（array）/instructions_path（string或null）/reason（string）；无本地修改时before_paths为空、instructions_path=null并注明无回退对象。数组空值必须有相应limitations或reason解释，不以空数组隐藏问题。

以下是**结构模板**，占位值须执行时替换，不能作为真实交付：

```json
{
  "schema_version": 1,
  "run_id": "REPLACE_RUN_ID",
  "generated_at": "REPLACE_ISO_TIME_WITH_OFFSET",
  "execution_mode": "audit",
  "delivery_kind": "audit_baseline",
  "baseline": {
    "head": "REPLACE_HEAD_40HEX",
    "branch": "REPLACE_BRANCH",
    "manifest_path": "review/REPLACE_RUN/file-manifest.json",
    "manifest_sha256": "REPLACE_64HEX",
    "runtime_manifest_sha256": "REPLACE_64HEX",
    "session_diff_path": "review/REPLACE_RUN/session-only.diff"
  },
  "requirements": {"version": "REPLACE_REQ_VERSION", "path": "review/REPLACE_RUN/requirements.csv", "sha256": "REPLACE_64HEX"},
  "conflicts": {"version": "REPLACE_CONFLICT_VERSION", "path": "review/REPLACE_RUN/conflicts.csv", "sha256": "REPLACE_64HEX"},
  "file_manifest": [],
  "artifacts": [],
  "fixes": [],
  "known_findings": [],
  "must_test_ids": ["B08", "B09", "Q12", "Q16"],
  "environments": [],
  "authorizations": [],
  "rollback": {"before_manifest_path": "review/REPLACE_RUN/before-manifest.json", "instructions_path": "review/REPLACE_RUN/rollback.md", "limitations": []},
  "limitations": ["结构占位模板，非真实交付；执行时填充全部适用数组及原字节哈希"]
}
```

生产者生成后必须校验类型、枚举、路径、原件/hash及TC引用；060消费者重复核验，并核manifest原件与内嵌file_manifest完全一致。remediated至少有一项fixed且对应证据/变化存在；audit_baseline只允许现状验证。**verified_no_fix**（R5，2026-10-04）：零必要FIX的已核证交付——核证条件=①requirements/conflicts/findings 台账完整且每条结论有证据；②known_findings 中不存在 status=open 且 severity=P0/P1 的必要修复项（产品暂缓/外部阻塞/资源阻塞须逐条给出理由与责任方，不得静默删项）；③must_test_ids 非空（核查后必须验证项照列）；④limitations 写明"零FIX=核查结论，不自动等于测试通过"。满足时 delivery_kind=verified_no_fix，060 按现状基线+必测清单执行并如实报告，不得因"无修复可验"降低覆盖或跳过必测。校验结果留证；失败只阻塞依赖交接的测试，独立环境准备可继续。

### A9 — 收尾交付与独立复核

1. 第二遍从要求和反例检查自己的结论；除非用户另有明确要求，不自动启动多代理评审或外发资料。
2. 运行文档检查；本地仅文档变更执行quick，业务整改执行full+锚及必需专项；交付以实测记录为准。
3. 保存本任务新增/修改文件清单和diff，核对既有现场未被覆盖；有文件/状态修改必须追加01，任务板标DONE或HANDOFF并给恢复第一步。
4. 报告“审计完成度、本地整改完成度、生产部署完成度、业务/临床验收完成度”四项，附分母与限制。不得把外部阻塞标成完成。

## 6. 必须保留的实现不变量

- Builder/存储使用`mr_text`；Dify边界映射`mr_txt`且为字符串；base_url归一化、JSONPath以`$`开头。
- Registry路径保留SQL校验、加密、脱敏；配置写端点exclude_unset合并，空密钥不覆盖；Relay局部保存不清空开关/地址/规则。
- 批量患者事务隔离；`pushed_flag/reviewed_flag/manual_override/skip_reason`保留，未复核与整改抑制语义不回退。
- 双调度按enabled判启动，job独立锁；EMR专用出院路径与四类专用转换不能被“统一”成失效SQL；diagnostics/effectiveness保留。
- V_QYBR真实列为所在/出院/入院科室，键为患者ID+次数；Oracle空串=NULL不能用`dept != ''`过滤候选。
- Vastbase列名lower、template筛文书、可选sslmode；就诊身份、文书来源与时间不能在截断或转换中丢失。
- high必须同一issue合格证据、来源和安全类别；warn不能升high，解析失败不能触发结论high。临床标准按109–115和最新裁定核对。
- 预检与主服务零双向运行时import；paperless仅元数据源不进入documents；RPA水位门禁用，RPTCOUNT仅对账；BLOCKED不伪造实测。
- 导出调用record_export_audit，历史NULL兼容；患者标识、原文、密钥不进共享正文/提交/公网。

## 7. 改进质量和完成判据

| 判据 | 必需证据 | 不满足时 |
| --- | --- | --- |
| 要求可追溯 | 所有纳入范围REQ有来源、版本、验收；缺口及排除分母已列 | 不能宣称全面对齐 |
| 冲突裁决可靠 | 同事项新要求出处、时间和范围；未决项保留 | 只阻塞依赖该冲突的工作 |
| 系统状态可信 | 实现/构建/部署/启用/验收分开，有环境和时点 | 未联机项标待核实 |
| 改进可实施 | AUD根因、FIX白名单、验收/回退/依赖齐全 | 不开始扩大修改 |
| 本地整改达标 | 每个获授权FIX复验通过，工程门禁与专项符合计划 | 修复并复验或明确阻塞 |
| 判断准确性边界明确 | 工程校验与临床标准分开，060样本/金标准/指标待办清楚 | 不发布“判断准确”结论 |
| 可交接 | handoff-060、执行记录、INDEX/01/02、证据定位 | 未登记不算交付完成 |

建议工作量：A0及P0领域首批A1/A2约1–2个有效工作日；其余领域A1/A2滚动约3–6日，A3–A5约2–4日并可随领域闭环推进。A6按FIX估算，A7–A9约1–2日。以上是有效工作量，不是连续日历保证；额度/会话长度有限时按批次checkpoint续跑。执行者A0按真实资料量修订估算，不以抽样或时间到期替代验收。

## 8. 证据保存和断点续跑

过程证据落`review/system-audit-<执行日期>-<run_id>/`，长期脱敏结论更新本文件；截图/含患者附件按00放`docs/attachments/`并禁止提交/外发。不得新建根目录散文件或重复会话报告。

每个任务包记录：状态、开始/完成时间、来源范围、执行命令/退出码、结论、修改文件、证据路径、阻塞、恢复第一步。CSV含长文本/换行应正确引用；JSON用结构化字段避免表格竖线歧义。

恢复时先读01/02和本文件最新检查点，重核HEAD/dirty哈希/需求版本；漂移先核归属，再决定哪些测试失效。已经验收的包不重复实现。旧门禁只作为历史证据，不冒充新版本实测。

## 9. 生产/外部待批准项模板

仅当具体动作必要且已有可审查结果后提交批准单：环境与目标身份、REQ/AUD/FIX、动作、表/配置键/工作流版本、日期/类型/科室/患者范围、数量上限、before hash、dry-run、alert_policy、接收人、外发开关、执行窗口、备份、回滚命令、停止条件、验证、审批人。

未批准项只做安全准备和记录；不自动恢复历史补推、177 INSERT、规则激活、生产DBA迁移、真实模型调用、 canary/default入口切换或历史高危降级。历史整改另按专项skill。

## 10. 启动和验证命令

以下在仓库根目录执行，命令结果保存到本次证据目录。数据库探查工具先查看help/dry-run及目标身份；不要从本计划复制旧生产参数。

```powershell
git status --short
git diff --stat
git rev-parse HEAD
python scripts/check_documentation_20261002.py
python scripts/run_gates_20260906.py --quick
# 完成本地整改后的正式全量；demo编排先按对应skill准备
python scripts/run_gates_20260906.py --full --anchor-file docs/reference/gate_anchors.json
```

## 11. 执行记录（启动后填写）

| 包 | 状态 | 关键结论/分母 | 修改范围 | 验证与证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| A0–A9 | **DONE（本地核查与整改模式，2026-10-04，ZCode/GLM-5.3，run_id=system-audit-20261004-r1）** | 见下方 A0–A9 执行行 | 见各行 | review/system-audit-20261004-r1/（baseline/manifest/台账/复现/执行日志）+ gate-runs/20261004-{130754,132712} | 残留=外部阻塞与用户裁定项（known_findings） |
| A0 现场冻结 | DONE | HEAD=5324fca、dirty=18（15M+1D+3??，全属 10-04 round-8 两轮已登记产物+.bak 归属未明）；924 tracked+3494 untracked 全量哈希；18 文件前镜像；quick 4/4 | review/system-audit-20261004-r1/{before-manifest.json(sha=3254635a…),baseline.json,before-files/} | gate-runs/20261004-130754 | 无 |
| A1 要求台账 | DONE | requirements.csv 56 REQ（四域 Explore 只读提取+抽样复核）；document-inventory 205 md（ACTIVE58/ref14/archive83/启动5/其他45）；分母=INDEX 登记全处置、archive 仅回溯、conversations 索引在场未逐份读（缺口登记）、09-30 FINDINGS.md 原件无法取得（以 01 行+独立复现代替） | 同上目录 | 同上 | 无 |
| A2 冲突裁决 | DONE | conflicts.csv 24 CON（179→177/finished→RPA/RPTCOUNT/签字/D-J1/密钥核销/09-23 分层/101 BFF 漂移等全有裁决或待裁项） | 同上 | 同上 | CON-08 生产 anchor 漂移待业务变更轨道 |
| A3 完成度表 | DONE | system-state.csv 17 模块五态分列；未联机项标"现值未复核"（生产只读不在本轮授权） | 同上 | 同上 | 生产现值复核待授权 |
| A4 偏差复现 | DONE | **组装层四疑点独立复现坐实 3.5 项**：AUD-A1(P1) normalize_status 子串顺序致"不一致/未通过"→pass（fail 分支死代码）；AUD-A2(P1) 缺省结论"护理记录"字面量对非护理类型生效+reasoning_brief 同源；AUD-A3(P2) fail 维度缺说明无标记；AUD-A4(P2 需业务裁定) 聚合随 issue_summary 文本有无翻转；AUD-E1=024 保守降级设计边界非缺陷。9 项重点核对全部完成（RPA 差距=CON-02/08、RPTCOUNT 符合、179 冻结在位、W10 占位就绪、D-J1 trigger.py:286-318 无回归、09-23 四层分列、密钥/补跑 CON-16 核销、117 真实路径通过） | repro_assembly_20261004.py（修复前 10 命中） | 同上 | AUD-A4 待业务裁定 |
| A5 分级拆包 | DONE | FIX-A1/A2/A3/C1 入本地修复队列；AUD-B1/B2/D5(生产/批准)、C2/C3(资源)、D4(清单)、E2(.bak 裁定) 外部队列；AUD-A4 建议项不自动实施 | findings.csv（14 条：3 证实可修+1 设计口径+6 外部阻塞+4 核销/边界记录） | 同上 | 无 |
| A6 本地整改 | DONE | FIX-A1（否定语义前置+未通过/不符合入 fail）、FIX-A2（_NURSING_SIDE_AUDIT_TYPES 三类型保留原句、其余"各核查维度整体基本一致。"）、FIX-A3（problem_dimension_missing_explanation 标记，置于高危守卫降级前按原始 status 判定）、FIX-C1（DEPLOY 双容器小节/ARCH 目录树/101 增量勘误节） | app/services/dify_result_normalizer.py、app/services/dify_schema_parser.py、tests/test_dify_assembly_remediation_20261004.py(新)、DEPLOY.md、ARCHITECTURE.md、docs/reference/101_FEATURE_BASELINE.md | 新测试 10/10；相邻链路 133 passed；复现脚本复跑 10→4 命中（剩余=设计边界+AUD-A4）；check_documentation PASS；quick 4/4（gate-runs/20261004-132656 前置） | 无 |
| A7 正式回归 | DONE | full+锚=10/11 PASS+锚全部不低于（main 1441=锚1379+10 新测试/0 fail、prearchive 454+1skip+1 FAIL、typecheck/unit 72/build/e2e 52+47skip PASS）；唯一 FAIL=test_pa_rules_fid11 备份完整性用例（.bak 删除归属未明，与 round-8 两轮 full 相同，非本批引入——本批零 prearchive 改动）；legacy 规则中心 E2E=no-demo 可选项 SKIPPED（本批零规则中心相关变更；094958 已实证该域） | 无（仅验证） | gate-runs/20261004-132712 + full-gate-stdout.log | .bak 裁定待用户 |
| A8 交接冻结 | DONE | handoff-060.json（schema v1，delivery_kind=remediated，7 FIX/8 known_findings/7 must_test/5 environments/6 authorizations；三类文件校验+runtime_manifest_sha256 生成并自校验 PASS）；file-manifest.json=会话起点18+本批3+运行时锚点15 | review/system-audit-20261004-r1/{handoff-060.json,file-manifest.json,session-only.diff,rollback.md} | make_handoff_20261004.py 校验输出 PASS | 060 按 handoff 启动 |
| A9 收尾 | DONE | 四级完成度=审计完成（P0 域全覆盖+全域台账/分母）、本地整改完成（4 FIX 验收通过、残留全部外部/裁定类）、生产部署=0（未提交未部署，分层状态见 system-state）、业务/临床验收=0（金标准未配置）；INDEX/01/02 同步 | 本文件§11、docs/INDEX.md、开发起步包/01/02、060 §13 | 本行+01 登记行 | 用户裁定项+060 执行 |
| R0–R7（round-8 修复计划执行，2026-10-04，ZCode/GLM-5.3） | DONE（计划修订+门禁补强，**非 A0–A9 业务执行**） | 8 包全落地：R5 本计划 A8 三类文件校验/append_only/verified_no_fix/冻结时点；R0 勘误（round-8 方案.md 八项标注+060 §3.1 汇总）；R1/R2/R4 落 060 v1.2；R3 journeys 四断言升级+定向回归 8 passed；R6 111 头修正；R7 E2/E3 资源单模板（资源本身待用户，T3/T8 相应包 BLOCKED）；R1.3b BFF fail-closed 代码门禁+4 单测 | §5 A8 契约、§14、docs/INDEX、review/round-8/方案.md 头、docs/reference/111 L5、app/services/isolated_mode.py、scripts/demo_env.py、tests/test_isolated_prearchive_bff.py、frontend/tests/e2e/uat054-journeys.spec.ts、060 v1.2 | review/059060-fix-20261004/（执行卡+执行报告+resource-e2/e3+artifacts）；文档批 check_documentation PASS+quick 4/4；单测 19 passed；full+锚终态见执行报告 §6 追记 | A0–A9 仍 NOT_STARTED；执行新增发现 F-1（导出不收 patient_id）/F-2（推送按钮双击 MessageBox 重入）建议 A5 立项 |
| 复核+F-1/F-2/F-7 修复（2026-10-04 第二轮，ZCode/GLM-5.3，授权=用户当轮「复核并对新发现问题修复完善」） | DONE | 第一轮复核全部成立（代码/文档/测试三层复验）；**新发现 F-7**：severity 参数被 /api/logs 与导出端点静默忽略（UI 严重度筛选无效，F-1 同族）；F-1/F-7/F-2 已修复=logs.py 两端点补 patient_id(contains)/severity 过滤+审计记录、ManualPushPage 守卫前置到确认框前；新增回归 tests/test_logs_export_scope_20261004.py(4)+frontend manual-push-guard.test.ts(3)；journeys①补筛选态导出对账、②恢复按钮级双击断言 | app/routers/logs.py、tests/test_stats_metadata.py（连带维护直调参数）、frontend/src/features/tasks/ManualPushPage.vue、frontend/tests/unit/manual-push-guard.test.ts、frontend/tests/e2e/uat054-journeys.spec.ts | 主 pytest 1431 passed(+4)、前端单测 72 passed(+3)、typecheck exit 0、定向 E2E 8 passed（artifacts/uat054-round2c）、full+锚=11/12 PASS+锚全不低于（gate-runs/20261004-094958；唯一 FAIL 仍为待裁定 .bak 用例）；详见执行报告 §7 | .bak 裁定与 E2/E3 资源仍待用户；A0–A9 NOT_STARTED |

启动后补：现行要求版本、未决冲突、AUD/FIX列表、工程回归结果、060交接位置、本地/生产/业务四级状态。不得预填PASS。

## 12. 可复制执行提示词

### 12.1 仅核查、出改进清单

```text
你是系统分析、架构和测试专家。请执行
docs/ACTIVE/059_SYSTEM_REQUIREMENTS_DRIFT_AUDIT_AND_IMPROVEMENT_PLAN_20261002.md
的核查模式：A0–A5、A8文档部分、A9。
先严格完成AGENTS和启动包规定的读取顺序、Git只读现场保护、任务板认领。
结合当前代码/模板/测试、INDEX/01、最新交付与可用本地对话，建立要求台账、冲突裁决表、系统完成度表和偏差清单。
同一事项冲突以有出处的最新用户要求为准；代码只证明实际行为，不自动取代要求；没有来源的聊天或授权不要编造。
每个领域逐项给证据、复现、根因、优先级、可执行FIX、白名单、验收/回退和060用例。
特别核对完成时提醒/RPA过渡、RPTCOUNT非护理缺项、177目标库、W10豁免签字、已关闭D-J1、密钥事故与补跑最新记录、必测E2E跳过项。
补读01的09-23预检启用、09-30两窗已补/判断组装线索；117按INDEX真实路径定位。按领域先P0分期核查，未读范围保留分母；未提交可用完整manifest冻结，不把commit当强制前置。
本次只做核查、证据与文档，不修改业务代码，不生产写入、不真实模型/Relay调用、不临床裁决、不Git写、不外发、不自动启动多代理。
授权范围内自主完成，不重复询问常规可逆细节。仅缺失信息实质影响目标/验收/范围/授权且现有证据无法确定时询问，同时继续其他工作。
更新059执行记录和060交接；按skill运行文档检查与quick，追加01、更新INDEX/02。
最终报告已确认偏差、已关闭旧项、仍待核实/外部依赖、改进顺序和060输入；明确本地、生产、业务状态与真实覆盖分母。
```

### 12.2 核查并完成本地明确缺陷整改

```text
请执行docs/ACTIVE/059_SYSTEM_REQUIREMENTS_DRIFT_AUDIT_AND_IMPROVEMENT_PLAN_20261002.md
的本地核查与整改模式，完整执行A0–A9。
本指令授权：核查后证实、现行要求明确且归属清楚的本地P0/P1缺陷修复，必要测试、构建准备和文档补正；逐包认领实际文件范围并保留其他会话现场。
先完成要求/冲突/状态/偏差台账，按最新有证据的用户要求裁决，确认根因和独立验收后再改。
不重新实现已经交付的旧任务，不扩展主服务WP8、不造W10规则、不新增护理直连，不放宽临床标准或高危硬门槛。
生产配置/DDL/DML/部署/触发/历史补推、177写入、真实Dify/Relay/外发、临床裁决及Git commit/tag/push/PR均不在本授权内；需要时先准备具体结果再提出精确批准事项。
任务按依赖和P0/P1顺序完成，每包保存复现、diff、回归、回退和01登记；使用med-audit-gates，涉及demo/sidecar使用med-audit-demo-stack；长任务按oneshot-delivery规程保存检查点，但不得继承旧提交批准。
获授权且可独立完成的工作持续推进；遇外部阻塞只暂停依赖包，不把BLOCKED/SKIPPED当PASS。
整改后跑full+锚及必需专项、更新现役契约和059记录，生成handoff-060.json并按实际变更细化060。
交接JSON按A8 v1契约校验；台账按领域冻结后推进，不等待全仓所有文档一次性读完，不把分期覆盖当全覆盖。
交付时分开报告审计、本地整改、生产部署、业务/临床验收，明确未提交、未部署及残留恢复第一步。
```

### 12.3 跨会话恢复提示词

```text
继续059，先完成共同启动并读取059最新执行记录、01/02及review中对应exec-log。
核对当前要求、HEAD和dirty hash是否漂移，保留归属未明内容；不重做已验收包，不迁移旧生产或Git授权。
按已记录模式、白名单和依赖从第一个未完成且可执行的包恢复；补齐证据、门禁、登记和060交接。
```

## 13. 2026-10-03外部复核意见评估与修订记录

本节只记录计划复核，不表示A0–A9已经执行；文件名保留10-02编制日期，版本升v1.1。

| 意见 | 核证结论与采纳方式 | 证据/修订落点 |
| --- | --- | --- |
| R01 必须先分批commit | 部分采纳：长期dirty风险成立，提交前先按真实批次/归属准备清单；不把未获批准commit设核查硬前置。本轮仅文档修订，无Git写授权 | 本地HEAD=ac699b5，dirty跨09-24/09-28/10-02；A0完整manifest/前镜像与续跑漂移检查 |
| R02 缺09-23生产线索 | 采纳，但不能说058“BFF未启用”；058描述sources禁用/空转，启用sidecar≠业务源和外发都启用。本轮未联机 | 01的09-23两行与09-27BFF200；§3新增分层线索；代码升级564e276阶段与compose ac699b5分开 |
| R03 117/900–906悬空 | 不采纳事实判断：INDEX已登记这些逻辑编号且实际路径存在；采纳可读性改进，用真实可点击路径 | INDEX117→wp0夹具README、900–906各有文件；§2/§4与INDEX导航明示 |
| R04 需求重建估算乐观 | 采纳分期，不接受用抽样替代P0要求或伪称全文覆盖 | A1按领域追加台账/分母、A1/A2分期闭环、§7排期修订 |
| R05 交接格式未固定 | 采纳，定义v1字段/类型/枚举/文件hash/TC引用和生产者、消费者校验 | A8 v1契约与结构模板，060§2.1引用同一契约 |
| R06 09-04后来源不具体 | 采纳具体来源清单，但01/交付中的用户转述不自动升为一手原话 | §2.1.8列09-23/24/27/29/30、054§4.1/§15.3/§16；§3追加09-30补跑和组装层线索 |

本轮追加发现：01后补09-30行的物理位置在10-02之后，事件时间仍是09-30；两窗旧待办须核销。103/62样本复核记录只作为核查线索，不能替代060独立临床金标准。

## 14. 2026-10-04 round-8 修复计划执行修订记录（v1.2）

本节记录 round-8 修复计划（review/round-8/修复计划.md）R0–R7 一次性执行中对本文件的修订；A0–A9 业务执行仍未启动，修订不预填任何 PASS。

| 修复包 | 对本文件的修订 | 落点 |
| --- | --- | --- |
| R5 handoff 契约闭合 | A8 v1 契约新增三类文件校验规则（不可变交付快照校原件/被测运行文件校 runtime 子集哈希/可追加执行记录标 append_only 漂移不判失败）；明确最终冻结时点=A9 收尾登记之后；delivery_kind 增 `verified_no_fix`（完整核查证据+零必要FIX理由+必测清单，不自动等于测试通过），file_manifest 增可选 append_only 字段 | §5 A8 契约表与校验规则段 |
| R0 核查结论校准 | round-8/方案.md 头部追加勘误（八项发现逐项标注撤回/历史已修/部分成立）；117 为 INDEX 有效逻辑编号非悬空；启动基线=用户裁定 commit（积压已分批提交）；生产部署四层状态与 tip=564e276 表述以勘误头为准 | review/round-8/方案.md 勘误头；本节记录 |

执行证据：`review/059060-fix-20261004/`（逐包执行卡、命令与退出码、diff 摘要、最终报告）。

## 15. 2026-10-04 A0–A9 本地核查与整改执行记录（v1.3）

本节记录用户 2026-10-04 提示词（§12.2 模式+九项重点核对+handoff 要求）授权下的完整执行；证据目录 `review/system-audit-20261004-r1/`（gitignored），逐包命令/退出码/结论见其 exec-log.md。

| 主题 | 结论 |
| --- | --- |
| 执行模式与边界 | 本地核查与整改模式；零生产写、零真实调度/补推、零 177/179、零真实 Dify/Relay、零临床裁决、零资料外发、零 Git 写（commit 基线=5324fca 不动） |
| 台账 | requirements.csv 56 REQ / conflicts.csv 24 CON / system-state.csv 17 模块 / findings.csv 14 AUD；分母与排除见 exec-log A1 节 |
| 证实缺陷与修复 | AUD-A1 status 翻转（P1，FIX-A1）、AUD-A2 结论字面量（P1，FIX-A2）、AUD-A3 缺说明无标记（P2，FIX-A3）、AUD-C1 部署文档漂移（P2，FIX-C1）；合计 4 包全部验收通过 |
| 设计边界（非缺陷） | AUD-E1 高危守卫保守降级（024 已批准）；reasoning_brief←conclusion 回退（设计内） |
| 建议项（不自动实施） | AUD-A4 聚合包含条件依赖说明文本有无——修复方向改变判定结果，需业务裁定 |
| 外部阻塞/用户裁定 | AUD-B1 生产 anchor 漂移（生产写授权）、AUD-B2 Vastbase 超时治理轨道、AUD-C2 E2 四前置、AUD-C3 临床金标准、AUD-D4 W10 清单、AUD-D5 177 第一批批准、AUD-E2 .bak 裁定（唯一门禁 FAIL） |
| 回归终态 | quick 4/4；full+锚 10/11 PASS+锚全部不低于（main 1441=1379 锚+10 新测试/0 fail）；唯一 FAIL=已知 .bak 用例非本批引入；legacy 规则中心 E2E 可选项 no-demo SKIPPED（本批零相关变更） |
| 交接 | handoff-060.json（v1 契约+R5 三类文件校验，delivery_kind=remediated）；060 §13 已同步修订并绑定 B08/B09/Q12/Q16/F18/F20/H15-UI |
| 四级完成度 | 审计=完成（分母如上）；本地整改=完成（4/4 FIX）；生产部署=0（未提交未部署）；业务/临床验收=0（资源未配置）——本地全绿不写成生产或临床验收完成 |
