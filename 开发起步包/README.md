# Med-Audit 多 AI 会话启动卡与资产地图

> 更新：2026-11-21（完成全仓目录治理、历史文档分阶段归档、台账封卷与启动体系精简）。本文件只维护**启动顺序、当前活跃任务路由与目录职责边界**；总宪章看 [AGENTS.md](../AGENTS.md)，文档台账看 [docs/INDEX.md](../docs/INDEX.md)，历史演进看 [124 系统升级编年史](../docs/reference/124_SYSTEM_EVOLUTION_HISTORY.md)。

---

## 1. 每次会话 4 步启动协议

1. **[AGENTS.md](../AGENTS.md)**：核心原则、生产/Git/PHI 授权红线、三级验证矩阵与全栈防坑守则。
2. **本文件 & [00_AI协作规则.md](00_AI协作规则.md)**：确定任务入口、文件落位与记账格式；若发现用户新建的散落文书/Excel/文档，按 `00` §3.1 主动协助规范归位并同步 `INDEX.md`。
3. **[01_统一修改记录.md](01_统一修改记录.md) 末 10 行 & [02_协作任务板.md](02_协作任务板.md)**：掌握上一任断点，执行 `git status --short` / `git diff --stat` 核对现场并认领文件范围（完整保留他人未提交改动）。
4. **[docs/INDEX.md](../docs/INDEX.md)**：按需打开对应现役计划或契约，再核读真实代码与测试；不要通读 `docs/archive/`。

> ZCode、Codex、Claude、Antigravity 等工具及所有模型共用此套仓库事实，不依赖私有聊天记忆。跨工具交接模板见 [119 多 AI 协作指南](../docs/reference/119_MULTI_AI_COLLABORATION_GUIDE.md)，代码定位见 [120 目录索引](../docs/reference/120_REPO_DIRECTORY_INDEX_20261012.md)。

---

## 2. 当前活跃任务路由（仅列未完结/现役主线）

| 任务主线 | 入口文档 | 当前状态与使用边界 |
| :--- | :--- | :--- |
| **全栈性能根治、业务重构与 UI/UX 升级（主力计划）** | [064 总计划](../docs/ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md) & `开发起步包/prompts-064/`（3 日验收读 `PROMPT-WP10-S7`） | WP-01 ~ WP-09 与 WP-10 S0 ~ S6 已于 2026-11-21 全部上线验收通过，进入 S7 3 日只读观察期；零生产写入、零未授权 Git 写 |
| **独立工作区总交接与 JHEMR 接口全景（新会话首选）** | [063 总交接与接口地图](../docs/ACTIVE/063_PROJECT_HANDOVER_AND_JHEMR_INTEGRATION_MAP_20261119.md) | 最新生产镜像 `9807a3e4c98f`、全院 2,383 用户/640 科室、177 锁定 9 开关与七大对接轨道台账；仅交接参考，不构成授权 |
| **企微 OAuth 真实联调与外网前置机代理** | [PROMPT-20261117](PROMPT-20261117_企微OAuth真实联调与外网前置机对接交接.md)、[122 代理规范](../docs/reference/122_MOBILE_TIMELINESS_WECOM_PROXY_ONBOARDING_20261117.md) | 代码与模拟验证已完成；待用户配企微 `secret` 及前置机侧实现 `/wecom-oauth/exchange` 与 5 前缀映射 |
| **病历时效质控上线收尾与危急值对接** | [062 执行指针](../docs/ACTIVE/062_TIMELINESS_QC_EXECUTION_POINTER_20261110.md)、[05 设计指针](05_病历时效质控设计指针.md)、[121 危急值契约](../docs/reference/121_CRITICAL_VALUE_WEBHOOK_AND_JHEMR_INTEGRATION_CONTRACT_20261114.md) | 线上影子运行中，写闸全关；D8（`CHIEF_FIRST_ROUND` 禁锁）有效；危急值待厂商联调 |
| **JHEMR 客户端 `FILEVERIFY` 177 写入** | [056 目标库勘误交接](../docs/ACTIVE/056_JHEMR_FILEVERIFY_TARGET_DB_CORRECTION_HANDOVER_20260924.md) §6 | 177 v4 候选包就绪（旧 179 路径永久冻结）；待用户在 177 明确写入批准 |
| **历史高危降噪红线与人工待裁定清单** | [024](../docs/ACTIVE/024_HIGH_RISK_SEVERITY_REMEDIATION_HANDOVER_20260817.md)、[025](../docs/ACTIVE/025_SPLIT_QC_AND_121_EXCEL_INDEPENDENT_REVIEW_HANDOVER_20260817.md)、[061](../docs/ACTIVE/061_CURRENT_MD_MANUAL_REVIEW_AND_UNFINISHED_WORK_20261006.md) §十 | 保留临床红线与少量待裁定项（AUD-A4 等）；专项整改须遵循 `.agents/skills/med-audit-history-remediation` |
| **全绿门禁与隔离演示编排** | `.agents/skills/med-audit-gates/SKILL.md`、`.agents/skills/med-audit-demo-stack/SKILL.md` | 唯一聚合入口 `scripts/run_gates_20260906.py`，锚文件 `docs/reference/gate_anchors.json` |

> 已完结的历史计划（`001`–`060` 大部分及历史 PROMPT）均已原字节分类归档至 `docs/archive/`，演进全貌见 [124 系统升级编年史](../docs/reference/124_SYSTEM_EVOLUTION_HISTORY.md)。历史 PROMPT 与旧批准均不构成当前授权。

---

## 3. 全仓目录职责与边界

| 类别 | 目录 / 文件 | 管理边界 |
| :--- | :--- | :--- |
| **启动与协作** | `AGENTS.md`、`CLAUDE.md`、`README_CN.md`、`开发起步包/` | 规则唯一来源为 `AGENTS.md`，各入口不复制红线；`01` 记修改事实（按里程碑封卷），`02` 仅留活跃与近 5 条任务 |
| **现役文档与契约** | `docs/INDEX.md`、`docs/ACTIVE/`（仅留真现役）、`docs/reference/`、`docs/skills/` | 变更任意 `docs/**/*.md` 同步更新 `INDEX.md` 并跑 `check_documentation_20261002.py` |
| **历史见证档案** | `docs/archive/` | 分阶段原字节保存历史计划/报告/台账/PROMPT，仅追溯不作现行依据 |
| **主服务与测试** | `app/`（含 `app/timeliness/`）、`tests/` | 路由仅在 `app/main.py` 注册；单测不连生产库 |
| **独立预归档服务** | `prearchive_service/` | 物理零 `import app.*`；保留 `rules/*.json.bak`（单测校验哈希） |
| **前端与发布资产** | `frontend/`、`design/`、`static/` | `frontend/` 为 Vue 3 源码，`static/` 含 legacy 页面、企微 H5 与 `ui-next/` 构建镜像，不可整目录删除 |
| **脚本资产** | `scripts/`（顶层现役 + `scripts/timeliness/` + `scripts/archive/`） | 新运维脚本强制带 `_YYYYMMDD.py` 后缀；`archive/` 内历史部署/热修禁止重跑 |
| **配置、数据与日志** | `config/`、`data/`、`logs/` | 区分模板与实例，保留 `config/backups/` 与密文；只读探查禁调 `init_db()` |
| **部署、提示词与驱动** | 根目录 Docker/依赖文件、`prompts/`、`oracle-client/`、`docs/3一致性核查*.yml` | 离线镜像与测试依赖资产，保留原位 |
| **过程证据与隐私附件** | `review/`、`docs/remediation/`、`docs/attachments/`、根目录 `user*.xlsx` | `review/`、`attachments/`、`user*.xlsx` 均不入 Git；含 PHI 资产严禁打开展开或外发 |
| **仓库技能与 CI** | `.agents/skills/`、`.github/workflows/` | 全部可执行工作流 Skill 唯一归口 `.agents/skills/` |
