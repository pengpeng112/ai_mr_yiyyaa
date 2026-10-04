# 060 — 改进后前端、后端、全链路与质控判断准确性详细测试执行计划

> 版本：v1.1；编制日期：2026-10-02；复核修订：2026-10-03；编制/修订者：Codex / GPT-6（会话系统标识）。
> 状态：测试计划已编制，T0–T12尚未执行。没有预填测试通过或判断准确结论。
> 前置：[059 系统要求偏差核查与改进计划](059_SYSTEM_REQUIREMENTS_DRIFT_AUDIT_AND_IMPROVEMENT_PLAN_20261002.md)的最新本地改进交付和handoff-060。属于023业务主线的验证专项。
> 适用：主服务、legacy和UI Next、独立预检/规则中心、Dify解析校验、Relay/H5/JHEMR链路；真实模型与临床金标准须满足各自输入和授权。

## 1. 测试目标与四个独立结论

必须分别回答：

1. **工程正确性**：接口、权限、配置、数据、任务、异常处理和恢复是否符合最新要求？
2. **前端可用性与一致性**：用户能否在两套界面完成流程，显示/操作是否与API和持久化一致？
3. **质控判断准确性**：输入是否完整且同患者同次，事实与证据是否真实，等级/时间/维度判断是否正确，误报漏报如何？
4. **实际可上线性**：当前构建、数据库方言、真实集成、临床复核、现场角色、观察窗口和回退是否分别达标？

Mock返回正确JSON不能证明模型判断准确；pytest和Playwright全绿不能代替真实Oracle/Vastbase验证、临床双审或生产验收。每项结论必须带版本、环境、样本分母、执行时间与未覆盖范围。

## 2. 启动前置与范围冻结

### 2.1 入场检查

1. 按AGENTS完成共同启动，读取01/02、INDEX、059最新记录、060全文、101/102/103/109–115与相关交付。
2. 取得`handoff-060.json`，按059 A8的v1契约校验schema_version、字段类型/枚举、manifest与实际文件（含untracked/deleted）、REQ/冲突原件hash、FIX与TC引用、环境/授权/回退。未知版本或哈希失配阻塞依赖测试，不凭自由文本猜字段；audit_baseline只允许现状验证，不标改进后验收。
3. 核对实际文件与交接哈希；未提交工作树同样可作为被测版本，但必须记录HEAD+差异哈希，不能只写一个旧commit。
4. 从真实路由和页面清单生成测试范围，核对[WP0前端夹具17页历史矩阵](../reference/wp0_frontend_baseline_fixtures/README.md)是否新增/删改，不把旧“17页”当执行时固定分母。117是INDEX逻辑编号，不是文件名前缀，资产真实存在。
5. 每个059 P0/P1、实际修改文件与对应REQ绑定至少一个TC-ID；修复缺陷覆盖“旧代码能复现→新代码期望成立→相邻场景不退化”。
6. 明确本次允许的测试环境和写入范围。只有核查报告、尚未改进时，可跑工程现状基线，但不得标成改进后最终验收。
7. 未决业务口径先标待裁定；受影响用例阻塞，其余可执行用例继续。真实模型、真实患者与生产写入均不从本计划继承旧批准。

### 2.2 环境分层

| 层级 | 环境与数据 | 可以证明 | 不能据此证明 |
| --- | --- | --- | --- |
| E0 | 单元/契约；独立临时库；合成payload；Mock Dify/Relay | 确定性逻辑、映射、校验、错误和事务 | 模型语义、生产SQL方言、真实部署 |
| E1 | 12科室隔离demo、真FastAPI/SQLite、Mock外部；sidecar；两套UI | 前后端持久化完整链、权限、状态、真实HTTP交互 | 真实Oracle/Vastbase、真实企微/嘉和客户端 |
| E2 | 隔离Oracle应用库/业务源测试库、Vastbase及多源测试连接 | 方言、真实列型、驱动、执行计划与数据源契约 | 无批准的生产DDL/DML/调度/患者外发 |
| E3 | 获批院内影子Dify版本、脱敏样本、告警抑制、人工金标准 | 模型准确性、版本对比和稳定性 | 自动临床裁决、生产推送验收 |
| E4 | 获批canary、真实四角色、测试科室/接收人、现场联调 | 部署、真实提醒/反馈体验、连续观察 | 全院切换、批量整改或新范围写入 |

E0/E1采用隔离文件SQLite，涉及跨进程状态避免共享`:memory:`连接伪影。禁将本地运行环境指向生产配置、应用库、Dify或Relay。

### 2.3 环境就绪清单

- Python/Node/npm版本、依赖锁、Oracle/Vastbase/MySQL/SQLServer等所需驱动、Playwright浏览器已核对实际仓库约束。
- 测试账号对应admin/auditor/dept_manager/clinician，权限/科室由实际seed和接口核实；不要臆造生产权限矩阵。
- demo主服务、Dify/Relay mock、预检sidecar进程属于本任务；应用库/配置/日志均隔离；输出不打印密钥。
- scheduler/通知默认关闭或仅指向隔离Mock；trial/suppress禁止真实外发；外部请求目标有清单与拦截证据。
- 4173只报告不杀；18080–18082/18600清理先核PID归属；L1双栈其他端口按脚本实际配置核对。
- 正式门禁使用med-audit-gates；demo生命周期/双轮使用med-audit-demo-stack；后续长期执行按oneshot-delivery检查点规程。

T0即建`resource-readiness`，逐项记录申请人/责任方、现有证据、需要输入、批准范围、预算和恢复第一步：

| 资源 | 编制修订时的证据边界 | T0应准备的具体材料 |
| --- | --- | --- |
| E2隔离Oracle应用库/测试业务源 | 058已核216生产Oracle、177有限视图权限；现资料未提供本任务可用隔离测试库，不能推断全院绝无其他实例 | DBA/信息科提供隔离库或授权只读生产窗口：目标身份、只读账号、允许SQL/EXPLAIN、时段/预算、超时/结束回滚。已有当前任务只读授权可沿用；有副作用的计划统计采集不当普通只读 |
| E2迁移/故障/压力 | 无本任务隔离DDL/DML与压测目标就绪证据 | 明确测试schema/备份/回退/最大负载；只读生产窗口只能验证结构、权限、方言和计划等获准子项，不能替代迁移、故障注入或压测 |
| E3临床金标准 | ≥300样本为设计建议，非已就绪人力/数据 | 质控科确认负责人、两位盲审者/仲裁者、样本数/标注时长/排期、患者使用/脱敏和模型预算、统计阈值；详见§7.4 |

资源未就绪在T0预标对应子项BLOCKED；先形成可审查资源单，不到T3/T8才开始准备，也不因资源不足阻塞E0/E1。

## 3. 测试数据、独立期望与覆盖矩阵

### 3.1 数据集分层

| 数据集 | 用途 | 最低设计覆盖 | 管理要求 |
| --- | --- | --- | --- |
| D-SYN | 工程、前端、权限、异常 | 12科室、四角色、同患者不同就诊、两种run mode、六类、历史NULL与current/superseded、空/长/脏数据 | TEST/SYNTH前缀、固定seed、独立库、预期行数/键集合 |
| D-QC | 判断规则与模型挑战集 | 六类每类至少20个适用正/反/边界向量，起步≥120；再补围术期两源、危急规则等专属组合 | 人工定义期望，独立于模型输出；不把不适用组合硬套六类 |
| D-PERF | 并发、分页、长文、资源恢复 | 依据真实容量/超时选小/常见/峰值规模与并发；smoke/showcase/performance档分开 | 固定行数/文本长度/并发/资源；不向生产压测 |
| D-GOLD | 临床真实准确性 | 按六类/科室/时间/结果类型分层；建议试点每类≥50个可审样本，总计≥300，数量最终由质控科确认 | 患者使用授权、脱敏、双审/仲裁、版本锁定、盲测留出 |
| D-OBS | 现场连续观察 | 按023至少7业务日双模式、生产总体14天；观察范围须另批准 | 每日分母、源健康、错误/超时、延迟、告警、反馈与未决问题 |

样本数是执行起步建议，不是已批准临床验收阈值。稀有高危阳性不足时明确补样和统计不确定性，不能用300例总数替代各类高危阳性分母；平衡挑战集不能推算生产发病/告警率。

### 3.2 必须覆盖的组合

采用风险驱动组合，不要求无意义全笛卡尔积：P0覆盖所有适用高风险组合，普通页面先做pairwise，关键主流程固定全覆盖。

- UI：legacy `/`与UI Next `/ui-next/`；四角色；1366×768、768×1024、390×844；必须现场核验浏览器范围，默认现有Chromium，其他院内浏览器列专项。
- 日期：日增量/出院终末、跨日/跨月/跨年、半开区间端点、未来报告、补记/签署时间差、同秒水位跨页。
- 数据：完整、整体缺源、单侧未提及、查询故障、部分覆盖、空键、NULL、重复、超长/截断、乱码、同义词/否定语句。
- 结果：pass、warn、fail/high、unknown/manual_review；预检pass/fail/unknown/pending/excluded和零规则not_run；当前/历史/被替代。
- 异常：400/401/403/404/422/429/500/502/503、Dify超时/空输出/非法JSON、Oracle/Vastbase错误、连接/事务失败、sidecar断开、重启恢复。
- 状态：未复核/已复核、整改抑制/手工覆盖、取消/重试、Outbox pending/success/failed、规则draft/trial/published/rollback的实际状态机。

### 3.3 每条用例的执行卡

下文用例是可执行场景清单。T1先建立全部79场景及新增FIX子用例的索引/REQ映射和未展开状态；执行卡**按包渐进冻结**：T2前冻结B卡适用E0子项、T3前冻结E2子项、T5前冻结F卡、T6前冻结J卡、T7前冻结Q卡、T9前冻结P/S卡。每次只冻结即将执行的包，不要求一次写完全部卡；实际执行前每条卡必须包含：

```text
TC-ID / REQ-ID / AUD-ID / FIX-ID / 优先级 / 层级
目的与风险 / 实际页面路由或API方法路径 / 源码与已有测试映射
前置权限、配置、数据与版本 / 精确输入fixture、seed和期望键集合
有序操作步骤 / 独立业务期望 / API断言 / DB断言 / UI断言
副作用断言（Dify/Relay调用数、审计、任务/连接回收）
清理与复位 / PASS/FAIL/BLOCKED/SKIPPED/N.A. / 实际结果
证据路径、时间、耗时、缺陷ID / 重测结果与受影响回归
```

不能只写“页面正常”“接口200”“数目大于0”；关键结果必须比较精确身份、字段、时间、集合、数量或状态。N.A.须写适用性依据；SKIPPED/BLOCKED不计PASS。

## 4. 前端详细用例（F01–F20）

F01–F20默认在E1执行，API错误可在E0 Mock补齐。两套UI缺少某功能时按059现行要求判断“缺陷/暂缓/不适用”，不能一律跳过。

| ID/级别 | 前置与操作步骤 | 关键期望/断言 | 证据 |
| --- | --- | --- | --- |
| F01/P0 登录会话 | 四角色分别正确/错误登录→刷新→直达授权路由→注销→浏览器后退；补账号禁用与token过期 | 会话/权限按实际契约；失效不留可操作敏感页面；错误不暴露账号/密钥；Cookie/Bearer分别核对 | 请求、页面、会话和服务端鉴权 |
| F02/P0 菜单/深链权限 | 四角色记录菜单→地址栏直达禁用页→调用页面写API→替换对象ID/科室 | 隐藏菜单不是唯一防线；后端拒绝；跨科室数据不泄漏；允许动作与角色权限相符 | role×menu×API矩阵与403 |
| F03/P1 路由和发布资源 | legacy和UI Next全部实际路由→刷新/后退/书签深链→资源加载→比对构建manifest | 无404、旧bundle混载、白屏；默认入口符合现配置；不得测试时悄改默认入口 | 路由清单、资源/版本哈希 |
| F04/P1 驾驶舱统计 | 固定日期/科室/类型与空结果→逐项比对列表、API、数据库聚合→切换筛选 | 时窗/范围/状态分母一致；空结果有说明；unknown不当pass，重复当前不重复计数 | 三层对账表 |
| F05/P0 患者/就诊 | 同患者两次就诊及同名患者→筛选→打开详情→上/下一条 | 每层保持patient_id+visit_number；科室/文书/质控结果不串次；分页边界正确 | 身份键与详情字段 |
| F06/P1 列表筛选分页 | 患者/类型/状态/科室/日期组合→分页→改变筛选→重置→连续快速输入 | 防抖/回到第一页；请求竞态不覆盖新结果；total和实际集合正确；NULL历史行可显示 | 请求序列、键集合、分页截图 |
| F07/P0 质控详情显示 | 加载pass/warn/high/unknown、旧v1与v2、extra.issues、长证据→展开→切换/关弹窗 | 等级/色彩/时间/来源/API一致；未评价不显示通过；换行保留；脱敏；关闭清状态 | fixture→API→UI字段映射 |
| F08/P0 推送/预检 | 合成候选→仅预检→核无PushLog与外呼→手动推送→轮询→查看日志 | 预检只读；真实HTTP完整流程；候选/成功/失败/skip数可解释；双击不超批准范围 | DB差异、Mock调用计数、漏斗 |
| F09/P1 任务进度取消 | 长任务启动→刷新/切路由→轮询→取消→断网再连 | 状态与后台一致；终态停止轮询；取消保留已完成记录；失败可解释；没有无限spinner | 状态序列与后台终态 |
| F10/P0 配置局部保存 | 只改alert_dept_filter或非敏感字段→保存→重开→请求空body/空密钥/空base_url | 未提交字段保留；空JSON拒绝；密钥空串不覆盖；已配Relay地址保留；无明文回显 | 保存前后脱敏键diff |
| F11/P1 类型编辑 | 卡片↔JSON→增删复制sources→非法SQL/JSONPath→取消/保存→刷新 | 可视化/JSON一致，错误定位明确；字段映射保留；不存在类型删除404；内置保护按契约 | 请求和Registry校验 |
| F12/P0 调度配置 | daily/discharge开关组合→合法/非法cron→局部保存→status→隔离手动触发 | enabled、next_run、diagnostics/effectiveness可见；未生效不显示成功执行；确认范围准确 | UI/配置/job/history对账 |
| F13/P0 反馈整改 | 可操作角色查看→提交整改→复核/误报及必填原因→再次推送 | UI/DB历史一致；权限受控；rectified_suppressed生效；重试不重复历史；QCFeedback与H5反馈轨道分清 | 操作请求、历史和后续skip |
| F14/P0 告警/H5 | Mock告警→H5合法token→查看→反馈→过期/错误/换alert token | 身份/证据正确；token仅绑定允许对象和动作；重放/失效按契约拒绝；无内部地址/密钥泄漏 | Relay/H5请求与反馈落库 |
| F15/P0 规则中心状态 | 有view角色→规则/版本/账本→非授权角色→断sidecar→恢复 | 403显示无权限；502/503显示不可用；主业务仍可用；false权限不能写；恢复可重试 | 正向/降级双轮日志 |
| F16/P0 核查工作台 | 造非空多科室run/issues→分页筛选→详情→已查看/整改/复检/误报→刷新 | 精确total/键集合；科室作用域；按钮与API权限一致；终态首次issues完整；动作原因/版本正确 | API/DB/UI、first稳定集合 |
| F17/P0 规则编辑发布 | draft改动→非法DSL→dry-run→trial→人工确认候选→publish→rollback | 状态机/权限/原子性；失败不半发布；trial无外发；AI候选不得自动成为有效规则 | 版本/审计/Outbox/调用计数 |
| F18/P1 导出打印 | 列表筛选后导出CSV/报告/打印；空命中；跨科室；脱敏和CSV特殊字符 | 列表与导出范围一致；0命中表头成功并记审计；无隐藏敏感字段；下载名/编码正确 | 文件哈希、计数、ExportAuditLog |
| F19/P1 长文本响应式 | 三视口；长中文/超宽表格/多维证据/弹窗/抽屉→滚动/键盘焦点/关闭 | 操作不遮挡，正文可读；横滚合理；键盘可达/aria；截图仅合成数据 | 视口截图与交互记录 |
| F20/P1 错误与竞态 | 模拟403/422/429/500/502/503、慢网、重复点击、先旧后新响应 | 中文错误与根因分类；无未处理pageerror/console error；保留输入、可恢复；无永久loading | 控制台、失败请求与恢复记录 |

## 5. 后端与数据详细用例（B01–B24）

| ID/级别 | 输入与执行步骤 | 核心期望 | 层级/证据 |
| --- | --- | --- | --- |
| B01/P0 JWT/RBAC/CSRF | 无认证、四角色Cookie/Bearer、过期/禁用、Cookie写缺CSRF头、跨科室ID | 精确允许/拒绝矩阵；写失败无DB/外呼副作用；H5豁免仅按token契约；错误不泄密 | E0/E1，鉴权与DB diff |
| B02/P0 配置部分保存 | 各config写端点省略字段/空body/空密钥；Relay仅科室过滤，原base_url非空 | exclude_unset合并；空body422；加密字段保留；错误不写文件；备份/掩码符合契约 | E0，前后配置脱敏diff |
| B03/P0 Registry校验 | SQL分隔符/注释/危险语句/非法占位符、JSONPath、重复code、类型CRUD | SQL安全、JSONPath和密钥加密走统一入口；合法查询不误杀；不存在/内置删除准确 | E0/E2，校验异常/DB |
| B04/P0 身份分组和join | 空键、同患者两次、重复行、1:N/M:N、required源缺失、来源行错患者 | 无跨次/串人；空键显式计数；fanout受控；bundle/skip精确，不能静默丢失 | E0/E1/E2，期望键集合 |
| B05/P0 EMR真实文书 | uppercase列、进展/出院/首程模板、非临床文书混入、sslmode缺省/显式 | lower后映射；template过滤正确；无知情同意混入；未配置不强传sslmode | E0/E2，查询参数/适配行 |
| B06/P0 日期与终末覆盖 | 六类daily/discharge；四专用转换、generic fallback、EMR空SQL专用路径 | 日期范围正确；无效alias诊断；无漏患者假象；effectiveness保留；不按空SQL误判不可用 | E0/E2，SQL/候选键集 |
| B07/P0 payload/Dify契约 | 四builder与类型参数、长原文、workflow_input_variable、base_url、output key | 内部mr_text，外部mr_txt字符串；JSONPath/目标准确；截断不改身份/来源；密钥不打日志 | E0/E1，请求Mock/102契约 |
| B08/P0 类型响应解析 | 合法v1/v2、专属维度、空输出/代码块/非法JSON/截断、extra | 不丢audit_type_code/证据/extra；解析异常有诊断不产生high；旧兼容无误升 | E0，解析/持久化向量 |
| B09/P0 high门槛与结论 | 合格issue及逐条件破坏、warn、合成结论high但维度不足 | 只降不升；不合格high不能通过结论fallback发告警；合格high必须保留 | E0/E1，Q01–Q18关联 |
| B10/P0 批量事务隔离 | 中间患者DB失败/唯一约束/超时，再处理后续患者；串/并执行器 | 仅该条失败且可追溯；会话rollback/嵌套隔离；后续成功，计数不误标 | E0/E1，DB行/事务/Mock |
| B11/P0 skip/幂等/current | 已成功/未复核/整改抑制/手工覆盖；重复同键，不同mode/query_date | skip原因/标记保留；合法双mode策略按最新裁定；无自替代或多current；不重复通知 | E0/E1，唯一键与状态 |
| B12/P0 双调度与锁 | enabled所有组合、legacy共存、daily/discharge同时触发、同job重复、异常退出 | 双模式优先正确；独立job锁互不抢；同任务受控；异常锁释放；手动路径锁实际行为记录 | E0/E1，job/lock/history |
| B13/P1 重试熔断取消 | Dify 429/5xx/超时、半开恢复、某目标失败、取消中断 | 有界重试/退避、目标隔离、取消回收；不重复落库/告警；剩余目标行为符合契约 | E0/E1，调用次数和状态 |
| B14/P0 logs与统计 | 历史NULL、空dept、类型/风险/日期/skip筛选、不同页total、CSV | 序列化不500；Oracle空串不清空科室候选；列表/统计/导出同分母；审计完整 | E0/E1/E2，SQL与计数 |
| B15/P0 科室补全 | payload无dept、patient_info不全、V_QYBR同患者不同次数、入/在/出院不同科室 | 用真实所在科室列与双键查询；补全优先级/副作用符合契约；不串次不捏造 | E0/E2，参数和补全字段 |
| B16/P0 Relay/HMAC | severity_levels、结论fallback、科室码/名过滤、空过滤、错签名/重放、失败重试 | 符合最新高危门槛和抑制；只命中对象/接收人；签名准确；pending/success/failed可追溯 | E0/E1，Mock事件/日志 |
| B17/P0 反馈并发与留存 | 同时修改反馈/复核、抑制、H5反馈；删除日志关联；留存L1/L2/L3 | 历史完整、并发一致、对象鉴权；按现契约清关联；Oracle留存语法可执行 | E0/E1/E2，关联表对账 |
| B18/P0 数据库schema | 新/旧SQLite与隔离Oracle，缺列/约束/迁移中断、自检 | 手动迁移/_verify_required_schema对齐；失败可见不假healthy；数据不丢；不触生产DDL | E0/E2，前后schema/回退 |
| B19/P0 预检锚点与水位 | finished/discharge/blws_status/paperless_rpa；同秒跨页、UPDATEAT变化 | 默认不变；RPA水位门禁用；稳定复合键分页/复检；RPTCOUNT只对账 | E0/E1，游标/规则实例 |
| B20/P0 五态规则与覆盖 | zero/disabled/dept excluded、资料不足、窗未结束、明确缺项、正常 | pass/fail/unknown/pending/excluded准确；零规则not_run；覆盖零分母null不100%；总数算术成立 | E0/E1，eval和summary |
| B21/P0 隔离与规则生命周期 | 禁双向import、paperless元数据、两轨合并重rule_id、trial、发布异常 | check_isolation通过；元数据不documents；重复rule_id拒绝；trial零外发；原子回退 | E0/E1，隔离/版本/审计 |
| B22/P0 工作台/JHEMR一致性 | run completed首读、物化失败、分页total、多科室对象、feedback/review权限 | first==stable==expected键集合；物化失败partial+diagnostic；有界分页；对象权限签名真实 | E0/E1，跨进程L1/DB/API |
| B23/P1 Outbox与AI匹配恢复 | 原子入队、重复/失败/重启、任务丢失、FID分批、人工确认候选 | 不丢任务/不重复外发；失败有状态和上限；匹配进度持久化；候选不自动发布 | E0/E1，任务/审计/Mock |
| B24/P1 运维恢复与错误码 | ORA-12609/Vastbase timeout/DB锁、连接中断、进程重启、配置密钥不匹配 | 根因错误码保留、连接关闭、有界恢复；不吞异常假成功；密钥失败不自动重写密文 | E0/E1/E2，资源/状态/脱敏日志 |

SQLite通过不能勾E2 Oracle通过。无隔离Oracle、只读权限不够或真实源不可用时，对应用例写BLOCKED和资源申请，照常完成E0/E1。

## 6. 端到端业务旅程（J01–J09）

端到端至少验证“用户动作→API→持久化→外部Mock→后续查询/UI”，不只点击页面。每条固定身份/期望集合，并复位合成数据。

| ID/级别 | 顺序 | 通过标准 |
| --- | --- | --- |
| J01/P0 日增量 | 管理员选日期/类型/科室→预检→推送→结果→详情→反馈→下次预检 | 预检零副作用；结果精确；未复核/整改抑制行为一致；多次就诊不串 |
| J02/P0 出院终末 | 出院候选→六类加载→EMR专用路径→终末结果→与日增量对账 | 候选覆盖和差额解释；独立锁；mode/日期保留；允许双发与幂等契约一致 |
| J03/P0 合格高危闭环 | 构造合格直接安全冲突→模型stub/解析→high落库→Mock Relay→H5→反馈→复检 | 同issue双侧真实证据、高危保留、准确接收人、反馈持久化、复检闭环 |
| J04/P0 不合格高危拦截 | 缺源/单侧/一般问题/非法JSON/跨issue拼证据→结论故意设high→enqueue | 每层不得错误提升；Mock告警数=0；页面正确显示medium/unknown与原因，不全部抹成pass |
| J05/P0 预检完成提醒 | 选锚点→采集完成→规则评估→Outbox→Mock提醒→工作台整改/复检→JHEMR读取 | 明确实际提醒时点；RPA过渡不伪称即时；护理无数据不判缺；run首读完整 |
| J06/P0 规则发布回退 | 授权用户编辑→dry-run/trial→确认→发布→新run→回退→再run | 版本快照/审计/结果可追溯；trial零外发；失败无半发布；已关闭issue不误重开 |
| J07/P0 四角色安全旅程 | 各角色登录→患者/记录/工作台→写操作→跨科室→会话失效 | UI/接口/对象三层一致；无越权、漏敏感数据和不受控动作 |
| J08/P1 外部降级恢复 | sidecar/Dify/Relay/源DB逐个故障→其他功能→恢复→重试 | 故障范围受控、解释准确；恢复无重复状态/推送；不是只验证报错文案 |
| J09/P1 导出和跨页面对账 | 相同范围驾驶舱→记录→详情→CSV/报告→导出审计 | 身份键/等级/时间/计数一致，空文件成功审计，历史和当前口径明确 |

JHEMR必须分别报告L1本地协议、L2真实客户端联调、L3现场医生验收。FILEVERIFY旧179驱动和冻结包禁止使用；任何177写入/启用必须另获精确批准。

## 7. “判断是否准确”的验证规程

### 7.1 先分清五层准确性

1. **数据层**：是否同患者同次、文书来源真实、时间可比较、必需源和截断范围已知。
2. **事实层**：issue是否有原文证据、是否把未提及/同义/不同时间变化误认为直接矛盾。
3. **决策层**：severity/status、维度、confidence与患者安全类别是否符合该类型现行规则。
4. **转换层**：节点二、后端校验/映射、DB、API、UI和结论fallback有无失真、误升/误降或丢证据。
5. **闭环层**：告警是否发给正确范围，整改/复检是否真处理了对应问题，而不是只改状态。

每个误报/漏报必须归因到上述层级，避免只调提示词掩盖错误数据或映射。

### 7.2 六类分别建立期望，不用通用模板强套

| audit_type_code | 真实比较对象与重点 | 专属必测 |
| --- | --- | --- |
| admission_vs_first_progress | 入院记录vs首次病程 | 缺任一文书、单侧遗漏、同义/合理诊断演变、身份/过敏等受控直接冲突 |
| discharge_vs_frontpage | 现有code保留；109/111口径为首次病程vs出院记录，不能按名字猜首页 | 本次诊疗时间变化、出院结局/诊断演变合理性、来源映射与code兼容 |
| surgery_chain | 术前/手术/术后三来源 | 少于两源跳过/无法判断；恰两源只比较可比范围，第三源缺失不判问题；两已有源合格直接安全冲突仍可high |
| progress_vs_nursing | 同一就诊可比较时间病程vs护理 | 当前状态变化、护理级别一般差异、否定/过敏/生命支持直接冲突 |
| jyjc_vs_bcnursing | 检验检查vs病程/护理 | 未来结果不能要求早期记录响应；护理未提及不是直接矛盾；危急未响应omission当前最高medium/manual_review，机构规则缺失不得编造 |
| syssvsscbc | 首页手术信息vs术后首次病程 | 错侧/术式/植入物直接证据；依赖外部知识诊断术式匹配只manual_review；补记/签署延迟与真正时间倒置区分 |

生产启用类型、alias及扩展类型必须从059交接和实际Registry核对，上表是六类现役提示词口径，不替代动态配置台账。

### 7.3 关键判断向量（Q01–Q18）

每个适用向量分别验证：独立金标准、事实提取输出、节点二输出、后端校验、DB/API/UI和Mock告警。E0以人工构造输出验证工程门槛；只有获授权E3才调用真实模型比较语义。

| ID/级别 | 受控样本/扰动 | 预期结果与错误禁止项 |
| --- | --- | --- |
| Q01/P0 必需源整体缺失 | A缺/B有、B缺/A有、都缺 | 按类型loader可skip；若进入模型则unknown/manual_review，不能捏造问题/high；围术期恰两源按Q17专属规则 |
| Q02/P0 单侧未提及 | 一方有事实、另一方文书完整但未谈该事项 | 不作为直接矛盾/高危；按类型允许pass或manual_review，不把每个遗漏都强制复核 |
| Q03/P1 同义/上下位/否定 | 等价诊断、标准缩写、肯定/否定极性最小变化 | 等价不误报；明确极性反转且满足其他条件能识别；缩写不无依据扩义 |
| Q04/P0 不同时间合理变化 | 早期有症状、晚期缓解；报告晚于记录；补记/签署差 | 不比较非同时状态制造高危；真正时间问题可追溯，窗口不足无法判断 |
| Q05/P0 一般明确冲突 | 双侧直接一般文书问题，非安全类别 | 保留warn/medium或类型规定低提示；不升high，不为了零误报抹成unknown/pass |
| Q06/P0 合格安全冲突 | 同issue、真实不同source、双侧直接不可调和证据、severe/high_eligible、confidence≥0.8、允许安全类别 | 适用类型必须保留high/red；证据与issue逐一绑定；不能全部降级来制造“零假高危” |
| Q07/P0 逐门槛破坏 | 从Q06分别删证据、改相同source/空source、false eligible、general级别、非受控类别 | 每次不合格high被拦截，原因准确；明确一般问题保留medium，证据不足才unknown |
| Q08/P0 置信度边界 | 0.5999/0.6/0.7999/0.8/1、越界/缺失/字符串/NaN | high边界0.8；低置信度按现类型契约；非法值拒绝/安全降级且诊断，不因默认填值升high |
| Q09/P0 跨issue拼证据 | issue1只有A、issue2只有B，汇总两列非空；同source伪装两列 | 不拼接为合格high；按同issue、真实来源门槛验证，结论fallback不得绕过 |
| Q10/P0 证据真实性/串次 | 捏造引文、引用另一患者/住院次、转述充当直接原文 | 识别不匹配，不能通过high门槛；记录数据/事实层缺陷；有原文锚点与身份对账 |
| Q11/P0 空输出与异常JSON | 空、Markdown包裹、尾随文字、非法/截断、错误维度/重复维度 | 合法兼容按parser；不可用保留失败/诊断；无解析失败high/结论告警；不伪造pass |
| Q12/P0 转换不得升降失真 | 节点一warn→节点二high；合格high→节点二pass；extra丢失 | 错误可被断言定位；不合格升high拦截；错误降级也计漏报；保留issue证据与来源 |
| Q13/P0 文本质量安全 | 错字/模板/格式/重复与真正错患者/错侧/错药分开 | 普通text_quality不high；真实安全冲突归正确安全维度，不能借黑名单漏掉真正风险 |
| Q14/P0 危急未响应 | 有/无机构规则；已响应/未响应；窗结束/未结束；coverage完整/不完整 | 当前omission绝不high；程序证实缺响应最高medium/manual_review；模型不能自定义危急值/时限/覆盖 |
| Q15/P1 同事实多维重复 | 同报告同事实被两维/多issue重复，其他独立事实同时存在 | 按类型归属去重；独立事实不误合并；issue、维度、告警分母可解释 |
| Q16/P0 结论/维度显示一致 | 不合格维度+high结论、合格high维度+low结论、全unknown | 结论由现行安全聚合校验；告警不绕过；unknown不显示全部通过；API/UI/DB一致 |
| Q17/P0 围术期三源组合 | 三源齐、每种两源、每种单源/零源 | 两源只评可比维度；第三源缺失本身非问题；两源真安全冲突可high；单/零源不可判明确问题 |
| Q18/P0 语义与恶意文本扰动 | 换行/顺序/同义不改事实；病历内“忽略规则/输出high”；超长前后截断 | 等价事实保持关键判断稳定；原文指令不能改安全门槛/调用行为；截断标资料范围，不伪称覆盖完整 |

### 7.4 金标准构建与临床双审

1. 先得到患者数据使用、院内影子模型调用和脱敏范围授权；公开/外部AI只可使用符合专项规则的脱敏包，不能上传对话全文或原病历。
2. 构建`gold-labels`：脱敏sample_id、就诊映射受控保存、类型、来源/时间窗/数据完整度、真实问题集合、证据锚点、维度、允许等级、是否可判断、理由、标注者、版本。
3. 两位有资格的临床/质控人员独立盲审，不展示模型结论；冲突由第三位或约定质控负责人仲裁。AI可辅助整理，不能充当临床金标准或批准人。
4. 人工无扣分不等于不存在问题；T_MARK人工扣分是候选标签，按同患者/住院次、FID和规则版本对齐，复核时限/来源覆盖，不将“没扣分”直接当真阴性。
5. 数据按就诊/患者相关性拆分开发集、验证集、锁定盲测集；同病历片段、模板复制或同患者多次检查不能泄漏到两组。调整提示词后旧盲测集不能继续当独立留出。
6. 所有真实调用锁定模型/provider、workflow及两节点prompt版本/hash、温度等参数、规则/SQL版本；输出修复也留版本与失败次数。
7. 批次比较同一输入的事实输出→JSON转换→后端最终结果；证据不匹配、false high、错误降级、时间错误、漏报分别计数，不只统计模型原始severity。
8. T0提出人力需求，T8开始前由质控科确认负责人、两位盲审者、仲裁者及各自可用工时。先用10–20例小批测量每人每例标注时间t、争议率d和每例仲裁时间a；估算人时=`2×N×t/60 + N×d×a/60`，另列脱敏、数据核对和报告工时。例：N=300、t=10–20分钟，仅双审约100–200人时，尚未含仲裁；这是排期示例，不是临床承诺或固定标准。人员/时长/负责人未落实则金标准资源BLOCKED，工程验证可继续。

### 7.5 指标、分母与验收标准

必须输出每类型、每科室/数据完整度的分层结果和总结果；避免平均数掩盖某类型失效。

| 指标 | 计算与解释 |
| --- | --- |
| Precision | TP/(TP+FP)，按issue级/患者就诊级分别算；TP匹配键含类型、事实/时间及证据，不能只比severity |
| Recall | TP/(TP+FN)，一般问题和合格高危分别统计；人工确认阳性才进阳性分母 |
| F1/混淆矩阵 | 2PR/(P+R)；pass/一般问题/high/不可判断分别对账，另报适用类别macro指标 |
| 高危错误升级率 | 人工不满足high但系统high数/人工非high数；另报false high/全部预测high，与precision区分 |
| 高危漏检/误降级 | 人工合格high而系统未报high数/人工合格high数，定位事实/转换/校验层 |
| 证据有效率 | 证据可在对应真实source/就诊/时间定位的issue数/需要证据的预测issue数；source和quote错误单列 |
| 可判断覆盖率 | 最终给可判结论数/适用样本数；人工可判断却系统unknown单独计入保守漏报/复核负担 |
| 非法high与契约失败 | 缺源/单侧/解析失败/warn升级/跨issue/伪source的high数量；JSON可用率与后端校验失败率单列 |
| 临床一致性 | 双审一致率及适用kappa；仲裁数量/原因；未仲裁不混入可靠金标准 |
| 波动和性能 | 固定样本建议重复3次，记录关键等级/证据/issue变化；模型p50/p95/p99、超时、token/调用成本 |

分母为0报告N.A.及原因，不填100%。模型unknown对人工明确阳性，在对应检测任务计漏报，另报拒判率；只在覆盖率中展示不能掩盖FN。高危等级漏检与一般问题检出分开。

P/R等输出95%置信区间与原始分子分母；同患者多issue存在相关性时按患者聚类计算区间或明确限制。稀有高危/小样本即使0误报也不能声称风险为0。

验收分三类：

- **现行硬门槛**：确定性契约向量必须100%符合；非法high=0、跨患者/就诊=0、越权/泄密=0、trial/suppress真实外发=0；Q06合格高危向量不得误降级。任何一项失败阻止相关发布/真实启用。
- **沿用已有工程门槛**：正式门禁与锚、059 FIX验收、023数据键/稳定ID/required源等，不能通过下调锚或扩大豁免凑绿。
- **待临床确认的统计指标**：建议试点目标Precision≥95%、Recall≥90%、合格high Recall≥95%、证据有效率100%；仅为候选目标，不构成临床验收批准。T8前确认适用样本、分层目标、置信区间/样本量要求、误报漏报容忍度和重复稳定性；未确认则可交工程报告，临床准确性验收保持BLOCKED。不得用候选阈值代替既有更严格标准。

## 8. 性能、恢复和安全专项

| ID | 执行设计 | 观测和判据 |
| --- | --- | --- |
| P01 查询/分页 | D-PERF小/常见/峰值记录量；患者、反馈、logs、工作台列表及统计；E2执行计划 | 响应p50/p95/p99、行数/扫描/内存；按023源查询p95<调用超时1/3；无无界全文/内存分页；不同端点预算T0记录 |
| P02 连接/并发 | 单worker，手动/两job/重推竞争；持续压力后注入超时并恢复 | pool占用/线程/句柄/事务归零或稳定；无跨患者污染、重复current、锁泄漏；不提高workers绕开 |
| P03 长文/模型预算 | 阶梯长度、截断边界、多个target、429/timeout | token/时延/成本、截断前后关键证据、重试次数；无无界重试和错误high；实际LLM需另批准 |
| P04 重启/恢复 | 处理中任务、Outbox/匹配/反馈状态→终止本任务进程→重启 | 持久状态可恢复，失败可解释，不重复外发，不completed但issues空；保留真实时钟/版本 |
| P05 备份回退 | 隔离配置/SQLite/Oracle测试表/规则/prompt版本/静态产物→变更→回退→复验 | 回退只作用本任务对象；数据/密钥稳定；版本和接口可用；生产恢复不在默认范围 |
| S01 对象越权 | 每角色跨科室、改patient/visit/log/issue/alert/export ID，读写分别试 | 后端拒绝或符合经确认的数据范围；无明细泄漏，失败无副作用 |
| S02 注入与泄密 | SQL配置/JSONPath/XSS文本/CSV公式/token签名/日志异常；不外网探测 | 校验/转义/导出按现安全契约；密钥/PHI不回显；漏洞有独立复现与安全回退 |
| S03 错目标/副作用 | 测试配置故意混生产目标、disabled源、错误密钥、trial/suppress | 隔离守卫fail-closed；不触生产/外呼；不能自动重建/初始化生产库或重写密文 |

暂无已批准端点响应预算时，T0记录现状并提出候选，不虚构“所有接口2秒”验收。资源不足导致的BLOCKED必须给缺什么及恢复第一步。

## 9. 测试包T0–T12与执行顺序

| 包 | 详细执行步骤 | 输入/产出与结束条件 |
| --- | --- | --- |
| T0 基线接管 | §2启动、v1交接与版本/dirty全manifest、环境隔离、角色权限、授权预算；预备E2资源单和金标准人员/时长/确认人；读取技能；初始quick | baseline/env/permission/resource-readiness齐；生产目标未混入；失败/资源缺口登记 |
| T1 用例与数据渐进冻结 | 全量REQ→FIX→F/B/J/Q/P/S索引和适用性；先冻结T2必要卡/D-SYN，其他包执行前再展开并按版本追加卡/数据manifest、seed/键集合和复位方法 | 索引P0/P1映射100%；下一包执行卡完整即可前进；其余标NOT_EXPANDED，不虚构已冻结；临床目标单列 |
| T2 后端单元/契约 | B01–B24适用E0层，重点事务/锁/日期/high/current；先复现既有缺陷再复验 | 定向测试与精确断言；无P0/P1未解释失败 |
| T3 数据源/方言 | E2身份/版本/列/权限/SQL参数、真实模板/日期候选/查询预算；隔离应用库迁移和回退 | SQLite/Oracle/Vastbase分别出结果；不足标BLOCKED，Mock不可顶替 |
| T4 前端静态/单元/构建 | typecheck、unit、build/sync；API契约/路由/权限/错误态；§10.4按相对路径和SHA-256核dist/static ui-next镜像，无多余旧hash；schema核查另属B18 | 正式full内门禁及定向验证、两目录manifest；无旧bundle或手改产物 |
| T5 浏览器功能 | F01–F20两UI/四角色/三视口，已有spec加新增缺口；控制台/请求/截图 | 每条矩阵实例PASS/FAIL等；真实demo请求不以全Mock覆盖替代 |
| T6 完整旅程/双轮 | J01–J09、规则中心正向/停sidecar降级/恢复、非空工作台、JHEMR L1 first集合 | 跨UI/API/DB/外部Mock证据；必测环境开关用例不跳过 |
| T7 判断工程挑战集 | D-QC/Q01–Q18逐类型，分事实输入/转换/校验/落库/UI/告警；变形测试 | 非法high=0且合格high保留，expected independently defined；只能得工程结论 |
| T8 金标准/真实影子 | 获取批准、临床双审与仲裁、锁定留出集和workflow，suppress；确认统计阈值和样本量后实际调用 | 金标准/版本/授权/成本记录、分层混淆矩阵/CI；无条件则临床BLOCKED |
| T9 性能安全恢复 | P01–P05/S01–S03，合理负载、故障注入、复位；真实环境仅按批准窗口 | p95/资源/连接/错误码/恢复/权限证据；无泄漏或意外外发 |
| T10 缺陷修复与回归 | 每FAIL独立DEFECT，给复现/根因/FIX/受影响TC；获授权本地修复后原用例+相邻链回归 | 不降低断言、删用例、扩大豁免或下调锚；新版本重锁受影响测试 |
| T11 全量与现场观察 | 清洁隔离数据→demo主服务→full+锚→补环境门专项；获批准才E4/L2/L3及7业务日/14天观察 | 工程门禁表、必测专项和现场/观察分别出证据，不等待时间就宣称通过 |
| T12 交付与回收 | 核覆盖分母/skip、报告四结论、恢复配置/环境变量、停止本任务进程；更新060/INDEX/01/02 | 可复核报告、缺陷/阻塞清单、证据定位与下一步；未提交/未部署如实说明 |

顺序：T0→T1索引/首包冻结→T2/T3/T4（可按独立性顺序执行）→T5→T6→T7→T8→T9→T10→T11→T12。每个包执行前回到T1追加冻结该包卡/数据，记录package_id、case_ids、版本/数据hash、frozen_at与未展开数量，不重做已完成索引。无E2/E3/E4条件时继续其他包，相关完成度保留差额。T12前所有纳入范围卡都必须完成展开并有执行/阻塞/N.A.证据；版本改变明确哪些结果STALE并重测。

建议排期：环境/用例索引/首包数据1–2个有效工作日，剩余卡和数据随测试包滚动展开；工程前后端/完整旅程3–5日，准确性挑战与专项2–3日。临床标注按§7.4实际人时/可用排班单独排期，不能混入工程估算；额度有限按包多会话续跑。现场观察按7业务日/14天实际历时，不能为排期压缩必要验证。

## 10. 现有测试资产与命令编排

### 10.1 先复用现有有效测试，补风险缺口

- 后端已有auth/cookie CSRF、config partial update、Registry、loader/join/fanout、Dify、串/并执行器、scheduler/discharge、logs/relay/feedback、数据库只读工具、文档检查等tests；按`rg --files tests`定位真实文件，不猜名称。
- 预检已有anchor/RPA、collectors、engine/five-state、rules/FID、publish/trial、coverage/backtest、Outbox/match recovery、workbench/closed-loop、terminal consistency和JHEMR测试。
- 前端unit在`frontend/tests/unit/`；UI Next在`frontend/tests/e2e/`，legacy在`frontend/tests/e2e-legacy/`。当前Playwright默认三个视口；legacy配置默认单桌面，legacy补平板/手机专项不能假装已有。
- 本地命令`npm run typecheck/test:unit/build`和Playwright均已在package.json；正式汇总仍由run_gates产生。历史测试数字只作线索，当前锚读取`docs/reference/gate_anchors.json`，不手填历史数字当预期结果。
- 真实环境开关有SYNTHETIC_DEMO_E2E、WORKBENCH_E2E、ONESHOT_E2E、UAT054_E2E、LEGACY_E2E；不同spec须分别核造数、权限/会话与副作用，不能打开开关后无条件跑所有有共享数据变更的spec。

### 10.2 Windows PowerShell可执行命令

先在根目录核help，固定本次run-id，确认不覆盖其他人的demo。以下run-id仅示例，实际以T0记录为准。

```powershell
python scripts/demo_env.py --help
python scripts/run_prearchive_demo_sidecar_20260904.py --help
python scripts/demo_env.py create --run-id audit060-20261002 --profile showcase --seed 20260813
python scripts/demo_env.py serve --run-id audit060-20261002
python scripts/demo_env.py status --run-id audit060-20261002
python scripts/run_gates_20260906.py --quick
# 正式full前仅主demo在听；聚合脚本自行起停sidecar，支持legacy正向/降级双轮
python scripts/run_gates_20260906.py --full --anchor-file docs/reference/gate_anchors.json
```

门禁可能修改demo库，不能直接假设数据仍是初始状态。独立专项前先保存门禁/数据证据，核run-id归属，按下方复位本任务主demo。`reset`内部会停止/销毁该run-id的三个目录再重建，不能用于未知或他人的run-id；它**不会复位预检sidecar数据库**。

```powershell
# 仓库根目录：完整复跑一轮有状态专项前执行；先保存上一轮证据
python scripts/demo_env.py stop --run-id audit060-20261002
python scripts/demo_env.py reset --run-id audit060-20261002 --profile showcase --seed 20260813
python scripts/demo_env.py serve --run-id audit060-20261002
python scripts/demo_env.py status --run-id audit060-20261002
```

随后在受控独立执行会话启动`python scripts/run_prearchive_demo_sidecar_20260904.py --serve --import-rules`，记录PID/配置/库路径，确认本任务独占此demo sidecar及其库；未知占用不擅杀。该命令为前台常驻，其他命令在另一执行会话运行。不要把外部sidecar留着再跑聚合自管sidecar的full。

**所有专项之前的种子前置（仓库根目录）**：确认sidecar健康、BFF指向该实例，再执行：

```powershell
python scripts/seed_workbench_demo_20260915.py --help
python scripts/seed_workbench_demo_20260915.py
python scripts/seed_workbench_demo_20260915.py --status
```

此脚本没有run-id/自定义DB参数，固定读取`prearchive_service/config.demo.json`的sqlite路径（默认`prearchive_service/data/demo/prearchive_result.db`）。运行前核对解析后的绝对目标与sidecar实际result_store一致、归属明确、非生产；预期WB-E2E-P001/P002各1个run和open issue。种子幂等会删除并重建这两名合成患者的run/eval/issue/action；保存上一轮动作证据后才复位，不能把它当任意数据库清理器。

以下在`frontend/`执行；执行前保存相关环境变量原值，完成后逐个恢复而不是覆盖用户全局环境。

```powershell
$env:PLAYWRIGHT_BASE_URL = 'http://127.0.0.1:18080/ui-next/'
$env:PLAYWRIGHT_SKIP_WEBSERVER = '1'
$env:SYNTHETIC_DEMO_E2E = 'true'
npx playwright test tests/e2e/synthetic-demo-real.spec.ts --workers=1 --retries=0
# 依赖顺序：synthetic先造SYNTH-FIX推送/告警/反馈事实，journeys再读它们；两者之间不要reset
# 后续journeys再次推送可能合法skip，不能把已有记录可见当本轮新推送成功
$env:ONESHOT_E2E = 'true'
npx playwright test tests/e2e/oneshot-uinext-sweep.spec.ts --workers=1 --retries=0
$env:UAT054_E2E = 'true'
npx playwright test tests/e2e/uat054-journeys.spec.ts tests/e2e/uat054-perm-session.spec.ts --project=desktop-1366 --workers=1 --retries=0
# workbench-real会改变open issue；在这条命令前回仓库根保存证据并重跑seed及--status，再回frontend
$env:WORKBENCH_E2E = 'true'
npx playwright test tests/e2e/workbench-real.spec.ts --workers=1 --retries=0
$env:PLAYWRIGHT_LEGACY_BASE_URL = 'http://127.0.0.1:18080/'
$env:LEGACY_E2E = 'true'
npx playwright test -c playwright.legacy.config.ts tests/e2e-legacy/legacy-pages.spec.ts tests/e2e-legacy/oneshot-sweep.spec.ts --workers=1 --retries=0
```

上述示例沿用既有默认seed以兼容专用spec；更换seed前必须核对产出的期望集，不为适配数据随意降低断言。实际测试卡需记录spec自身选择的projects，不能仅因全局配置有三个projects就宣称各spec都覆盖三个视口。

054§15.3已实证共享库5 worker造成P002竞态假失败，故有状态专项统一`--workers=1 --retries=0`，不依赖Playwright默认并行值。此处UAT命令仅桌面轮；平板/手机的相同有状态旅程须各自完整复位→种子→synthetic→UAT独立运行，F19响应式检查仍覆盖三视口。不能拿桌面通过勾三视口。

现有journeys首先读取SYNTH-FIX记录，后推送断言较弱，且synthetic已推同候选并提交H5反馈：**固定顺序只保证现有spec的数据依赖，不保证journeys新成功推送**。T1/J01/F08必须另冻结“干净候选/精确成功行数/新增PushLog键集合/Mock Dify调用数”的完整旅程；若需要调整spec以便单独证明新推送，按已授权本地测试范围处理，预先定义独立期望。不能修改生产skip逻辑、手动翻复核标记或用旧结果冒充新成功。

复跑有状态专项时：先保存失败trace/API/DB摘要，再按root复位块重新创建主demo，重新seed sidecar，从synthetic开始重跑依赖序列；不能让自动retry在被改动的库上反复执行。只重跑workbench或perm-session且主库未被污染时，也要先确认其专用前置并复位WB种子。不会因复位删除历史证据目录。

规则中心手动双轮（frontend目录）：正向需本任务sidecar已在听；降级前先停本任务sidecar并核端口，再设环境变量；变量本身不会停服务。

```powershell
$env:LEGACY_E2E = 'true'
Remove-Item Env:RULE_CENTER_SIDECAR -ErrorAction SilentlyContinue
# 正向动作轮前先在根目录保存上一轮证据并重跑WB种子，再回frontend
npx playwright test -c playwright.legacy.config.ts tests/e2e-legacy/rule-center.spec.ts tests/e2e-legacy/workbench.spec.ts --workers=1 --retries=0
# 此处由执行者先停止自己的sidecar并确认18600不在听
$env:RULE_CENTER_SIDECAR = '0'
npx playwright test -c playwright.legacy.config.ts tests/e2e-legacy/rule-center.spec.ts tests/e2e-legacy/workbench.spec.ts --workers=1 --retries=0
```

根目录JHEMR L1与收尾：

```powershell
python scripts/run_jhemr_l1_20260915.py --help
python scripts/run_jhemr_l1_20260915.py --out-dir review/test060-20261002/jhemr-l1
python scripts/check_documentation_20261002.py
python scripts/demo_env.py stop --run-id audit060-20261002
python scripts/clean_demo_ports_20260906.py
```

执行者核现时代码的端口/输出参数后再运行。L1只用隔离合成栈；不把上述命令用于179/177 FILEVERIFY或生产JHEMR。`clean_demo_ports`默认只读，不能因看到端口就`--yes`杀未知进程。

### 10.3 跳过项管理

每个skip登记spec/TC、环境门、原因、是否必测、已覆盖替代证据、责任方和恢复动作。历史058的47skip与锚的23skip不是固定目标；T1盘点执行时实际集合和分母。

规则中心降级轮刻意不适用的正向用例可记N.A.，须对应正向实跑证据。`/api/users/me`未登录冷加载403仅沿用现spec范围豁免；不能扩展到登录后失败、其他接口403或全局控制台忽略。

### 10.4 构建产物镜像一致性核对（frontend目录）

F03/T4核构建发布资源；B18是数据库schema，不应用dist差异代替schema/迁移核验。`npm run build`按package.json调用sync-static，Windows镜像用受边界保护的robocopy；`npm run test:sync-static`验证同步机制，但不能单独证明当前目录字节一致。

以下在获授权构建测试阶段执行。本轮计划修订不执行build、不改产物。运行前保存static/ui-next本批前镜像和归属；构建后比对两个目录的完整相对路径集合及每个文件原字节SHA-256，包含额外旧hash文件：

```powershell
npm run build
if ($LASTEXITCODE -ne 0) { throw 'frontend build failed' }
npm run test:sync-static
if ($LASTEXITCODE -ne 0) { throw 'sync-static mechanism check failed' }
@'
from pathlib import Path
import hashlib, json
dist = Path('dist').resolve()
published = Path('../static/ui-next').resolve()
if not dist.is_dir() or not published.is_dir():
    raise SystemExit('build directory missing')
def manifest(base):
    return {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(base.rglob('*')) if p.is_file()}
a, b = manifest(dist), manifest(published)
out = Path('../review/test060-build-manifests').resolve()
out.mkdir(parents=True, exist_ok=True)
for name, value in [('dist.json', a), ('static-ui-next.json', b)]:
    (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
different = sorted(set(a) ^ set(b) | {name for name in set(a) & set(b) if a[name] != b[name]})
if different:
    print('mismatched paths:', different)
    raise SystemExit(1)
if 'index.html' not in a:
    raise SystemExit('index.html missing')
print(f'build mirror PASS: {len(a)} files, paths and SHA-256 identical')
'@ | python -
if ($LASTEXITCODE -ne 0) { throw 'build mirror byte check failed' }
```

证据目录示例必须执行时替换成本任务唯一目录并保存前后manifest；不覆盖他人或历史输出。目录字节一致只证明镜像同步，F03仍须浏览器实际加载资源无404/旧bundle，生产镜像/代理缓存另按获批E4核验。

## 11. 缺陷处理、退出与交付

### 11.1 缺陷卡和修复原则

每个缺陷保存：DEFECT-ID、REQ/FIX/TC、版本/环境、可复现输入与步骤、实际/期望、源码/请求/DB/截图证据、严重度、根因、影响范围、负责人、修复diff、回退、原用例复验和邻接回归。

可用现有授权修复本地明确缺陷；需要放宽验收、改临床规则、增产品范围/数据源、写生产或调用真实外部时，先形成具体方案再请求必要批准。不能删除失败数据、换掉困难样本、增skip、降低assert或下调门禁锚掩盖失败。

### 11.2 停止条件

出现跨患者/次、越权/PHI泄露、真实目标误连、trial/suppress外发、非法high、数据丢失/不可恢复、生产状态意外变化，立即停止相关测试和依赖写入，保护证据，报告具体事实；只在已有授权内处置，继续无关安全工作。

外部不可用、金标准/临床阈值缺失、权限不足/未批准只阻塞相应层级。时间流逝、测试数量很多、退出码0都不能充当批准或临床验收。

### 11.3 退出判据

| 结论层 | 必需条件 |
| --- | --- |
| 本地工程通过 | 所有适用E0/E1的P0/P1执行且通过；059 FIX覆盖；正式full+锚通过；必需demo/双轮/非空工作台/L1专项实跑；无未解释失败/必测skip；E2/E3/E4差额单列 |
| 方言与数据源通过 | 每个被纳入真实支持范围的应用库/业务源有E2证据；键、时间、列型、权限/驱动、查询性能达既有标准 |
| 判断准确性通过 | 独立金标准/双审仲裁、足够分层样本、确认过的临床阈值、真实影子版本、原始分母/CI及零非法high；漏报/拒判负担可接受 |
| 现场上线通过 | 精确批准、L2/L3/四角色/测试科室接收人、回退演练、7业务日/14天既定观察与残留关闭 |

只满足第一层可交“本地工程通过、临床/现场未验证”。其余层不能被本地测试覆盖率或门禁表代替。

## 12. 证据目录、报告模板与续跑

过程资产：`review/test060-<执行日期>-<run_id>/`内保存baseline、cases、coverage、data-manifest、每层结果/命令与退出码、skip-register、defects、gold-labels受控版本、metrics、exec-log。真实患者映射/原文和截图按00隐私落位，不写本文件、不提交/外发；文档仅脱敏汇总。

本文件追加T0–T12结果和以下报告，不每个会话另建重复总结；确需独立长期报告先取INDEX可用编号并登记。

```text
被测版本：HEAD、dirty hash、规则/SQL/prompt/workflow/config模板版本与时间
现行要求：059 REQ/冲突裁决版本；改进FIX数量与未修项
测试范围：两UI、页面/API分母、角色/视口、环境与数据源
执行结果：计划/适用/执行/PASS/FAIL/BLOCKED/SKIPPED/N.A.及独立分母
门禁：聚合Markdown表、锚比较、环境门专项与豁免范围
工程结论：前端/后端/事务/权限/方言/完整旅程/性能恢复
判断结论：分层TP/FP/FN/TN、不可判断、证据准确率、高危误升/误降、CI、临床批准阈值
临床金标准：双审/仲裁、留出隔离、未标注/数据不足数量
部署/现场：L1/L2/L3、观察天数、当前批准范围与未验证范围
缺陷：修复/未修/阻塞/待裁定，风险、负责方、恢复第一步
回收：本任务进程、端口、数据/配置复位及环境变量恢复
文件清单：本任务diff、INDEX/01/02登记；Git/生产动作状态
```

恢复先共同启动，重核被测版本、环境数据seed和gold版本；代码/提示词/规则改变则标记受影响结果STALE并重测。用例执行记录不能覆盖旧失败，只追加修复后结果。

## 13. 执行记录（启动后填写）

| 包 | 状态 | 适用/执行/通过/失败/阻塞/跳过 | 版本/证据 | 下一步 |
| --- | --- | --- | --- | --- |
| T0–T12 | NOT_STARTED | 未执行，不填数字或PASS | 本轮仅编制计划；未临床抽检、未真实模型调用 | 取得059整改交付与测试授权后启动 |

本地工程、方言/真实源、临床准确性、现场上线四个结论分别维护；批准单和阈值确认引用具体出处，不能预填已批准。

## 14. 可复制执行提示词

### 14.1 执行改进后的本地完整工程测试

```text
你是前端、后端、系统测试和医疗质控测试专家。请按
docs/ACTIVE/060_POST_IMPROVEMENT_FRONTEND_BACKEND_AND_QC_ACCURACY_TEST_PLAN_20261002.md
执行改进后的详细本地测试，先读059最新整改记录和handoff-060。
本次授权E0/E1隔离合成环境的造数、启动/停止本任务demo和sidecar、单元/集成/浏览器测试、构建、故障注入、必要本地明确缺陷修复与文档登记。
不生产写入/部署、不177或179 FILEVERIFY执行、不真实患者处理、不真实Dify/Relay/外发、不临床裁决、不Git commit/tag/push/PR、不自动多代理。E2/E3/E4如无已有明确授权与条件标BLOCKED并继续本地工作。
完成AGENTS共同启动、任务板认领和既有现场保护，冻结HEAD+dirty hash、REQ/FIX/规则/prompt/SQL版本。
按T0–T12建立逐条执行卡和REQ→FIX→TC映射，执行F01–F20、B01–B24、J01–J09、Q01–Q18及性能安全专项的适用部分；复用现有测试并补风险缺口。
T1先建全量索引再按包渐进冻结卡，不等待79张一次写完；059→060交接严格核A8 v1。T0提前准备E2资源单和临床双审人力/时长/确认人。
两套UI、四角色、三视口必须核真实覆盖；每条关键用例核UI/API/DB/外部Mock的身份、集合、数量、状态和副作用，不以HTTP200或数目>0代替正确性。
重点验证同患者多次、双模式独立锁、局部配置保存、NULL/Oracle空串、未复核/整改抑制、批量事务隔离、预检五态、规则发布/trial、D-J1首读完整、RPA过渡和RPTCOUNT仅对账。
高危既要拦缺源/单侧/跨issue/低置信度/解析失败/warn误升，也要保留合格真实安全冲突；围术期两源可比范围按专属规则处理。
按med-audit-demo-stack编排隔离栈，正式汇总必须med-audit-gates full+锚；补开环境门专项，必测SKIPPED/BLOCKED不能算PASS，禁止降断言/下调锚/扩大豁免。
共享库专项固定workers=1/retries=0，先准备WB种子；保持synthetic→UAT依赖序列，复跑先存证再reset主demo并另seed sidecar。journeys旧结果/合法skip不能当新推送成功，J01/F08另做精确新增行和调用数断言；构建镜像用§10.4原字节hash核对。
发现失败建立缺陷卡，在已授权本地范围修复并重测原用例和受影响链；新版本重锁，旧结果标清适用性。
长任务逐包检查点和批次01登记，结束更新060/INDEX/02，回收自己的进程并恢复环境变量。
最终交付四个独立结论、实际覆盖分母、门禁/专项证据、缺陷与恢复步骤；本地工程通过不能写成模型临床判断准确或生产可上线。
```

### 14.2 工程改进后，启动真实判断准确性影子验证

```text
继续060的T8真实判断准确性专项，先核059整改、060工程结果、当前被测版本与已有批准。
在运行前取得并核对本任务具体批准：院内环境/模型/workflow及两节点版本、脱敏样本范围和数量上限、患者数据使用、成本预算、alert_policy=suppress、零企业微信外发、回滚版本/停止条件、临床双审人员与验收阈值。
落实质控科确认负责人、两位标注者及仲裁者，先小批测每例耗时和争议率，按§7.4估算人时/排期；人员和输入不齐保留金标准BLOCKED。
这段提示词本身不替代缺失批准；先完成独立金标准方案、样本设计、脱敏工具审查和可审查候选结果，必要信息缺失仅阻塞真实调用。
真实样本按类型/科室/时间/高危与数据完整性分层；金标准由临床双审/仲裁，按患者/就诊拆留出，禁止模型输出当标签和人工无扣分当真阴性。
逐样本比较事实提取、转换、后端最终结果、DB/API/UI与告警抑制；计算issue级/就诊级Precision、Recall、F1、混淆矩阵、高危误升/漏检、证据有效率、拒判覆盖与95%置信区间。
为缺源、单侧未提及、一般冲突、合格high、危急omission、围术期两源、跨issue和时间演变保留专属反例；合格high误降也计漏报。
固定版本重复样本观察波动和成本；调提示词后重新锁版本并重新安排独立验证，不挑样本或改标签凑准确率。
达到现行硬门槛和临床确认统计标准才可报告准确性通过；小样本/阳性不足/未仲裁/未批准标准如实列限制。
不写生产历史结果、不真实告警、不自动临床裁决和上线；按060记录证据、01/02交接和后续现场验收恢复第一步。
```

### 14.3 测试断点恢复提示词

```text
继续060。先共同启动，读059交接、060执行记录、01/02及本次exec-log/cases/skip-register/defects。
重核HEAD+dirty hash、规则/prompt/workflow和数据/gold版本；保留其他会话现场，只重跑受版本变化影响或未完成的用例。
按当前授权从首个可执行任务包恢复，BLOCKED/SKIPPED不算通过；执行和修复结果追加保留证据，完成门禁、四层结论和登记。
```

## 15. 2026-10-03外部复核意见评估与修订记录

本轮仅修订计划，T0–T12未执行；79场景及三种提示词保留，文件名编制日期不变、版本升v1.1。

| 意见 | 核证结论与采纳方式 | 证据/修订落点 |
| --- | --- | --- |
| R07 UAT缺单worker/seed | 采纳；同源有状态专项加workers=1/retries=0，WB种子提前，明确脚本无run-id参数且固定demo配置库 | 054§15.3设施-2、perm-session开头注释/源码、seed脚本；§10.2 |
| R08 专项顺序/复位不明确 | 采纳复位与顺序，但更正“顺序正确就证明成功”：synthetic先创建记录；journeys后读旧记录/再推可能skip，其现有弱断言不足证明新推送 | 两spec源码及skip契约；§10.2独立J01/F08精确断言，reset主demo不复位sidecar |
| R09 T1一次冻结79卡太重 | 采纳包级渐进冻结，索引和未展开分母必须全量，执行前仍要求对应卡完整 | §3.3、T1/T2–T9入场、顺序/排期、执行提示词 |
| R10 E2测试库不存在 | 采纳提前资源单；“当前没有可用测试库证据”不能写成“全院没有其他实例”，只读生产核证不顶迁移/故障/压测 | 058现有范围+T0 resource-readiness；§2.3 |
| R11 临床双审缺责任/估算 | 采纳负责人/盲审者/仲裁者、试标、每例时间与人时公式，100–200人时仅为300例示例 | §2.3/§7.4/T0/T8及影子提示词 |
| R12 构建一致性缺具体手段 | 采纳dist/static路径集合+原字节SHA-256和同步机制检查；B18为DB schema须独立验证 | package/sync-static/test-sync-static实现；F03/T4/§10.4 |

补充：117是INDEX有效逻辑编号，已在§2.1改用真实资产链接方便执行；从未要求117前缀文件。BFF/sidecar部署与来源数据/外发开关的分层状态从059交接读取，不能套旧摘要判断。
