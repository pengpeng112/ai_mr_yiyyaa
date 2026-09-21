# Med-Audit 开发起步包（会话启动目录）

> 用途：任何 AI 或开发者在本仓库工作的**统一入口**。多 AI 协作，规则与修改记录集中在这里。
> 建立日期：2026-08-24（参考 `F:\python\数据资产` 的开发起步包模式）
> 维护义务：目录结构变化、新增长期入口时，必须同步更新本 README。

---

## 1. 会话启动顺序（每次必做）

1. `AGENTS.md` —— 仓库红线与核心约束
2. **本 README** —— 目录地图与当前入口
3. `00_AI协作规则.md` —— 协作与登记规则（按启动顺序读取）
4. `01_统一修改记录.md` —— 最近几行，了解上一任做了什么、生产处于什么状态
5. 按任务需要读 `docs/INDEX.md`（文档系统索引）与相关 `docs/ACTIVE/` 现役文档

## 2. 当前关键入口（截至 2026-08-24）

| 事项 | 入口 |
|---|---|
| 系统可靠性与工作台完善（048已执行，交付=049） | `docs/ACTIVE/049_048_EXECUTION_DELIVERY_REPORT_20260915.md`（作业书=048 v1.0；工作台分页/有界聚合/科室强制+双前端恢复+匹配事务+L1 复跑全绿；发现 D-J1 待授权；零生产、未 commit）。 |
| D-J1 修复与历史批次提交（050 已执行，交付=051） | 作业书=`docs/ACTIVE/050_DJ1_FIX_AND_BATCHED_COMMIT_ONESHOT_PLAN_20260921.md`（v1.1=round-6 三方互查修订）；提示词=`开发起步包/PROMPT-20260921_DJ1修复与历史批次提交一次性执行.md`；范围=D-J1 修复+未提交累积终态（编制时 134 项，以 T0 实测为准）五批本地 commit（**待用户明示批准提交条款**）+锚更新；不 push。 |
| 系统收口唯一执行入口 | `docs/ACTIVE/023_SYSTEM_COMPLETION_AND_ONE_SHOT_EXECUTION_PLAN_20260813.md` |
| 无纸化/JHEMR统一修复与闭环（046 v1.2，已执行完毕，交付=047） | `docs/ACTIVE/047_046_EXECUTION_DELIVERY_REPORT_20260910.md`（046 作业书两段执行 T0-T10 全包闭合；终版门禁全绿含 legacy 双轮实跑 main 1376/prearchive 438+1skip；JHEMR 五接口+联调包 `prearchive_service/integration/jhemr/`，L1 已验收、L2/L3 未开始；045 全核销；零生产、未 commit）。 |
| oneshot 测试问题一次性修复（已执行，交付=038；生产已随 039-B3 部署） | `docs/ACTIVE/038_ONESHOT_FINDINGS_REPAIR_DELIVERY_20260902.md` |
| 无纸化规则中心+EMR/HIS JSON+医保插件（已执行，交付=040） | `docs/ACTIVE/040_039_EXECUTION_DELIVERY_REPORT_20260902.md`（生产已部署：六表 DDL+代码+latest=0ff639fb78e0，全开关关闭零外发；EMR/HIS/医保=框架就绪未启用，启用路径见 040 §10；B4 影子 7 天待预检进程启动=036-RP7 轨道） |
| 规则中心隔离可用性一次性执行（已执行，交付=042） | `docs/ACTIVE/042_041_EXECUTION_DELIVERY_REPORT_20260904.md`（作业书=041 v1.1；隔离 demo 两步启动：sidecar `--serve --import-rules` + demo serve 18080；读端点已收紧 `prearchive_rule_view`；零生产、未 commit） |
| 跨会话效率治理一次性执行（已执行，交付=044） | `docs/ACTIVE/044_043_EXECUTION_DELIVERY_REPORT_20260906.md`（作业书=043 v1.1）；沉淀 3 Skill（`.agents/skills/med-audit-{gates,oneshot-delivery,demo-stack}`）+3 脚本（`scripts/{run_gates,clean_demo_ports,update_gate_anchor}_20260906.py`，门禁唯一入口=`python scripts/run_gates_20260906.py --quick\|--full`）+锚单一来源 `docs/reference/gate_anchors.json`；cron 仅建议未启用；零生产、未 commit |
| 044核查修复（045已归并046执行完毕） | `docs/ACTIVE/045_044_VERIFICATION_REMEDIATION_PLAN_20260908.md`仅历史依据；F0–F5/D1–D8 已随 046 全核销（更正落 044 §11，证据=047 §10/§11）。 |
| 历次会话导出与跨 AI 分析素材 | `review/conversations-export-20260906/`（13 主会话+INDEX，gitignored）；导出工具 `scripts/export_zcode_conversations_20260906.py`；分析交接=`开发起步包/PROMPT-20260906_会话全量获取与跨AI分析.md` |
| 高危严重度整改交接（契约校验器/语义规则/三轮降级） | `docs/ACTIVE/024_HIGH_RISK_SEVERITY_REMEDIATION_HANDOVER_20260817.md` |
| 121 人表独立复核 + 分质控架构裁定 | `docs/ACTIVE/025_SPLIT_QC_AND_121_EXCEL_INDEPENDENT_REVIEW_HANDOVER_20260817.md` |
| Dify 唯一待复核工作流（质控门禁影子 V2） | `docs/3一致性核查正式版-质控门禁影子V2.yml`（生成脚本 `scripts/build_admission_fact_gate_shadow_yml_20260819.py`） |
| 整改证据与备份 JSON | `docs/remediation/` |
| 任务交接提示词 | `开发起步包/PROMPT-*.md`（如 028 一期开发一次性交接） |
| 生产环境访问方式 | 见 `AGENTS.md` "Remote Production Server" 节；只读红线见 024/025 |

## 3. 仓库目录地图

```text
ai_mrzk/
├─ AGENTS.md / CLAUDE.md / ARCHITECTURE.md / DEPLOY.md   # 仓库级说明（历史保留）
├─ 开发起步包/            # ★ 本目录：启动索引 + 协作规则 + 统一修改记录
├─ app/                   # FastAPI 后端代码
├─ frontend/              # Vue3 前端
├─ tests/                 # pytest 测试
├─ scripts/               # 运维/整改/生成脚本（命名必须带 _YYYYMMDD 日期后缀）
├─ config/                # 运行配置；历史备份进 config/backups/
├─ data/  logs/           # 本地运行数据（不入库内容见 .gitignore）
├─ design/                # UI 设计资产（med-audit-ui-next）
├─ packages/              # 离线部署轮子（27MB whl，Linux 离线安装用，勿删）
├─ static/  prompts/  oracle-client/   # 前端构建产物 / 提示词资产 / Oracle 客户端
├─ docs/
│  ├─ INDEX.md            # 文档系统唯一索引（docs/**.md 增删移动必须同步）
│  ├─ ACTIVE/             # 现役编号文档（001-025，含计划/交接/复核）
│  ├─ reference/          # 参考契约（101-117）
│  ├─ remediation/        # 整改证据 JSON 与说明（含三轮降级备份、MOCK 回退说明）
│  ├─ attachments/        # 截图、导出附件（含患者隐私，禁止外发/提交）
│  ├─ archive/            # 历史归档（root-cleanup-20260824/ 等，只读追溯）
│  ├─ skills/ sql/        # 技能与 SQL 资产
│  └─ INDEX.md / README.md / 唯一门禁影子V2.yml   # 顶层仅保留索引与现役工作流（2026-08-24 起旧计划已归档）
└─ .agents/skills/        # 仓库技能（med-audit-history-remediation 等）
```

## 4. 禁止事项（速查，完整版见 00_AI协作规则.md）

- 根目录与 `docs/` 顶层**不得新增散文件**；新资产按 §3 地图落位。
- 患者隐私文件（xlsx/导出/截图含 PHI）只进 `docs/attachments/`，禁止提交 git、禁止外发。
- 修改仓库或生产后必须登记 `01_统一修改记录.md`；未登记时按 AGENTS.md 保留现场、核查归属，可继续无关工作，依赖归属不明内容时再请用户裁定。
