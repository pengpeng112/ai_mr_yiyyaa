# 执行任务书 `PROMPT-WP04`：时效三大业务页深度优化（台账补全 + 审批增强 + 月度考核任意区间 / Excel / 分页 / 固定表头）

> **所属总计划**：`docs/ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md`（工作包 4 / 10）  
> **预计耗时**：约 3.0~3.5 小时  
> **前置依赖**：`WP-02`（`data_scope` + `HolographyButton`）；建议在 `WP-03` 之后  
> **先读文件顺序**：`AGENTS.md` → `开发起步包/README.md` → `00_AI协作规则.md` → `01_统一修改记录.md` 末 10 行 → `02_协作任务板.md` → **`prompts-064/PROMPT-00_通用事实基线与勘误_必读.md`** → `git status --short` 存 `review/064-wp04/git_status_before.txt`。

---

## 一、目标（用户反馈第 3、5、6 项）

1. **在院时效台账** `EventLedgerPage.vue`（路由 `/quality/timeliness-events`）：补全住院号、性别年龄、入院日期、入院诊断、护理级别、实际完成时间、直观「剩余/已超时」胶囊、关联解锁审批状态、360 全息、固定表头、医生筛选。
2. **解锁审批与豁免** `ApprovalCenterPage.vue` + `ApprovalLedgerPage.vue`（路由 `/timeliness/approvals`）：补全审批人姓名、审批时间、申请原因全文、豁免原因、关联事件时限、申请日期范围与申请人筛选、状态汇总卡、页头「立即同步 JHEMR 审批」、360 全息、固定表头。
3. **时效月度考核** `MonthlyReportPage.vue`（路由 `/quality/timeliness-monthly`）：**任意日期范围**（如 11 月 1 日 ~ 11 月 10 日）+ 快捷预设、**真 Excel `.xlsx` 导出**、**分页**、**固定表头 + 冻结左侧科室/医生列**、移除页内重复的「审批与扣罚台账」Tab。

> 真实端点（PROMPT-00 §1.2）：月度统计是 `GET /api/timeliness/stats/monthly`（返回 `{month, totals, rows}`），导出是 `GET /api/timeliness/export/monthly`（CSV，已调用 `record_export_audit`）。**不存在 `/reports/monthly`，不要新建平行端点，在这两个端点上做向后兼容扩展。**

---

## 二、文件白名单

### 允许新增
1. `tests/test_wp04_timeliness_ledger_and_excel.py`
2. `frontend/tests/unit/timeliness-monthly-range.test.ts`
3. `review/064-wp04/`

### 允许修改
1. `app/routers/timeliness.py`
2. `app/timeliness/his_oracle_reader.py`（仅扩展 `fetch_patient_visit_meta` 返回列，见 3.1）
3. `scripts/timeliness/reconcile_native.py`（仅可选任务 3.5）
4. `frontend/src/features/timeliness/{types.ts, api.ts, EventLedgerPage.vue, ApprovalCenterPage.vue, ApprovalLedgerPage.vue, MonthlyReportPage.vue}`
5. `frontend/tests/unit/timeliness-approvals.test.ts`、`frontend/tests/unit/timeliness-pages.test.ts`（同步移除 Tab 后的断言，不削弱其他断言）
6. `开发起步包/01_统一修改记录.md`、`02_协作任务板.md`

---

## 三、后端实施

### 3.1 扩展 `fetch_patient_visit_meta`（`app/timeliness/his_oracle_reader.py` 约第 640 行）
- 先读该函数现有 SELECT 列与返回结构；在 SELECT 中**追加**（均在 V_QYBR 40 列契约内）：`"住院号"`, `"性别"`, `"年龄"`, `"入院日期"`, `"出院日期"`, `"入院诊断"`, `"护理级别"`, `"出院主诊断"`；返回 dict 增加对应英文键 `inp_no, sex, age, admission_date, discharge_date, admission_diagnosis, nursing_level, discharge_diagnosis`（日期转 ISO 字符串）。
- **保持**：`execute_with_view_compat` 执行、单列 `患者ID IN (...)` ≤50 分批、每轮封顶、3600s TTL 缓存、异常降级返回空。原有键不变（scanner 依赖）。
- ⚠️ 降级内联视图中「护理级别」为 NULL，属预期。

### 3.2 `GET /api/timeliness/events` 扩展
- 先读现有函数签名（约第 611 行）与 `_event_dict`。追加可选参数：`doctor: str | None`（匹配 `responsible_doctor_id` 精确，或先查 `_display_maps` 的 staff 字典把姓名模糊匹配转工号集合）、`date_from`/`date_to`（若已有同义参数则复用，不重复加）。
- 对当页事件（≤分页上限）追加字段（`_event_dict` 之外在路由里补，避免影响详情接口以外的调用）：
  - `inp_no, sex, age, admission_date, admission_diagnosis, nursing_level`（来自 3.1，按当页 pairs 一次性批量取）；
  - `remaining_minutes`：未进入终态时 `int((deadline - now).total_seconds() // 60)`（正=剩余，负=已超时）；终态为 `None`；
  - `latest_approval`：按当页 `(patient_id, visit_id)` 一次查询 `TLApproval`，取 `apply_date_time` 最新一条，返回 `{flag, apply_date_time, approve_date_time, penalty_exempt}` 或 `None`（注意：`TLApproval` 按 `monitor_code` 对应规则，若能通过 `TLRuleVersion.jhemr_monitor_code` 关联到同一规则则优先匹配同规则，否则取同患者最新一条并标 `match: "patient"`）。

### 3.3 `GET /api/timeliness/approvals` 扩展
- 先读现有函数（约第 1012 行）与 `_approval_dict`。追加可选参数：`apply_date_from`、`apply_date_to`（`YYYY-MM-DD`，闭区间）、`applicant: str | None`（工号精确或姓名模糊→工号集合）。
- 每行追加：`approve_user_name`（staff 字典映射）、`apply_reason`（全文，已有则确保不截断）、`exempt_reason`、`inp_no`、`admission_date`、`admission_diagnosis`（3.1 批量）、`event_deadline`、`event_overdue_minutes`（同患者同规则最近 TLEvent，可选，找不到为 `None`）。
- 顶层追加 `status_counts: {total, pending, approved, exempted}`：在**同样筛选条件（不含 flag 筛选）**下 1 条 SQL `SUM(CASE ...)`（pending=`flag=='1'`，approved=`flag=='2'`，exempted=`penalty_exempt==True`）。

### 3.4 月度考核：任意日期范围 + 分页 + Excel
1. **重构 `_monthly_rows` 签名为区间版**（保持旧调用可用）：
   ```python
   def _resolve_period(month: str | None, date_from: str | None, date_to: str | None) -> tuple[datetime, datetime, str]:
       """返回 [start, end_exclusive) 与展示标签。优先 date_from/date_to；否则 month；都没有→本月1日~明天0点。"""
   def _period_rows(db, current_user, start: datetime, end: datetime, dept: str | None) -> list[dict]: ...
   def _monthly_rows(db, current_user, month, dept=None):   # 旧函数保留为薄包装，调用 _period_rows
   ```
   - `_period_rows` 用 **SQL 聚合**替代 `query.all()` 循环：事件按 `(dept_code, responsible_doctor_id)` + `SUM(CASE WHEN status=...)`；审批按 `(dept_code, apply_user_id)` 聚合 `approval_count / approved_unlock_count / exempt_count / penalty_amount_total`；两者在 Python 合并（键与现有 `_blank_row` 一致：`total, completed_on_time, completed_late, overdue, pending, warning, other, approval_count, approved_unlock_count, exempt_count, penalty_amount_total`）。
   - 新增计算字段 `on_time_rate`（按时/(按时+超时完成)×100，1 位小数）。
   - 用旧数据跑新旧两种实现，结果必须逐行一致（写进单测）。
2. **`GET /api/timeliness/stats/monthly` 扩展**：追加可选 `date_from`、`date_to`、`page`、`limit`（`limit` ≤ 200）、`doctor`。
   - 不传 `page` 时：返回结构**完全不变**（`{month, totals, rows}`），仅多 `date_from, date_to` 两个键；
   - 传 `page` 时：`rows` 只返回当页，另加 `total_rows, page, limit`；`totals` 始终是**全量合计**（换页不变）。
   - 日期非法、倒序、跨度 > 366 天 → 400。
3. **`GET /api/timeliness/export/monthly` 扩展**：`month` 改为可选；追加 `date_from`、`date_to`、`doctor`、`format: str = Query("csv", pattern="^(csv|xlsx)$")`（**默认仍是 csv，保证旧调用与旧测试不变**；前端新按钮传 `xlsx`）。
   - `xlsx` 用 `openpyxl`（已在 `requirements.txt`）：
     - Sheet 名「时效考核统计」；第 1 行合并标题「病历时效考核统计表（YYYY-MM-DD 至 YYYY-MM-DD）」14 号加粗居中；
     - 第 2 行表头（中文）：`科室名称, 科室编码, 责任医生, 工号, 事件总数, 按时完成, 超时完成, 超时未完成, 预警中, 未到期, 按时率, 锁定(超时申请)次数, 解锁通过次数, 豁免次数, 应扣金额(元)`，浅蓝底 `DBEAFE`、加粗、细边框；
     - `ws.freeze_panes = "E3"`（冻结前 2 行 + 左 4 列）；按时率单元格写小数并设 `number_format = '0.0%'`；
     - 末行「合计」加粗；列宽按内容估算（12~28）；
     - 返回 `StreamingResponse(BytesIO)`，`media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"`，`Content-Disposition: attachment; filename*=UTF-8''<urlencoded 中文文件名>`（`urllib.parse.quote`）；
   - csv/xlsx 都调用 `record_export_audit(..., export_type="timeliness_monthly", export_format=<csv|xlsx>, filter_criteria={"date_from":…, "date_to":…, "dept":…, "doctor":…, "rows":…})`（照抄现有调用写法）。

### 3.5（可选，≤20 分钟）日间病历对账口径对齐
- 背景：2026-11-19 已只读确认 177 上 39 个日间/24h 模板已改绑 `JH04.03.013`、6 个诊断证明 `monitor_code` 已清空。**ai_mrzk 按 `mr_class` 判完成，不受 `monitor_code` 影响，时效判定本身不需改。**
- 仅在 `scripts/timeliness/reconcile_native.py` 中：把「ai_mrzk 有 ADM_REC/DISCHARGE_REC 事件、JHEMR 原生无监控行」且完成文书 `mr_class == 'EMR09.00.02'` 或标题含「日间」「24小时」「24h」的差异，归类为「日间病历·原生免锁（预期差异）」，不计入异常。若找不到可安全落点，跳过本项并在交付报告说明。

---

## 四、前端实施

### 4.1 `EventLedgerPage.vue`
- 先读现有 `applyRouteQuery`（支持 `status / patient_id / rule_code / dept`），**新增支持 `doctor`**（WP-03 统计页会带此参数跳转）。
- `FilterPanel` 主行：科室（filterable）、状态（全部/预警中/已超时/按时完成/超时完成/已豁免/未到期，value 用英文枚举、label 中文）、规则（中文名）、患者（姓名或患者号）、责任医生（姓名或工号）；`#more`：起止日期。
- 表格 `:max-height="tableMaxHeight"`（`const tableMaxHeight = 'calc(100vh - 340px)'`，CSS 给表格容器 `min-height: 360px`），列：
  1. 患者信息（fixed left，宽 180）：姓名粗体 + `性别 · 年龄岁` 灰标；第二行 `患者号 / 住院号`；
  2. 科室与医生（宽 160）：科室名；下行 `医生名（工号）`；
  3. 入院与诊断（宽 190）：入院日期 `MM-DD HH:mm` + 护理级别小 tag；下行入院诊断 `show-overflow-tooltip`；
  4. 质控规则（宽 150）：规则中文名；
  5. 计时节点（宽 175）：`起算 MM-DD HH:mm` / `截止 MM-DD HH:mm` / 已完成时 `完成 MM-DD HH:mm`；
  6. 时效状态（宽 150）：用纯函数 `countdownBadge(row)` 返回 `{type, text}`：
     - 终态 `COMPLETED_ON_TIME` → success「按时完成」；`COMPLETED_LATE` → info「超时完成」；`EXEMPT` → info「已豁免」；`CANCELLED` → info「已取消」；
     - `remaining_minutes < 0` → danger「已超时 X天Y时」（≥1440 分钟显示天时，否则「X小时Y分」）；
     - `WARNING` → warning「剩余 X小时Y分」；其他 → 默认「剩余 X小时Y分」；
  7. 解锁审批（宽 120）：`latest_approval` 为空显示「—」；`flag==='1'` → warning「锁定待审批」；`flag==='2'` → success「已解锁」；豁免加「已豁免」小标；
  8. 操作（fixed right，宽 200）：「详情」、「豁免」（保留现有权限判断）、`<HolographyButton :patient-id="row.patient_id" link />`。
- 详情弹窗：两个 `el-descriptions :column="2" border size="small"`（「患者临床信息」「时效与解锁记录」），标题栏右侧放 `<HolographyButton :patient-id="current?.patient_id" />`；动作日志保持现有中文化。

### 4.2 `ApprovalCenterPage.vue` / `ApprovalLedgerPage.vue`
- `ApprovalCenterPage`：PageHeader actions 增加「立即同步 JHEMR 审批」（调用现有 `POST /api/timeliness/approvals/sync`，loading，成功后 `ElMessage.success('已同步 N 条')` 并通知子组件刷新——可用 `ref` 调子组件 `reload()` 或 `key` 自增）；保留手机端入口弹窗。
- `ApprovalLedgerPage`：
  - 顶部 `SummaryStrip` 4 卡（来自 `status_counts`）：申请总数 / 锁定待审批（warning，点击切 `flag=1`）/ 已解锁 / 已豁免；
  - `FilterPanel`：科室、审批状态、申请日期范围（daterange）、申请人（姓名或工号）、患者号；`#more`：监控项/规则；保留现有 `patient_id`、`flag` 路由预填；
  - 表格固定表头（`calc(100vh - 380px)`），列：患者信息（fixed left：姓名、患者号、住院号、入院日期）、科室与申请医生、触发规则与超时（规则中文名 + 「超时 X 小时」红字，来自 `event_overdue_minutes`，无则省略）、申请时间与原因（原因两行省略 + tooltip 全文）、审批结果（状态 tag + 审批人姓名 + 审批时间；豁免显示豁免原因）、应扣金额（豁免时删除线并显示「0 元」）、操作（fixed right，宽 210：现有「同意解锁」「豁免」按钮 + `<HolographyButton link />`）。

### 4.3 `MonthlyReportPage.vue`
1. 删除页内 `el-tabs` 中「审批与扣罚台账」页签（只保留考核统计）；标题改「病历时效考核统计」；actions：`解锁审批台账 →`（`/timeliness/approvals`）、主按钮 `导出 Excel`（`apiDownload('/timeliness/export/monthly', { params: { ...当前筛选, format: 'xlsx' } })` + `triggerBrowserDownload`，loading）。
2. `FilterPanel`：
   - 「快捷区间」`el-radio-group size="small"`：本月（默认）/ 上月 / 近7天 / 近10天 / 近30天 / 自定义；选非自定义时自动算出起止并写回日期框；
   - 「考核时间范围」`el-date-picker type="daterange" value-format="YYYY-MM-DD" range-separator="至" :clearable="false"`；手动改日期 → 快捷区间自动切「自定义」；
   - 「科室」`el-select filterable clearable`；「责任医生」`el-input clearable`（回车查询）。
3. `SummaryStrip` 6 卡用后端 `totals`（全量合计）：事件总数、按时率（前端用 totals 计算）、超时未完成、锁定次数（`approval_count`）、豁免次数、应扣金额。
4. 表格（**固定表头 + 冻结左两列 + 分页**）：
   ```html
   <DataTableShell :loading="loading" :error="error" :empty="!rows.length"
     :total="totalRows" v-model:page="page" v-model:page-size="pageSize"
     @update:page="load" @update:page-size="onPageSizeChange" @retry="load">
     <el-table :data="rows" border stripe :max-height="tableMaxHeight"
       show-summary :summary-method="summaryMethod" header-cell-class-name="ma-sticky-th">
       <el-table-column prop="dept_name" label="科室名称" min-width="150" fixed="left" show-overflow-tooltip />
       <el-table-column label="责任医生" width="140" fixed="left">
         <template #default="{ row }">{{ row.responsible_doctor_name || '—' }}<span class="cell-sub">（{{ row.responsible_doctor_id || '无工号' }}）</span></template>
       </el-table-column>
       <el-table-column prop="total" label="事件总数" width="96" align="right" />
       <el-table-column prop="completed_on_time" label="按时完成" width="96" align="right" />
       <el-table-column prop="completed_late" label="超时完成" width="96" align="right" />
       <el-table-column prop="overdue" label="超时未完成" width="106" align="right" />
       <el-table-column prop="warning" label="预警中" width="86" align="right" />
       <el-table-column label="按时率" width="100" align="right">
         <template #default="{ row }"><el-tag size="small" :type="row.on_time_rate >= 95 ? 'success' : row.on_time_rate >= 85 ? 'warning' : 'danger'">{{ Number(row.on_time_rate || 0).toFixed(1) }}%</el-tag></template>
       </el-table-column>
       <el-table-column prop="approval_count" label="锁定次数" width="96" align="right" />
       <el-table-column prop="approved_unlock_count" label="解锁通过" width="96" align="right" />
       <el-table-column prop="exempt_count" label="豁免" width="80" align="right" />
       <el-table-column prop="penalty_amount_total" label="应扣金额(元)" width="116" align="right" />
     </el-table>
   </DataTableShell>
   ```
   - `tableMaxHeight = 'calc(100vh - 380px)'`；样式 `:deep(.ma-sticky-th){ background:#f1f5f9 !important; color:#0f172a; font-weight:600 }`；
   - 请求带 `page`、`limit=pageSize`、`date_from`、`date_to`、`dept`、`doctor`；
   - `summaryMethod` 首列显示「全期合计」，其余列取后端 `totals`（**不是当页小计**），按时率列由 totals 计算。

---

## 五、红线
1. 只用 V_QYBR 40 列内的列；不新增 BFF/新平行端点；`export/monthly` 默认格式保持 csv。
2. `.xlsx` 必须是 openpyxl 生成的真二进制，不得把 CSV 改后缀。
3. 不删除现有页面路由、权限判断与手机端入口；禁止生产写入与 Git 写操作。

## 六、验收

`tests/test_wp04_timeliness_ledger_and_excel.py` 至少：
1. `stats/monthly?date_from=2026-11-01&date_to=2026-11-10` 只计区间内事件与审批；
2. 旧调用 `stats/monthly?month=2026-11` 返回结构与改造前一致（`month/totals/rows` 键与行内容逐项相等）；
3. 新旧聚合实现对同一数据逐行一致；
4. `page=1&limit=2` 返回 2 行 + 正确 `total_rows` + 全量 `totals`；
5. `export/monthly?format=xlsx&date_from=…&date_to=…`：`openpyxl.load_workbook(BytesIO(resp.content))` 校验标题、表头、`freeze_panes == "E3"`、数据行数、合计行，并写入 `ExportAuditLog(export_format='xlsx')`；旧 `export/monthly?month=…` 仍返回 CSV；
6. `home` 范围用户导出只含本科室；
7. `events` 返回新增字段（`remaining_minutes`、`latest_approval`、临床字段，visit_meta 用 mock）；`approvals` 新筛选与 `status_counts` 正确；非法日期 400。

```powershell
python -m compileall app tests scripts
python -m pytest tests/test_wp04_timeliness_ledger_and_excel.py tests/timeliness/test_api_timeliness.py tests/timeliness/test_his_oracle_reader.py tests/timeliness/test_event_exempt_20261115.py tests/timeliness/test_scanner.py -q
python -m pytest tests/timeliness -q
cd frontend
npm run typecheck
npm run test:unit -- tests/unit/timeliness-approvals.test.ts tests/unit/timeliness-pages.test.ts tests/unit/timeliness-monthly-range.test.ts
npm run test:unit
npm run build
cd ..
python scripts/run_gates_20260906.py --quick
```
收工写 `review/064-wp04/DELIVERY.md`，登记 01/02（本地交付完成，未提交）。
