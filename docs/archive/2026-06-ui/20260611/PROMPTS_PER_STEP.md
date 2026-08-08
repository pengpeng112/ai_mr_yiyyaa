# 分阶段执行提示词（每界面独立）

> 用途：将下列每个提示词单独复制给其他 AI，按编号顺序分阶段执行。
> 项目：`F:\python\前后端代码\ai_mrzk`
> 先决条件：执行前必须阅读 `AGENTS.md` 和对应的设计文档。

---

## 提示词 1：菜单统一（navigation.js）

```text
你是 Med-Audit 前端开发助手。请执行"菜单统一"改造。

【项目背景】
- 项目路径：F:\python\前后端代码\ai_mrzk
- 技术栈：FastAPI + Vue3 + Element Plus 静态前端
- 菜单配置在 static/scripts/navigation.js
- 所有页面通过 static/index.html 中的 Vue 应用挂载，activeMenu 控制显示
- 请先阅读 AGENTS.md 和 docs/20260611界面设计/ai_mr_menu_redesign_plan.md

【已确认决策】
1. 前置机告警从患者质控 Tab 拆分为独立菜单页面，放入"质控业务"组。
2. 推送进度作为新增独立页面，放入"推送管理"组。
3. 权限管理保留在"运维管理"组。

【任务】
修改 static/scripts/navigation.js，使菜单结构最终为：

工作台
└─ 首页总览

质控业务
├─ 患者质控
├─ 前置机告警        ← 新增独立入口，target: { activeMenu: 'relay-alert-logs' }
├─ 质控反馈
└─ 推送日志

推送管理
├─ 手动推送
├─ 定时任务
├─ 推送进度          ← 新增独立入口，target: { activeMenu: 'push-progress' }

配置中心
├─ 系统配置
├─ 审计类型
├─ 企业微信推送配置
└─ 运行总览

运维管理
├─ 系统健康
├─ Dify 调试
├─ 权限管理
├─ Oracle 连接       ← 可先保留，未实现页面点击显示"功能建设中"
└─ 运行日志          ← 可先保留，未实现页面点击显示"功能建设中"

【具体要求】
1. 修改 FALLBACK_GROUPS 和 FALLBACK_MENU。
2. 新增菜单项 key 建议：
   - 前置机告警：id='relay-alert-logs', label='前置机告警', group='qc', target={ activeMenu: 'relay-alert-logs' }
   - 推送进度：id='push-progress', label='推送进度', group='push', target={ activeMenu: 'push-progress' }
3. 患者质控 target 保持 { activeMenu: 'patient-qc', tab: 'patients' }。
4. 在 static/index.html 的 Vue 应用中，为新的 activeMenu 值添加对应 v-show 容器占位（即使暂时为空内容），避免点击报错。
5. 确保 dashboard、push、scheduler、audit、config、health 等原有入口仍可正常跳转。
6. 不要删除任何现有菜单项，仅做新增/调整分组。

【约束】
- 只改前端，不改后端。
- 不要修改现有路由处理逻辑。
- 保持现有代码风格。

【验证】
1. python -m compileall app tests scripts 通过。
2. 浏览器打开首页，侧边栏能看到"前置机告警"和"推送进度"。
3. 点击两个新菜单，页面切换正常，控制台无 JS 报错。
4. 原有菜单入口（患者质控、手动推送、定时任务等）仍可正常跳转。

【输出】
返回：修改文件清单、关键代码片段、验证结果、是否遇到阻塞。
```

---

## 提示词 2：前置机告警独立页面

```text
你是 Med-Audit 前端开发助手。请执行"前置机告警独立页面"改造。

【项目背景】
- 项目路径：F:\python\前后端代码\ai_mrzk
- 当前前置机告警是 patient_qc.html 中的 Tab（患者总览 / 前置机告警）
- 接口：/api/patient-qc/relay-alert/*
- 请先阅读 AGENTS.md 和 docs/20260611界面设计/ai_mr_premachine_alert_ui_plan.md

【任务】
将前置机告警从患者质控 Tab 拆分为独立页面。

【步骤】
1. 新建 static/templates/pages/relay_alert.html
   - section v-show="activeMenu==='relay-alert-logs'"
   - 46px 标题操作条：标题"前置机告警" + 副标题 + 右侧按钮（刷新 / 批量重试 / 批量提醒 / 导出）
   - 38px 指标细条：告警总数 / 发送成功率 / 发送失败 / 待发送 / 医生查看率 / 未查看
   - 42px 筛选条：患者ID / 在院科室 / 严重度 / 发送状态 / 查看状态 / 日期范围 / 查询 / 重置
   - 主体左右布局：左侧告警表格 + 右侧选中告警摘要

2. 新建 static/scripts/modules/relay_alert.js（或扩展 patient_qc.js 导出相关方法）
   - 复用现有接口 /api/patient-qc/relay-alert/*
   - 加载列表、筛选、分页、详情、重试功能
   - 批量操作按钮可先保留 UI，如后端无批量接口则点击提示"功能待实现"

3. 在 static/index.html 中引入并注册新页面
   - 确保 activeMenu==='relay-alert-logs' 时显示 relay_alert.html

4. 修改 static/templates/pages/patient_qc.html
   - 移除"患者总览 / 前置机告警"Tab，仅保留"患者总览"
   - 移除 patient_qc.js 中与前缀机告警相关的 Tab 切换和数据加载逻辑（或迁移到 relay_alert.js）

5. 如有需要，新建 static/styles/pages/relay_alert.css 或复用 patient_qc.css

【具体 UI 要求】
- 表格列：患者ID(96) / 在院科室(100) / 严重度(56) / 发送状态(62) / 查看状态(62) / 查看次数(64) / 查看人(80) / 最后查看(132) / 核查摘要(自适应) / 创建时间(132) / 操作(96)
- 操作列："详情 / 重试"，仅失败记录显示重试。
- 状态颜色：高危红、中危橙、低危蓝；发送成功绿、失败红、待发送橙/灰；已查看绿、未查看灰/橙。
- 右侧摘要：患者ID、科室、严重度、状态、查看次数、查看人、最后查看、发送时间、重试次数、核查摘要、失败原因。
- 空态使用 el-empty，提示"暂无前置机告警记录"。

【约束】
- 只改前端，不改后端接口。
- 保留原有详情抽屉、重试、筛选逻辑。
- 表格行高 38px～42px，字体 12px～13px。
- 不要破坏患者质控页面的现有功能。

【验证】
1. python -m compileall app tests scripts 通过。
2. 侧边栏"前置机告警"点击进入新页面，列表正常加载。
3. 筛选、分页、详情、重试功能正常。
4. 患者质控页面不再显示前置机告警 Tab，只有"患者总览"。
5. 控制台无 JS 报错。

【输出】
返回：新建/修改文件清单、迁移说明、验证结果、阻塞问题。
```

---

## 提示词 3：患者质控右侧摘要

```text
你是 Med-Audit 前端开发助手。请执行"患者质控右侧摘要"改造。

【项目背景】
- 项目路径：F:\python\前后端代码\ai_mrzk
- 当前患者质控页面：static/templates/pages/patient_qc.html
- 逻辑模块：static/scripts/modules/patient_qc.js
- 请先阅读 AGENTS.md 和 docs/20260611界面设计/ai_mr_patient_qc_ui_plan.md

【已确认】
前置机告警已拆分为独立页面，患者质控页面仅保留"患者总览"。

【任务】
在患者质控列表页增加点击行后的右侧摘要卡，并收敛操作列。

【具体要求】
1. 修改 static/templates/pages/patient_qc.html
   - 主体区改为左右布局：左侧患者列表（flex:1），右侧摘要卡（宽度 320px）。
   - 右侧摘要包含：
     - 基本信息：患者ID、姓名、住院号、住院次、在院科室、出院科室、入出院日期
     - 质控结果：问题数 / 高危 / 中危 / 待处理 / 已闭环
     - 主要问题：Top 3 问题摘要
     - 维度状态：高危/中危/低危维度数量
     - 处理记录：最近处理状态
     - 快捷操作：打开报告 / 提醒医生 / 查看文书 / 闭环反馈
   - 操作列从仅"详情"改为"报告 + 更多"：
     - 报告：调用 openReport(row.id)
     - 更多下拉：详情 / 弹出提醒 / 复制患者ID / 闭环反馈
   - 点击表格行（除操作按钮外）更新右侧摘要，不触发后端写操作。

2. 修改 static/scripts/modules/patient_qc.js
   - 新增选中患者状态：selectedPatientQc
   - 点击行时设置 selectedPatientQc = row
   - 为右侧快捷操作绑定现有函数：openReport、openPopup、openPatientQcDetail、copyPatientId、openFeedbackAction
   - 如果某些函数不存在，使用当前等效函数或添加 TODO 注释。

3. 修改 static/styles/pages/patient_qc.css
   - 左右布局响应式：小屏下右侧摘要下移，列表可横向滚动。
   - 摘要卡样式：圆角 12px、边框、阴影、内部信息分区。

【约束】
- 只改前端，不改后端接口。
- 保留现有详情抽屉、筛选、分页、导出汇总功能。
- 表格行高保持 40px 左右。
- 不要破坏原有 openReport、openPopup 等功能。

【验证】
1. python -m compileall app tests scripts 通过。
2. 点击患者行，右侧摘要正确更新。
3. 报告按钮可正常打开报告。
4. 更多菜单中的详情、弹出提醒可用。
5. 页面在 1366px 宽度下正常，小屏下右侧摘要下移。

【输出】
返回：修改文件清单、右侧摘要字段说明、验证结果、阻塞问题。
```

---

## 提示词 4：质控反馈紧凑改造

```text
你是 Med-Audit 前端开发助手。请执行"质控反馈紧凑改造"。

【项目背景】
- 项目路径：F:\python\前后端代码\ai_mrzk
- 当前页面：static/templates/pages/feedback.html
- 逻辑模块：static/scripts/modules/feedback.js
- 请先阅读 AGENTS.md 和 docs/20260611界面设计/ai_mr_feedback_ui_plan.md

【任务】
将质控反馈页面从大统计卡改为紧凑版反馈处理台，并增加右侧选中反馈摘要。

【具体要求】
1. 修改 static/templates/pages/feedback.html
   - 移除顶部 4 个大统计卡。
   - 新增 38px 指标细条：近期不一致 / 高风险 / 待确认 / 已关闭 / 今日新增 / 未打印报告 / 整改闭环率
     - 整改闭环率优先通过前端已有数据计算：resolved_count / issue_count * 100，若无法计算则显示"--"。
   - 顶部操作条右侧：刷新 / 批量确认 / 批量关闭 / 导出 Excel。
   - 筛选区一行展示：患者ID / 姓名 / 住院号 / 科室 / 核查类型 / 风险等级 / 反馈状态 / 日期范围 / 查询 / 重置。
   - 表格行高压缩到 38px～42px，字体 12px～13px。
   - 操作列改为"详情 / 打印 / 更多"：
     - 更多中放：确认反馈 / 关闭反馈 / 提醒医生 / 删除 / 复制患者ID
   - 主体区改为左右布局：左侧反馈列表，右侧选中反馈摘要（宽度 320px）。
   - 右侧摘要包含：患者信息 / 质控结果 / 风险等级 / 反馈状态 / 主要问题摘要 / 处理记录 / 快捷操作。

2. 修改 static/scripts/modules/feedback.js
   - 新增 selectedFeedbackCase 状态。
   - 点击行时更新右侧摘要。
   - 为批量操作按钮绑定函数（若后端无批量接口，先提示"功能待实现"）。
   - 保留现有 viewFeedbackDetail、openPrintableReport、deleteFeedbackCase、看板视图功能。

3. 修改 static/styles/pages/feedback.css
   - 指标细条样式：紧凑、无大卡片、带颜色阈值。
   - 右侧摘要卡样式。
   - 小屏响应式：右侧摘要下移。

【约束】
- 只改前端，不改后端接口。
- 保留现有详情弹窗、打印报告、删除、看板视图功能。
- 批量确认/关闭可先保留 UI，不要破坏现有删除逻辑。

【验证】
1. python -m compileall app tests scripts 通过。
2. 页面加载正常，指标细条显示正确。
3. 筛选、分页、详情、打印报告、删除正常。
4. 点击行右侧摘要更新。
5. 操作列"更多"下拉可正常弹出。

【输出】
返回：修改文件清单、指标细条计算逻辑、验证结果、阻塞问题。
```

---

## 提示词 5：审计类型编排控制台

```text
你是 Med-Audit 前端开发助手。请执行"审计类型编排控制台"改造。

【项目背景】
- 项目路径：F:\python\前后端代码\ai_mrzk
- 当前页面：static/templates/pages/audit_types.html
- 逻辑模块：static/scripts/modules/audit_types.js
- 请先阅读 AGENTS.md 和 docs/20260611界面设计/ai_mr_audit_type_orchestration_ui_plan.md

【任务】
将审计类型管理从表格平铺改为"左侧规则列表 + 中间规则详情 Tab + 右侧执行链路摘要"的三栏编排控制台。

【具体要求】
1. 修改 static/templates/pages/audit_types.html
   - 顶部：46px 标题操作条（审计类型管理 + 新建类型 / 导入配置 / 刷新）
   - 状态概览条：审计类型总数 / 已启用 / 默认调度 / 配置告警 / SQL 已配置 / Dify 已配置
   - 三栏主体：
     - 左侧规则列表（宽度 300px～340px）：显示编码、名称、启用状态、默认调度、配置风险、最近测试状态
     - 中间规则详情 Tab（自适应）：基础信息 / 数据源 SQL / Payload 构建 / Dify 工作流 / 测试调试
     - 右侧执行链路摘要（宽度 300px～340px）：执行链路、配置完整性、最近测试、风险提示
   - 主列表每行操作收敛为"编辑 / 更多"：
     - 更多中放：克隆 / 测试数据源 / 测试 Dify / 导出 JSON / 删除
   - 保留现有编辑弹窗（含所有 Tab），点击左侧规则时可选中并显示详情。

2. 修改 static/scripts/modules/audit_types.js
   - 新增 selectedAuditType 状态。
   - 新增 activeAuditTab 状态（basic/sql/payload/dify/test）。
   - 加载审计类型列表后，默认选中第一条。
   - 点击左侧规则切换详情和摘要。
   - 状态概览条数据从 auditTypesList 计算。
   - 右侧执行链路摘要根据 selectedAuditType 计算：
     - SQL 是否配置 / 展示是否配置 / 密钥是否有 / URL 是否配置
     - 最近测试状态（可从 auditTypeRuntimeSummary 取）
     - 风险提示（从 auditTypeRuntimeWarnings 过滤）

3. 修改 static/styles/pages/audit_types.css
   - 三栏布局、左侧列表、右侧摘要样式。
   - Tab 高度 36px，SQL 编辑器高度 220px～260px。
   - 小屏下三栏降级为上下布局。

【约束】
- 只改前端，不改后端接口和审计类型 JSON 配置结构。
- 保留现有新建、编辑、克隆、测试数据源、测试 Dify、删除功能。
- 保留原有编辑弹窗内的所有 Tab 和数据结构。
- 原有"运行解析摘要"中的配置完整性信息不丢失。

【验证】
1. python -m compileall app tests scripts 通过。
2. 审计类型列表正常显示。
3. 点击左侧规则能切换中间详情和右侧摘要。
4. 新建、编辑、克隆、测试、删除功能正常。
5. 状态概览条数据正确。
6. 小屏下三栏可正常降级。

【输出】
返回：修改文件清单、三栏布局说明、验证结果、阻塞问题。
```

---

## 提示词 6：推送进度新页面（可选 P1 扩展）

```text
你是 Med-Audit 前端开发助手。请执行"推送进度新页面"开发。

【项目背景】
- 项目路径：F:\python\前后端代码\ai_mrzk
- 当前手动推送页已有任务进度面板，定时任务页已有执行历史
- 请先阅读 AGENTS.md 和 docs/20260611界面设计/ai_mr_push_progress_ui_plan.md

【任务】
新增"推送进度"独立页面，放入左侧菜单"推送管理"组。

【具体要求】
1. 新建 static/templates/pages/push_progress.html
   - section v-show="activeMenu==='push-progress'"
   - 46px 标题操作条：标题"推送进度" + 副标题 + 右侧按钮（刷新 / 查看最近任务）
   - 42px 状态细条：运行中 / 今日完成 / 今日失败 / 总任务 / 平均耗时
   - 44px 筛选条：任务状态 / 触发方式 / 审计类型 / 日期范围 / 查询 / 重置
   - 表格主体：任务列表

2. 新建 static/scripts/modules/push_progress.js
   - 复用现有接口：
     - /api/push/task/latest
     - /api/push/task/{task_id}/progress
     - /api/scheduler/history（可选，用于展示定时任务历史）
   - 加载任务列表、筛选、分页、详情
   - 运行中任务显示"停止"按钮（如后端支持停止接口）

3. 在 static/index.html 中注册新页面

4. 表格列：任务ID / 触发方式 / 查询日期 / 审计类型 / 总数 / 已处理 / 成功 / 失败 / 跳过 / 成功率 / 耗时 / 状态 / 开始时间 / 操作

5. 右侧抽屉详情：
   - 任务摘要
   - 进度条
   - 审计类型分布
   - 诊断信息
   - 跳过原因统计
   - 查看关联推送日志入口

6. 新建 static/styles/pages/push_progress.css 或复用现有样式。

【约束】
- 只改前端，不新增后端推送执行逻辑。
- 不修改已有手动推送接口。
- 表格行高 38px～44px。

【验证】
1. python -m compileall app tests scripts 通过。
2. 侧边栏"推送进度"点击进入新页面。
3. 列表、筛选、分页、详情正常。
4. 控制台无 JS 报错。

【输出】
返回：新建/修改文件清单、接口复用说明、验证结果、阻塞问题。
```

---

## 通用约束（所有提示词共用）

1. **只改前端**：不修改后端接口、业务逻辑、数据库模型。
2. **如需新增后端 KPI 接口**：先停止并请示用户，不要自行实现。
3. **保留现有功能**：所有原有按钮、接口调用、状态字段必须继续可用。
4. **命名规范**：
   - HTML 文件：小写 + 下划线，如 `relay_alert.html`、`push_progress.html`
   - JS 模块：小写 + 下划线，如 `relay_alert.js`
   - activeMenu key：小写 + 连字符，如 `relay-alert-logs`、`push-progress`
5. **样式规范**：
   - 侧边栏宽度保持 240px
   - 卡片圆角 8px～12px
   - 紧凑列表行高 38px～44px
   - 继续使用 CSS 变量
6. **测试验证**：
   - 每步完成后运行 `python -m compileall app tests scripts`
   - 浏览器验证菜单切换、页面加载、筛选、分页、弹窗/抽屉正常
   - 无 JS 报错、无 404
7. **Git 提交**：
   - 每完成一步单独提交：`feat: P1-步骤X-简短说明`
   - 不要一次提交大量无关文件
   - 不要推送，除非用户明确要求
8. **部署**（如需要）：
   - 目标容器：`med-audit` @ `10.10.8.84:40022`
   - 方式：`docker cp` 更新静态资源 → `docker commit -m "msg" med-audit med-audit:latest` → `docker restart med-audit`
   - 不要执行 `docker-compose down`
