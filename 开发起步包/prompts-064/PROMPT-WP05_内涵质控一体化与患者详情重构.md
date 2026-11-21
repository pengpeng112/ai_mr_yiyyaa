# 执行任务书 `PROMPT-WP05`：内涵与终末质控一体化重构 + 患者质控详情升级 + 360 全线打通

> **所属总计划**：`docs/ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md`（工作包 5 / 10）  
> **预计耗时**：约 3.5 小时  
> **前置依赖**：必须已完成 `WP-01`（后端 CLOB 优化）与 `WP-02`（`data_scope.py` + `HolographyButton.vue` + 菜单隐藏 `audit`）  
> **先读文件顺序**：`AGENTS.md` → `开发起步包/README.md` → `开发起步包/00_AI协作规则.md` → `开发起步包/01_统一修改记录.md` 末 10 行 → `开发起步包/02_协作任务板.md` → **`开发起步包/prompts-064/PROMPT-00_通用事实基线与勘误_必读.md`（真实路由：患者全景 `/quality/patients`、质控记录 `/quality/records`、独立详情 `/quality/patient-detail?patient_id=&visit_number=`；详情接口 `GET /api/patient-qc/patient-detail?patient_id=&visit_number=&dept=`）** → `git status --short` 存 `review/064-wp05/git_status_before.txt`。

---

## 一、任务背景与已拍板业务口径

解决用户反馈第 3、6b、7 项（**用户正式拍板 D2**）：
1. **消除重复别扭的双菜单**：原先「患者质控全景（`PatientQcPage.vue`）」与「AI 内涵质控记录（`AuditRecordsPage.vue`）」功能高度重叠，医生和质控员不知道该进哪个。
   - **拍板方案**：统一收口为唯一主界面 **「内涵质控工作台」**（菜单 ID `patient-qc`，路由 `/quality/patients`），页面顶部提供清晰直观的 **双视角切换**：
     - **`按患者汇总（默认，临床/科主任视角）`**：1 行 = 1 位患者本次住院，不刷屏，一眼看清最高风险和核心缺陷；
     - **`按核查流水（排障/管理员视角）`**：逐条推送记录，支持单条重推、复核、批量删除、导出 CSV。
   - 旧路由 `/quality/records`（菜单 ID `audit`，WP-02 已设 hidden）保留重定向壳：自动跳转到 `/quality/patients?view=records` 并完整保留原有 query 参数，不破坏书签和跨页跳转（总览、反馈页等处若有跳 `/quality/records` 的链接可保持不改，由壳页转发）。
2. **彻底优化「患者质控详情」**（抽屉 + 独立全屏/打印页复用同一套高可读性组件）：
   - 取消原页面右侧僵硬拥挤的 320px 夹板；
   - 详情页顶部提供 **临床患者摘要卡片 + 醒目蓝色「打开 360 全息视图」按钮**；
   - 问题清单采用 **「左右双栏证据对比卡（病程/医嘱证据 vs 护理/检验/手术佐证）」+ 行内一键闭环（确认/已整改/误报）**；
   - 技术排障报文默认折叠，绝不裸铺满屏 JSON。
3. **闭环两页同步补全 360 全息跳转**：`FeedbackPage.vue`（整改反馈）与 `AlertLogsPage.vue`（企微告警）列表与详情抽屉均接入 `<HolographyButton />`。

---

## 二、允许修改与新增的文件白名单（严禁改动白名单外文件）

### 允许新增
1. `frontend/src/features/quality/components/PatientQcDetailView.vue`
2. `frontend/src/features/quality/components/AuditRecordListPanel.vue`
3. `frontend/tests/unit/patient-qc-detail-view.test.ts`（以及 `review/064-wp05/`）

### 允许修改
1. `app/routers/patient_qc.py`（仅在单患者详情接口补全 `V_QYBR` 临床摘要字段：性别/年龄/住院号/入院日期/出院日期/入院诊断/出院主诊断/管床医生/手术名称；容错降级不阻断主流程）
2. `frontend/src/features/quality/PatientQcPage.vue`
3. `frontend/src/features/quality/AuditRecordsPage.vue`（改为薄重定向壳）
4. `frontend/src/features/quality/PatientDetailStandalonePage.vue`（复用 `PatientQcDetailView.vue`）
5. `frontend/src/features/closure/FeedbackPage.vue`
6. `frontend/src/features/closure/AlertLogsPage.vue`
7. `开发起步包/01_统一修改记录.md` & `开发起步包/02_协作任务板.md`

---

## 三、后端微调规范（`app/routers/patient_qc.py`）

现有详情接口是 `GET /api/patient-qc/patient-detail?patient_id=&visit_number=&dept=`（`app/routers/patient_qc.py`，已用 `apply_push_log_visibility` 做科室隔离，并已「跨推送日志逐字段合并患者信息、缺失时从 mr_text 回退解析」）。**先完整读这个函数，确认它已返回哪些患者字段，只补缺失的，不改名、不删已有字段**；另外该函数当前对 `PushLog` 用 `.all()` 全量加载 4 个 CLOB——在不改变返回内容的前提下，仅对合并患者信息时不需要的大字段使用 `defer`（若某 CLOB 在返回中确实要用，例如技术报文 Tab，则保持加载）：
- 新增可选嵌套对象 `clinical_summary`：
  ```json
  "clinical_summary": {
    "patient_id": "00985003",
    "patient_name": "...",
    "admission_no": "...",
    "sex": "男",
    "age": 54,
    "dept_name": "骨科一病区",
    "discharge_dept_name": "骨科一病区",
    "doctor_in_charge": "李明",
    "admission_date": "2026-11-10 08:30:00",
    "discharge_date": null,
    "admission_diagnosis": "...",
    "discharge_diagnosis": "...",
    "surgery_name": "...",
    "surgery_date": null
  }
  ```
- 获取顺序：优先从最新一条 `PushLog.request_json` 的 `patient_info` 提取（零 DB 额外开销），缺失字段再按 `fetch_patient_visit_meta`（已带 `V_QYBR` compat 降级与 3600s 缓存）兜底补全，异常静默降级不报错。

---

## 四、超详细前端实现蓝图（请严格照此结构编写，避免凌乱排版）

### 4.1 统一工作台 `frontend/src/features/quality/PatientQcPage.vue`

1. **顶部页头 + 双视角切换器**：
   ```html
   <PageHeader title="内涵质控工作台" subtitle="AI 语义内涵与终末病历质控，支持按患者聚合查阅或按核查流水排障管理">
     <template #actions>
       <el-radio-group v-model="activeView" size="default" @change="onViewChange">
         <el-radio-button value="patients">按患者汇总</el-radio-button>
         <el-radio-button value="records">按核查流水</el-radio-button>
       </el-radio-group>
       <el-button v-if="activeView === 'patients'" :loading="exporting" @click="exportCurrent">导出当前筛选</el-button>
     </template>
   </PageHeader>
   ```
   - 响应 URL query：`?view=records` 自动切到「按核查流水」，不传或 `?view=patients` 默认「按患者汇总」；切换时同步 `router.replace({ query: { ...route.query, view: activeView.value } })`。

2. **视角 A「按患者汇总」（直接内嵌在 `PatientQcPage.vue`，彻底移除旧右侧 320px 夹板！）**：
   - **紧凑 `SummaryStrip` 4 张可点击快捷筛选卡**：
     - 全部患者 | 高危患者（红，点击切 `severity='high'`） | 中危患者（橙，点击切 `severity='medium'`） | 待复核（蓝，点击切 `reviewed_flag='false'`）；
   - **`FilterPanel` 主行仅露出 5 项（持久中文标签）**：
     1. 核查日期范围（快捷预设：近7天 / 近30天 / 全部 + 日期选择）；
     2. 在院/质控科室（`<el-select filterable clearable>`）；
     3. 质控类型（下拉）；
     4. 最高风险（全部 / 高危 / 中危 / 低危 / 无异常）；
     5. 患者姓名 / ID / 住院号（回车查询）；
     - 其余低频筛选（出院科室、运行模式[每日/出院]、复核状态、整改状态）**全部放入 `#more` 折叠槽**！
   - **全宽固定表头 `<el-table :max-height="'calc(100vh - 380px)'" border stripe @row-click="openDetail">`**，严格 8 列：
     1. `患者信息`（`fixed="left"`，宽 185px）：第一行姓名加粗 + 性别年龄标签；第二行 `患者号 · 第N次` 灰小字；
     2. `科室与管床`（宽 165px）：科室名（若出院科室不同用小字标出）+ 下行管床医生；
     3. `核查维度摘要`（min-width 240px）：最多展示 2 个高/中危维度名称 `<el-tag size="small" effect="plain">`，多余显示 `+N 项`，鼠标悬停 tooltip 展示核心结论；
     4. `最高风险`（宽 90px，居中）：`<RiskTag :severity="row.highest_severity" />`；
     5. `核查次数`（宽 95px，居中）：`共 X 次（高危 Y）`；
     6. `复核闭环`（宽 105px，居中）：`<StatusTag />` 中文状态（待复核 / 已确认 / 已整改 / 已关闭）；
     7. `最近核查时间`（宽 155px）：`formatDateTime(row.latest_push_time)`；
     8. `操作`（`fixed="right"`，宽 165px）：`查看详情` + `<HolographyButton :patient-id="row.patient_id" link />`。
   - **宽敞详情抽屉**：
     ```html
     <DetailDrawer v-model="detailVisible" title="患者质控详情" size="820px">
       <PatientQcDetailView
         v-if="selectedPatientId"
         :patient-id="selectedPatientId"
         :visit-number="selectedVisitNumber"
         :in-drawer="true"
         @updated="loadPatients"
       />
     </DetailDrawer>
     ```

3. **视角 B「按核查流水」（新建独立子组件 `AuditRecordListPanel.vue`）**：
   - 将原 `AuditRecordsPage.vue` 的完整功能（流水筛选、单条详情、重新推送、复核标记、勾选批量删除、CSV 导出）迁移到清爽规范的 `AuditRecordListPanel.vue`；
   - 表格固定表头，每行操作列新增 **`<HolographyButton :patient-id="row.patient_id" link />`**；
   - 保留所有既有权限校验与二次确认弹窗。

4. **旧路由兼容壳 `AuditRecordsPage.vue`**：
   - 仅保留约 20 行 `<script setup>`：在 `onMounted` **和** `onActivated`（路由有 keepAlive）中调用 `router.replace({ path: '/quality/patients', query: { ...route.query, view: 'records' } })`，确保所有旧链接无缝落到流水视角。

### 4.2 核心高可读性组件 `PatientQcDetailView.vue`（抽屉与独立页共用！）

**必须严格按以下 4 区块从上到下排版，严禁铺满原始 JSON！**

1. **区块 1：吸顶患者临床摘要卡（`.patient-banner`）**：
   - 背景 `#f8fafc`、`border: 1px solid var(--ma-border)`、`border-left: 4px solid var(--ma-blue-600)`、`border-radius: var(--ma-radius)`、`padding: 14px 16px`、`margin-bottom: 16px`；
   - **顶行（左右 Flex 对齐）**：
     - 左：患者姓名（`20px font-weight: 700`） + 性别/年龄灰标 + 住院号/患者号（点击可复制） + `<RiskTag />`；
     - 右：操作按钮组——
       1. **`<HolographyButton :patient-id="patientId" size="default" label="打开 360 全息视图" />`**（醒目主色按钮）；
       2. 若 `inDrawer === true`，显示「全屏查看」（用 `router.resolve({ path: '/quality/patient-detail', query: { patient_id, visit_number } }).href` 后 `window.open` 新窗口）；
       3. 若 `inDrawer === false`，显示「打印质控单」（`window.print()`，附 `@media print` 隐藏按钮样式）。
   - **次行（4 列紧凑信息网格 `grid-template-columns: repeat(4, minmax(120px, 1fr))`）**：
     - 所属科室 | 管床医生 | 入院 / 出院日期 | 主要诊断（占满整行或跨 2 列 `show-overflow-tooltip`）。

2. **区块 2：总体质控结论与闭环进度条**：
   - 3 项小数字徽章：本次住院累计高危 `N` 项 / 中危 `N` 项 / 低危 `N` 项；
   - 醒目一句话总体 AI 质控总结（去除了技术字段，中文自然段落 `line-height: 1.65`）。

3. **区块 3：缺陷问题可视化对照卡片列表（默认高危展开、中危展开、低危/通过折叠）**：
   - 顶部过滤小按钮：`仅看高/中危（默认）` | `查看全部维度`；
   - 每张问题卡 `.issue-card`（白底 + 左侧 3px 风险色条：高红 `#ef4444` / 中橙 `#f59e0b` / 低绿 `#22c55e`）：
     - **卡片头**：`<RiskTag />` + **问题维度中文名（15px 加粗）** + 所属质控类型灰色 tag + 右侧行内快捷操作组（**「确认属实」/「已整改」/「误报」**——点击弹出简短备注确认框并调用现有 `/qc/feedback/cases/{log_id}/confirm` 或复核接口，成功后 `emit('updated')` 刷新列表）；
     - **问题描述正文**：清晰展示 `conclusion` / `issue_summary`；
     - **左右双栏证据对比区（`display: grid; grid-template-columns: 1fr 1fr; gap: 12px;`；`< 680px` 自动单列）**：
       - 若结构化结果含双侧证据（如 `progress_evidence`/`nursing_evidence` 或 `evidence_list`），左盒（浅蓝灰底 `#f1f5f9`，小标题「病历 / 医嘱摘录」）与右盒（浅暖灰底 `#fffbeb`，小标题「佐证材料（护理/检验/手术）」）对照展示；
       - 若只有单段证据文本，优雅展示为全宽证据引用盒（左侧 2px 蓝线），**不出现空白半栏！**
     - **AI 建议行**：浅绿提示条「整改建议：...」。

4. **区块 4：底部 3 个干净 `<el-tabs>`**：
   - **Tab 1「历次核查历史」**：`<el-timeline>` 按时间倒序展示每次 AI 核查时间、质控类型、风险等级、是否成功、以及「单条重推」按钮；
   - **Tab 2「企微推送与医生反馈」**：展示告警推送时间、送达状态、医生查看次数/查看时间、医生反馈内容；
   - **Tab 3「技术排障报文」**：内部套 `<el-collapse>`（**默认全折叠！**），点开才展示「请求上下文」「AI 原始输出」「脱敏病历原文预览」三个独立可复制代码块。

### 4.3 `FeedbackPage.vue` & `AlertLogsPage.vue` 补全 360 入口
- 两页主表格的操作列均追加 `<HolographyButton :patient-id="row.patient_id" link />`（适当加宽操作列避免换行）；
- 两页详情抽屉顶部患者信息栏均追加 `<HolographyButton :patient-id="detail?.patient_id" size="small" label="360全息视图" />`。

---

## 五、绝对红线与禁令

1. 绝对不要直接把 `JSON.stringify(detail)` 铺在患者详情主界面上，技术报文必须默认收在 Tab 3 的 `<el-collapse>` 内。
2. 保留 `PatientDetailStandalonePage.vue` 路由路径与所有既有导出/复核/重推/删除权限检查，不可绕过权限。
3. 严禁修改 `prearchive_service/`；严禁 `git commit/push` 或连接生产写入。

---

## 六、验收测试与交付标准

1. 新建 `frontend/tests/unit/patient-qc-detail-view.test.ts` 覆盖：
   - 正常渲染患者临床摘要卡与 `<HolographyButton />`；
   - 默认仅展示高/中危问题卡片、可切全部维度；
   - 左右双栏证据对比正常渲染且单侧证据不出现空盒；
   - 技术排障报文默认处于折叠态（不直接渲染大块 JSON 到可见主区域）。
2. **收工必跑验收命令**：
```powershell
python -m compileall app tests scripts
python -m pytest tests/test_patient_qc_export_filters.py tests/test_patient_qc_frontend_static.py tests/test_logs_regression.py tests/test_logs_schema.py tests/test_logs_frontend_static.py tests/test_wp02_data_scope_and_holography.py -q
cd frontend
npm run typecheck
npm run test:unit -- tests/unit/patient-qc-detail-view.test.ts
npm run test:unit
npm run build
cd .. && python scripts/run_gates_20260906.py --quick
```
收工前登记 `开发起步包/01_统一修改记录.md` 与 `02_协作任务板.md`（本地交付完成，未提交）。
