# Med-Audit 开发起步包（会话启动目录）

> 用途：任何 AI 或开发者在本仓库工作的**统一入口**。多 AI 协作，规则与修改记录集中在这里。
> 建立日期：2026-08-24（参考 `F:\python\数据资产` 的开发起步包模式）
> 维护义务：目录结构变化、新增长期入口时，必须同步更新本 README。

---

## 1. 会话启动顺序（每次必做）

1. `AGENTS.md` —— 仓库红线与核心约束
2. **本 README** —— 目录地图与当前入口
3. `00_AI协作规则.md` —— 协作与登记规则（**改过任何东西就必须看**）
4. `01_统一修改记录.md` —— 最近几行，了解上一任做了什么、生产处于什么状态
5. 按任务需要读 `docs/INDEX.md`（文档系统索引）与相关 `docs/ACTIVE/` 现役文档

## 2. 当前关键入口（截至 2026-08-24）

| 事项 | 入口 |
|---|---|
| 系统收口唯一执行入口 | `docs/ACTIVE/023_SYSTEM_COMPLETION_AND_ONE_SHOT_EXECUTION_PLAN_20260813.md` |
| 高危严重度整改交接（契约校验器/语义规则/三轮降级） | `docs/ACTIVE/024_HIGH_RISK_SEVERITY_REMEDIATION_HANDOVER_20260817.md` |
| 121 人表独立复核 + 分质控架构裁定 | `docs/ACTIVE/025_SPLIT_QC_AND_121_EXCEL_INDEPENDENT_REVIEW_HANDOVER_20260817.md` |
| Dify 唯一待复核工作流（质控门禁影子 V2） | `docs/3一致性核查正式版-质控门禁影子V2.yml`（生成脚本 `scripts/build_admission_fact_gate_shadow_yml_20260819.py`） |
| 整改证据与备份 JSON | `docs/remediation/` |
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
│  └─ 顶层旧计划 md / 界面设计目录   # INDEX 002-009 编号管理，位置不动
└─ .agents/skills/        # 仓库技能（med-audit-history-remediation 等）
```

## 4. 禁止事项（速查，完整版见 00_AI协作规则.md）

- 根目录与 `docs/` 顶层**不得新增散文件**；新资产按 §3 地图落位。
- 患者隐私文件（xlsx/导出/截图含 PHI）只进 `docs/attachments/`，禁止提交 git、禁止外发。
- 修改仓库或生产后**不登记 `01_统一修改记录.md` = 工作不被承认**，下任 AI 有权拒绝在未登记变更上继续。
