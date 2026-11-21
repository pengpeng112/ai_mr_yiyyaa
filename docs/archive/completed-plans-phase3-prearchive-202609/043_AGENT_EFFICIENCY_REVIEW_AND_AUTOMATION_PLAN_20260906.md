# 043 — 跨会话效率治理与自动化一次性执行计划（Skill 沉淀/脚本化/指令治理/卡点台账/回归重跑）

> 文档编号：043 ｜ 编制：2026-09-06 ｜ 编制者：ZCode/GLM-5.3（基于 13 个历史会话导出与仓库取证）
> 版本：**v1.1**（2026-09-06 外部 AI 复核 18 条意见全采纳修订：弃行号按主题、白名单补 023 §0.6、锚文件时序解死锁、4173 只报不杀、env 审计空窗不算失败、--full 补 legacy 规则中心 E2E 等）
> 性质：**从属 023 的本地一次性作业书**；不构成生产写入授权，不改变任何业务行为，不切换任何入口。
> 完成定义：按本文做完 R1–R5，门禁全绿，交付报告写入 `docs/ACTIVE/044_043_EXECUTION_DELIVERY_REPORT_20260906.md`（文件名钉死，与 038/040/042 命名一致）。
> 配套提示词：`开发起步包/PROMPT-20260906_跨会话效率治理一次性执行.md`（v1.1）

---

## 0. 修订记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v1.0 | 2026-09-06 | 初稿 |
| v1.1 | 2026-09-06 | 外部 AI 复核后修订（全采纳）：①C1 **作废一切行号**，改写目标=功能状态表主题行「双模式与终末覆盖」，静态测试锁子串不锁全文；②§5 白名单增「023 §0.6 追加一行」，并明确 036-042/020 等带日期历史正文与历史数字一律不动；③**首版 `gate_anchors.json` 随 R2 落地**，run_gates 未传 `--anchor-file` 或文件不存在时只出表不比锚；101 只加指针不写数字；④R3.6 清扫范围=只处理自称"当前锚"的句子；⑤R4 本地修复改为 **conftest autouse 环境快照守卫**，审计空窗不算失败，卡点台账不凑数；⑥R5 规则关闭只写 044 不回改 042；`--full` 补可选 legacy 规则中心 E2E（无 demo 则表内标 SKIPPED，禁止默认覆盖）；⑦clean_demo_ports **4173 只报不杀**、netstat 中英文双关键词；⑧PROMPT 基线承认脏工作区=043 起草现场；⑨`--quick` 缩为真冒烟（compileall 含 prearchive_service+naming+isolation+sidecar --check）；⑩停机条件统一为"包红即停，根因是作业书缺陷→升级出口"；⑪R1 只静态测试；⑫Skill description 必须含触发词；⑬证据边界声明=仅 ZCode 执行会话。 |

## 0.1 用户原始需求（2026-09-06，逐条对应 R 包）

1. 找出跨会话反复出现的 Prompt，把稳定流程沉淀成 Skill；→ **R1**
2. 找出人工重复执行的步骤，把它们改成脚本、集成或 cron job；→ **R2**
3. 检查项目指令和长期记忆，合并重复内容，修正冲突；→ **R3**
4. 回看经常中断的任务，定位卡住 Agent 的文件、权限、测试和上下文缺口；→ **R4**
5. 用真实项目重跑回归，依据失败案例决定哪些规则继续保留。→ **R5**

## 1. 证据盘点（编制时已取证，执行 AI 禁止再当新发现重做）

数据源：`review/conversations-export-20260906/`（13 个主会话，2026-07-07～2026-09-06）+ 仓库 grep。

> **证据边界（重要）**：导出仅覆盖 **ZCode 执行侧会话**。037/041 作业书起草（Grok）、039 计划（Codex）等外部 AI 会话**不在包内**；`review/conversation-analysis-20260906/` 当前不存在。R4 补挖与 044 结论均以此边界声明，未纳入的在 044 记「未纳入」，**不得自称跨 AI 穷尽**。

### 1.1 反复出现的流程（R1 依据）

| 流程 | 出现频度 | 证据 |
|---|---|---|
| 全绿门禁序列（compileall/pytest/naming/prearchive/isolation/typecheck/unit/build/e2e/+sidecar --check） | `compileall` 出现于 10/13 会话；pytest 13/13 | 导出全文 grep |
| 一次性执行模式（PROMPT-* → 作业书 NNN → T0-Tn → 门禁 → 交付报告 NNN+1 → INDEX/01 登记） | ≥6 次完整执行（028/031/0901/0902×2/0904） | PROMPT-20260827/20260828/20260831/20260901/20260902/20260904 |
| 会话启动五步（AGENTS→README→00→01 末 10 行→INDEX） | 每会话开头（写入 AGENTS 的强制项） | 各会话 §1 |
| 台账登记收尾（01_统一修改记录 append + INDEX 同步） | 10/13 会话 | 导出全文 grep |
| demo 隔离环境编排（demo_env create/serve/stop + sidecar 双终端） | 5/13 会话（035/oneshot/039/041） | 导出全文 grep |

### 1.2 人工重复步骤（R2 依据）

1. **门禁 10 条命令逐条手敲**——每轮执行至少 2 遍（基线+收尾），且后台任务下 pytest 摘要行会被吞（需二进制安全 grep 绕过）。scripts/ 现无聚合脚本。
2. **Windows 端口残留清理**——041 T6 实录 18600/18080 残留需手写 netstat+taskkill /T；无现成脚本。
3. **基线锚数字人工比对**——锚散落在 040/041/042 各文档，每轮人工对照。
4. **demo 双终端手动起停**——sidecar 与主服务分终端，`--with-demo-e2e` 编排存在但 041 实际未用（042 §7 偏差 2）。
5. **git 提交信息拼装+01 补 hash**——每轮授权后手工。

### 1.3 指令文件冲突与重复（R3 依据）

| # | 问题 | 证据 | 处置方向 |
|---|---|---|---|
| C1 | **功能状态表「双模式与终末覆盖」行**仍写「生产 discharge 仍配置 3 个无转换类型」，与 AGENTS 2026-09-01 只读核验结论冲突（实为空 SQL 的 EMR 专用出院路径，非"无转换漏患者"） | INDEX 功能状态表该行 vs `AGENTS.md` Dual-Mode 节。**禁止用行号定位**（行号随现役文档表增删漂移，v1.0 的 :88 已失效） | 按主题行改写，改写稿见 §4 R3.1 |
| C2 | CLAUDE.md「常用命令」节与 AGENTS「Commands」节大面积重复 | 两文件对比 | CLAUDE 命令节压缩为指针（"命令唯一来源=AGENTS.md Commands 节"），围栏内最多保留 2-3 条 CLAUDE 独有命令（如 init_rbac、docker logs） |
| C3 | 测试锚数字多处漂移（1211/1254/1272/1295），无"当前锚"单一来源 | grep 实证 | **机器源=** `docs/reference/gate_anchors.json`（R2 落地首版）；101 只加一小段指针（"当前数字以 json 为准，禁止手改"）；INDEX 的 101 行补 json 路径一句；历史交付报告数字不改写 |
| C4 | 门禁命令清单在 AGENTS/041 §8/042 §4/各 PROMPT 至少 4 份拷贝 | 文档 grep | R2 脚本成为唯一执行入口后，AGENTS Commands 节末加一行指向脚本（不改历史文档） |
| C5 | 00_AI协作规则 §1/§2/§3 与 AGENTS「会话启动/散文件治理」语义重叠 | 两文件；00 文首已有"冲突以 AGENTS 为准" | 不合并不复制：00 §1 末加一行互指（指向 AGENTS 会话启动节）；AGENTS 对应节加一行指向 00 |

### 1.4 已知卡点台账（R4 种子，执行 AI 补全证据）

| # | 卡点 | 类别 | 状态 | 可否本地修 |
|---|---|---|---|---|
| 1 | Docker daemon 不可用 → WP9 镜像 SBOM/签名/备份恢复演练欠账 | 环境 | 阻塞（023 WP9） | 否（环境/运维） |
| 2 | C# 提醒助手冒烟被本机安全策略阻断 | 环境/权限 | 留试点机（031 W1） | 否（用户/信息科） |
| 3 | EMR/HIS/医保接口材料未到（G2/G3/G5） | 外部材料 | 等待 | 否 |
| 4 | W10 清单/心电 xd 对接信息/FID 检验首页族回填 | 外部材料 | 等待 | 否 |
| 5 | Playwright 未装（031 当时 UI E2E 标待跑） | 环境 | **已解决**（后续会话已装并真机跑） | — |
| 6 | 18600/18080 端口残留致 E2E 偶发失败 | 环境 | 041 T6 实录，手工绕过 | **是**（R2 清理脚本） |
| 7 | 测试进程内 env 全局污染（041 T9 实录一类问题：直写 os.environ 泄漏到后续用例，全量跑才暴露） | 测试缺口 | 已修一处（test_isolated_prearchive_bff teardown）；**同类风险无通用守卫** | **是**（R4 conftest 守卫） |
| 8 | 后台任务吞 pytest 摘要行（Windows 换行/缓冲） | 工具缺口 | 本会话实录 | **是**（R2 脚本内聚捕获） |
| 9 | 超长会话上下文压缩（769 消息会话） | 上下文 | 已由台账/checkpoint 制度缓解 | 制度化即可（R1 skill 内固化） |
| 10 | SSH/Vastbase 密钥每次人工提供 | 权限（设计如此） | 正常 | 否（红线，不改） |

**R4 补挖口径（防灌水）**：只在 13 个导出会话中找「Agent 停住/重做/换路」事件，每条必须带会话文件名+小节号证据；关键词 grep（失败/卡/阻塞）只作线索不作收录依据；**十种子条必须全部落地，追加条有证据才收，不设数量下限**。Grok/Codex 会话缺口在 044 记「未纳入」。

### 1.5 规则取舍候选（R5 依据）

保留（有失败案例背书）：oneshot E2E 默认 skip（RP-I）、LEGACY_E2E 外部 webServer 门、prearchive isolation 零 import 门、naming 门、compileall 含 scripts+prearchive_service（**以 041 §8 为准，AGENTS Commands 那条不含 prearchive_service，脚本不得照抄**）、双调度独立锁、relay 部分保存红线。
清理/降级（只写 044，**不回改任何历史交付报告**）：文档中自称"当前锚"却写旧 e2e 46 的句子（带日期的历史数字一律不动）；`docker-compose.demo.yml` 可选项正式关闭（042 已写"可选项未做、脚本启动"，044 登记终态即可）；各文档重复门禁命令清单改指向脚本（仅 AGENTS Commands 节加一行，历史文档不动）。

## 2. 本轮纪律（违反任一条=执行作废）

1. **零生产访问**：不 SSH、不 docker、不碰生产 config/Oracle/Dify/Relay、不启预检进程。
2. 不改业务行为：不动 `app/`、`prearchive_service/prearchive/` 下任何业务代码；不改 14 条正式规则 JSON；不切 UI 入口；不动 Dify/推送/调度。
3. 新增文件只允许 §5 清单；测试只增不减（主 ≥1295、prearchive ≥283+1skip、unit ≥57、e2e 0 failed）。
4. 改任何 `docs/**/*.md` 同步 `docs/INDEX.md`；结束追加 `开发起步包/01_统一修改记录.md`。
5. 不删 CLAUDE.md/AGENTS.md/00 任何文件，只做去重与指针化（C2/C5）。
6. **不擅自创建任何定时任务**（cron/schtasks/自动化）：R2 的定时项仅产出"建议+命令"，默认不启用，等用户批准。
7. PHI 不进新产物；新脚本/文档引用会话导出时只引文件名与小节号。
8. 既有测试禁改凑绿；对 C1 类文档修正必须给出 AGENTS 出处；**带日期的历史文档数字/正文一律不改写**（append-only 精神）。
9. 用户未要求不 commit/push。
10. 执行前记录 `git status`/HEAD。**工作区=043 起草现场（已知未提交：INDEX/README/01 三处 M + 043/两份 PROMPT/export 脚本 ??），全部保留，禁止 reset/clean/stash。**

## 3. 已裁定事实（禁止再争论）

1. Skill 落位 `.agents/skills/<name>/SKILL.md`，格式参照现有 `med-audit-history-remediation`（YAML frontmatter：name+description，正文中文）。**description 必须含触发词**（何时必须加载本 skill），否则其他 AI 不会自动用。
2. 本轮沉淀 **3 个** skill：`med-audit-gates`（任何改动后回归/交付前）、`med-audit-oneshot-delivery`（接手 PROMPT 一次性执行任务时）、`med-audit-demo-stack`（起停隔离 demo/规则中心 E2E 编排时）。
3. 门禁聚合脚本唯一入口：`scripts/run_gates_20260906.py`。
   - `--quick`（真冒烟，分钟级）= compileall（**app tests scripts prearchive_service**）+ naming + isolation + sidecar `--check`。
   - `--full`（约数十分钟）= quick 全部 + 主 pytest + prearchive pytest + typecheck + unit + build + e2e + **可选 legacy 规则中心 E2E**（探测 18080 与 18600 都在听才跑，否则表内标 `SKIPPED(no-demo)` 并在 044 声明，**禁止默认当成已覆盖**）。
   - 锚比较：显式传 `--anchor-file` 且文件存在才比锚退出（非零=低于锚）；未传/文件不存在只出表。
   - 摘要解析二进制安全（bytes/`errors=replace`）；每项完整输出落 `review/gate-runs/<时间戳>/`；**最终以脚本打印的 Markdown 门禁表为准**，执行 AI 不得去翻可能截断的原始日志。
   - e2e 前探测 4173：占用则**警告并复用**（与 Playwright `reuseExistingServer:!CI` 一致），除非 `--strict-ports` 才 fail。
4. C1 修正口径以 **AGENTS.md Dual-Mode 节（2026-09-01 生产只读核验）** 为准；**定位用主题行不用行号**。
5. 锚单一来源：机器源=`docs/reference/gate_anchors.json`（**首版随 R2 落地**：主 1295/prearchive 283+1skip/unit 57/e2e 52+17skip/check PASS）；101 只加指针段；update_gate_anchor 只改 json 不碰 101。
6. 定时任务本轮不创建，只交付建议清单。
7. CLAUDE.md 处置=去重+指针化，不删除；00 与 AGENTS 保持双文件，仅互指一行。
8. R4 本地修复=**tests/conftest.py autouse fixture**：每个测试前快照 `os.environ`、测试后恢复（拦住"全量才暴露"的跨文件泄漏）；审计发现业务侧泄漏点（如 app/services/isolated_mode.py 的 `os.environ.update`）**只记录不改**（禁区）。
9. 停机条件（全文档统一）：**包红即停**；若根因是本作业书缺陷 → 走 §9 升级出口问用户，禁止现场改口径硬过。
10. 交付文件名钉死：`docs/ACTIVE/044_043_EXECUTION_DELIVERY_REPORT_20260906.md`。

## 4. 任务包规格（按序执行，红则停）

### R1 — Skill 沉淀（3 个）

**做：**
1. `.agents/skills/med-audit-gates/SKILL.md`：description 含触发词（"改动后回归/交付前/门禁/全绿检查"等）；正文=命令（`python scripts/run_gates_20260906.py --quick|--full`）、锚源位置（gate_anchors.json）、失败处置（先定位根因再重跑，禁止跳过单项、禁止翻截断日志以脚本表为准）。
2. `.agents/skills/med-audit-oneshot-delivery/SKILL.md`：description 含触发词（"一次性执行/PROMPT-*/作业书/交付报告"）；正文=全流程（读 PROMPT→作业书 T0-Tn→每包测试→checkpoint 到 review/exec-log.md→门禁→交付报告 NNN+1 结构照 042 §1-§10→INDEX/01 登记→等批准 commit）；附已验证模板指针（041/042 对）。
3. `.agents/skills/med-audit-demo-stack/SKILL.md`：description 含触发词（"demo/隔离环境/规则中心 E2E/sidecar"）；正文=demo_env create/serve/stop + sidecar --serve/--check + 端口清理脚本用法（4173 只报不杀）+ 降级轮 RULE_CENTER_SIDECAR=0 口径 + 已知豁免 `/api/users/me`。
4. 三个 skill 均含"红线引用"（指向 AGENTS/00 对应节名），不复制正文。

**测试/验收：** **仅静态契约测试**（不 subprocess 调脚本——run_gates 在 R2 才出现）：每个 skill 存在性+frontmatter 含 name/description+description 含触发词+红线指针节名，≥3 用例。

### R2 — 脚本化（3 脚本 + 首版锚 json + 1 建议）

**做：**
1. `scripts/run_gates_20260906.py`：行为按 §3.3 裁定（quick/full 两档、锚比较可选、二进制安全、Markdown 表、4173 警告复用、可选 legacy 规则中心步骤）。
2. `scripts/clean_demo_ports_20260906.py`：
   - **默认可杀端口=18080/18081/18082/18600**；**4173 只报告不杀**（Playwright preview 归属，注明原因）。
   - netstat 解析**同时匹配 `LISTENING` 与 `侦听`**（中文 Windows 本地化）；Windows `taskkill /PID <pid> /T /F`；POSIX 只杀脚本自身创建的进程组（`start_new_session`），不误伤父进程。
   - 默认 `--dry-run` 只打印；`--yes` 才执行。
3. `scripts/update_gate_anchor_20260906.py`：读取一次 run_gates 结果 JSON → **只更新 `docs/reference/gate_anchors.json`**（幂等、带时间戳；**不改 101**）。
4. **首版 `docs/reference/gate_anchors.json` 随本包落地**（手写首版即 §3.5 数字），解 R2/R3 时序。
5. 定时建议（不执行）：044 交付"可选 cron 清单"（例：每工作日 22:00 `run_gates --quick`），等用户逐条批准。

**测试/验收：** `run_gates --quick` 真机跑通产出 Markdown 门禁表；**未传 --anchor-file 时不比锚也退出 0**（单测覆盖）；传锚且低于锚→非零（单测 mock）；锚 json 首版存在且 schema 校验过；`clean_demo_ports --dry-run` 在无残留时打印 none、4173 占用时打印 REPORT-ONLY；update 脚本幂等（跑两次 json 一致）；≥5 用例（参数解析/摘要解析函数/锚比较/端口解析 mock/netstat 中英文双关键词）。

### R3 — 指令治理（C1–C5）

**做：**
1. C1：改 INDEX 功能状态表**主题行「双模式与终末覆盖」**（grep 该主题定位，禁止行号），改写稿（保留后半未完成句）：
   > 双源已生产启用并有单轮对账；本地正式六类安全模板已闭包；生产 discharge 下 admission_vs_first_progress / surgery_chain / discharge_vs_frontpage 为空 SQL 的 EMR 专用出院路径（2026-09-01 只读核验，非「无转换漏患者」）；`syssvsscbc` 日增量锚点、六类真实 SQL 和连续观察未完成。
2. C2：CLAUDE.md「常用命令」节压缩：出现指针句「命令唯一来源=AGENTS.md Commands 节」；围栏内不再完整重复 uvicorn/`pytest tests/ -v`/docker-compose up；最多保留 2-3 条 CLAUDE 独有项（如 init_rbac、docker logs）。
3. C3：101 只加一小段指针（「当前门禁锚以 `docs/reference/gate_anchors.json` 为准，禁止手改本节」）；INDEX 的 101 行补一句 json 路径；**不改任何历史数字**。
4. C4：AGENTS「Commands」节末加一行："Gate aggregation: `python scripts/run_gates_20260906.py --full`"（不改其他行；AGENTS 原有 compileall 行保持原样）。
5. C5：00 §1 末加一行互指（"会话启动顺序详见 AGENTS.md 对应节，语义一致"）；AGENTS 会话启动节加一行指向 00。
6. 清扫（窄口径）：grep 全仓**自称"当前锚/当前基线"却写 e2e 46** 的句子并修正；**023/020/036/038 等带日期的历史数字一律不动**（与 C3 append-only 一致）。
7. **023 §0.6 追加一行 043/044**（仿 041 先例，只加行不重写既有行）。

**测试/验收：** 静态测试：INDEX 功能状态表「双模式与终末覆盖」行**不再含「3 个无转换」且含「EMR 专用」**（只锁该行子串，不锁 INDEX 全文）；CLAUDE 命令节含指针句且围栏内不再含 `uvicorn app.main:app --reload` 完整重复；≥2 用例。

### R4 — 卡点台账 + 本地可修项

**做：**
1. §1.4 十条种子全部落进 044《卡点台账》（列：卡点/类别/证据会话+小节/当前状态/责任人/下一步）；按 §1.4 补挖口径追加（有证据才收，无下限）。
2. 本地修复一：端口清理脚本（R2.2，归本包验收引用）。
3. 本地修复二：`tests/conftest.py` 新增 autouse fixture——`os.environ` 快照/恢复（`monkeypatch` 之外兜底直写场景）；配 1 个守卫用例（测试 A 直写 env → 测试 B 断言已恢复，模拟跨文件泄漏）。
4. env 审计清单照出落 044 附录：已修 1 处（test_isolated_prearchive_bff）；业务泄漏点（app/services/isolated_mode.py `os.environ.update`、scripts/demo_env.py）**只记录不改**；**审计空窗（零新增泄漏）不算失败**。

**测试/验收：** 台账十条种子全落地+追加条全带证据；conftest 守卫存在+守卫用例绿；全量主 pytest 仍 ≥1295 绿。

### R5 — 回归重跑 + 规则取舍

**做：**
1. `python scripts/run_gates_20260906.py --full` 真机全量（预期数十分钟，一次跑完），产出 2026-09-06 Markdown 门禁表；若 18080/18600 未起，legacy 规则中心行标 `SKIPPED(no-demo)` 并在 044 声明（想跑可手工起 demo 后单跑该项补录）。
2. 失败案例复盘：失败项（若有）归因（环境/代码/口径）写 044，据此出《规则取舍表》。
3. 《规则取舍表》（保留/清理/降级 三档+理由+证据引用）覆盖 §1.5 全部候选；**被清理/降级规则的终态只写 044，不回改 036-042/020 正文**（docker-compose.demo.yml 关闭即此口径）。
4. R5 全量过后可选跑 `update_gate_anchor`（新测试可能把 1295 顶上去；更新只落 json）。

**测试/验收：** 门禁表全绿（计数 ≥ §2.3 锚或 json）；取舍表每行有证据引用；SKIPPED 项有声明。

## 5. 允许修改的文件清单

**可新建：** `.agents/skills/med-audit-{gates,oneshot-delivery,demo-stack}/SKILL.md`；`scripts/{run_gates,clean_demo_ports,update_gate_anchor}_20260906.py`；`docs/reference/gate_anchors.json`；`docs/ACTIVE/044_043_EXECUTION_DELIVERY_REPORT_20260906.md`；相关新测试文件；`tests/conftest.py`（若不存在则新建，存在则只加 autouse 守卫）。

**可修改：** `docs/INDEX.md`（C1 主题行+043/044 行+101 行补 json 路径）、`docs/reference/101_FEATURE_BASELINE.md`（锚指针段）、`CLAUDE.md`（命令节指针化）、`AGENTS.md`（Commands 节加聚合脚本一行+会话启动节加 00 互指一行）、`开发起步包/00_AI协作规则.md`（§1 互指一行）、`开发起步包/README.md`（入口行）、`开发起步包/01_统一修改记录.md`、`docs/ACTIVE/023_*`（**仅 §0.6 追加 043/044 一行**）、tests/ 下守卫用例相关、`review/exec-log.md`（checkpoint，不入库）、`review/gate-runs/`（脚本产物，不入库）。

**禁止修改：** `app/**`、`prearchive_service/prearchive/**`、`prearchive_service/rules/*.json`、`config/config.json`、`static/**`、`frontend/src/**`、生产相关 `scripts/deploy_*`、`docker-compose*.yml`、`.env*`、**既有交付报告（036-042）正文与 020 等带日期历史文档的数字/正文**、`docs/INDEX.md` 历史行数字。

## 6. 逐包验收表

| 包 | 新测试最低 | 关键验收 |
|---|---|---|
| R1 | 3 | 三 SKILL.md 存在+frontmatter+**description 含触发词**+红线指针；仅静态测试 |
| R2 | 5 | `--quick` 真机门禁表；未传锚不比锚退出 0；传锚低于→非零；锚 json 首版在；清理脚本 dry-run 正确+4173 REPORT-ONLY+中英文 netstat；幂等 |
| R3 | 2 | 双模式主题行子串断言（不含「3 个无转换」含「EMR 专用」）；CLAUDE 指针句+无完整重复命令；101 指针段 |
| R4 | 1 | 十种子全落地+追加全带证据；conftest 守卫+守卫用例绿；全量仍 ≥1295 |
| R5 | 0（证据型） | 全量门禁表（含 legacy 规则中心 PASS 或 SKIPPED 声明）；取舍表全覆盖 §1.5 |

## 7. 全绿门禁（=R2.1 脚本）

```
python scripts/run_gates_20260906.py --full
```

判据同 041 §8 全集并补 legacy 规则中心项：0 failed；主 ≥1295、prearchive ≥283+1skip、unit ≥57、e2e 52+17skip（oneshot 默认 skip）；isolation 零 `import app.*`；sidecar `--check` PASS；legacy 规则中心 E2E PASS 或表内 `SKIPPED(no-demo)`+044 声明。

## 8. 交付物（044）必须包含

1. 执行前后 git status（证明 043 起草现场保留）；2. R1-R5 逐包勾选+新文件清单+测试数；3. 2026-09-06 门禁表（复制脚本 Markdown 输出）；4. **《卡点台账》**（十种子+证据追加，含 Grok/Codex 会话「未纳入」声明）；5. **《规则取舍表》**；6. 指令治理 diff 摘要（C1-C5 各一条前后对照）；7. 可选 cron 建议清单（未启用声明）；8. env 审计附录（已修/只记录/空窗说明）；9. 偏差说明；10. INDEX+01 登记证明。

## 9. 升级出口（停下问用户）

- 必须改业务代码/生产才能过门禁；- 必须删除 CLAUDE/00/AGENTS 内容而非指针化；- 锚低于基线且根因在既有 037/039/041 改动；- 用户材料类卡点需要现在催办；- 任何定时任务创建需求；- **作业书本身缺陷导致包红**（口径冲突/清单缺漏/时序问题）——报告缺陷等裁定，禁止现场改口径硬过。

## 10. 完成定义

- [ ] R1-R5 验收全过（§6）
- [ ] §7 门禁全绿（legacy 规则中心 PASS 或 SKIPPED+声明）
- [ ] `docs/ACTIVE/044_043_EXECUTION_DELIVERY_REPORT_20260906.md` + INDEX（043/044 行）+ 023 §0.6 追加行 + 01 登记
- [ ] 未 commit、未 push、零生产、未创建定时任务、043 起草现场未丢
