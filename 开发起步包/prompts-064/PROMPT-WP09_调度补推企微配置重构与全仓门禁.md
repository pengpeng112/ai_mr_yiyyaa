# 执行任务书 `PROMPT-WP09`：定时调度 / 手动补推 / 企微接收人配置三页重构 + 全仓全绿门禁收口

> **所属总计划**：`docs/ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md`（工作包 9 / 10）  
> **预计耗时**：约 3.5 小时  
> **前置依赖**：`WP-01` ~ `WP-08` 全部完成  
> **先读文件顺序**：`AGENTS.md` → `开发起步包/README.md` → `00_AI协作规则.md` → `01_统一修改记录.md` 末 10 行 → `02_协作任务板.md` → **`prompts-064/PROMPT-00_通用事实基线与勘误_必读.md`** → `git status --short` 存 `review/064-wp09/git_status_before.txt`。

---

## 一、目标
1. **定时调度管理** `frontend/src/features/tasks/SchedulerPage.vue`（`/tasks/scheduler`，约 576 行）：分页签 + 状态卡 + 诊断提示可视化。
2. **手动补推与重查** `frontend/src/features/tasks/ManualPushPage.vue`（`/tasks/push`，约 819 行）：3 段式卡片流程 + 结果可视化 + 360 入口。
3. **企微接收人配置** `frontend/src/features/governance/RelayConfigPage.vue`（`/governance/relay`，约 11KB 却只有 37 行——压缩模板）：3 页签 + 可搜索科室多选 + 结构化接收人规则表。
4. **全仓全绿收口**：跑 `--full` 门禁与锚比对。

---

## 二、开工前「防回归盘点」（写进 `review/064-wp09/exec-log.md`）
1. 列出 3 个页面现有调用的全部接口：
   - 调度：`/api/scheduler/status|start|stop|trigger|history|run-summary|directed-retry`、`/api/config/scheduler|scheduler-daily|scheduler-discharge`（GET/POST）；
   - 补推：`/api/push/*`、`/api/push/historical-rerun/*`、`/api/config/departments/list`；
   - 企微：`/api/config/relay-alert`（GET/POST/test）、`/api/relay/receiver-config|preview-receivers|test-nurse-head|search-user|receiver-rules`。
2. 搜索测试中的选择器与文案并保留：`frontend/tests/unit/manual-push-guard.test.ts`、`frontend/tests/unit/relay-contracts.test.ts`、`frontend/tests/e2e/*`、`tests/test_*frontend_static*.py`。
3. 必须保留的行为（AGENTS.md 回归红线）：
   - 调度状态与保存响应中的 `discharge_effectiveness` / `effectiveness_warnings` / `diagnostics` 诊断信息要展示，不能丢；
   - 手动补推的防双击/重入守卫（`manual-push-guard.test.ts` 覆盖）；
   - `POST /api/config/relay-alert` 是局部合并：**只发送改动字段**；`base_url` 为空时不发送；`secret_key` 留空不发送（保护 `secret_key_enc`）；不得改成整段覆盖保存。

---

## 三、文件白名单
- 修改：上述 3 个页面；可新增子组件到 `frontend/src/features/tasks/components/`、`frontend/src/features/governance/components/`
- 修改（仅同步断言）：`frontend/tests/unit/manual-push-guard.test.ts`、`frontend/tests/unit/relay-contracts.test.ts`
- 新增：`frontend/tests/unit/scheduler-page-tabs.test.ts`、`frontend/tests/unit/relay-config-partial-save.test.ts`、`review/064-wp09/`
- 登记：`开发起步包/01`、`02`；全量门禁通过后更新 `docs/ACTIVE/064_…` 状态行与 `docs/INDEX.md` 064 行状态
- **不改后端**。

---

## 四、页面规范

### 4.1 `SchedulerPage.vue`
- `SummaryStrip` 4 卡：调度器（运行中/已停止）、每日在院任务（启用状态 + 下次执行时间）、出院终末任务（同上）、病历时效扫描（每 5 分钟 + 最近一次耗时，若 `/status` 无此字段则显示「—」）。
- `el-tabs` 3 页签：
  1. 「每日在院质控」：左卡配置表单（启用开关、频率单选：每 10 分钟 / 每 30 分钟 / 每天定时 / 自定义 Cron（选 Cron 才显示输入框并提示格式）、执行时间、查询日期偏移、质控类型多选卡片（中文名 + 一句用途）、科室范围 `el-select multiple filterable`、并发数（若 WP-01 已加 `max_workers`，范围 1~4，默认 1））+ 保存；右卡「立即执行一次」（二次确认，调用 `/api/scheduler/trigger` 并带 mode）+ 最近一次执行结果。
  2. 「出院终末质控」：同结构；顶部 `discharge_effectiveness` 诊断卡：全部有效显示绿色 `el-alert`「所选质控类型均支持出院终末路径」，否则橙色逐条列出（类型中文名 + 中文原因），保存响应里的 `effectiveness_warnings` 同样展示。
  3. 「执行历史」：`/api/scheduler/history` + `/run-summary` 表格（开始时间、模式中文、耗时、成功/失败/跳过、状态 tag），失败行可展开看错误。
- 遗留 `scheduler`（单任务）配置：若双调度任一启用，显示灰色说明「已启用双调度，旧版单任务配置不生效」，旧配置放 `el-collapse` 折叠。

### 4.2 `ManualPushPage.vue`
- 保留页头「查看任务执行进度」按钮与守卫逻辑。
- 3 张纵向卡片：
  1. 「① 选择核查范围」：模式 `el-radio-group`（按日期批量 / 指定患者重查 / 历史重新核查（若现有页面有此模式））、日期选择、科室多选（filterable，来源 `/api/config/departments/list`）、质控类型卡片多选（全选/反选）；指定患者模式显示患者号输入（支持多行粘贴，前端去重）。
  2. 「② 执行选项」：常用开关（跳过已推送、仅预览人数）在外；其余放 `el-collapse`「高级选项」。
  3. 「③ 预览与结果」：「预览影响人数」+ 主按钮「开始执行」（loading 期间禁用，二次确认显示将处理的人数与类型）；结果区：进度条 + 4 格（总数/成功/跳过/失败）+ 跳过原因分布（中文映射 `skip_reason`，如 `unreviewed_pending`→「待复核未推送」、`empty_lab_exam`→「无检验检查数据」、`insufficient_surgery_docs`→「手术文书不足」，未知键显示「其他原因」并在 tooltip 给原值）+ 失败明细中文卡片 + 结果表（含 `<HolographyButton :patient-id="row.patient_id" link />`）。

### 4.3 `RelayConfigPage.vue`
- `el-tabs` 3 页签：
  1. 「推送开关与前置机」：启用开关、前置机地址、签名密钥（留空不修改）、详情页地址、推送风险级别（`el-select multiple`：高危/中危/低危）、**生效科室**（`el-select multiple filterable clearable`，选项来自科室列表接口，提示「不选表示全院生效」，对应后端 `alert_dept_filter`）+「测试前置机连接」（结果中文卡片）。保存逻辑：与加载时的值做 diff，**只提交变化的字段**；`base_url` 为空字符串时从提交体删除；`secret_key` 为空时删除。
  2. 「科室接收人规则」：表格展示 `receiver_rules`（科室、接收对象类型、人员、触发级别、启用），弹窗新增/编辑（人员用 `/api/relay/search-user` 远程搜索），保存调用 `/api/relay/receiver-rules`；提供「预览某条记录会推送给谁」（`/api/relay/preview-receivers`）。
  3. 「护士长/重点接收人」：表格 + 搜索 + 分页 + 弹窗维护；「按科室查询护理负责人」调用 `/api/relay/test-nurse-head`。

---

## 五、全仓全绿门禁（WP-09 最后执行，逐条贴输出）
```powershell
cd f:\python\前后端代码\ai_mrzk\frontend
npm run typecheck
npm run test:unit
npm run build

cd f:\python\前后端代码\ai_mrzk
python -m compileall app tests scripts prearchive_service
python scripts/check_naming_convention.py
python prearchive_service/check_isolation.py
python scripts/check_documentation_20261002.py
python -m pytest -q
python -m pytest prearchive_service/tests -q
python scripts/run_gates_20260906.py --full --anchor-file docs/reference/gate_anchors.json
```
- `--full` 中 E2E 若出现失败：先用 `git stash` 以外的方式（例如对照 `review/gate-runs/20261118-183713/frontend_e2e-recheck.log` 记录的 2 条既有失败用例：Relay 中文标签、工作台 `.meta-grid` 定位）判断是否为既有问题；**本计划改版导致的选择器失效必须修复测试或页面**；既有问题在报告中列明。
- 锚值（`docs/reference/gate_anchors.json`）任何一项低于基线都算失败，不得修改锚文件来「通过」。

## 六、验收与交付
- `scheduler-page-tabs.test.ts`：诊断警告渲染、Cron 选项才显示输入框；
- `relay-config-partial-save.test.ts`：只改「生效科室」时提交体仅含 `alert_dept_filter`；`base_url` 清空不提交；`secret_key` 为空不提交；
- 原 `manual-push-guard.test.ts`、`relay-contracts.test.ts` 全绿。
- 交付：`review/064-wp09/DELIVERY.md`（含全量门禁数字表）；登记 01/02；把 064 总计划与 INDEX 064 行状态更新为「WP-01~WP-09 本地完成，待 WP-10 生产发布审批」。
