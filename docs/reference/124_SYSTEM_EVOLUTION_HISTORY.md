# 124 · Med-Audit 系统历史升级需求与架构演进总览（2026-04 ~ 2026-11）

> **建立日期**：2026-11-21
> **文档定位**：系统升级编年史与历史资产导航。沉淀从 2026-04 至今六个演进阶段的核心业务需求、关键里程碑、归档文档坐标与当前权威承接入口，避免新接手成员和 AI 重复通读数十份已完结计划。
> **使用规则**：本文件仅作演进脉络索引，不替代现役契约或构成执行授权；当前运行行为以代码、配置模板、[063 总交接](../ACTIVE/063_PROJECT_HANDOVER_AND_JHEMR_INTEGRATION_MAP_20261119.md) 及 [064 主力整改计划](../ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md) 为准。

---

## 一、六大演进阶段全景

| 阶段 | 时间 | 核心升级需求与业务背景 | 关键交付与里程碑 | 归档 / 历史坐标 | 当前权威承接 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Phase 1：底座稳定与多源 AI 内涵质控** | 2026-04 ~ 2026-08-08 | 从单一病程/护理 SQL 抽取升级为 6 类临床一致性 Dify 工作流；治理 Oracle 兼容性（`ORA-12609`、空串、`EXISTS`、CLOB）、幂等防双当前结果、历史按日补跑、Vastbase EMR 文书直连、在院/出院双模式调度，以及 JWT 与默认管理员安全加固 | 多源 `PatientBundle` 与 `AuditTypeRegistry`；`MED_PUSH_EXECUTION/ATTEMPT` 原子 claim；`emr_vastbase_client.py`；双调度独立 DB 锁；`015` 综合整改热部署 | `archive/2026-04-06/`、`archive/plans-202606-202607/`、`archive/completed-plans-phase1-202607-202608/`（`001`–`016`）、`archive/phase1-legacy-004-and-snapshot-202607-202608/` | [101 功能基线](101_FEATURE_BASELINE.md)、[102 数据与 Dify 契约](102_DATA_AND_DIFY_CONTRACTS.md)、[109–115 六类提示词](../INDEX.md) |
| **Phase 2：UI-Next 架构升级与高危精准降噪** | 2026-08-09 ~ 2026-08-24 | 重构旧版 CDN 单页为 Vue 3 + Vite + TypeScript 模块化前端（`ui-next`）与 12 科离线隔离演示环境；解决高危误报过多痛点——落实契约校验器“只降不升”、硬门槛与语义降级开关、Dify 唯一门禁影子工作流 V2、三轮存量降级 1,356 条假高危；建立 `开发起步包/` 统一修改台账与多 AI 协作制度 | `frontend/` 模块化 App Shell 与 `UI_DEFAULT_ENTRY` 开关；`scripts/demo_env.py`；唯一影子工作流 `docs/3一致性核查正式版-质控门禁影子V2.yml`；`docs/remediation/` 三轮降级审计证据；`开发起步包/00` 与 `01` | `archive/2026-06-ui/`、`archive/2026-07-dify-prompts/`、`archive/completed-plans-phase2-ui-202608/`（`017`–`022`） | [024 高危整改交接](../ACTIVE/024_HIGH_RISK_SEVERITY_REMEDIATION_HANDOVER_20260817.md)、[025 121 核查复核](../ACTIVE/025_SPLIT_QC_AND_121_EXCEL_INDEPENDENT_REVIEW_HANDOVER_20260817.md)、[023 第一代总入口（封存）](../ACTIVE/023_SYSTEM_COMPLETION_AND_ONE_SHOT_EXECUTION_PLAN_20260813.md) |
| **Phase 3：归档前形式预检、规则中心与 JHEMR 集成** | 2026-08-27 ~ 2026-09-25 | 将无纸化人工终末质控（`CDMS.T_MARK_ITEM` 92 项评分）中确定性规则代码化；建设零 `import app.*` 物理隔离的 `prearchive_service/`（现行 16 条质控科免签字规则 v`2026.09.10-046-t3`）、规则中心六表/状态机/BFF/医保插件、JHEMR 提交前 HMAC API 与 `FILEVERIFY` 客户端提醒；完成 177 Vastbase 为 EMR 主库勘误（永久冻结旧 179 Oracle 路径）；建立 `run_gates` 聚合门禁与 `.agents/skills/` 技能体系 | `prearchive_service/` 与 `check_isolation.py`；`app/routers/jhemr_integration.py`；`FILEVERIFY` v4 候选包；`scripts/run_gates_20260906.py` 与 `gate_anchors.json`；首批核心 Skill | `archive/completed-plans-20261002/`（`045/048/050/057`）、`archive/completed-plans-phase3-prearchive-202609/`（`026`–`044/046–047/049/051–055/058`）、`archive/governance-20260925/` | [056 FILEVERIFY 177 交接](../ACTIVE/056_JHEMR_FILEVERIFY_TARGET_DB_CORRECTION_HANDOVER_20260924.md)、[123 预检影子激活 Runbook](123_PREARCHIVE_SHADOW_AND_PAPERLESS_PUSH_RUNBOOK_20261119.md)、[gate_anchors.json](gate_anchors.json) |
| **Phase 4：全仓要求偏差审计、挑战测试与文档治理** | 2026-10-02 ~ 2026-10-12 | 对全系统开展 56 REQ / 24 CON 偏差核查与 79 场景分层验收（含 64 条判断准确性挑战用例）；修复 Dify 否定语义翻转、logs 导出范围过滤与 D4 失败尝试挤占旧当前缺陷；建立跨工具协作指南 `119`、全仓代码目录索引 `120`、任务认领板 `02` 及自动化文档检查器 | `app/services/dify_result_normalizer.py`、`push_log_supersede.py` 修复；`scripts/check_documentation_20261002.py`；`061` 全量人工复核清单 | `archive/completed-plans-phase4-audit-202610/`（`059`–`060`）、`archive/prompts-202610-202611/` | [061 人工复核与未闭环项](../ACTIVE/061_CURRENT_MD_MANUAL_REVIEW_AND_UNFINISHED_WORK_20261006.md)、[119 多 AI 协作指南](119_MULTI_AI_COLLABORATION_GUIDE.md)、[120 目录索引](120_REPO_DIRECTORY_INDEX_20261012.md) |
| **Phase 5：病历时效质控、企微 H5 与全院目录打通** | 2026-11-10 ~ 2026-11-18 | 在主服务新增独立包 `app/timeliness/`（T0–T11 完整交付）：18 条时效规则、5 分钟自动扫描 `timeliness_scan`、接入 HIS 医嘱/手麻排台/医师职称 7 项核心规则、全院 JHEMR 解锁审批与 200 元扣罚同步、受控双模板写回器（D8 禁锁红线）；攻克 Oracle `V_QYBR`/`V_CYBR` 角色权限失效（`ORA-04063`）内联降级；切换默认入口为 `ui-next`（5 组 22 项菜单）；上线企微手机端 H5 三 Tab 门户与 OAuth 直签发；完成全院 2,383 员工 / 640 科室同步上线；冻结危急值双路对接契约 | `app/timeliness/`、`app/services/oracle_patient_view_compat.py`、`app/routers/mobile_timeliness.py`、`app/services/timeliness_access.py`、生产镜像 `9807a3e4c98f` | `archive/prompts-202610-202611/`、`archive/changelog-202606-202610/` | [062 时效执行指针](../ACTIVE/062_TIMELINESS_QC_EXECUTION_POINTER_20261110.md)、[121 危急值对接契约](121_CRITICAL_VALUE_WEBHOOK_AND_JHEMR_INTEGRATION_CONTRACT_20261114.md)、[122 企微代理对接规范](122_MOBILE_TIMELINESS_WECOM_PROXY_ONBOARDING_20261117.md) |
| **Phase 6：独立工作区总交接与 064 全栈重构升级** | 2026-11-19 ~ 进行中 | 本仓独立开发维护，沉淀 JHEMR 原生全院锁定 9 开关与七大对接轨道总交接 `063`；启动 `064`（WP-01 ~ WP-10，D1–D6 拍板）：根治 `timeliness_scan` 脏写与 CLOB 慢查、总览单接口聚合、全院统一菜单+科室双层 RBAC 与 360 全息视图、时效统计专页与任意区间 Excel 考核、内涵质控双视角融合与患者详情重绘、规则中心三轨重构与 JHEMR 提交前 AI 提醒拉取接口、预检影子激活工具链与病案室工作台、系统运维美化及分步审批发布 | `WP-01` ~ `WP-07` 已完成本地交付（含 `ttl_cache.py`、`data_scope.py`、`stats_service.py`、三轨规则页、`123` Runbook 等）；`WP-08` ~ `WP-10` 待顺序推进 | `开发起步包/prompts-064/` | [063 独立总交接与接口地图](../ACTIVE/063_PROJECT_HANDOVER_AND_JHEMR_INTEGRATION_MAP_20261119.md)、[064 全栈升级总计划](../ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md) |

---

## 二、历史见证资产分布总图

系统升级过程中保留的文档、表格与审计证据均已分类沉淀，按需追溯路径如下：

| 资产类型 | 所在位置 | 说明 |
| :--- | :--- | :--- |
| 历史计划、评审与阶段报告（原文不改） | `docs/archive/` 各阶段子目录 | 均保留原文字节与 `README.md`；编号计划配套 `archive-manifest.json`（SHA-256 校验） |
| 历史变更台账（2026-06 ~ 2026-10 封卷） | `docs/archive/changelog-202606-202610/` | 与现行 `开发起步包/01_统一修改记录.md`（2026-11 起）首尾衔接，严格 append-only |
| 历史质控导出 Excel 与架构截图 | `docs/attachments/` | 保留高危核查报告、反馈导出 Excel 与成效图（含 PHI，`.gitignore` 已忽略，禁提交禁外发） |
| 高危存量降级 dry-run / apply 审计 JSON | `docs/remediation/` | 2026-08-17 三轮降级原始备份与回退说明（`MOCK-20260813`） |
| 历史一次性运维/热修与早期诊断脚本 | `scripts/archive/` | `ops-history/`（历史部署/热修留档）与 `diag-legacy/`（早期连通性诊断草稿） |
| 历史已完成提示词（PROMPT） | `docs/archive/governance-20260925/prompts/`、`docs/archive/prompts-202610-202611/` | 仅追溯历史需求口径，不作为当前待办或授权来源 |
