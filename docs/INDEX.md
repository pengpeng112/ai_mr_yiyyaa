# Med-Audit 文档索引

> **唯一文档台账**：会话启动顺序与授权红线以 [AGENTS.md](../AGENTS.md) 为准。
> **当前导航更新时间**：2026-11-21（完成全仓目录治理与启动体系重构：① `docs/ACTIVE/` 瘦身至 9 份现役文档，54 份已完结历史计划/报告按 4 阶段原字节归档至 `docs/archive/` 并生成 SHA-256 manifest；② 新增 [124 系统历史升级演进总览](reference/124_SYSTEM_EVOLUTION_HISTORY.md)；③ 封卷 `01_统一修改记录.md` 2026-06~10 历史行并瘦身 `02_协作任务板.md`；④ `023` 降格为第一代历史总入口，现行主力为 `064`（WP-01~WP-07 本地交付待走查，WP-08~WP-10 待推进）与 `063` 独立总交接。历次早期首页盘点快照见 [索引历史快照](archive/navigation-20260925/INDEX_STATUS_HISTORY.md)）。

## 使用规则

1. 新任务先按 `AGENTS.md` 完成 4 步启动，再通过本索引定位现役文档与契约，不要从 `archive/` 开始检索。
2. 新增、重命名、移动、归档或删除任意 `docs/**/*.md` 时，**同一变更内**必须同步更新本索引并运行 `python scripts/check_documentation_20261002.py`。
3. 现役文档采用三位连续编号；`archive/` 原字节保留历史升级过程，仅供追溯，不作现行实现依据或授权来源。
4. 文档与可执行代码冲突时以当前代码、配置模板及测试为准，并同步更新文档说明。
5. 现行主线以本索引「按用途查找」表中标注的现役文档（`064`、`063`、`062`、`056`）为准；原 `023` 为第一代系统收口历史总入口（2026-08~10 封存），不再阻塞新计划推进。
6. 生产批量推送、历史 high 降级/补跑、生产 DDL/DML 与全院默认入口切换等高冲击操作，按 `00_AI协作规则.md` §4 与 `023` §9.1 履行完整审批要素与回滚点；其余变更按 `AGENTS.md` §2 执行。

## 按用途查找

| 用途 | 入口 | 判读方法 |
| :--- | :--- | :--- |
| **全栈性能优化、业务重构与 UI/UX 全面升级（当前主力）** | [064 全栈整改总计划](ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md) | 2026-11-21 更新：**WP-01~WP-09 本地交付完成（--full 门禁全绿、锚比较不低于锚），待 WP-10 生产发布分步审批**；v1.1 定稿（D1–D6 拍板）；每包先读 `开发起步包/prompts-064/PROMPT-00` |
| **独立工作区总交接与 JHEMR 接口地图（新会话首选）** | [063 总交接与 JHEMR 接口地图](ACTIVE/063_PROJECT_HANDOVER_AND_JHEMR_INTEGRATION_MAP_20261119.md) | 生产镜像 `9807a3e4c98f`、全院 2,383 用户/640 科室、177 锁定 9 开关与七大对接轨道全景；仅作交接事实，不构成授权 |
| **系统历史升级需求与架构演进总览** | [124 系统历史升级演进总览](reference/124_SYSTEM_EVOLUTION_HISTORY.md) | 2026-04 ~ 2026-11 六阶段编年史与历史资产索引；快速了解系统如何演进至当前形态 |
| **病历时效质控上线收尾与危急值契约** | [062 时效执行指针](ACTIVE/062_TIMELINESS_QC_EXECUTION_POINTER_20261110.md)、[121 危急值契约](reference/121_CRITICAL_VALUE_WEBHOOK_AND_JHEMR_INTEGRATION_CONTRACT_20261114.md)、[122 企微代理规范](reference/122_MOBILE_TIMELINESS_WECOM_PROXY_ONBOARDING_20261117.md) | 线上影子运行且写闸全关；D8（`CHIEF_FIRST_ROUND` 禁锁）有效；企微联调见 `开发起步包/PROMPT-20261117_*` |
| **归档前形式预检影子激活与 FILEVERIFY 177** | [123 预检影子激活 Runbook](reference/123_PREARCHIVE_SHADOW_AND_PAPERLESS_PUSH_RUNBOOK_20261119.md)、[056 FILEVERIFY 交接](ACTIVE/056_JHEMR_FILEVERIFY_TARGET_DB_CORRECTION_HANDOVER_20260924.md) | 123 为 WP-10 预检影子上线操作手册；056 §6 为 177 v4 候选包（旧 179 路径永久冻结） |
| **多 AI 启动、代码定位与协作方法** | [启动卡](../开发起步包/README.md)、[任务板](../开发起步包/02_协作任务板.md)、[119 协作指南](reference/119_MULTI_AI_COLLABORATION_GUIDE.md)、[120 目录索引](reference/120_REPO_DIRECTORY_INDEX_20261012.md) | 任务板管当前会话分工，01 管修改事实，120 管代码位置，本 INDEX 管文档状态 |
| **功能基线、数据/Dify 契约与门禁锚** | [101 功能基线](reference/101_FEATURE_BASELINE.md)、[102 数据与 Dify 契约](reference/102_DATA_AND_DIFY_CONTRACTS.md)、[103 中继契约](reference/103_RELAY_AND_MOBILE_CONTRACT.md)、[med-audit-codex](skills/med-audit-codex.md)、109–115 | 门禁锚唯一机器源为 `reference/gate_anchors.json`；正式门禁见 `.agents/skills/med-audit-gates/SKILL.md` |
| **高危降噪红线、历史整改与人工待裁定项** | [024 高危整改交接](ACTIVE/024_HIGH_RISK_SEVERITY_REMEDIATION_HANDOVER_20260817.md)、[025 121 复核](ACTIVE/025_SPLIT_QC_AND_121_EXCEL_INDEPENDENT_REVIEW_HANDOVER_20260817.md)、[061 未闭环复核清单](ACTIVE/061_CURRENT_MD_MANUAL_REVIEW_AND_UNFINISHED_WORK_20261006.md) | 保留历史高危不授权清单与临床边界；专项整改遵循 `.agents/skills/med-audit-history-remediation` |
| **架构、部署、风格与归档地图** | [ARCHITECTURE](../ARCHITECTURE.md)、[DEPLOY](../DEPLOY.md)、[CODE_STYLE](../CODE_STYLE.md)、[归档总说明](archive/README.md) | 根目录说明登记为 `900`–`906`；已完成历史计划分阶段原字节封存于 `archive/` |

## 现役计划、交接与参考资料

| 编号 | 路径 | 状态 | 用途 |
| --- | --- | --- | --- |
| 064 | `ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md` | **现役主力（WP-01~WP-09 本地完成，待 WP-10 生产发布审批）** | 全栈性能优化、业务重构与 UI/UX 全面升级总计划（D1–D6 拍板 + 16 项勘误），配套 `开发起步包/prompts-064/`。 |
| 063 | `ACTIVE/063_PROJECT_HANDOVER_AND_JHEMR_INTEGRATION_MAP_20261119.md` | **现役总交接（新会话首选）** | 独立工作区总交接与 JHEMR/HIS 七大对接轨道全景地图、生产快照（镜像 `9807a3e4c98f`）与待办路线图。 |
| 062 | `ACTIVE/062_TIMELINESS_QC_EXECUTION_POINTER_20261110.md` | 现役（生产影子运行中，写回/上线收尾待批） | 病历时效质控专项执行指针，区分本地实现与生产验收顺序，D8 禁锁保留。 |
| 061 | `ACTIVE/061_CURRENT_MD_MANUAL_REVIEW_AND_UNFINISHED_WORK_20261006.md` | 现役参考（2026-10-08 本地补修完成，少量人工项保留） | 历史非归档 Markdown 复核与未关闭人工裁定清单（AUD-A4、通知策略、现场验收等，见 §十）。 |
| 056 | `ACTIVE/056_JHEMR_FILEVERIFY_TARGET_DB_CORRECTION_HANDOVER_20260924.md` | 现役（待 177 写入批准） | 177 Vastbase EMR 主库勘误与 `FILEVERIFY` v4 候选包交接（旧 179 Oracle 路径永久冻结）。 |
| 025 | `ACTIVE/025_SPLIT_QC_AND_121_EXCEL_INDEPENDENT_REVIEW_HANDOVER_20260817.md` | 现役红线交接（待临床双审） | 121 人高危导出独立复核与 CDB/事实结构层临床口径边界，不授权生产写入。 |
| 024 | `ACTIVE/024_HIGH_RISK_SEVERITY_REMEDIATION_HANDOVER_20260817.md` | 现役红线交接 | 契约校验器“只降不升”、硬门槛黑名单、三轮存量降级 1,356 条实录及不授权红线。 |
| 023 | `ACTIVE/023_SYSTEM_COMPLETION_AND_ONE_SHOT_EXECUTION_PLAN_20260813.md` | **第一代总入口·历史封存**（保留原位以兼容 `023 §9.1` 审批参考与历史治理测试） | 2026-08~10 第一代系统收口主线；现行开发以 `064`/`063` 为准，不再要求新计划回写 `§0.6`。 |
| 004C | `ACTIVE/多数据源扩展与可视化自定义规则质控实施方案.md` | 暂缓立项 | 主服务侧多数据源自定义规则引擎方案（独立于 `prearchive_service` 预检规则中心）。 |
| 101 | `reference/101_FEATURE_BASELINE.md` | 现役基线 | 已完成能力与不可回退基线；当前门禁锚数字以 `reference/gate_anchors.json` 为唯一机器源（043 指针）。 |
| 102 | `reference/102_DATA_AND_DIFY_CONTRACTS.md` | 现役契约 | 数据源字段、维度、Dify 输入输出与 `extra_json` 契约。 |
| 103 | `reference/103_RELAY_AND_MOBILE_CONTRACT.md` | 现役契约 | 告警中继、H5、token、反馈与路由约定。 |
| 104 | `reference/104_PORT_AND_ROUTE_MAPPING.md` | 现役参考（部署变动后复核） | 网络端口与代理映射说明。 |
| 105 | `skills/med-audit-codex.md` | 现役防回归卡 | 推送、日志、调度、Oracle、Dify 与 prearchive 不可回退约束参考。 |
| 107 | `../prompts/v2_consistency_audit.md` | 参考，待 Dify 复核 | 旧病程/护理工作流人工维护 Prompt 资产。 |
| 108 | `../prompts/v2_json_output_schema.md` | 参考，待 Dify 复核 | 旧病程/护理工作流 JSON 输出结构 Prompt 资产。 |
| 109 | `reference/109_DIFY_PROMPT_FINAL_IMPLEMENTATION_PLAN.md` | 现役（后端已落地，待 Dify 灰度） | 六类 Dify 提示词统一实施入口与高危硬门槛口径。 |
| 110 | `reference/110_DIFY_PROMPT_ADMISSION_VS_FIRST_PROGRESS.md` | 现役提示词契约 | 入院记录 vs 首次病程两节点完整提示词。 |
| 111 | `reference/111_DIFY_PROMPT_DISCHARGE_VS_FIRST_PROGRESS.md` | 现役提示词契约 | 首次病程 vs 出院记录两节点完整提示词（保持生产 code `discharge_vs_frontpage`）。 |
| 112 | `reference/112_DIFY_PROMPT_SURGERY_CHAIN.md` | 现役提示词契约 | 围手术期三源两节点完整提示词。 |
| 113 | `reference/113_DIFY_PROMPT_PROGRESS_VS_NURSING.md` | 现役提示词契约 | 病程 vs 护理两节点完整提示词（固定 6 维度）。 |
| 114 | `reference/114_DIFY_PROMPT_JYJC_VS_BCNURSING.md` | 现役提示词契约 | 检验检查 vs 病程/护理两节点完整提示词。 |
| 115 | `reference/115_DIFY_PROMPT_SYSSVSSCBC.md` | 现役提示词契约 | 首页手术 vs 术后首次病程两节点完整提示词（固定 4 维度）。 |
| 116 | `reference/116_SYSTEM_FUNCTION_UI_PUSH_REVIEW_20260714.md` | 历史参考 | 2026-07 系统功能、UI、推送与安全独立复核基线报告。 |
| 117 | `reference/wp0_frontend_baseline_fixtures/README.md` | 现役基线夹具 | UI-Next WP0 基线矩阵、角色菜单与脱敏 API fixture。 |
| 118 | `remediation/MOCK-20260813_需要修改回去的说明.md` | 现役参考（代码 13 处引用） | 历史演示 MOCK 热更回退说明清单。 |
| 119 | `reference/119_MULTI_AI_COLLABORATION_GUIDE.md` | 现役指南 | 多工具/多模型协同开发、交接模板、归档与文档维护规范。 |
| 120 | `reference/120_REPO_DIRECTORY_INDEX_20261012.md` | 现役索引（2026-11-21 附注） | 仓库代码目录、路由/服务分组与前端/预检边界速查。 |
| 121 | `reference/121_CRITICAL_VALUE_WEBHOOK_AND_JHEMR_INTEGRATION_CONTRACT_20261114.md` | 现役契约（待厂商联调） | 危急值 Webhook 接数 + 6h 时效接线 + 177 `jhcdr`/`jhcriticalvalues_msg` 双路临床引用契约。 |
| 122 | `reference/122_MOBILE_TIMELINESS_WECOM_PROXY_ONBOARDING_20261117.md` | 现役契约 | 企微手机端 H5 外网前置机代理、OAuth 直签发与 5 前缀最小暴露面规范。 |
| 123 | `reference/123_PREARCHIVE_SHADOW_AND_PAPERLESS_PUSH_RUNBOOK_20261119.md` | 现役操作手册 | 归档前核查影子激活 6 步、CDMS 金标准回测与无纸化推送对接 Runbook（WP-10 审批执行）。 |
| 124 | `reference/124_SYSTEM_EVOLUTION_HISTORY.md` | 现役编年史（2026-11-21 新建） | 系统 2026-04 ~ 2026-11 六大升级阶段需求脉络与历史资产总图。 |

## 已归档专项计划与阶段报告

> 全部原文逐字节保留，SHA-256 映射与承接关系由各目录 `archive-manifest.json`（及 `checksums.sha256.json`）记录并经 `check_documentation_20261002.py` 自动校验。历史文档仅用于追溯，不构成当前待办或授权。

| 编号 | 路径 | 状态 | 阶段与承接摘要 |
| --- | --- | --- | --- |
| 001 | `archive/completed-plans-phase1-202607-202608/001_PENDING_WORK_EXECUTION_PLAN.md` | 已归档（2026-11-21） | Phase 1 早期全局遗留清单；承接 `124` / `101`。 |
| 002 | `archive/completed-plans-phase1-202607-202608/002_PUSHLOG_IDEMPOTENCY_DESIGN_GATE.md` | 已归档（2026-11-21） | Phase 1 PushLog 幂等表与原子 claim（已生产落地）。 |
| 003 | `archive/completed-plans-phase1-202607-202608/003_PRODUCTION_QC_REMEDIATION_PLAN_20260715.md` | 已归档（2026-11-21） | Phase 1 2026-07 生产质控整改计划。 |
| 004A | `archive/phase1-legacy-004-and-snapshot-202607-202608/004_DISCHARGE_FINAL_20260715_RERUN_PLAN.md` | 已归档（2026-11-21） | Phase 1 07-15 出院定向补跑窗口（已关闭）。 |
| 004B | `archive/phase1-legacy-004-and-snapshot-202607-202608/004_ORACLE_RECOVERY_AND_DISCHARGE_RERUN_PLAN_20260716.md` | 已归档（2026-11-21） | Phase 1 07-16 Oracle 连接恢复方案（已闭环）。 |
| 005 | `archive/completed-plans-phase1-202607-202608/005_DIFY_WORKFLOW_INDEPENDENT_REVIEW_20260716.md` | 已归档（2026-11-21） | Phase 1 Dify 六类工作流独立复核（已被影子 V2 替代）。 |
| 006 | `archive/completed-plans-phase1-202607-202608/006_SCHEDULED_DIFY_MULTI_TARGET_CONFIGURATION_PLAN_20260716.md` | 已归档（2026-11-21） | Phase 1 调度多 Dify 节点池配置方案（已实现）。 |
| 007 | `archive/completed-plans-phase1-202607-202608/007_HISTORICAL_MANUAL_RERUN_AND_CURRENT_RESULT_PLAN_20260728.md` | 已归档（2026-11-21） | Phase 1 历史批次重跑与当前结果替代方案（已上线）。 |
| 008 | `archive/completed-plans-phase1-202607-202608/008_PROGRESS_NURSING_HISTORICAL_RERUN_AND_LOG_DETAIL_REMEDIATION_PLAN_20260729.md` | 已归档（2026-11-21） | Phase 1 病程护理历史重推与详情整改方案。 |
| 009 | `archive/completed-plans-phase1-202607-202608/009_008_IMPLEMENTATION_INDEPENDENT_REVIEW_AND_REMEDIATION_PLAN_20260729.md` | 已归档（2026-11-21） | Phase 1 008 复核补丁与契约门禁落地（已生产部署）。 |
| 010 | `archive/completed-plans-phase1-202607-202608/010_009_HANDOVER_VERIFICATION_GUIDE_20260730.md` | 已归档（2026-11-21） | Phase 1 009 生产交接核查指南。 |
| 011 | `archive/completed-plans-phase1-202607-202608/011_ORACLE_12609_PROGRESS_NURSING_REMEDIATION_PLAN_20260803.md` | 已归档（2026-11-21） | Phase 1 Oracle 19c 与 `ORA-12609` 整改方案（已部署）。 |
| 012 | `archive/completed-plans-phase1-202607-202608/012_PROGRESS_NURSING_DUAL_VIEW_REVIEW_20260804.md` | 已归档（2026-11-21） | Phase 1 病程护理双源接入与影子复核（已启用）。 |
| 013 | `archive/completed-plans-phase1-202607-202608/013_ACTIVE_PLAN_INVENTORY_AND_MANUAL_HANDOVER_20260806.md` | 已归档（2026-11-21） | Phase 1 08-06 计划盘点与人工交接证据。 |
| 014 | `archive/completed-plans-phase1-202607-202608/014_CROSS_REVIEW_REPORT_20260807.md` | 已归档（2026-11-21） | Phase 1 四轮交叉核查报告（含 JWT/默认管理员 P0）。 |
| 015 | `archive/completed-plans-phase1-202607-202608/015_CONSOLIDATED_REMEDIATION_EXECUTION_PLAN_20260807.md` | 已归档（2026-11-21） | Phase 1 综合整改执行计划（已执行热部署）。 |
| 016 | `archive/completed-plans-phase1-202607-202608/016_HANDOVER_AFTER_015_AND_NEXT_TRACKS_20260808.md` | 已归档（2026-11-21） | Phase 1 015 后交接快照。 |
| 017 | `archive/completed-plans-phase2-ui-202608/017_FRONTEND_ARCHITECTURE_MENU_LAYOUT_REMEDIATION_PLAN_20260809.md` | 已归档（2026-11-21） | Phase 2 UI-Next 架构、路由与 `UI_DEFAULT_ENTRY` 方案（已上线切换）。 |
| 018 | `archive/completed-plans-phase2-ui-202608/018_HANDOVER_AFTER_017_FRONTEND_LOCAL_WP0_WP5_20260810.md` | 已归档（2026-11-21） | Phase 2 017 WP0–WP5 本地交接快照。 |
| 019 | `archive/completed-plans-phase2-ui-202608/019_LEGACY_TO_UI_NEXT_FUNCTION_AND_FIGMA_PLAN_20260811.md` | 已归档（2026-11-21） | Phase 2 legacy→UI Next 全功能迁移记录。 |
| 020 | `archive/completed-plans-phase2-ui-202608/020_WP6_CANARY_ACCEPTANCE_BLOCKED_REPORT_20260811.md` | 已归档（2026-11-21） | Phase 2 早期 WP6 canary 阻塞历史证据。 |
| 021 | `archive/completed-plans-phase2-ui-202608/021_UI_NEXT_WORKBENCH_PAYLOAD_PATIENTQC_REVIEW_PACKAGE_20260811.md` | 已归档（2026-11-21） | Phase 2 UI-Next 工作台与患者质控复核包。 |
| 022 | `archive/completed-plans-phase2-ui-202608/022_ISOLATED_12_DEPARTMENT_INTERACTIVE_DEMO_PLAN_20260813.md` | 已归档（2026-11-21） | Phase 2 12 科离线隔离演示环境方案（已交付 `demo_env.py`）。 |
| 026 | `archive/completed-plans-phase3-prearchive-202609/026_PAPERLESS_MANUAL_QC_TO_AI_FEASIBILITY_20260827.md` | 已归档（2026-11-21） | Phase 3 无纸化人工终末质控转 AI/规则可行性分析。 |
| 027 | `archive/completed-plans-phase3-prearchive-202609/027_JHEMR_SUBMISSION_REMINDER_INTEGRATION_20260827.md` | 已归档（2026-11-21） | Phase 3 JHEMR 提交提醒五路径评估（含 09-24 主库勘误）。 |
| 028 | `archive/completed-plans-phase3-prearchive-202609/028_PREARCHIVE_CHECK_AND_JHEMR_REMINDER_EXECUTION_PLAN_20260827.md` | 已归档（2026-11-21） | Phase 3 归档前预检独立服务隔离架构执行计划。 |
| 029 | `archive/completed-plans-phase3-prearchive-202609/029_PREARCHIVE_P0_READONLY_VERIFICATION_REPORT_20260828.md` | 已归档（2026-11-21） | Phase 3 预检 P0 五大实证核验报告。 |
| 030 | `archive/completed-plans-phase3-prearchive-202609/030_PREARCHIVE_RULE_MAPPING_TABLE_V1_UNSIGNED_20260828.md` | 已归档（2026-11-21） | Phase 3 CDMS 92 项评分映射表（已获质控科免签字授权）。 |
| 031 | `archive/completed-plans-phase3-prearchive-202609/031_REMAINING_WORK_ONE_SHOT_LOCAL_EXECUTION_PLAN_20260828.md` | 已归档（2026-11-21） | Phase 3 全仓收敛与全源接入作业书（交付=032）。 |
| 032 | `archive/completed-plans-phase3-prearchive-202609/032_031_EXECUTION_DELIVERY_REPORT_20260829.md` | 已归档（2026-11-21） | Phase 3 031 执行交付报告。 |
| 033 | `archive/completed-plans-phase3-prearchive-202609/033_PENDING_REQUESTS_QC_IT_USER_20260829.md` | 已归档（2026-11-21） | Phase 3 三项外部请求书（签字与四源已闭环，心电待后续）。 |
| 034 | `archive/completed-plans-phase3-prearchive-202609/034_T8_2B_3_REALIZED_COLLECTORS_HISBASE_DELIVERY_20260830.md` | 已归档（2026-11-21） | Phase 3 T8 四源实测与 HIS 工号映射交付报告。 |
| 035 | `archive/completed-plans-phase3-prearchive-202609/035_SYSTEM_ANALYSIS_AND_REPAIR_TEST_PLAN_20260831.md` | 已归档（2026-11-21） | Phase 3 前后端 17 项问题分析与修复计划（交付=036）。 |
| 036 | `archive/completed-plans-phase3-prearchive-202609/036_035_EXECUTION_DELIVERY_REPORT_20260901.md` | 已归档（2026-11-21） | Phase 3 035 执行交付与生产热更报告。 |
| 037 | `archive/completed-plans-phase3-prearchive-202609/037_ONESHOT_FINDINGS_REPAIR_EXECUTION_PLAN_20260902.md` | 已归档（2026-11-21） | Phase 3 oneshot 问题修复计划（交付=038）。 |
| 038 | `archive/completed-plans-phase3-prearchive-202609/038_ONESHOT_FINDINGS_REPAIR_DELIVERY_20260902.md` | 已归档（2026-11-21） | Phase 3 037 执行交付报告。 |
| 039 | `archive/completed-plans-phase3-prearchive-202609/039_PAPERLESS_QC_RULE_CENTER_JSON_EMR_HIS_INSURANCE_ONE_SHOT_PLAN_20260902.md` | 已归档（2026-11-21） | Phase 3 无纸化规则中心六表/BFF/医保插件计划（交付=040）。 |
| 040 | `archive/completed-plans-phase3-prearchive-202609/040_039_EXECUTION_DELIVERY_REPORT_20260902.md` | 已归档（2026-11-21） | Phase 3 039 交付与生产六表 DDL 升级报告。 |
| 041 | `archive/completed-plans-phase3-prearchive-202609/041_ISOLATED_RULE_CENTER_USABILITY_ONE_SHOT_PLAN_20260904.md` | 已归档（2026-11-21） | Phase 3 规则中心隔离 demo 与 sidecar 可用性计划（交付=042）。 |
| 042 | `archive/completed-plans-phase3-prearchive-202609/042_041_EXECUTION_DELIVERY_REPORT_20260904.md` | 已归档（2026-11-21） | Phase 3 041 执行交付报告。 |
| 043 | `archive/completed-plans-phase3-prearchive-202609/043_AGENT_EFFICIENCY_REVIEW_AND_AUTOMATION_PLAN_20260906.md` | 已归档（2026-11-21） | Phase 3 跨会话效率治理与聚合门禁计划（交付=044）。 |
| 044 | `archive/completed-plans-phase3-prearchive-202609/044_043_EXECUTION_DELIVERY_REPORT_20260906.md` | 已归档（2026-11-21） | Phase 3 043 交付报告（3 Skill + `run_gates` + 锚 json）。 |
| 045 | `archive/completed-plans-20261002/045_044_VERIFICATION_REMEDIATION_PLAN_20260908.md` | 已归档（2026-10-02） | Phase 3 044 复核整改计划（并入 046 核销，交付=047）。 |
| 046 | `archive/completed-plans-phase3-prearchive-202609/046_PAPERLESS_RULES_JHEMR_CLOSED_LOOP_PLAN_20260910.md` | 已归档（2026-11-21） | Phase 3 无纸化 16 条规则与 JHEMR 闭环计划（交付=047）。 |
| 047 | `archive/completed-plans-phase3-prearchive-202609/047_046_EXECUTION_DELIVERY_REPORT_20260910.md` | 已归档（2026-11-21） | Phase 3 046 两段执行交付报告（JHEMR L1 通过）。 |
| 048 | `archive/completed-plans-20261002/048_SYSTEM_HARDENING_ONESHOT_PLAN_20260915.md` | 已归档（2026-10-02） | Phase 3 系统加固计划（交付=049）。 |
| 049 | `archive/completed-plans-phase3-prearchive-202609/049_048_EXECUTION_DELIVERY_REPORT_20260915.md` | 已归档（2026-11-21） | Phase 3 048 加固交付报告（D-J1 由 051 承接）。 |
| 050 | `archive/completed-plans-20261002/050_DJ1_FIX_AND_BATCHED_COMMIT_ONESHOT_PLAN_20260921.md` | 已归档（2026-10-02） | Phase 3 D-J1 修复与五批 commit 计划（交付=051）。 |
| 051 | `archive/completed-plans-phase3-prearchive-202609/051_050_EXECUTION_DELIVERY_REPORT_20260921.md` | 已归档（2026-11-21） | Phase 3 050 执行交付报告。 |
| 052 | `archive/completed-plans-phase3-prearchive-202609/052_JHEMR_CLIENT_EVENT_REMINDER_ONESHOT_PLAN_20260921.md` | 已归档（2026-11-21） | Phase 3 FILEVERIFY 客户端提醒调查计划（主库勘误承接 `056`）。 |
| 053 | `archive/completed-plans-phase3-prearchive-202609/053_052_EXECUTION_DELIVERY_REPORT_20260921.md` | 已归档（2026-11-21） | Phase 3 052 调查交付报告（承接 `056`）。 |
| 054 | `archive/completed-plans-phase3-prearchive-202609/054_JHEMR_FILEVERIFY_T4_TWO_BATCH_EXECUTION_PLAN_20260922.md` | 已归档（2026-11-21） | Phase 3 旧 179 Oracle 两批方案（已冻结，承接 `056`）。 |
| 055 | `archive/completed-plans-phase3-prearchive-202609/055_JHEMR_FILEVERIFY_PRODUCTION_EXECUTION_RUNBOOK_20260923.md` | 已归档（2026-11-21） | Phase 3 旧 179 Runbook（已冻结，承接 `056`；09-27 密钥漂移已修）。 |
| 057 | `archive/completed-plans-20261002/057_STARTUP_GOVERNANCE_AND_DATABASE_READONLY_PLAN_20260925.md` | 已归档（2026-10-02） | Phase 3 启动治理与数据库只读探索计划（交付=058）。 |
| 058 | `archive/completed-plans-phase3-prearchive-202609/058_057_EXECUTION_DELIVERY_REPORT_20260925.md` | 已归档（2026-11-21） | Phase 3 057 执行交付报告。 |
| 059 | `archive/completed-plans-phase4-audit-202610/059_SYSTEM_REQUIREMENTS_DRIFT_AUDIT_AND_IMPROVEMENT_PLAN_20261002.md` | 已归档（2026-11-21） | Phase 4 56 REQ/24 CON 偏差核查与组装层整改（承接 `061`）。 |
| 060 | `archive/completed-plans-phase4-audit-202610/060_POST_IMPROVEMENT_FRONTEND_BACKEND_AND_QC_ACCURACY_TEST_PLAN_20261002.md` | 已归档（2026-11-21） | Phase 4 79 场景与 64 条准确性挑战测试计划（承接 `061`）。 |
| 106 | `archive/retired-skills-20261121/med-audit-refactor-workflow.md` | 已退役归档（2026-11-21） | 早期改造流程卡，已被 `AGENTS.md` + `120` + `.agents/skills/med-audit-gates` 取代。 |

## 历史功能状态摘要（2026-09~10 快照，最新生产现状见 063）

> 下表按早期复核快照保留（最新 2026-11 全栈生产快照见 [063 总交接](ACTIVE/063_PROJECT_HANDOVER_AND_JHEMR_INTEGRATION_MAP_20261119.md) §2；门禁锚见 `reference/gate_anchors.json`）。

| 主题 | 状态 | 结论 |
| --- | --- | --- |
| 患者质控、告警、H5反馈 | 部分完成 | 主链路、细粒度 feedback permission 和失败响应隐私收口已完成；企微真实 OAuth 外网映射待联调（见 122）。 |
| Vastbase 文书接入 | 已生产运行 | 客户端、双源 loader、回退、截断和批量查询已稳定运行；`aizk_user` 全 6 Schema 只读权限已于 2026-11-19 补齐。 |
| 双模式与终末覆盖 | 部分完成 | 双源已生产启用并有单轮对账；本地正式六类安全模板已闭包；生产 discharge 下 admission_vs_first_progress / surgery_chain / discharge_vs_frontpage 为空 SQL 的 EMR 专用出院路径（2026-09-01 只读核验，非「无转换漏患者」）；`syssvsscbc` 日增量锚点、六类真实 SQL 和连续观察未完成。 |
| 配置运行总览 | 部分完成 | 只读 resolver/summary 已完成；配置重构纳入 `064` WP-08/WP-09。 |
| 多源规则引擎 | 分轨 | 主服务 004C 暂缓立项；预检规则中心已落地 16 条免签字规则，影子激活手册见 `123`（WP-10 审批）。 |
| 安全与权限 | 已升级（WP-02/08 推进中） | 全院 2,383 用户 / 640 科室已上线；统一双层 RBAC（菜单 + 科室数据范围）在 `064` WP-02/WP-08 统一收口。 |
| 前端与默认入口 | 已切 `ui-next` | 2026-11-15 生产已切换 `UI_DEFAULT_ENTRY=ui-next`（`/index.html` 保留回退）；全站 UX 重绘由 `064` WP-03~WP-09 推进。 |

## 仓库级说明与早期归档文档登记

| 编号 | 路径 | 状态 | 用途 |
| --- | --- | --- | --- |
| 002 | `archive/plans-202606-202607/CONFIG_REORGANIZATION_PLAN_2026-06.md` | 已归档（2026-08-24） | 早期配置重组方案。 |
| 003 | `archive/plans-202606-202607/在院出院双模式质控改造实施方案.md` | 已归档（2026-08-24） | 双模式 SQL 口径与终末覆盖方案（已上线）。 |
| 005 | `archive/plans-202606-202607/RELAY_SERVER_REQUIREMENTS.md` | 已归档（2026-08-24） | 早期中继服务器需求（现役契约见 103）。 |
| 006 | `archive/plans-202606-202607/系统整体核查与整改计划_20260710.md` | 已归档（2026-08-24） | 早期风险核查清单。 |
| 007 | `archive/2026-06-ui/20260624/浏览器回归复核执行计划.md` | 已归档（2026-08-24） | 旧版 UI 浏览器复核计划。 |
| 008 | `archive/2026-06-ui/20260624/质控结果准确性抽检执行计划.md` | 已归档（2026-08-24） | Dify 临床抽检模板。 |
| 009 | `archive/2026-06-ui/20260624/质控问题分析与改进方案.md` | 已归档（2026-08-24） | 早期空输出与文本质量改进方案。 |
| 900 | `../ARCHITECTURE.md` | 现役 | 架构、模块与数据流参考。 |
| 901 | `../README_CN.md` | 现役（2026-11-21 更新） | 项目总入口与常用命令。 |
| 902 | `../DEPLOY.md` | 现役 | Docker 部署、升级与回滚手册。 |
| 903 | `../CODE_STYLE.md` | 现役 | 代码风格与文件组织规范。 |
| 904 | `../AGENTS.md` | 现役（2026-11-21 重构） | AI 最高宪章、授权红线、三级验证与防回归守则。 |
| 905 | `../CLAUDE.md` | 现役短指针（2026-11-21 瘦身） | Claude Code 轻量入口，指向 `AGENTS.md` / `063` / `120`。 |
| 906 | `../static/templates/README.md` | 现役参考 | 静态模板异步加载约定与页面清单。 |

## 启动与导航文件登记

| 编号 | 路径 | 状态 | 用途 |
| --- | --- | --- | --- |
| 907 | `README.md` | 现役（2026-11-21 更新） | 文档目录职责入口。 |
| 908 | `archive/README.md` | 现役导航（2026-11-21 更新） | 历史归档使用规则与全部分组地图。 |
| 909 | `../开发起步包/README.md` | 现役（2026-11-21 更新） | 多 AI 4 步启动卡、活跃任务路由与目录边界。 |
| 910 | `../开发起步包/00_AI协作规则.md` | 现役（2026-11-21 更新） | 记账、落位、并发分工与生产审批细则。 |
| 911 | `../开发起步包/01_统一修改记录.md` | 现役，追加维护（2026-11 起） | 跨工具/模型变更台账（2026-06~10 已封卷归档）。 |
| 912 | `../开发起步包/02_协作任务板.md` | 现役（2026-11-21 瘦身） | 活跃与近期 5 条会话任务认领板（历史快照已归档）。 |

## 归档包总清单

| 分类 | 归档目录 | 包含内容 |
| --- | --- | --- |
| 2026-04 ~ 06 早期方案与工具草稿 | `archive/2026-04-06/` | 早期 Vastbase、Relay、菜单、旧架构与多审计类型方案。 |
| 2026-04 Sisyphus 早期草稿 | `archive/sisyphus-202604/` | 从原 `.sisyphus/` 迁出的 7 份已入库早期草稿与证据。 |
| 2026-06 界面设计 | `archive/2026-06-ui/` | 06-11 与 06-24 旧版驾驶舱、逐页设计与测试报告。 |
| 2026-07 Dify 提示词修订 | `archive/2026-07-dify-prompts/` | 旧 109–112 复核包与原始 `.txt` 提示词。 |
| Phase 1 底座与双调度（001–016） | `archive/completed-plans-phase1-202607-202608/` | 15 份原字节计划/报告 + `archive-manifest.json`。 |
| Phase 1 双 004 与配置快照 | `archive/phase1-legacy-004-and-snapshot-202607-202608/` | `004A`/`004B` 与 `p0_prod_config_snapshot_20260809_masked.json`。 |
| Phase 2 UI-Next 迁移（017–022） | `archive/completed-plans-phase2-ui-202608/` | 6 份原字节计划/报告 + `archive-manifest.json`。 |
| Phase 3 预检/规则中心/治理（026–058） | `archive/completed-plans-phase3-prearchive-202609/` | 28 份原字节计划/报告 + `archive-manifest.json`。 |
| 2026-10-02 首批专项归档（045/048/050/057） | `archive/completed-plans-20261002/` | 4 份原字节计划 + `archive-manifest.json`（承接链已同步）。 |
| Phase 4 偏差核查与测试（059–060） | `archive/completed-plans-phase4-audit-202610/` | 2 份原字节计划 + `archive-manifest.json`。 |
| 历史 PROMPT 归档 | `archive/governance-20260925/prompts/` | 2026-09-28 归档的 16 份一次性执行 PROMPT 原文。 |
| 2026-10 ~ 11 历史 PROMPT | `archive/prompts-202610-202611/` | `PROMPT-20261003` 与两份 `PROMPT-20261112` 原文。 |
| 变更台账封卷（2026-06 ~ 10） | `archive/changelog-202606-202610/` | 原 `01_统一修改记录.md` 2026-06~10 完整历史 165 行封卷。 |
| 任务板历史快照 | `archive/taskboard-202610-202611/` | 截至 2026-11-21 的完整 `02_协作任务板.md` 历史快照。 |
| 退役技能与首页历史快照 | `archive/retired-skills-20261121/` | 退役的 `med-audit-refactor-workflow.md`（首页盘点历史见 `archive/navigation-20260925/INDEX_STATUS_HISTORY.md`）。 |
