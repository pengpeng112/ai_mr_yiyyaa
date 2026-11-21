# 执行任务书 `PROMPT-WP07`：归档前形式核查激活——无纸化打回分析 + 影子模式准备 + 病案室辅助工作台重构

> **所属总计划**：`docs/ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md`（工作包 7 / 10）  
> **预计耗时**：约 3.5 小时  
> **前置依赖**：`WP-02`（`HolographyButton` + `data_scope`）  
> **先读文件顺序**：`AGENTS.md` → `开发起步包/README.md` → `00_AI协作规则.md` → `01_统一修改记录.md` 末 10 行 → `02_协作任务板.md` → **`prompts-064/PROMPT-00_通用事实基线与勘误_必读.md`（尤其 §1.4 预检服务已有能力）** → `prearchive_service/README.md` → `git status --short` 存 `review/064-wp07/git_status_before.txt`。

---

## 一、背景与拍板口径（用户反馈第 8 项，拍板 D3）

1. **线上实锤为什么「一直不行」**（2026-11-19 只读核查）：`med-prearchive` 容器运行 8 周、Oracle 18 张 `MED_PREARCHIVE_*` 表已建但**全部 0 行**。根因是生产 `/app/config/prearchive.prod.json`：① `service.anchor_mode="finished"`（177 上 `finished_date_time` 100% 为 NULL）；② 13 个数据源全部 `enabled:false` 且主机为 `<..._PLACEHOLDER>`；③ 规则未导入生产库。每 5 分钟日志 `[poll] fetch failed`。
2. **两步走**：
   - 第 1 步（立即可做）：接已验证的 `177 JHEMR + 216 HIS/SM`，`anchor_mode="discharge"` 开纯观察影子模式（`push.enabled=false`、`result_delivery.enabled=false`），病案室在系统内看真实缺陷并标注准确性；
   - 第 2 步（拿到无纸化 `10.10.10.93` CDMS 只读账号后）：用 CDMS 人工扣分/打回数据做金标准回测，达标后再考虑 `paperless_rpa` 锚点与对外推送。
3. **后期推送无纸化**：以 **HTTP/WebService** 为主，**同时支持受控中间表写入**；均默认关闭，且只推送病案室人工确认过的缺陷。

> **本包只做本地开发与工具准备。生产配置修改、规则入库、容器重启全部放到 WP-10，由用户逐项批准后执行。**

---

## 二、复用原则（最重要，违反即打回）

`prearchive_service/` 已有以下能力，**必须复用，不得另写平行实现**：

| 需求 | 复用现有实现 | 本包要做的事 |
| --- | --- | --- |
| 规则导入生产库 | `prearchive/rule_service.py::RuleService.import_files(paths, *, apply, actor, …)`（`scripts/run_prearchive_demo_sidecar_20260904.py::do_import_rules` 是现成调用示例） | 写一个薄 CLI 包装（见 3.3），不重写导入逻辑 |
| 金标准回测 | `prearchive/backtest.py::backtest_v2(manual, results, …)` + `render_markdown_v2` | 写「从 CDMS 只读取人工结果 → 组装 `manual` 结构」的适配脚本（见 3.2），先读 `backtest_v2` 的 `manual` 入参格式 |
| HTTP 投递 / 重试 / 死信 | `prearchive/outbox.py::DeliveryWorker` + `prearchive/delivery_wiring.py` | 新增「中间表」投递方式作为同一框架下的另一种传输（见 3.4），不新建独立 Adapter 体系 |
| 病案室确认/误报反馈 | 预检服务 `POST /api/admin/issues/{issue_id}/actions`，主服务 BFF 白名单已有（权限 `prearchive_issue_feedback`） | 前端直接通过主服务现有 BFF 端点调用（先读 `app/routers/prearchive_admin.py` 找到对应的 POST 路由路径） |
| 无纸化规则目录 | `prearchive/paperless.py`、`sync_paperless_rules.py`、`rules/paperless_items_snapshot_20260828.json` | 只读引用，不改语义（AGENTS.md：CDMS 是规则目录/元数据源，禁止接入 PatientContextBuilder.documents） |

**隔离铁律**：`prearchive_service/` 下**零 `import app.*`**；主服务也不得 `import prearchive_service.*`。

---

## 三、后端/预检服务实施

### 3.1 文件白名单
- 新增（预检服务内）：
  - `prearchive_service/scripts/analyze_paperless_rejections_ro.py`
  - `prearchive_service/scripts/paperless_gold_backtest_ro.py`
  - `prearchive_service/scripts/import_rules_cli.py`
  - `prearchive_service/config.shadow.prod.template.json`（与 `config.example.json` 同级；**没有 `config/` 子目录**）
  - `prearchive_service/tests/test_wp07_shadow_tools.py`
- 修改（预检服务内）：`prearchive_service/prearchive/outbox.py`、`prearchive_service/prearchive/delivery_wiring.py`（仅为中间表传输增量扩展）、`prearchive_service/README.md`（补「影子模式」一节）
- 新增文档：`docs/reference/123_PREARCHIVE_SHADOW_AND_PAPERLESS_PUSH_RUNBOOK_20261119.md`（并同步 `docs/INDEX.md`）
- 修改前端：`frontend/src/features/governance/WorkbenchPage.vue`（路由 `/governance/workbench`，菜单 ID `workbench`）
- 新增前端单测：`frontend/tests/unit/prearchive-workbench.test.ts`
- `review/064-wp07/`、`开发起步包/01`、`02`

### 3.2 只读脚本（凭据只从环境变量读；全部只 `SELECT`；输出一律脱敏）
1. **`analyze_paperless_rejections_ro.py`**（近 N 天无纸化人工质控盘点）：
   - 环境变量：`PAPERLESS_ORACLE_DSN`、`PAPERLESS_ORACLE_USER`、`PAPERLESS_ORACLE_PASSWORD`；另支持 `--mock-json <file>` 离线模式（单测用）；
   - 查询（表名来自 CDMS 活库字典）：
     - `T_MARK_DETAIL d JOIN T_MARK_ITEM i ON d.FMARKITEMID = i.FID`：扣分项 TOP30（FID、名称、次数、病历数）；
     - `T_MSS_REWORK`：返工量、按 `FCONTROLTYPE` 分布、`ISVOERDATE`/`VOERDAYS` 超期分布；
     - `T_MSS_MRCONTROL`：按 `FDOCNAME` 统计、`FREMARK` 高频关键词（只输出词频，不输出原文整句）；
   - 读取 `prearchive_service/rules/example_rules.json` 中各规则对应的 `t_mark_item` FID（先读文件确认字段名），输出「已覆盖 / 高频未覆盖·可规则化 / 高频未覆盖·建议 AI」三组；
   - Oracle 11g 语法：用 `ROWNUM` 不用 `FETCH FIRST`；
   - 输出 Markdown 到 `--output`（默认 `review/prearchive/paperless_rejections_<YYYYMMDD>.md`），**零患者姓名/住院号**。
2. **`paperless_gold_backtest_ro.py`**（影子结果 vs 人工金标准）：
   - 输入①：影子检出结果（从预检服务自身结果库只读，或 `--results-json`）；输入②：CDMS 人工结果（只读查询，或 `--manual-json`）；
   - 把两者转换成 `backtest_v2` 需要的结构后**直接调用 `backtest_v2` 与 `render_markdown_v2`**；患者标识在报告中哈希/掩码（如 `P***8503`）；
   - 必须支持纯离线 `--results-json/--manual-json` 模式（单测用）。

### 3.3 规则导入 CLI `import_rules_cli.py`
- 参数：`--config <prearchive config 路径>`、`--files rules/example_rules.json rules/system_push_rules.json`、`--apply`（不传即 dry-run）、`--actor <名称>`；
- 内部只做：加载配置 → 构造 `RuleService` → 调 `import_files(paths, apply=…, actor=…)` → 打印结果摘要；
- 必须幂等（重复 `--apply` 不产生重复版本——以 `RuleService` 现有行为为准，单测验证）。

### 3.4 中间表投递（在现有 Outbox 框架内增量扩展）
- 先读 `outbox.py` 中 `DeliveryWorker` 的 `transport` 注入方式与 destination 配置结构；
- 新增一种传输/目的地类型 `staging_table`：
  - 配置项：`dsn_env`（存放连接串的环境变量名）、`table`（必须匹配 `^[A-Za-z][A-Za-z0-9_]{0,29}(\.[A-Za-z][A-Za-z0-9_]{0,29})?$`，否则拒绝启动）、`idempotency_column`；
  - 写入用**参数化** `INSERT ... SELECT ... FROM dual WHERE NOT EXISTS (SELECT 1 FROM <table> WHERE <idempotency_column> = :k)`（Oracle）；
  - 与 HTTP 一样走现有重试/死信状态机；
  - **默认不启用**；单测用注入的假连接验证 SQL 与参数，零真实连接。
- 复用/确认现有「仅人工确认后才投递」的闸门：先读 `delivery_wiring.py::DeliveryGovernance`，若已有确认/审核开关就复用；若没有，增加 `require_manual_confirm`（默认 `true`），未确认的缺陷不入 Outbox。

### 3.5 影子配置模板 `config.shadow.prod.template.json`
- 以 `config.example.json` 为底（**结构一字不改，只改值**）：
  - `service.anchor_mode = "discharge"`（`_comment` 写明：CDMS 到位并回测达标后可改 `paperless_rpa`）；
  - `sources.jhemr.enabled = true`（177）、`sources.his.enabled = true`、`sources.sm.enabled = true`（216），主机/端口/库名按 063 文档填写，**密码只写环境变量占位**，例如 `"password_env": "PREARCHIVE_JHEMR_PASSWORD"`——先看现有配置/加载代码支持哪种取密方式（`password_env` 或 `password_enc`），按支持的写；
  - `sources.paperless.enabled = false`（保留 `10.10.10.93` 主机与注释）；其余源保持 `false`；
  - `push.enabled = false`、`result_delivery.enabled = false`、新增的中间表目的地 `enabled = false`。
- 单测：模板可被预检服务配置加载函数成功解析；所有对外投递开关均为 `false`。

### 3.6 Runbook `docs/reference/123_…`
写清并登记 INDEX：
1. 影子激活 6 步（备份现配置 → 宿主机注入密码环境变量 → 替换为影子模板 → `import_rules_cli.py` 先 dry-run 后 `--apply` → 重启 `med-prearchive` → 核验 `MED_PREARCHIVE_*` 运行/问题表开始有数据且零对外投递），每步给回滚方法；
2. CDMS 账号到位后：盘点脚本与回测脚本命令、从影子转「辅助上线」的建议阈值（例如命中率 ≥ 80%、误报率 ≤ 20%，需病案室确认）；
3. 无纸化推送对接：HTTP/WebService 报文示例（JSON/SOAP 字段映射：患者号、住院次、`t_mark_item` FID、规则码、缺陷描述、确认人、确认时间、幂等键）与中间表建议 DDL（只作为与厂商评审的草案）。

---

## 四、前端：病案室辅助核查台（`frontend/src/features/governance/WorkbenchPage.vue`）

**先读现有页面**：它通过主服务 BFF（`/api/prearchive-admin/checks`、`/issues` 等）取数，保留这些调用与权限判断，只重构布局和补交互。

1. `PageHeader`：title「归档前形式核查」，subtitle「出院病历归档前自动检查缺失文书、签名与形式规范，辅助病案室质控」。
2. 模式横幅（`el-alert :closable="false" show-icon`）：
   - 列表 0 条 / 服务不可用：`type="warning"`「归档前检查引擎尚未接入数据（影子模式待启用，详见 123 操作手册）。启用后这里会自动列出每日出院病历的检查结果。」
   - 有数据：`type="info"`「当前为影子辅助模式：结果仅供病案室在本系统内核对，不会推送给临床或无纸化系统。」
3. `SummaryStrip` 5 卡（数值来自现有接口统计；接口没有的指标就用当前筛选结果在前端计算并在 hint 写「按当前页」）：已检查病历 / 检出缺陷病历 / 待病案室确认 / 已确认缺陷 / 误报占比。
4. `FilterPanel`：出院日期范围、出院科室（filterable）、复核状态（全部/待确认/已确认/误报/已补齐，value 用接口实际枚举值，label 中文）、患者姓名或住院号；`#more`：规则分类。
5. 主表（`DataTableShell` + `max-height="calc(100vh - 380px)"`），按患者聚合：
   - 患者信息（fixed left：姓名、患者号/住院号）、出院科室与日期、**检出缺陷**（最多 3 个红/橙小 tag + `+N`）、最高严重度 `<RiskTag>`、病案室复核状态（中文胶囊）、无纸化推送（统一灰标「影子模式·未推送」，为后期预留）、操作（fixed right，宽 190：「核查处理」+ `<HolographyButton :patient-id="row.patient_id" link />`）。
6. 核查抽屉（`DetailDrawer size="780px"`）：
   - 顶部患者卡 + 主按钮 `<HolographyButton :patient-id="current.patient_id" size="default" label="打开 360 全息核对病历" />`；
   - 每条缺陷一张卡：规则名、对应无纸化扣分项名称、证据说明（中文一句话）、右侧 3 个按钮「确认缺陷」「标为误报」「已补齐」——点击弹出备注框（误报必须选原因：文书其实存在 / 规则不适用本科室 / 时间判断错误 / 其他），提交到现有 `issues/{issue_id}/actions` BFF 端点（动作枚举以预检服务接口定义为准），成功后刷新；
   - 技术证据（运行批次、原始 JSON）放 `el-collapse` 默认折叠。

---

## 五、红线
1. `python prearchive_service/check_isolation.py` 必须 0 违规；
2. 脚本、模板、报告零明文口令、零患者姓名/未脱敏患者号；
3. 不连接任何生产库做写入；不修改生产配置；不重启容器；禁止 Git 写操作；
4. 新 `docs/reference/123_*.md` 必须登记 INDEX 并通过 `check_documentation_20261002.py`。

## 六、验收
`prearchive_service/tests/test_wp07_shadow_tools.py` 至少：
1. 盘点脚本 `--mock-json`：TOP 扣分项统计与三组覆盖分类正确，输出无患者标识；
2. 回测脚本离线模式：调用 `backtest_v2` 得到正确命中/漏检/误报数，报告患者号已掩码；
3. `import_rules_cli.py`：dry-run 零写入；`--apply` 两次幂等（SQLite 临时库）；
4. 中间表传输：非法表名拒绝；SQL 为参数化且含幂等 `NOT EXISTS`；未启用时零连接；未人工确认的缺陷不入 Outbox；
5. 影子模板可被配置加载器解析，所有对外开关为 false。

```powershell
python prearchive_service/check_isolation.py
python -m compileall app tests scripts prearchive_service
python -m pytest prearchive_service/tests -q
python scripts/check_documentation_20261002.py
cd frontend
npm run typecheck
npm run test:unit -- tests/unit/prearchive-workbench.test.ts
npm run build
cd ..
python scripts/run_gates_20260906.py --quick
```
收工写 `review/064-wp07/DELIVERY.md`，登记 01/02（本地交付完成，未提交）。
