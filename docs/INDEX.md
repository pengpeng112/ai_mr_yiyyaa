# Med-Audit 文档索引

> 唯一入口：所有 AI 和开发者开始任务时，先读本文件，再按任务类型读取对应现役文档。
> 最后盘点：2026-08-24（docs 顶层旧计划 002/003/005/006 与旧UI设计已归档、004C 移入 ACTIVE、025 按复核结论修订，顶层仅剩 INDEX/README/V2YML；同日建立 `开发起步包/` 统一修改记录制度。此前盘点：2026-08-19（`docs` 下 Dify DSL 已收敛为唯一 `3一致性核查正式版-质控门禁影子V2.yml`：全分支只降不升并执行形式 High Gate，入院分支增加事实/证据闭环、CDB 临床确认和事件去重；旧导出、旧谨慎版、2026-08-17 原版/中间影子均已清理。该文件只供新建影子应用导入，不授权覆盖生产或真实患者推送。025/024 均不授权新的生产写入。024 的当日契约/语义整改与三轮存量降级仍按运营方当日授权有效，后续写入服从 023 §9.1。其余盘点延续 2026-08-13：023 为**唯一系统收口执行入口**；生产 `UI_DEFAULT_ENTRY=legacy`，Stage A/B、Dify/Relay、配置/数据库写入均未授权）。带“人工验收”的项目不得视为已上线。

## 使用规则

1. 新任务先读 `AGENTS.md`、本索引和相关现役文档，不要从 `archive/` 开始检索。
2. 新增、重命名、移动、归档或删除任意 `docs/**/*.md` 时，必须在同一变更中更新本索引的编号、状态、路径和本节更新时间。
3. 现役文档使用三位编号；历史材料只放 `archive/`，不能作为当前实现依据。
4. 计划完成后，将结论并入现役文档或参考文档，再移动原计划至 `archive/`；避免新增会话总结或重复执行计划。
5. 文档与代码冲突时以可执行代码、配置和测试为准，并更新文档说明差异。
6. `ACTIVE/023_SYSTEM_COMPLETION_AND_ONE_SHOT_EXECUTION_PLAN_20260813.md` 是唯一综合执行入口。001–022 仅按 INDEX/023 标注作为证据、交接、契约或专项目录，不得并行启动；未归档不等于已获批执行。
7. 生产配置保存、DDL/DML、真实 Dify/Relay/调度、历史 high/补跑和默认入口切换，必须按 023 §9.1 提供环境、类型、日期/科室、数量、`alert_policy`、接收人、before hash、回滚点和批准单；“全部执行”无效。

## 现役文档

| 编号 | 路径 | 状态 | 用途 |
| --- | --- | --- | --- |
| 001 | `ACTIVE/001_PENDING_WORK_EXECUTION_PLAN.md` | 历史全局清单证据；执行服从 023（2026-08-13） | 认证、脱敏、权限、健康、留存、Oracle 超时、Vastbase、规则引擎和前端遗留事项的早期清单；不再作为独立执行入口。 |
| 002 | `ACTIVE/002_PUSHLOG_IDEMPOTENCY_DESIGN_GATE.md` | 生产已部署 execution/attempt 表与 claim 接线（2026-07-28）；深度并发压测待完成 | 幂等状态表、原子 claim；已接入 serial/bulk 与历史重跑；Oracle `MED_PUSH_EXECUTION/ATTEMPT` 与唯一索引已落地。 |
| 003 | `ACTIVE/003_PRODUCTION_QC_REMEDIATION_PLAN_20260715.md` | 服务器已升级，等待运行观察，G 仍禁止（2026-07-15） | 镜像 `3ddfa3…` 已部署且容器 healthy；未触发任务/Dify/告警/补跑，生产真基线、临床/DBA/白名单、002 幂等和 G 仍未完成，详见第 13 节。 |
| 004A | `ACTIVE/004_DISCHARGE_FINAL_20260715_RERUN_PLAN.md` | 专项证据/目录；禁止并行执行、禁止未批准补跑（2026-07-16） | 2026-07-15 `discharge_final` 六类定向补跑门禁、触发参数、对账与回滚；执行统一服从 023 WP5/WP7 和 §9.1。 |
| 004B | `ACTIVE/004_ORACLE_RECOVERY_AND_DISCHARGE_RERUN_PLAN_20260716.md` | 专项证据/目录；仅可按 023 安排本地 A，禁止生产补跑（2026-07-16） | Oracle 陈旧连接/监听瞬断恢复、加锁前失败历史与 spool；与 004A 不构成并行计划，生产动作统一服从 023。 |
| 005 | `ACTIVE/005_DIFY_WORKFLOW_INDEPENDENT_REVIEW_20260716.md` | 确定项已修订，待重新导入影子验证；禁止直接上线（2026-07-16） | 六类 Dify 优化版已补路由失败关闭、jyjc 纯结构校验、转换温度和后端六类 mr_type 映射；生产 output key、来源结构、真实回放和历史 high 路径仍待核。 |
| 006 | `ACTIVE/006_SCHEDULED_DIFY_MULTI_TARGET_CONFIGURATION_PLAN_20260716.md` | 本地开发已完成；禁止未批准生产部署（2026-07-16） | 自动日常/出院与手动推送共用 Dify 节点池；系统配置 UI、策略/熔断持久化、统一 resolver、调度接线与测试已落地。 |
| 007 | `ACTIVE/007_HISTORICAL_MANUAL_RERUN_AND_CURRENT_RESULT_PLAN_20260728.md` | 生产镜像已热更新代码（2026-07-28）；禁止未批准全量补跑 | 历史质控按日期范围持久批次重跑；新结果 success+parse_success 后替代当前结果；默认列表/统计/导出去重；`/api/push/historical-rerun/*` 与推送页模式已落地；Oracle 新表/唯一索引已建；生产业务补跑仍须 preview+书面批准。 |
| 008 | `ACTIVE/008_PROGRESS_NURSING_HISTORICAL_RERUN_AND_LOG_DETAIL_REMEDIATION_PLAN_20260729.md` | 外部复核有条件通过；3 个 P0 待修复（2026-07-29） | 病程护理 1–7 月历史重推与实际 Oracle 文书逐日对账；已补 legacy 空 key/concurrent_changed 防双当前、批次恢复、claim fail-closed、分片 preview、契约校验及日志详情滚动门禁；含修订后的外部 AI 提示词。 |
| 009 | `ACTIVE/009_008_IMPLEMENTATION_INDEPENDENT_REVIEW_AND_REMEDIATION_PLAN_20260729.md` | 生产已部署；复核补丁已合入（2026-07-30） | 契约维度、contract 门禁、preview fail-closed、self-supersede 消除；生产 DDL 已执行；当前结果过滤排除 contract_valid=0。 |
| 010 | `ACTIVE/010_009_HANDOVER_VERIFICATION_GUIDE_20260730.md` | 交接+复核修订（2026-07-30） | 009 交接与生产真实状态；含 6 月 ABORT、H1 断点、核查 SQL/curl、回滚与安全约束。 |
| 011 | `ACTIVE/011_ORACLE_12609_PROGRESS_NURSING_REMEDIATION_PLAN_20260803.md` | 19c 与 P4 补丁已部署；等待正常调度连续观察（2026-08-03） | `progress_vs_nursing` Oracle `ORA-12609` 整改；查询超时、有限重试、连接池退役、调度错误可观测性和镜像一致性已部署，历史补跑仍受门禁约束。 |
| 012 | `ACTIVE/012_PROGRESS_NURSING_DUAL_VIEW_REVIEW_20260804.md` | 双源已生产启用并完成批量修订/首轮全院只读影子；等待 7 业务日与 14 天连续观察（2026-08-09） | 三个 mr_class + caption_date_time、护理双时间和 572/709 固定口径；daily/discharge 批量 target 查询、身份/截断/配置门禁、生产影子证据、回滚点及后续 DBA/连续观察事项。 |
| 013 | `ACTIVE/013_ACTIVE_PLAN_INVENTORY_AND_MANUAL_HANDOVER_20260806.md` | 交接/盘点证据；执行服从 023（2026-08-13） | 严格/宽口径计划数量、重复 004、旧状态冲突、人工与 AI 工作边界和停止条件；本身不授权实施，也不再维护独立执行主线。 |
| 014 | `ACTIVE/014_CROSS_REVIEW_REPORT_20260807.md` | 交叉核查完成，供整合计划使用；不授权生产变更（2026-08-07） | 整合 116 系统级 G1-G11 遗漏项、011 ORA-12609、012 病程护理双源、007/008 历史补跑四轮核查；含 2 个 P0 安全项（JWT 架空/默认管理员后门）、计划与代码不符项、优先级排序与证据索引。 |
| 015 | `ACTIVE/015_CONSOLIDATED_REMEDIATION_EXECUTION_PLAN_20260807.md` | 执行完成并热部署（2026-08-08） | A1–A4/B1–B3/C1 完成；C1 热修为 success-only 唯一索引 + `attach_success_push_log_as_current`；留存 L3 CLOB 修复；详见 016 交接。 |
| 016 | `ACTIVE/016_HANDOVER_AFTER_015_AND_NEXT_TRACKS_20260808.md` | 交接现役（2026-08-08） | 015 后状态事实、对交接提示词复核修正、已完成/未完成分轨（A–E）、011/P5 FAIL 口径、红线与下一任 AI 精简提示词。 |
| 017 | `ACTIVE/017_FRONTEND_ARCHITECTURE_MENU_LAYOUT_REMEDIATION_PLAN_20260809.md` | WP0–WP5 本地完成；`UI_DEFAULT_ENTRY` 本地已实现；WP6/WP7 未完成（2026-08-11） | 前端菜单信息架构、Vue 3/Vite/TypeScript 模块化 App Shell、路由/RBAC 契约、默认入口开关、离线构建与 canary/回滚作业书；不授权阶段 A/B 生产写操作直至书面批准。 |
| 018 | `ACTIVE/018_HANDOVER_AFTER_017_FRONTEND_LOCAL_WP0_WP5_20260810.md` | 交接现役（2026-08-10） | 017 完成度裁定：WP0–WP5 本地已完成项、未完成/质量债、红线、验证命令、WP6 前置与下一任提示词；不授权生产变更。 |
| 019 | `ACTIVE/019_LEGACY_TO_UI_NEXT_FUNCTION_AND_FIGMA_PLAN_20260811.md` | 本地功能迁移与 P1 收口完成；患者导出=当前筛选全部结果；Figma 正式画布用户取消；待 WP6 canary（2026-08-11） | legacy → UI Next 完整矩阵、本地设计与实施结果；医院品牌、核心 P0 页面、患者筛选导出、跨页钻取、任务聚合、独立详情入口和键盘无障碍已本地完成；Figma 正式画布用户取消、不再实施（fileKey/design 资产保留）；未生产部署、未真实调用 Dify/推送/调度/Relay。 |
| 020 | `ACTIVE/020_WP6_CANARY_ACCEPTANCE_BLOCKED_REPORT_20260811.md` | **BLOCKED 证据；执行服从 023**（缺四角色/Relay 批准包；2026-08-13） | WP6 矩阵与 Relay 实发门禁；本地 patient-qc 权限补丁未进当前生产镜像 digest 验收结论；不授权 canary 或 Stage B。 |
| 021 | `ACTIVE/021_UI_NEXT_WORKBENCH_PAYLOAD_PATIENTQC_REVIEW_PACKAGE_20260811.md` | **复核证据/专项目录；执行服从 023**（2026-08-13） | UI Next 工作台 ECharts/缓存、质控记录报文、患者质控布局的复核清单；不授权 Stage B、真实 Dify/Relay 或生产写入。 |
| 022 | `ACTIVE/022_ISOLATED_12_DEPARTMENT_INTERACTIVE_DEMO_PLAN_20260813.md` | **从属演示专项；本地交付完成，未部署生产；执行服从 023**（2026-08-13） | 12 科室独立 SQLite、合成数据、Mock Dify/Relay 和 smoke/showcase 证据；仅在 023 明确安排并满足 022 Gate 时执行，不与 023 并行改变生产。 |
| 023 | `ACTIVE/023_SYSTEM_COMPLETION_AND_ONE_SHOT_EXECUTION_PLAN_20260813.md` | **唯一执行入口；本地整改/测试与生产 Stage 0 只读已完成；等待历史候选范围/脱敏规则复核；不授权生产写入**（2026-08-13） | 当前系统未完成功能、P0/P1/P2 完善项、Codex/Luna 实施结果、自动化证据、生产聚合基线和下一阶段精确审批清单；所有其他 ACTIVE 文档均不得并行执行。 |
| 024 | `ACTIVE/024_HIGH_RISK_SEVERITY_REMEDIATION_HANDOVER_20260817.md` | 交接；当日生产写入已获运营方授权；旧 YML 已由唯一门禁影子版替代（2026-08-19） | 契约校验器"只降不升"修复、text_quality 硬门槛黑名单、语义降级配置开关、三轮存量降级 1,356 条假高危；旧 YML 的历史结构与哈希保留在文档，当前导入资产统一为质控门禁影子 V2。 |
| 025 | `ACTIVE/025_SPLIT_QC_AND_121_EXCEL_INDEPENDENT_REVIEW_HANDOVER_20260817.md` | 交接+待临床影子验证；不授权生产写入；2026-08-24 按复核结论修订（口径钉死/日期上界/Excel暂缺注记，见文内§11修订记录） | 对 024 与 121 人高危导出表的只读独立复核；CDB/事实结构层分析已落实到唯一质控门禁影子 V2，仍需脱敏样本与临床双审。 |
| 026 | `ACTIVE/026_PAPERLESS_MANUAL_QC_TO_AI_FEASIBILITY_20260827.md` | 可行性分析；不授权生产写入/不改 Dify/无纸化/JHEMR（2026-08-27） | 无纸化人工终末质控（t_mark_*，7.3万份/385万明细/8200条扣分说明）纳入 AI 质控路径：A类确定性规则代码化、B类并入六类语义质控、C类提示级；提交时提醒三方案（推荐准实时轮询）；人工结果作金标准回流；P0-P4 分阶段建议。 |
| 027 | `ACTIVE/027_JHEMR_SUBMISSION_REMINDER_INTEGRATION_20260827.md` | 可行性分析；不授权生产写入/不改JHEMR/不部署客户端补丁（2026-08-27） | JHEMR提交病历时质控提醒对接五路径评估（基于嘉和逆向工作区证据）：R1库轮询+企微推送推荐首选（读库链路已验证，2周可上线）；R2复用CDSS jssdk通道（UX最优，需院内协调）；R3客户端IL补丁技术可行但运维风险高仅限试点；R4/R5服务端/厂商路径；P0-P4分阶段建议。 |
| 117 | `reference/wp0_frontend_baseline_fixtures/README.md` | 参考 | 017 WP0 基线：17 页矩阵、角色菜单、vendor 体积、Node 决策与脱敏 API fixture。 |
| 118 | `remediation/MOCK-20260813_需要修改回去的说明.md` | 参考（待回退清单，2026-08-24 由根目录移入） | 演示 MOCK 热更的回退说明（主管医师姓名/前端写死数据）；代码内 13 处引用已同步指向新路径。 |
| 101 | `reference/101_FEATURE_BASELINE.md` | 参考 | 已完成能力和不可回退基线。 |
| 102 | `reference/102_DATA_AND_DIFY_CONTRACTS.md` | 参考 | 数据源字段、维度、Dify 输入输出和 extra_json 契约。 |
| 103 | `reference/103_RELAY_AND_MOBILE_CONTRACT.md` | 参考 | 中继、H5、token、反馈和当前路由约定。 |
| 104 | `reference/104_PORT_AND_ROUTE_MAPPING.md` | 需人工更新 | 网络端口与代理映射；部署变化后必须复核。 |
| 105 | `skills/med-audit-codex.md` | 参考 | 推送、日志、调度、反馈的防回归约束。 |
| 106 | `skills/med-audit-refactor-workflow.md` | 参考 | 持续改造的检索、实施和回归流程。 |
| 107 | `../prompts/v2_consistency_audit.md` | 参考，待 Dify 复核 | 旧病程/护理工作流的人工维护 Prompt 资产。 |
| 108 | `../prompts/v2_json_output_schema.md` | 参考，待 Dify 复核 | 旧病程/护理工作流的 JSON 输出 Prompt 资产。 |
| 109 | `reference/109_DIFY_PROMPT_FINAL_IMPLEMENTATION_PLAN.md` | 后端已实施，待 Dify 灰度（2026-07-13） | 六类 Dify 提示词统一实施入口；后端已执行统一高危硬门槛，提示词待人工更新、回放和临床抽检。 |
| 110 | `reference/110_DIFY_PROMPT_ADMISSION_VS_FIRST_PROGRESS.md` | 待 Dify 影子验证 | 入院记录 vs 首次病程两节点完整提示词。 |
| 111 | `reference/111_DIFY_PROMPT_DISCHARGE_VS_FIRST_PROGRESS.md` | 待 Dify 影子验证 | 首次病程 vs 出院记录两节点完整提示词；保持生产现有 code `discharge_vs_frontpage`，不做重命名。 |
| 112 | `reference/112_DIFY_PROMPT_SURGERY_CHAIN.md` | 待三来源 payload/config 验证 | 围手术期两节点完整提示词，明确术前/手术/术后三类真实 source。 |
| 113 | `reference/113_DIFY_PROMPT_PROGRESS_VS_NURSING.md` | 待 Dify 影子验证 | 病程 vs 护理两节点完整提示词；保持固定 6 维度和 legacy 落库兼容。 |
| 114 | `reference/114_DIFY_PROMPT_JYJC_VS_BCNURSING.md` | 待危急规则确认与影子验证 | 检验检查 vs 病程/护理两节点完整提示词；危急未响应高危依赖本院规则和完整时间窗。 |
| 115 | `reference/115_DIFY_PROMPT_SYSSVSSCBC.md` | 待 Dify 影子验证 | 首页手术 vs 术后首次病程两节点完整提示词；保持当前 code 和固定 4 维度。 |
| 116 | `reference/116_SYSTEM_FUNCTION_UI_PUSH_REVIEW_20260714.md` | 二次独立复核完成，待确认整改范围（2026-07-14） | 当前系统功能、界面、Dify 推送、调度、告警、安全与生产运行状态的独立复核报告、外部复核裁定、整改优先级及实施 AI 提示词。 |

## 已核验的功能状态

| 主题 | 状态 | 结论 |
| --- | --- | --- |
| 患者质控、告警、H5反馈 | 部分完成 | 主链路、细粒度 feedback permission 和失败响应隐私收口已完成；真实四角色、企业微信/前置机验收未完成。 |
| Vastbase 文书接入 | 部分完成 | 客户端、双源 loader、回退、截断和批量查询已实现并有生产单轮证据；DBA 执行计划、历史键例外、7 业务日/14 天性能稳定性未关闭。 |
| 双模式与终末覆盖 | 部分完成 | 双源已生产启用并有单轮对账；本地正式六类安全模板已闭包；生产 discharge 仍配置 3 个无转换类型，`syssvsscbc` 日增量锚点、六类真实 SQL 和连续观察未完成。 |
| 配置运行总览 | 部分完成 | 只读 resolver/summary 已完成；配置迁移和统一读取未完成。 |
| 多源规则引擎 | 未开始 | 只有设计，没有 engine、API、迁移或 UI。 |
| 安全与权限 | 本地整改完成，现场未验 | JWT、运行时默认管理员、通知 SSRF、Dify/Relay/Push 日志脱敏、QCFeedback permission、demo fail-closed 和匿名 health 已修；真实四角色验收仍开放。 |
| 前端驾驶舱/表格页 | 本地自动化通过；WP6 现场仍阻塞 | legacy `/` 仍默认。最新 Playwright 46 passed / 0 failed / 11 expected skipped；`static/ui-next` 已安全镜像为 110 个当前 asset；020 仍缺 canary 地址/四角色凭据/测试科室/脱敏长数据。 |

## 现役补充文档

| 编号 | 路径 | 状态 | 用途 |
| --- | --- | --- | --- |
| 002 | `archive/plans-202606-202607/CONFIG_REORGANIZATION_PLAN_2026-06.md` | 已归档（2026-08-24）；已实现部分见代码与 101 | 运行摘要已实现，配置结构迁移待业务确认。 |
| 003 | `archive/plans-202606-202607/在院出院双模式质控改造实施方案.md` | 已归档（2026-08-24）；双模式已上生产，契约见 101/AGENTS | 双模式 SQL 口径、终末覆盖与真实数据验收。 |
| 004C | `ACTIVE/多数据源扩展与可视化自定义规则质控实施方案.md` | 待执行；执行服从 023 WP8（2026-08-24 移入 ACTIVE） | 多数据源与规则引擎的独立大功能；与 ACTIVE 004A/004B 不同文件，采用 004C 避免索引编号歧义。 |
| 005 | `archive/plans-202606-202607/RELAY_SERVER_REQUIREMENTS.md` | 已归档（2026-08-24）；Relay 已上线，现役契约见 103 | 前置机反向代理、限流和消息对接要求。 |
| 006 | `archive/plans-202606-202607/系统整体核查与整改计划_20260710.md` | 已归档（2026-08-24）；被 014/023 取代 | 安全与可靠性风险清单；当前功能计划不自动实施暂缓项。 |
| 007 | `archive/2026-06-ui/20260624/浏览器回归复核执行计划.md` | 已归档（2026-08-24）；对象为旧版 UI，已被 UI Next 取代 | 真实浏览器与响应式人工验收。 |
| 008 | `archive/2026-06-ui/20260624/质控结果准确性抽检执行计划.md` | 已归档（2026-08-24）；临床抽检模板仍可参考 | Dify 结果临床抽检模板。 |
| 009 | `archive/2026-06-ui/20260624/质控问题分析与改进方案.md` | 已归档（2026-08-24） | 空输出、文本质量和历史记录复核。 |
| 900 | `../ARCHITECTURE.md` | 现役 | 当前架构、模块和数据流。 |
| 901 | `../README_CN.md` | 现役 | 项目入口与常用命令。 |
| 902 | `../DEPLOY.md` | 现役 | Docker 部署、升级和回滚。 |
| 903 | `../CODE_STYLE.md` | 现役 | 代码风格与文件组织。 |
| 904 | `../AGENTS.md` | 现役 | AI 启动规则、文档索引更新要求与开发约束。 |
| 905 | `../CLAUDE.md` | 参考，待校正 | 深层模块地图；与代码冲突时以代码和 DOC-001 为准。 |
| 906 | `../static/templates/README.md` | 现役，待更新 | 静态模板异步加载约定与页面清单。 |

## 归档清单

下列源文件均已逐份阅读并按最终用途归档；文件名保留以便审计追溯。

| 分类 | 归档目录 | 包含内容 |
| --- | --- | --- |
| 2026-04 至 2026-06 核心方案 | `archive/2026-04-06/` | 已完成/被替代的 Vastbase、Relay/H5、菜单、旧架构、旧前端和多审计类型方案。 |
| 2026-06-11 界面设计 | `archive/2026-06-ui/20260611/` | 菜单、患者、告警、反馈、审计类型、调度、配置、推送进度等逐页方案与提示词。 |
| 2026-06-24 界面设计 | `archive/2026-06-ui/20260624/` | 驾驶舱 V2、登录页、逐页优化和历史测试报告。 |
| 2026-07 Dify 提示词修订 | `archive/2026-07-dify-prompts/` | 被最终 109–115 替代的旧 109–112 复核包、方案稿及五份原始 `.txt` 提示词。 |

## 本次归档判定

- 已完成或被后续版本替代：页面 V2 设计、早期 UI 执行提示词、旧 relay 端口方案、2026-04/06 阶段记录。
- 保留为参考：功能基线、数据契约、当前中继协议、端口映射和两份防回归 skill。
- 合并后的待办：安全、可靠性、双模式、H5、Vastbase、规则引擎、准确性抽检、前端遗留项，统一写入 `ACTIVE/001_PENDING_WORK_EXECUTION_PLAN.md`。
