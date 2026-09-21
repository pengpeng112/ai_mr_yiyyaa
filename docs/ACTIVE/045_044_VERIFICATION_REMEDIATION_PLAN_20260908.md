# 045 — 044 核查修复一次性作业书（脚本缺陷 / 计数更正 / 09-08 补登记）

> **2026-09-10执行归并说明（新增，不改历史正文）**：用户要求统一到046。本文件F0–F5/D1–D8已完整并入 `046_PAPERLESS_RULES_JHEMR_CLOSED_LOOP_PLAN_20260910.md` v1.2 §6.4，尚未实施；不再独立启动045。更正仍追加044 §11，总交付047；执行顺序、文件范围和测试契约迁移以046为准，下文是原v1.0历史作业书。

> 文档编号：045 ｜ 编制：2026-09-08 ｜ 编制者：Grok 4.6（只读核查 044，不执行本作业书的修复包）
> 版本：**v1.0**
> 性质：**从属 023 的本地一次性作业书**；不构成生产写入授权，不切换入口，不创建定时任务，不上抬门禁锚。
> 完成定义：按本文做完 F0–F5，门禁按 §7 通过，**044 文末追加 §11 核查更正（不改写原 §0–§10 数字）**，INDEX/01 登记。不新建 046（避免重复会话总结）。
> 配套提示词：`开发起步包/PROMPT-20260908_044核查修复一次性执行.md`

---

## 0. 修订记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v1.0 | 2026-09-08 | 初稿。依据对 044、043 v1.1、权威门禁 `review/gate-runs/20260907-215610/`、脚本/测试/INDEX/01 的只读核查。 |

## 0.1 用户原始需求（2026-09-08）

用户给出 `044_043_EXECUTION_DELIVERY_REPORT_20260906.md`，要求：**核查，并生成计划交给其他 AI 修复**。本文件即该计划。编制会话只落作业书/提示词/索引登记，**不执行 F1–F5**。

## 1. 核查结论（编制时已取证，执行 AI 禁止当新发现重做）

### 1.1 总判

**044 作为 043 v1.1 的交付，主体属实，不是推倒重来。** 权威门禁、C1–C5、卡点抽查、零生产/未 commit/未建 cron 均可复核。需要修的是：脚本两处缺陷、044 计数与文件数误差、INDEX 023 行漏写 043、以及 044 之后混入工作区的 09-08 指令修订未在 01 登记。

### 1.2 已复核通过（不要再论证）

| 项 | 证据 |
|---|---|
| HEAD 仍 `58ea350`，分支 `fix/ora-12609-p4-error-code`，未 commit | `git rev-parse HEAD`（2026-09-08 核查） |
| 043 起草现场未丢（INDEX/01/README 的 M + 043/两 PROMPT/export 脚本的 ??） | 当前 `git status --porcelain`；044 §0 执行前清单仍在 |
| 权威门禁 044 §2 与产物逐格一致 | `review/gate-runs/20260907-215610/summary.md` 与 `result.json`：compileall/naming/isolation/sidecar_check PASS；主 **1327 passed**；prearchive **283+1 skip**；unit 57；e2e 52+17 skip；legacy 正向+降级 PASS；exit 0；isolation.log=`scanned 67 python files` |
| C1–C5 落地 | INDEX「双模式与终末覆盖」含「EMR 专用出院路径」、无「3 个无转换」；CLAUDE 命令节指针化；101 锚指针段；AGENTS Commands 有 `run_gates_20260906.py`；00 §1 与 AGENTS 互指；023 §0.6 有 043 行 |
| 卡点 A/B 行号抽查属实 | 导出 `07_*.md`：2252/2473 heredoc 截断；3048 Temp exe 消失；3058 PS1 BOM；3064 Python Popen |
| 新测试当前全绿 | 2026-09-08 本核查会话：`tests/test_{agent_efficiency_skills,gate_scripts_20260906,instruction_governance_20260907,env_guard_conftest}.py` **34 collected / 34 passed**（6+19+7+2） |
| 零生产、未创建 cron、锚未上抬 | 044 §6/§8.5；`gate_anchors.json` 仍是首版 1295/283+1/57/52+17 |
| 既有测试零删改 | `git diff --stat` 的 `tests/` 仅 `conftest.py`（加守卫）；四份新测试为 ?? |

### 1.3 必须修（F 包对应）

| # | 缺陷 | 严重度 | 证据 | 处置 |
|---|---|---|---|---|
| D1 | `run_legacy_rule_center_e2e` **双轮都 PASS 时未传入 duration**，表上耗时恒为 0 | P1 | `scripts/run_gates_20260906.py` 约 294–295 行 `return GateResult(..., "PASS", note=...)` 无 `duration=`；权威 `result.json` `legacy_rule_center_e2e.duration_sec=0.0`；FAIL 降级路径（287–288）反而加了两轮耗时 | F1 补 `duration=positive.duration + degraded.duration`；单测锁非 0 |
| D2 | sidecar **拉起后 `_wait_port` 失败直接 return，未杀进程树** | P1 | 同文件约 263–267 行：`sidecar_proc = _spawn_sidecar(...)` 后 wait 失败即 return FAIL，无 `_kill_process_tree`。会留下 18600 占用（卡点 6 同类） | F1 失败路径必须杀树；单测断言调用了 kill |
| D3 | 模块头注释仍写「探测 18080 **与 18600 都在听**才跑」，与实现（只探测 18080，sidecar 自起自灭）不一致 | P2 | 文件头第 6 行 vs `run_legacy_rule_center_e2e` 文档字符串/实现；044 §8.4 已说明改口，脚本头未改 | F1 改注释对齐实现，**不改** 043 历史作业书正文 |
| D4 | 044 写 R2「**17** 用例」、新测试合计 **32**（6+17+7+2）；现场已是 **19 / 34** | P2 | `tests/test_gate_scripts_20260906.py` 现 19 个 `def test_`（含文件头 `test_external_sidecar_*` / `test_owned_sidecar_*`）。044/01/INDEX 仍写 32。权威跑 1327=1295+32，说明这 2 条是 **215610 之后**补的，未重跑 `--full`、未回写 044 | F2：044 **文末追加**更正，不改写原 §1 数字；F5 按 §7 重跑门禁 |
| D5 | 044 §0「本轮新增 **11** 项（3 skill 目录、3 脚本、gate_anchors.json、044、4 测试文件）」括号内实为 **12** | P2 | 3+3+1+1+4=12 | F2 更正节写明 |
| D6 | INDEX **023 行**状态句仍只写「§0.6 已追加 031 与 041」，漏 043/044 | P2 | `docs/INDEX.md` 023 行；023 正文 §0.6 其实已有 043 行 | F2 只改 023 **这一行状态句**，不重写 023 历史正文 |
| D7 | 044 §0 称「全清单见 `git status --porcelain`（044 收尾时留档）」——**仓库内无该留档文件** | P2 | 全仓无对应留档路径 | F2 更正节声明「未留档，以当时 prose + 当前 porcelain 为准」；本轮不要补造 09-07 伪留档 |
| D8 | **2026-09-08 指令修订未在 01 登记** | P1 | `01_统一修改记录.md` 无「2026-09-08」行；INDEX 文首已写「指令治理更新时间：2026-09-08」；023 §9.1 有「用户批准指令治理修订」；备份=`review/instruction-revision-20260908/`。改动超出 043 白名单：AGENTS 核心原则、00 §2/§4/§6/§8、023 §9.1、`med-audit-history-remediation`、三份 043 Skill 正文 | F3 **补登记、不回滚**（INDEX 已记用户批准）。044 §11 声明：这些改动**不属于 043/044 交付** |

### 1.4 明确不是缺陷（禁止当修复项）

- 执行日 09-07 vs 文件名 20260906：044 §8.1 已说明。
- 未跑 `update_gate_anchor`、未创建 cron：043 裁定 6 + 044 §6/§8.5，**仍等用户逐条批准**。
- 043 §3.3 仍写「18080 与 18600 都在听才跑」：历史作业书，**不改写**；以脚本实现 + demo-stack skill 为准。
- `--full` 整体 PASS 把可选 legacy 的 SKIPPED 当非失败：043 原设计；必测项 SKIPPED 不算覆盖（gates skill 09-08 已写）。本轮不改整体退出码语义。
- 09-08 对 AGENTS/00/技能「自主执行与完成条件」的修订：用户已批准，**保留**。
- 上抬锚 1295→1327+：仍等用户批准，本轮不做。

### 1.5 工作区分层（提交时必须按层核对，禁止一锅端）

| 层 | 内容 | 本轮 |
|---|---|---|
| A 043 起草现场 | INDEX/README/01 的早期 M；043；两份 PROMPT-20260906；`export_zcode_conversations_20260906.py` | 保留 |
| B 043 执行（044） | 3 Skill 目录、3 门禁脚本、`gate_anchors.json`、044、4 份新测试、conftest 守卫、C1–C5 文档 | 保留；只允许 F 包白名单内修补 |
| C 09-08 指令修订 | AGENTS 核心原则、00 §2/4/6/8、023 §9.1、history-remediation、三份 Skill 正文微调、INDEX 文首 | **保留不回滚**，F3 补登记 |
| D 本作业书 | 045、PROMPT-20260908、INDEX 045 行、023 §0.6 045 行、README 入口、01 本行 | 编制会话已落；执行 AI 只更新状态/追加 044 §11/01 执行行 |

---

## 2. 本轮纪律（违反任一条=执行作废）

1. 零生产访问：不 SSH、不 docker、不碰生产 config/Oracle/Dify/Relay。
2. 不改 `app/**`、`prearchive_service/prearchive/**`、规则 JSON、`static/**`、`frontend/src/**`、`docker-compose*.yml`、`.env*`。
3. **禁止 reset / clean / stash**；层 A/B/C 全部保留。
4. **044 §0–§10 数字与原文不改写**；更正只追加 §11（append-only）。不改写 036–043 历史正文。
5. 不回滚 09-08 指令修订。
6. 不创建 cron/schtasks；不跑 `update_gate_anchor`（除非用户在本任务中另批）。
7. 用户未要求不 commit/push。
8. PHI 不进新产物。
9. 测试只增不减；禁止为凑绿削弱既有断言。
10. 改任何 `docs/**/*.md` 同步 INDEX；结束追加 01 一行。

---

## 3. 已裁定事实（禁止再争论）

1. 044 主体合格，本轮是修补不是重做 R1–R5。
2. 交付落点=**044 文末 §11** + 本文件勾选；**不新建 046**。
3. D1/D2 是脚本真缺陷，必须改 `scripts/run_gates_20260906.py` 并补单测。
4. 09-08 指令修订执行者在 01 中写 **未署名AI**，推测依据=INDEX 文首 + `review/instruction-revision-20260908/` + 023 §9.1「用户批准指令治理修订」；不得冒充为 043/044 执行者或本编制者。
5. 门禁：F1 之后必须 `--quick`；`--full` 见 §7（demo 未起则 legacy 标 SKIPPED 并在 044 §11 声明，禁止把 SKIPPED 写成双轮完成）。
6. 锚文件保持首版数字。
7. INDEX 023 行只补「§0.6 已含 043（交付=044）」类状态句，不重写 023 其它段落。

---

## 4. 任务包（按序，红则停）

### F0 — 冻结基线

记录 `git status --porcelain` + `git rev-parse HEAD` 到 `review/exec-log.md`（不入库）。确认 HEAD=`58ea350`、层 A/B/C 仍在。禁止 reset。

**验收：** exec-log 有 F0 一行；未丢 043/044 文件。

### F1 — 修 run_gates 两处缺陷 + 注释对齐

**做：**

1. PASS 路径补 `duration=positive.duration + degraded.duration`（与降级 FAIL 路径对称）。
2. `_spawn_sidecar` 之后任何提前 return（wait 失败 / 正向 FAIL）必须 `_kill_process_tree(sidecar_proc.pid)`（`sidecar_proc is not None` 才杀）。
3. 文件头注释改为：只探测 18080；无 demo → `SKIPPED(no-demo)`；无外部 sidecar 则自起、正向后杀树再跑降级；外部占用 18600 → 只跑正向，汇总 `SKIPPED(external-sidecar)`，不得擅杀。

**测试：** 在 `tests/test_gate_scripts_20260906.py` **追加**（不要改坏现有 19 条）：

- 自建 sidecar 双轮 PASS 时 `result.duration == positive.duration + degraded.duration`（mock 两轮 duration）。
- `_wait_port` 失败时断言调用了 `_kill_process_tree`，且返回 FAIL。

**验收：** 新单测绿；原 19 条仍绿。

### F2 — 044 §11 核查更正 + INDEX 023 行

**做：** 在 `docs/ACTIVE/044_043_EXECUTION_DELIVERY_REPORT_20260906.md` **文末追加** `## 11. 核查更正（2026-09-08，作业书=045）`，至少包含：

- 总判：主体属实；权威跑仍以 215610 为准。
- D1–D8 表（修了哪些、哪些只更正文档）。
- 测试计数更正：现场 34=6+19+7+2（权威跑当时 32=6+17+7+2，多出的 2 条为 215610 之后补的 sidecar 双轮单测）。
- 新增文件括号计数 11→12。
- git status 留档不存在。
- 09-08 指令修订不属于 043/044。
- 回滚说明：044 §9 清单不覆盖 09-08 文件；回滚 044 不得误还原 C 层。
- 本轮门禁表（复制脚本 Markdown；`--full` 若 SKIPPED 必须声明）。

INDEX：023 行状态句补上 043/044；044 行加「2026-09-08 核查更正见文末 §11，作业书=045」；045 行改为已执行；盘点前缀更新。**不要改写**盘点里 09-07 的 1327 等历史数字。

**验收：** 044 原 §1「17/32」仍在；§11 有更正；INDEX 023 行能 grep 到 043。

### F3 — 01 补登记

**做：** `开发起步包/01_统一修改记录.md` **追加两行**（不改历史行）：

1. 补登记 09-08 指令修订：执行者=`未署名AI`；类型=文档；摘要写清改了 AGENTS 核心原则 / 00 §2§4§6§8 / 023 §9.1 / 四份技能 / INDEX 文首；生产写入=无；证据=`review/instruction-revision-20260908/` + INDEX 文首。
2. 本轮 045 执行行：类型=工具/文档/复核；列 F1–F5 要点与测试数；生产写入=无；证据=044 §11 + gate-runs 新目录。

**验收：** 01 能 grep 到 `2026-09-08` 且至少两行；历史 09-07 044 行未被改写。

### F4 — 044 相关测试

```
python -m pytest tests/test_agent_efficiency_skills.py tests/test_gate_scripts_20260906.py tests/test_instruction_governance_20260907.py tests/test_env_guard_conftest.py -q
```

**验收：** 0 failed；collected ≥ 36（原 34 + F1 至少 2 条）。

### F5 — 门禁

见 §7。checkpoint 写 `review/exec-log.md`。

---

## 5. 允许修改的文件清单

**可新建：** 无（045 与 PROMPT-20260908 由编制会话已建）。F 包执行中可新建 `review/gate-runs/<ts>/`、更新 `review/exec-log.md`（均不入库）。

**可修改：**

- `scripts/run_gates_20260906.py`（仅 D1/D2/D3）
- `tests/test_gate_scripts_20260906.py`（只追加 F1 单测）
- `docs/ACTIVE/044_043_EXECUTION_DELIVERY_REPORT_20260906.md`（只追加 §11）
- `docs/INDEX.md`（023/044/045 状态句 + 盘点前缀）
- `docs/ACTIVE/023_*`（**仅 §0.6 把 045 行从待执行改为已执行**，或若编制行已是待执行则改状态字；不重写其它行）
- `开发起步包/01_统一修改记录.md`（追加）
- `开发起步包/README.md`（045 入口改为已执行，指向 044 §11）
- 本文件勾选/状态字（可选）

**禁止修改：** `app/**`、`prearchive_service/prearchive/**`、`prearchive_service/rules/*.json`、`config/config.json`、`static/**`、`frontend/src/**`、`docker-compose*.yml`、`.env*`、`docs/reference/gate_anchors.json`（不上抬）、036–043 正文、044 §0–§10、AGENTS/00/CLAUDE/101/history-remediation（09-08 已改，本轮不动）、既有测试断言。

---

## 6. 逐包验收表

| 包 | 新测试最低 | 关键验收 |
|---|---|---|
| F0 | 0 | HEAD=58ea350；porcelain 含 043/044；未 reset |
| F1 | 2 | duration 非 0；wait 失败必杀树；头注与实现一致；原 19 条仍绿 |
| F2 | 0 | 044 §11 存在；原 §1 数字仍在；INDEX 023 行含 043 |
| F3 | 0 | 01 追加 09-08 补登记 + 045 执行行 |
| F4 | （含 F1） | 四文件 pytest 0 failed、collected ≥ 36 |
| F5 | 0 | `--quick` 全 PASS；`--full` 按 §7 |

---

## 7. 全绿门禁

```
python scripts/run_gates_20260906.py --quick
```

必须 PASS（compileall 含 prearchive_service + naming + isolation + sidecar `--check`）。

然后：

```
python scripts/run_gates_20260906.py --full --anchor-file docs/reference/gate_anchors.json
```

- 0 failed；主 pytest ≥ 1295（预期 ≥ 1327，因 F1 新增单测可能再 +2）；prearchive ≥ 283+1 skip；unit ≥ 57；e2e 0 failed。
- 若 18080 未听：legacy 行必须是 `SKIPPED` 且 note 含 `no-demo`，044 §11 **声明未跑双轮**，禁止写成 PASS。
- 若要补双轮：按 `med-audit-demo-stack` 只起 **demo 主服务**（不要预先起外部 sidecar），再跑 `--full`。起停用 demo-stack skill；4173 只报不杀。
- 最终以脚本 Markdown 表为准，复制进 044 §11。

---

## 8. 交付物（044 §11 必须包含）

1. 本核查总判 + D1–D8 处置结果；2. F1 diff 要点（duration / 杀树 / 注释）；3. 本轮门禁表（脚本输出原样）；4. 测试 collected 数；5. 09-08 补登记证明（01 行号/摘要）；6. 未做清单（上抬锚、cron、commit）；7. 回滚增量（相对 044 §9：另还原 `run_gates` 三处 + 删除 §11 + 还原 INDEX 状态句，**不要** checkout 掉 09-08 指令修订）。

---

## 9. 升级出口（停下问用户）

- 必须改业务代码/生产才能过门禁。
- 必须回滚 09-08 指令修订才能过测试。
- 锚低于 1295 且根因在 037/039/041 旧改动。
- 用户要求本轮就创建 cron 或上抬锚。
- 作业书本身缺陷导致包红。

---

## 10. 完成定义

- [ ] F0–F5 验收全过
- [ ] 044 文末 §11 已追加且原 §0–§10 未改写
- [ ] INDEX 023/044/045 + 01 两行 + README 入口
- [ ] 未 commit、未 push、零生产、未创建定时任务、未上抬锚
- [ ] 层 A/B/C 工作区未丢
