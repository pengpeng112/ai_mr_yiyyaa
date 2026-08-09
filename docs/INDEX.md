# Med-Audit 文档索引

> 唯一入口：所有 AI 和开发者开始任务时，先读本文件，再按任务类型读取对应现役文档。
> 最后盘点：2026-08-08（015 完成并热部署；011/P5 仍 FAIL；新增 016 交接：完成项/续做轨 B–E；轨 A 源标注在本地）。带"人工验收"的项目不得视为已上线。

## 使用规则

1. 新任务先读 `AGENTS.md`、本索引和相关现役文档，不要从 `archive/` 开始检索。
2. 新增、重命名、移动、归档或删除任意 `docs/**/*.md` 时，必须在同一变更中更新本索引的编号、状态、路径和本节更新时间。
3. 现役文档使用三位编号；历史材料只放 `archive/`，不能作为当前实现依据。
4. 计划完成后，将结论并入现役文档或参考文档，再移动原计划至 `archive/`；避免新增会话总结或重复执行计划。
5. 文档与代码冲突时以可执行代码、配置和测试为准，并更新文档说明差异。

## 现役文档

| 编号 | 路径 | 状态 | 用途 |
| --- | --- | --- | --- |
| 001 | `ACTIVE/001_PENDING_WORK_EXECUTION_PLAN.md` | 本地复核整改完成，幂等状态须结合 002/INDEX 当前证据复核（2026-08-06） | 全局剩余事项总入口；认证、脱敏、权限、健康、留存、Oracle 超时和 Vastbase 本地加固已回归；具体专项以编号更新的现役文档为准。 |
| 002 | `ACTIVE/002_PUSHLOG_IDEMPOTENCY_DESIGN_GATE.md` | 生产已部署 execution/attempt 表与 claim 接线（2026-07-28）；深度并发压测待完成 | 幂等状态表、原子 claim；已接入 serial/bulk 与历史重跑；Oracle `MED_PUSH_EXECUTION/ATTEMPT` 与唯一索引已落地。 |
| 003 | `ACTIVE/003_PRODUCTION_QC_REMEDIATION_PLAN_20260715.md` | 服务器已升级，等待运行观察，G 仍禁止（2026-07-15） | 镜像 `3ddfa3…` 已部署且容器 healthy；未触发任务/Dify/告警/补跑，生产真基线、临床/DBA/白名单、002 幂等和 G 仍未完成，详见第 13 节。 |
| 004 | `ACTIVE/004_DISCHARGE_FINAL_20260715_RERUN_PLAN.md` | 仅计划，禁止未批准执行（2026-07-16） | 2026-07-15 `discharge_final` 六类定向补跑门禁、触发参数、对账与回滚；依赖应用库 listener 恢复及连接池/锁历史代码部署。 |
| 004 | `ACTIVE/004_ORACLE_RECOVERY_AND_DISCHARGE_RERUN_PLAN_20260716.md` | 待独立复核；仅允许本地 A（2026-07-16） | 修复 Oracle 陈旧连接/监听瞬断后的有限恢复、加锁前失败历史与持久化 spool；2026-07-15 六类 discharge_final 补跑须另行书面批准。 |
| 005 | `ACTIVE/005_DIFY_WORKFLOW_INDEPENDENT_REVIEW_20260716.md` | 确定项已修订，待重新导入影子验证；禁止直接上线（2026-07-16） | 六类 Dify 优化版已补路由失败关闭、jyjc 纯结构校验、转换温度和后端六类 mr_type 映射；生产 output key、来源结构、真实回放和历史 high 路径仍待核。 |
| 006 | `ACTIVE/006_SCHEDULED_DIFY_MULTI_TARGET_CONFIGURATION_PLAN_20260716.md` | 本地开发已完成；禁止未批准生产部署（2026-07-16） | 自动日常/出院与手动推送共用 Dify 节点池；系统配置 UI、策略/熔断持久化、统一 resolver、调度接线与测试已落地。 |
| 007 | `ACTIVE/007_HISTORICAL_MANUAL_RERUN_AND_CURRENT_RESULT_PLAN_20260728.md` | 生产镜像已热更新代码（2026-07-28）；禁止未批准全量补跑 | 历史质控按日期范围持久批次重跑；新结果 success+parse_success 后替代当前结果；默认列表/统计/导出去重；`/api/push/historical-rerun/*` 与推送页模式已落地；Oracle 新表/唯一索引已建；生产业务补跑仍须 preview+书面批准。 |
| 008 | `ACTIVE/008_PROGRESS_NURSING_HISTORICAL_RERUN_AND_LOG_DETAIL_REMEDIATION_PLAN_20260729.md` | 外部复核有条件通过；3 个 P0 待修复（2026-07-29） | 病程护理 1–7 月历史重推与实际 Oracle 文书逐日对账；已补 legacy 空 key/concurrent_changed 防双当前、批次恢复、claim fail-closed、分片 preview、契约校验及日志详情滚动门禁；含修订后的外部 AI 提示词。 |
| 009 | `ACTIVE/009_008_IMPLEMENTATION_INDEPENDENT_REVIEW_AND_REMEDIATION_PLAN_20260729.md` | 生产已部署；复核补丁已合入（2026-07-30） | 契约维度、contract 门禁、preview fail-closed、self-supersede 消除；生产 DDL 已执行；当前结果过滤排除 contract_valid=0。 |
| 010 | `ACTIVE/010_009_HANDOVER_VERIFICATION_GUIDE_20260730.md` | 交接+复核修订（2026-07-30） | 009 交接与生产真实状态；含 6 月 ABORT、H1 断点、核查 SQL/curl、回滚与安全约束。 |
| 011 | `ACTIVE/011_ORACLE_12609_PROGRESS_NURSING_REMEDIATION_PLAN_20260803.md` | 19c 与 P4 补丁已部署；等待正常调度连续观察（2026-08-03） | `progress_vs_nursing` Oracle `ORA-12609` 整改；查询超时、有限重试、连接池退役、调度错误可观测性和镜像一致性已部署，历史补跑仍受门禁约束。 |
| 012 | `ACTIVE/012_PROGRESS_NURSING_DUAL_VIEW_REVIEW_20260804.md` | 双源已生产启用并完成批量修订/首轮全院只读影子；等待 7 业务日与 14 天连续观察（2026-08-09） | 三个 mr_class + caption_date_time、护理双时间和 572/709 固定口径；daily/discharge 批量 target 查询、身份/截断/配置门禁、生产影子证据、回滚点及后续 DBA/连续观察事项。 |
| 013 | `ACTIVE/013_ACTIVE_PLAN_INVENTORY_AND_MANUAL_HANDOVER_20260806.md` | 首轮独立 AI 复核已修订，待人工查看（2026-08-06） | 严格/宽口径计划数量、重复 004、旧状态冲突、当前唯一执行主线、人工与 AI 工作边界、停止条件；本身不授权实施。 |
| 014 | `ACTIVE/014_CROSS_REVIEW_REPORT_20260807.md` | 交叉核查完成，供整合计划使用；不授权生产变更（2026-08-07） | 整合 116 系统级 G1-G11 遗漏项、011 ORA-12609、012 病程护理双源、007/008 历史补跑四轮核查；含 2 个 P0 安全项（JWT 架空/默认管理员后门）、计划与代码不符项、优先级排序与证据索引。 |
| 015 | `ACTIVE/015_CONSOLIDATED_REMEDIATION_EXECUTION_PLAN_20260807.md` | 执行完成并热部署（2026-08-08） | A1–A4/B1–B3/C1 完成；C1 热修为 success-only 唯一索引 + `attach_success_push_log_as_current`；留存 L3 CLOB 修复；详见 016 交接。 |
| 016 | `ACTIVE/016_HANDOVER_AFTER_015_AND_NEXT_TRACKS_20260808.md` | 交接现役（2026-08-08） | 015 后状态事实、对交接提示词复核修正、已完成/未完成分轨（A–E）、011/P5 FAIL 口径、红线与下一任 AI 精简提示词。 |
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
| 患者质控、告警、H5反馈 | 部分完成 | 主链路存在；需补自动化与真实企业微信/前置机验收。 |
| Vastbase 文书接入 | 部分完成 | 客户端、回退、截断和 loader 已实现；未完成生产字段/性能验证与 SQL 过滤加固。 |
| 双模式与终末覆盖 | 部分完成 | 内部框架存在；模板审计类型不一致、日增量锚点和真实 Oracle 验收未完成。 |
| 配置运行总览 | 部分完成 | 只读 resolver/summary 已完成；配置迁移和统一读取未完成。 |
| 多源规则引擎 | 未开始 | 只有设计，没有 engine、API、迁移或 UI。 |
| 2026-07 安全 P0 | 未完成 | 默认管理员、JWT 回退、匿名 SSRF、反馈越权和日志脱敏未关闭。 |
| 前端驾驶舱/表格页 | 部分完成 | 基础页面已落地；浏览器回归和若干工作台收口未完成。 |

## 现役补充文档

| 编号 | 路径 | 状态 | 用途 |
| --- | --- | --- | --- |
| 002 | `CONFIG_REORGANIZATION_PLAN_2026-06.md` | 部分完成 | 运行摘要已实现，配置结构迁移待业务确认。 |
| 003 | `在院出院双模式质控改造实施方案.md` | 部分完成 | 双模式 SQL 口径、终末覆盖与真实数据验收。 |
| 004 | `多数据源扩展与可视化自定义规则质控实施方案.md` | 待执行 | 多数据源与规则引擎的独立大功能。 |
| 005 | `RELAY_SERVER_REQUIREMENTS.md` | 待外部验收 | 前置机反向代理、限流和消息对接要求。 |
| 006 | `系统整体核查与整改计划_20260710.md` | 参考，部分暂缓 | 安全与可靠性风险清单；当前功能计划不自动实施暂缓项。 |
| 007 | `20260624界面设计/浏览器回归复核执行计划.md` | 待执行 | 真实浏览器与响应式人工验收。 |
| 008 | `20260624界面设计/质控结果准确性抽检执行计划.md` | 待业务执行 | Dify 结果临床抽检模板。 |
| 009 | `20260624界面设计/质控问题分析与改进方案.md` | 待业务确认 | 空输出、文本质量和历史记录复核。 |
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
