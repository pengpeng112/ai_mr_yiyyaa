# AI质控首页总览深色科技驾驶舱 V2 改造方案

参考设计稿：`AI质控深色科技驾驶舱V2设计稿.png`
目标页面：AI质控运营驾驶舱 / 首页总览
目标项目：`pengpeng112/ai_mr_yiyyaa`
改造原则：**不改接口、不改字段、不改路由、不改权限、不改统计口径，只调整首页样式、布局、指标组织和空状态。**

---

## 1. 这版为什么要调整

上一版科技感不足，主要原因是仍然偏“白底后台卡片”。本版改为“深色态势指挥中心”风格，但不改变业务功能：左侧深色菜单、顶部运行状态、中心质控态势、右侧风险与健康矩阵，整体更适合申报材料、领导汇报和院内大屏展示。

---

## 2. GitHub 当前能力分析

当前代码中统计接口已经支持多个驾驶舱指标，不需要新增大量后端接口即可增强首页：

1. `/api/stats/summary` 可提供总推送数、成功数、失败数、成功率、不一致数、不一致率。
2. `/api/stats/daily` 可提供最近 N 天总量、成功、失败、不一致趋势。
3. `/api/stats/dept` 可提供科室分布。
4. `/api/stats/severity` 可提供风险等级分布。
5. `/api/stats/anomaly-top` 可提供异常高发科室或患者 Top10。
6. `/api/stats/dimensions` 可提供审计维度通过率。
7. `/api/health` 可提供 Oracle、Dify、Scheduler 等组件状态。

因此首页可以增加“质控维度通过率、AI闭环链路、异常高发科室Top、风险等级分布、系统健康矩阵”等模块，且多数数据可直接复用现有接口。

---

## 3. 页面整体布局

建议页面结构如下：

```text
AI质控运营态势指挥中心
├── 左侧科技菜单
├── 顶部运行状态栏
├── 8个核心态势指标
├── 近30天质控趋势
├── AI闭环链路
├── 风险等级分布
├── 质控维度通过率
├── 科室风险TOP
├── 系统健康矩阵
└── 高风险事件流
```

---

## 11. 可行性评估与风险结论

结论：**方案可行，且适合当前代码基础。** 当前首页已经具备 Dashboard 骨架、KPI 数据、趋势图、风险分布、维度分布、健康矩阵、科室 Top、高风险事件流等模块，V2 改造主要是视觉主题、布局密度和指标组织优化，不需要大改后端。

但是交给开发 AI 执行时必须收紧以下边界：

1. 当前项目不是完整 Vue 单文件组件工程，首页模板在 `static/templates/pages/dashboard.html`，逻辑在 `static/scripts/modules/dashboard.js`，样式在 `static/styles/pages/dashboard.css`。
2. 不能引入 Tailwind、Framer Motion、GSAP、Three.js、AntV 等新依赖；当前是静态资源 + Vue 全局对象 + Element Plus + ECharts。
3. 菜单 id 必须保持现有值，例如首页是 `dashboard`，前置机告警是 `relay-alert-logs`，推送日志是 `audit`。
4. 不要把“科室风险”“维度分析”等设计中的新菜单直接做成新页面，除非后端已有菜单和权限；本轮只能在首页内展示这些模块。
5. 不要把 `Dify` 强行展示为异常。当前代码已过滤 `dify`，因为生产健康检查里可能是 disabled，这是已知状态，不应影响首页整体健康判断。
6. “医生未查看”“前置机发送成功率”“医生查看率”优先来自 `/api/patient-qc/relay-alert/summary`，不是 `/api/stats/summary`。
7. “高风险事件流”当前从 `/api/logs` 过滤 `severity=high` 或 `risk_score>=80`，不应新造接口。
8. “累计红灯”如果没有独立字段，不建议单独展示，可合并为“高风险事件”或“高危维度数”。

---

## 12. 当前代码映射

| 改造内容 | 当前文件 | 说明 |
|---|---|---|
| 首页结构 | `static/templates/pages/dashboard.html` | 增删模块、调整布局顺序、保留 `activeMenu==='dashboard'` |
| 首页数据 | `static/scripts/modules/dashboard.js` | 已并发请求 summary/today/daily/severity/logs/anomaly-top/dimensions/health/relay summary |
| 首页样式 | `static/styles/pages/dashboard.css` | 本次改造主战场，建议大部分通过 CSS 完成 |
| 菜单结构 | `static/scripts/navigation.js` | 不建议本轮大改，仅可微调文案/视觉；不要改 id |
| 全局布局 | `static/index.html`、`static/styles/app.css` | 如需左侧菜单整体深色化，应谨慎改全局变量，避免影响其它页面 |
| 图表实例 | `getChart()` / `renderDash*Chart()` | 只改 ECharts option，不改图表容器 id |

---

## 13. 推荐最终首页结构

建议保持现有数据接口，只调整成以下更稳定的布局：

```text
dashboard-screen dashboard-tech-v2
├── 科技 Hero 顶栏
│   ├── 标题：AI质控运营态势指挥中心
│   ├── 副标题：住院病历一致性质控 / 风险预警 / 推送闭环 / 系统健康
│   └── 右侧：当前时间 / 系统状态 / 刷新按钮
├── 运行状态指挥条
│   ├── 今日不一致率
│   ├── 前置机失败
│   ├── 医生未查看
│   └── 最近调度/下次调度
├── 8 个核心态势 KPI
│   ├── 今日核查量
│   ├── AI核查成功率
│   ├── 今日不一致
│   ├── 今日推送成功
│   ├── 累计高危问题
│   ├── 待处理反馈
│   ├── 前置机成功率
│   └── 医生查看率
├── 主内容三栏
│   ├── 左：风险等级分布 + 系统健康矩阵
│   ├── 中：近30天质控趋势 + AI闭环链路
│   └── 右：科室风险 TOP + 高风险事件流
└── 底部：质控维度通过率/问题分布
```

说明：当前 `dashboard.html` 已有大部分模块，开发 AI 不必从零重写，只需重排 DOM 和替换 class。

---

## 14. 指标口径补充

| 展示名称 | 当前字段建议 | 兜底规则 |
|---|---|---|
| 今日核查量 | `dashboardKpis.total` | 无值显示 `0` |
| AI核查成功率 | `dashboardKpis.successRate` + `dashboardKpis.effectiveTotal` | `effectiveTotal=0` 显示 `--` |
| 今日不一致 | `dashboardKpis.inconsistency` | 无值显示 `0` |
| 今日推送成功 | `dashboardKpis.todaySuccess` | 无值显示 `0` |
| 累计高危问题 | `dashboardKpis.highRisk` | 来自 severity high，不能写死 |
| 待处理反馈 | `dashboardKpis.pendingFeedback` | 来自 feedback cases total |
| 前置机成功率 | `dashboardKpis.relaySuccessRate` | null 显示 `--` |
| 医生查看率 | `dashboardKpis.viewRate` | null 显示 `--` |
| 医生未查看 | `dashboardKpis.relayUnviewed` | 无值显示 `0` |
| 前置机失败 | `dashboardKpis.relayFailed` | 无值显示 `0` |

不建议把 `/api/stats/summary.total_pushes` 直接当“今日核查量”，因为当前 `dashboard.js` 已经调用 `/api/stats/today` 并按今日口径计算，避免全量/今日口径混淆。

---

## 15. 视觉规范补充

### 15.1 颜色

```css
.dashboard-tech-v2 {
  --dash-bg: #020617;
  --dash-panel: rgba(15, 23, 42, 0.82);
  --dash-panel-strong: rgba(8, 15, 32, 0.92);
  --dash-border: rgba(56, 189, 248, 0.22);
  --dash-border-strong: rgba(56, 189, 248, 0.42);
  --dash-text: #e2f3ff;
  --dash-muted: #8fb4d6;
  --dash-cyan: #22d3ee;
  --dash-blue: #3b82f6;
  --dash-green: #22c55e;
  --dash-orange: #f59e0b;
  --dash-red: #ef4444;
}
```

### 15.2 风格要求

1. 背景使用深蓝黑径向光斑，不使用纯黑。
2. 卡片使用半透明深色面板 + 青色细边框 + 内阴影，不使用大面积蓝紫渐变。
3. 只允许轻微动效：hover 上浮、边框高亮、扫描线慢速移动。
4. 必须支持 `prefers-reduced-motion: reduce`，关闭动画。
5. 移动端仍要能阅读，不允许固定 1920 大屏宽度。

---

## 16. 图表深色化要求

开发 AI 修改 `renderDashTrendChart`、`renderDashSeverityChart`、`renderDashDimensionChart` 时，只允许改 ECharts option 的展示属性：

1. `legend.textStyle.color` 改为浅蓝灰。
2. `xAxis/yAxis.axisLabel.color` 改为浅蓝灰。
3. 增加 `splitLine.lineStyle.color = 'rgba(148, 163, 184, 0.12)'`。
4. tooltip 使用深色背景：`backgroundColor: 'rgba(15,23,42,.96)'`。
5. 不改 series 字段来源，不改 data map 逻辑。
6. 空数据时不手写假数据，显示空状态。

---

## 17. AI闭环链路模块补充

该模块是静态说明模块，不需要接口。推荐 HTML 结构：

```html
<div class="dashboard-panel dashboard-flow-panel">
  <div class="panel-title">AI质控闭环链路</div>
  <div class="ai-flow-line">
    <div class="ai-flow-node">采集</div>
    <div class="ai-flow-node">解析</div>
    <div class="ai-flow-node">核查</div>
    <div class="ai-flow-node">推送</div>
    <div class="ai-flow-node">整改</div>
  </div>
</div>
```

节点只用于展示系统能力，不代表任务实时状态。不要在没有数据源时显示“成功/失败”。

---

## 18. 验收清单

开发完成后必须逐项检查：

1. 首页能正常加载，无控制台报错。
2. 点击刷新仍调用 `loadDashboard`，按钮 loading 正常。
3. 8 个 KPI 均来自现有 `dashboardKpis`，没有硬编码业务数字。
4. 点击 KPI 后仍能跳转：推送日志、患者质控、质控反馈、前置机告警。
5. 趋势图、风险环图、维度图 tooltip 正常。
6. 接口失败时页面不崩溃，保留兜底空状态。
7. `/api/health` 中 disabled 组件不应导致全屏红色异常。
8. 1366 宽度、1920 宽度、移动端宽度都不横向溢出。
9. 不修改 `app/routers/*` 后端接口文件。
10. 执行 `python -m compileall app tests scripts` 通过。

---

## 19. 建议分阶段执行

### 阶段 1：只改首页深色科技皮肤

只改：

```text
static/styles/pages/dashboard.css
static/templates/pages/dashboard.html
static/scripts/modules/dashboard.js
```

目标：实现深色背景、面板、KPI、图表深色化、AI闭环链路。

### 阶段 2：优化全局左侧菜单深色化

只改：

```text
static/styles/app.css
static/scripts/navigation.js（仅在确认菜单分组需要调整时）
```

目标：菜单视觉与首页统一，但不改变菜单 id、route、权限。

### 阶段 3：补充交互细节

目标：hover 微动效、空状态、骨架屏深色化、移动端适配。

---

## 20. 修订后的开发 AI 提示词

```markdown
请基于 `docs/20260624界面设计/AI质控深色科技驾驶舱V2开发改造方案.md`，只改造 AI质控首页总览为深色科技驾驶舱风格。

项目现状：
- 首页模板：static/templates/pages/dashboard.html
- 首页逻辑：static/scripts/modules/dashboard.js
- 首页样式：static/styles/pages/dashboard.css
- 当前是静态 Vue + Element Plus + ECharts，不是 SFC 工程。

本轮必须遵守：
1. 不改任何后端接口、字段名、权限逻辑、路由 id。
2. 不新增 npm 依赖，不引入 Tailwind/GSAP/Framer/Three。
3. 不写死业务数字，不伪造图表数据。
4. 保留现有刷新、KPI 点击跳转、图表 tooltip、空状态。
5. 首页 activeMenu 必须仍是 `dashboard`。
6. 前置机告警菜单 id 必须仍是 `relay-alert-logs`。
7. 推送日志菜单 id 必须仍是 `audit`。

改造目标：
1. 为首页根节点增加 `dashboard-tech-v2` 风格类。
2. 将页面视觉改为深蓝黑科技态势驾驶舱。
3. 保留并重组现有 8 个 KPI：今日核查量、AI核查成功率、今日不一致、今日推送成功、累计高危问题、待处理反馈、前置机成功率、医生查看率。
4. 深色化近30天趋势图、风险等级环图、质控维度图，只改 ECharts 展示 option，不改数据来源。
5. 新增静态 AI闭环链路模块：采集→解析→核查→推送→整改。
6. 优化科室风险 TOP、系统健康矩阵、高风险事件流为深色卡片。
7. 骨架屏和空状态也要适配深色背景。
8. 保持响应式，移动端不能横向溢出。

验收：
- 运行 `python -m compileall app tests scripts`。
- 打开首页确认无 JS 报错。
- 点击刷新、KPI 跳转、图表 tooltip 均正常。
```

---

## 4. 左侧菜单优化

### 4.1 菜单风格

采用深色科技风：

```css
--nav-bg: #030817;
--nav-active: #2563eb;
--nav-line: #00d4ff;
--nav-text: #dbeafe;
--nav-muted: #8fb4d6;
```

### 4.2 菜单分组

```text
工作台
├── 首页总览

质控闭环
├── 患者闭环
├── 前置机告警
├── 推送日志
├── 质控反馈

数据分析
├── 科室风险
├── 维度分析

运维配置
├── 系统健康
├── 系统配置
```

要求：不重复显示分组；当前“首页总览”高亮；badge 数量来自真实数据；不改原 route/path/权限。

---

## 5. 核心指标调整建议

### 5.1 顶部 8 个态势指标

| 指标 | 数据来源建议 | 说明 |
|---|---|---|
| 总核查量 | `/api/stats/summary.total_pushes` 或今日接口 | 今日推送/核查总量 |
| 成功率 | `/api/stats/summary.success_rate` | AI核查成功情况 |
| 不一致率 | `/api/stats/summary.inconsistency_rate` | 质控核心指标 |
| 失败任务 | `/api/stats/summary.failed_count` | 失败/重试入口 |
| 医生未查看 | 当前业务接口或日志筛选 | 闭环触达效果 |
| 高风险事件 | `/api/stats/severity` high | 高风险问题数量 |
| 累计红灯 | 高风险累计数 | 可复用 severity 或日志聚合 |
| 质控维度 | `/api/stats/dimensions` | 维度数量与通过率入口 |

### 5.2 指标处理建议

如果“今日成功率”分母异常导致显示 `--`，不建议放在最显眼位置，可改为：

```text
AI核查成功率
失败任务数
有效核查任务数
```

---

## 6. 中部增强模块

### 6.1 近30天质控趋势

复用 `/api/stats/daily`，深色化展示：

```text
推送总数：青色
高风险：红色
中风险：橙色
低风险：蓝色/绿色
```

要求：保留原 tooltip、日期筛选和数据接口；空数据时显示“暂无趋势数据”。

### 6.2 AI闭环链路

新增静态视觉模块：

```text
采集 → 解析 → 核查 → 推送 → 整改
```

该模块用于说明系统工作流，不需要新增接口，不影响功能。

### 6.3 风险等级分布

复用 `/api/stats/severity`，建议改为环形图：

```text
低危：蓝色
中危：橙色
高危：红色
```

---

## 7. 底部增强模块

### 7.1 质控维度通过率

复用 `/api/stats/dimensions`，按接口实际返回维度展示，不写死维度名称。

### 7.2 科室风险 TOP

复用 `/api/stats/anomaly-top?group_by=dept`，Top 3 高亮，点击科室可带入筛选条件跳转日志或质控反馈。

### 7.3 系统健康矩阵

复用 `/api/health`，当前后端明确有 oracle、dify、scheduler。app_db、PostgreSQL 如当前接口没有，可不展示或作为后续扩展项。

### 7.4 高风险事件流

可从日志列表或 severity=high 的过滤结果获取。点击事件应进入详情，复用原“详情/更多/重推/闭环处理”能力。

---

## 8. 前端实现约束

必须遵守：

```text
1. 不修改接口URL。
2. 不修改字段名。
3. 不修改统计口径。
4. 不写死业务数字。
5. 不影响刷新按钮。
6. 不影响菜单跳转。
7. 不影响图表 tooltip。
8. 不影响日志详情、更多、重推等操作。
9. 不影响权限控制。
10. 不影响已有部署方式。
```

---

## 9. 建议开发步骤

### Commit 1：深色科技主题样式

```text
fix: add dark tech dashboard theme
```

### Commit 2：核心 KPI 重组

```text
fix: reorganize dashboard kpi metrics
```

### Commit 3：图表区科技化

```text
fix: polish dashboard trend and risk charts
```

### Commit 4：新增静态闭环链路模块

```text
feat: add ai closed loop pipeline visualization
```

### Commit 5：底部风险与健康矩阵

```text
fix: improve risk top and health matrix panels
```

---

## 10. 给开发 AI 的执行提示词

```markdown
请基于“AI质控深色科技驾驶舱V2设计稿.png”对 AI质控首页总览进行高端科技感改造。要求只优化展示，不影响任何原功能。

请先核查现有接口：
- /api/stats/summary
- /api/stats/daily
- /api/stats/severity
- /api/stats/anomaly-top
- /api/stats/dimensions
- /api/health

改造要求：
1. 首页改为深色科技驾驶舱风格。
2. 左侧菜单深色化，当前首页总览高亮。
3. 顶部保留系统管理员、时间、系统状态、刷新、退出。
4. KPI 调整为 8 个态势指标：总核查量、成功率、不一致率、失败任务、医生未查看、高风险事件、累计红灯、质控维度。
5. 近30天趋势图深色化，不改数据接口。
6. 新增静态 AI闭环链路：采集→解析→核查→推送→整改。
7. 风险等级分布使用环形图，复用 severity 接口。
8. 质控维度通过率复用 dimensions 接口。
9. 科室风险 TOP 复用 anomaly-top 接口。
10. 系统健康矩阵复用 health 接口。
11. 高风险事件流复用日志或风险过滤结果。
12. 无数据时必须显示空状态，不允许大面积空白。

严格禁止：
- 改接口 URL
- 改字段名
- 改统计口径
- 写死业务数据
- 删除原功能入口
- 改权限逻辑
- 影响刷新、跳转、详情、重推、筛选功能
```
