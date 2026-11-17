# Med-Audit 会话启动与资产导航

> 导航更新：2026-10-12。目录细目见 `docs/reference/120_REPO_DIRECTORY_INDEX_20261012.md`。此文件仍只维护启动顺序、目录职责和当前入口；完整计划状态查 `docs/INDEX.md`，历史交接事实查 `01_统一修改记录.md`，当前会话的负责者/文件范围/恢复点查 `02_协作任务板.md`。

## 1. 每次会话读取顺序

1. `AGENTS.md`：授权、协作和回归约束。
2. 本文件：按任务找到入口。
3. `开发起步包/00_AI协作规则.md`：登记、资产落位和协作规则。
4. `开发起步包/01_统一修改记录.md` 末 10 行：近期交接；不足以判断归属时定向追溯，不把旧授权当常设授权。
5. `docs/INDEX.md`：定位相关计划、最新交付报告、勘误和检查点；再读相关真实代码、配置模板、测试。不要通读全部历史材料。

开始修改前执行 `git status --short`、`git diff --stat`，保留其他人的改动。历史报告、现时核查、待核实假设应分开记录。

完成五步启动后，修改前读取 [02_协作任务板.md](02_协作任务板.md)，登记本任务及文件范围。ZCode/zcod、Codex、Claude等工具和GPT/Kimi/GLM/Grok等模型共用这套流程；具体方法、可复制启动指令和交接模板见 [119协作指南](../docs/reference/119_MULTI_AI_COLLABORATION_GUIDE.md)。不同客户端的私有记忆不能替代共同记录。

## 2. 当前任务路由

| 任务 | 入口 | 状态使用方式 |
| --- | --- | --- |
| 启动、分类整理与跨AI协作 | `docs/reference/119_MULTI_AI_COLLABORATION_GUIDE.md`、`docs/reference/120_REPO_DIRECTORY_INDEX_20261012.md`、`02_协作任务板.md` | 119 管协作方法，120 管目录和文件在哪；不重复启动旧057 |
| 057治理与数据库只读调查交付 | `docs/ACTIVE/058_057_EXECUTION_DELIVERY_REPORT_20260925.md` | 本地治理/报告已交付；全源复核资源差额见058，旧057原文已归档 |
| 系统业务收口 | `docs/ACTIVE/023_SYSTEM_COMPLETION_AND_ONE_SHOT_EXECUTION_PLAN_20260813.md` | 总入口；专项完成情况以最新交付和代码证据为准 |
| FILEVERIFY 目标库与现场交接 | `docs/ACTIVE/056_JHEMR_FILEVERIFY_TARGET_DB_CORRECTION_HANDOVER_20260924.md` §6、058 §6–§7 | 177 P0/v4为历史证据；056 §6.6登记归属与现时对账阻塞见058。旧179包冻结；本导航不批准177写入或激活 |
| 密钥事故与漏跑补推记录 | `01_统一修改记录.md` 2026-09-27/29行、055 §0.4-5 | 已登记密钥修复及7窗补推；残留缺口见09-29行，本轮未核查现时生产，不重复列旧“待修密钥” |
| D-J1、历史提交与可靠性 | `docs/ACTIVE/051_050_EXECUTION_DELIVERY_REPORT_20260921.md` | 050 已交付，不重复修复或提交；049 遗留项须结合 051 更正核销 |
| 059/060 修复计划 R0–R7 一次性执行（2026-10-04 已执行完毕） | `开发起步包/PROMPT-20261003_059060修复计划R0-R7一次性执行.md`（自包含；计划详情=review/round-8/修复计划.md）；用户 10-03 三裁定：commit 基线已提交/BFF 校验入 R1/R0–R7 一次授权；执行者不 commit，完成后回 059 §11/060 §13 登记。 | R0–R7 八包+复核轮 F-1/F-7/F-2 已于 10-04 完成（见 01 当日登记与 review/059060-fix-20261004/）；PROMPT 为历史交接件，不是当前待办或授权 |
| 054 本地模拟专项 | `docs/ACTIVE/054_JHEMR_FILEVERIFY_T4_TWO_BATCH_EXECUTION_PLAN_20260922.md` §15–§16 | 本地专项已交付；生产旧方案冻结 |
| 规则中心、预检与 JHEMR 联调 | `docs/INDEX.md` 中 040/042/047/049/051/053 | 分清本地实现、生产部署、外部启用和业务验收，历史 L2/L3 状态须按后续证据判断 |
| 历史高危整改 | `docs/ACTIVE/024_HIGH_RISK_SEVERITY_REMEDIATION_HANDOVER_20260817.md`、025 | 专项只读/批准边界有效；不是本轮数据库探索中的整改任务 |
| 正式回归 | `.agents/skills/med-audit-gates/SKILL.md` | `scripts/run_gates_20260906.py` 为唯一汇总入口；锚=`docs/reference/gate_anchors.json` |

## 3. 目录分类与维护责任

| 类别 | 目录/文件 | 管理规则 |
| --- | --- | --- |
| 启动和协作 | `AGENTS.md`、本目录README/00/01/02、`README_CN.md` | 规则不复制，业务状态指向INDEX；02记会话分工，01记历史；PROMPT不是当前授权 |
| 长期文档 | `docs/INDEX.md`、`docs/reference/`（目录细目=120） | INDEX 管编号/状态/路径；reference 管当前契约；120 管代码目录 |
| 计划与交付证据 | `docs/ACTIVE/` | 混有现役计划与历史报告；以状态列判定，归档前核对完成证据和入站引用 |
| 历史档案 | `docs/archive/` | 只追溯；按主题/日期归档、保留来源和替代入口；本批045/048/050/057在`completed-plans-20261002/` |
| 主服务与验证 | `app/`、`tests/`、`scripts/` | 运行路径不因目录整理改变；新运维脚本带日期后缀 |
| 独立预检 | `prearchive_service/` | 零 `import app.*`；独立配置/测试/SQL/联调资产，不拆散 |
| 前端与设计 | `frontend/`、`design/`、`static/` | 源码/设计/发布资源分工；不能把 static 全当缓存删除 |
| 配置与数据 | `config/`、`data/`、`logs/` | 模板与运行实例区分；保留密文与备份；不为整理启动服务或迁移库 |
| 提示词与部署 | `prompts/`、`oracle-client/`、`packages/`、根目录 Docker/依赖文件 | 当前运行资产保留原位，离线包和驱动不能按体积清理 |
| 审计与本地过程 | `review/`、`docs/remediation/` | review 保存检查点、门禁、前镜像；长期脱敏结论进入登记文档；不整包提交 review |
| 隐私附件 | `docs/attachments/` | 禁止提交和外发。根目录 `user.xlsx` / `user_dict.xlsx` 按 119 留在原位：不打开、不迁移、不在正文展开 |
| 工具工作区与缓存 | `.agents/`、`.github/`、`.claude/`、`.opencode/`、`.qodo/`、`.sisyphus/`、`.vscode/`、`.v2c/`、`.video_agent/`、`.venv/`、`.pytest_cache/` | 仓库配置、个人工具和缓存分别盘点；不得仅凭隐藏目录名删除 |
| 仓库级说明 | `ARCHITECTURE.md`、`DEPLOY.md`、`CLAUDE.md`、`CODE_STYLE.md` | 主题参考；冲突时以 AGENTS 和可执行实现为准，后续按 057 核对 |

## 4. 检查点与交付

- 当前整理证据：`review/document-governance-20261002/`；上一轮证据：`review/governance-20260925/`，交付见058。
- 历史通用检查点：`review/exec-log.md`；FILEVERIFY：`review/jhemr-fileverify-056/exec-log.md`。不能只凭日志最后一行推断所有任务完成。
- 新增或迁移 docs Markdown 同步 INDEX；任何仓库修改追加 `01_统一修改记录.md`，历史行不改写。
- 修改前认领02文件范围；长任务每批保存检查点和登记，交接标HANDOFF，验证/登记完成后标DONE。文档专项只读检查：`python scripts/check_documentation_20261002.py`。
- 文档归档不改变业务授权。详细红线查 `AGENTS.md` 和 `00_AI协作规则.md`。
