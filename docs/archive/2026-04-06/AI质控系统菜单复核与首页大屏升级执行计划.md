# AI质控系统界面菜单整合与首页大屏升级计划（复核修订版）

项目仓库：`pengpeng112/ai_mr_yiyyaa`  
当前审查提交：`8ef64979e8c0240f5111a4e9ab6eae0479b226db`  
计划版本：`ui-menu-dashboard-v2`  
目标：在不影响现有功能的基础上，完成后台菜单整合、页面入口归类、患者质控与前置机告警整合，并把首页升级为更直观、更高端的大屏驾驶舱。

---

## 1. 本次复核结论

### 1.1 commit `8ef6497` 本身影响很小

该提交只涉及：

1. `Dockerfile` 中 `NLS_LANG` 增加引号。
2. `app/routers/mobile_qc.py` 增加顶部 `import json`，删除函数内重复 import。

该提交没有直接改后台菜单和首页界面，因此本计划主要针对当前 HEAD 的整体 UI 结构进行优化。

### 1.2 结合当前代码后的执行口径

本计划已经按当前 HEAD 复核修订，后续开发 AI 必须以以下事实为准：

1. 前端是无构建步骤的 `static/index.html` + Vue 全局对象 + ES module 架构，不存在 Vue Router、打包入口或 `src/` 目录。
2. 页面模板通过 `data-template-src` 动态加载，改造首页只改 `static/templates/pages/dashboard.html`、`static/scripts/modules/dashboard.js`、`static/styles/pages/dashboard.css`，必要时同步更新 `static/index.html` 中 `app.js` 版本号。
3. 当前菜单仍在 `static/index.html` 中桌面/移动两份硬编码；后端 `/api/menu` 暂未被前端主导航消费。
4. 权限管理页面的菜单目录来自 `GET /api/roles/menus/catalog`，该接口复用 `app.routers.menu.MENU_CATALOG`。只改 `/api/menu/all` 不会让角色菜单分配页完整可用。
5. `RoleMenuInfo` 当前 schema 只有 `id/label/icon/path`。如果后端 catalog 返回 `group/target/order`，必须先扩展 `app/schemas.py`，否则 response_model 会丢字段或产生兼容问题。
6. `patient_qc.html/js` 当前没有 `patientQcTab`、`relayAlertList`、`relayAlertFilter` 等状态；前置机告警 tab 是新增前端功能，不是已有 tab 调整。
7. 后端已经有 `GET /api/patient-qc/relay-alert/logs` 和 `POST /api/patient-qc/relay-alert/retry/{alert_id}`，第一版不要另起后端模块。
8. 后端已经有 `/api/stats/severity`、`/api/stats/anomaly-top`、`/api/stats/dimensions`，首页第一版可以复用现有统计接口。
9. 不要修改 `config/config.json`，不要提交本地临时分析脚本、Excel 文件或 `backups/`。

---

## 2. 上一版菜单计划复核意见

上一版“界面与菜单整合优化计划”整体方向正确，但需要补充和修正以下点。

### 2.1 正确的部分

上一版判断准确：

1. 当前菜单来源不统一。
2. 后端 `MENU_CATALOG` 与前端硬编码菜单不一致。
3. 桌面菜单和移动菜单重复硬编码。
4. `patient-qc`、`audit-types`、`relay` 等前端菜单没有完整纳入后端菜单目录。
5. 不应第一版引入 Vue Router。
6. 不应删除现有 `activeMenu` key。
7. 应保留 `switchMenu()` 中的 legacy 映射。

### 2.2 需要修正的部分

#### 修正 1：动态菜单不能只依赖后端返回值

当前后端 `RoleMenu` 如果已经配置过，新增菜单可能不会自动出现在用户菜单中。  
因此前端必须保留 `FALLBACK_MENU`，后端也需要提供“菜单补全/重置”说明。

当前主导航实际仍是 `static/index.html` 的硬编码菜单，暂未调用 `/api/menu`。第一版如果改为动态菜单，必须同时保留硬编码等价的 `FALLBACK_MENU`，并保证接口失败、token 过期、角色菜单缺项时仍能进入核心页面。

要求：

- `/api/menu` 获取失败时使用前端 fallback。
- 后端新增菜单后，不要导致已有角色菜单为空或缺项。
- `/api/menu/all` 必须返回完整 `catalog`，方便权限管理页面分配新增菜单。
- `GET /api/roles/menus/catalog` 也必须返回完整 `catalog`，因为当前权限管理页面实际读取该接口。
- 若新增 `group`、`target`、`order` 字段，必须同步扩展 `RoleMenuInfo`，或只在前端 `navigation.js` 中维护这些展示元数据，避免后端 response_model 兼容风险。

#### 修正 2：菜单项 target 不能影响 `activeMenu` 原语义

新增如 `relay-alert-logs`、`config-runtime` 这类逻辑菜单时，不要把它们直接作为 `activeMenu`，而应映射到已有页面：

```text
relay-alert-logs -> activeMenu='patient-qc', patientQcTab='relay-alerts'
config-runtime   -> activeMenu='config', configTab='runtime-summary'
```

注意当前 legacy 映射里已有 `cfg-runtime -> configTab='runtime-summary'`，新增 `config-runtime` 时应复用同一语义，不要新增第二个页面 key。

#### 修正 3：前置机告警列表已有后端落点

当前后端已有：

```text
GET /api/patient-qc/relay-alert/logs
POST /api/patient-qc/relay-alert/retry/{alert_id}
```

因此不要另起新的后端模块。应在 `patient_qc.html` 中增加 “前置机告警” tab。

当前接口尚不支持 `viewed_flag` 查询筛选；如果 tab 需要“已查看/未查看”过滤，应在 `list_relay_alert_logs()` 中新增可选 `viewed_flag: Optional[int]`，并保持默认行为兼容。

#### 修正 4：首页大屏不应与普通后台页面混在一起

首页 dashboard 当前只是普通页面卡片布局。  
如果要做“大屏感”，应在 `dashboard.html / dashboard.js / dashboard.css` 内完成，不影响其它页面主题。  
建议通过 `.dashboard-screen` 局部样式实现，不要全局改 `body`、`.page-card` 等基础样式，避免影响其它页面。

#### 修正 5：首页数据接口应尽量复用现有接口，必要时新增聚合接口

当前首页已经调用：

```text
/api/stats/summary
/api/health
/api/stats/today
/api/logs
/api/qc/feedback/cases
/api/scheduler/status
/api/stats/daily
```

这些接口可支撑第一版大屏。  
如果需要更强的“闭环率、前置机查看率、高危待办、科室TOP、维度TOP”，建议新增一个聚合接口：

```text
GET /api/stats/dashboard-overview
```

但第一版可以先复用现有接口，第二版再合并性能优化。

当前 `/api/stats/daily` 已返回 `inconsistency` 字段，升级趋势图时应直接使用，不要重复从 `/api/logs` 计算近 30 天不一致趋势。

---

## 3. 当前首页现状

### 3.1 当前 dashboard 页面结构

当前首页主要包含：

1. 今日推送总数
2. 今日推送成功
3. 今日发现不一致
4. 今日新增
5. 待确认病例
6. 最近执行时间
7. 近 30 天推送趋势
8. 组件状态
9. 最近 5 条高风险告警

页面文件：

```text
static/templates/pages/dashboard.html
static/scripts/modules/dashboard.js
static/styles/pages/dashboard.css
```

### 3.2 当前首页问题

1. 视觉上偏普通后台卡片，缺少驾驶舱大屏层次。
2. 指标之间没有业务闭环逻辑，例如：
   - AI 推送量
   - 不一致发现
   - 高危问题
   - 前置机发送
   - 医生查看
   - 反馈整改
   - 系统健康
3. 缺少“今日重点风险态势”。
4. 缺少“科室排行 / 维度排行 / 严重度分布”。
5. 组件状态只是列表，不够直观。
6. 最近高风险告警展示较弱，没有形成风险事件流。
7. 首页没有“运营指挥”感觉，不适合作为大屏展示。

---

## 4. 首页大屏设计目标

### 4.1 设计定位

建议首页改名为：

```text
AI质控运营驾驶舱
```

副标题：

```text
住院病历一致性质控 · 推送闭环 · 风险预警 · 系统运行状态
```

### 4.2 设计风格

建议采用“医疗科技大屏”风格：

```text
深蓝 / 靛蓝 / 青绿 / 冰蓝
玻璃拟态卡片
柔和光晕背景
高对比数字指标
风险红、预警橙、正常绿、信息蓝
```

注意：

- 只在 dashboard 页面使用深色大屏样式。
- 不要影响其它管理页面。
- 通过 `.dashboard-screen` 包裹，样式限定在 `.page-dashboard.dashboard-screen` 下。

### 4.3 首页业务主线

首页必须按闭环逻辑展示：

```text
数据进入 → AI质控 → 风险发现 → 前置机推送 → 医生查看 → 反馈整改 → 系统运行
```

对应指标：

```text
今日推送总数
成功率
不一致数量
高危数量
待处理数量
前置机发送成功率
医生查看率
整改闭环率
最近调度时间
系统健康状态
```

---

## 5. 推荐首页布局

### 5.1 总体布局

建议使用 24 栅格大屏布局：

```text
┌────────────────────────────────────────────────────────────┐
│ 顶部大屏标题区：AI质控运营驾驶舱 / 日期 / 系统状态 / 刷新 │
├────────────────────────────────────────────────────────────┤
│ 核心指标 KPI：推送总数 成功率 不一致 高危 待处理 查看率 闭环率 │
├───────────────┬──────────────────────────────┬──────────────┤
│ 风险态势雷达   │ 近30天趋势主图                 │ 系统健康矩阵 │
├───────────────┼──────────────────────────────┼──────────────┤
│ 科室风险TOP    │ 高风险事件流                   │ 前置机闭环    │
└───────────────┴──────────────────────────────┴──────────────┘
```

### 5.2 第一屏区域

#### A. 顶部 Hero 区

内容：

```text
AI质控运营驾驶舱
今日日期 / 当前时间
系统状态：正常 / 部分异常 / 异常
最近调度时间
自动刷新状态
```

视觉：

- 深色渐变背景
- 左侧大标题
- 右侧系统状态灯
- 中间或右侧显示“今日运行中 / 已完成 / 异常”

#### B. KPI 指标卡

建议 8 个核心指标：

```text
1. 今日推送总数
2. 今日成功率
3. 今日不一致
4. 高危问题
5. 待处理反馈
6. 前置机发送成功率
7. 医生查看率
8. 整改闭环率
```

第一版如果部分指标暂时没有接口，先做：

```text
前置机发送成功率：无数据时显示 --
医生查看率：无数据时显示 --
整改闭环率：可由 feedback cases 或后续接口补
```

每个指标卡包含：

```text
标题
大数字
单位
环比/说明
点击跳转目标
```

跳转：

```text
今日推送总数 -> 审计中心
不一致/高危 -> 患者质控总览
待处理反馈 -> 质控反馈
前置机发送成功率/查看率 -> 患者质控总览 - 前置机告警
系统状态 -> 系统健康
最近调度 -> 定时任务
```

---

## 6. 首页图表设计

### 6.1 主图：近 30 天质控趋势

当前已有 `dashChart`，建议升级为组合图：

```text
柱状图：每日推送总数
折线图：不一致数
折线图：失败数
面积线：成功数
```

ECharts option 建议：

```javascript
series: [
  { name: '推送总数', type: 'bar', data: total },
  { name: '成功', type: 'line', smooth: true, data: success },
  { name: '不一致', type: 'line', smooth: true, data: inconsistency },
  { name: '失败', type: 'line', smooth: true, data: failed },
]
```

视觉：

- 深色背景下使用蓝、绿、橙、红。
- tooltip 增加成功率、不一致率。
- legend 放顶部或底部。

### 6.2 严重度分布图

接口：

```text
GET /api/stats/severity
```

展示：

```text
高危 / 中危 / 低危 / unknown
```

推荐图形：

```text
环形图 / 玫瑰图
```

位置：

```text
左侧风险态势区
```

### 6.3 科室风险 TOP

接口：

```text
GET /api/stats/anomaly-top?group_by=dept
```

展示：

```text
科室名称
不一致数量
横向进度条
```

推荐：

- 不一定用 ECharts，HTML 排行榜更清晰。
- 高危科室前三用红/橙标识。

### 6.4 维度问题 TOP

接口：

```text
GET /api/stats/dimensions
```

展示：

```text
诊断一致性
护理级别一致性
生命体征一致性
病情描述一致性
治疗措施一致性
时间线一致性
```

展示：

```text
总数 / 通过率 / fail / warn
```

推荐：

- 横向条形图
- 或小型矩阵卡片

### 6.5 前置机闭环面板

数据来源：

第一版复用：

```text
/api/patient-qc/relay-alert/logs
```

统计：

```text
总告警数
发送成功
发送失败
已查看
未查看
平均查看次数
```

如果接口分页不适合统计，第二版新增：

```text
GET /api/patient-qc/relay-alert/summary
```

### 6.6 系统健康矩阵

当前 `/api/health` 返回 components。  
建议从列表改成矩阵：

```text
数据库
Dify
调度器
前置机
存储
接口
```

展示：

```text
绿色：正常
橙色：降级
红色：异常
延迟 ms
```

---

## 7. 首页数据接口计划

### 7.1 第一版：复用现有接口

修改 `loadDashboard()`，增加并发请求：

```text
/api/stats/summary
/api/stats/today
/api/stats/daily?days=30
/api/stats/severity
/api/stats/anomaly-top?group_by=dept
/api/stats/dimensions
/api/health
/api/scheduler/status
/api/qc/feedback/cases?status=pending
/api/patient-qc/relay-alert/logs?page=1&limit=50
```

优点：

- 后端改动少。
- 快速上线。
- 风险低。

缺点：

- 请求较多。
- 首页加载稍重。
- `/api/patient-qc/relay-alert/logs` 是分页列表，首页用它计算发送成功率/查看率只能代表最近 N 条，不是全量精确统计。第一版 UI 必须标注“最近告警”。
- `GET /api/qc/feedback/cases?status=pending` 只能支持待处理数；整改闭环率若无明确接口，第一版显示 `--` 或“待接入”，不要用错误口径硬算。

### 7.2 第二版：新增聚合接口

建议新增：

```text
GET /api/stats/dashboard-overview
```

返回：

```json
{
  "today": {
    "date": "2026-06-07",
    "total": 120,
    "success": 118,
    "failed": 2,
    "inconsistency": 18,
    "high": 5,
    "pending_feedback": 12
  },
  "rates": {
    "success_rate": 98.3,
    "inconsistency_rate": 15.2,
    "relay_success_rate": 96.0,
    "view_rate": 72.5,
    "closure_rate": 61.0
  },
  "scheduler": {
    "last_run_time": "",
    "next_run_time": "",
    "running": false
  },
  "health": {
    "status": "healthy",
    "components": {}
  },
  "trend": [],
  "severity": [],
  "dept_top": [],
  "dimension_top": [],
  "relay": {
    "total": 0,
    "success": 0,
    "failed": 0,
    "viewed": 0,
    "unviewed": 0
  },
  "alerts": []
}
```

优点：

- 首页只请求一个接口。
- 数据口径统一。
- 适合大屏自动刷新。

建议：第一版先复用接口，稳定后再新增聚合接口。

---

## 8. 前端状态字段设计

文件：

```text
static/scripts/app.js
```

新增 dashboard 状态：

```javascript
dashboardScreen: {
  autoRefresh: false,
  refreshSeconds: 60,
  lastRefreshAt: '',
},
dashboardKpis: {
  total: 0,
  successRate: 0,
  inconsistency: 0,
  highRisk: 0,
  pendingFeedback: 0,
  relaySuccessRate: null,
  viewRate: null,
  closureRate: null,
},
dashboardCharts: {
  daily: [],
  severity: [],
  deptTop: [],
  dimensions: [],
},
dashboardRelay: {
  total: 0,
  success: 0,
  failed: 0,
  viewed: 0,
  unviewed: 0,
},
dashboardEvents: [],
```

保留现有：

```text
dashboardToday
dashboardAlerts
healthComps
overallHealth
```

但逐步迁移到新结构。

患者质控/前置机告警 tab 需要在 `static/scripts/app.js` 的 `data()` 中同步新增以下状态，否则模板绑定会报错：

```javascript
patientQcTab: 'patients',
relayAlertLoading: false,
relayAlertList: [],
relayAlertTotal: 0,
relayAlertPage: 1,
relayAlertPageSize: 20,
relayAlertFilter: {
  patient_id: '',
  status: '',
  viewed_flag: '',
},
```

如果使用动态菜单，还需要新增：

```javascript
currentMenu: [],
menuTree: [],
menuLoading: false,
```

不要把这些状态放在 `patient_qc.js` 顶层；当前项目的模块文件只导出 methods，响应式状态集中在 `app.js` 的 `data()`。

---

## 9. 首页模板改造计划

文件：

```text
static/templates/pages/dashboard.html
```

建议结构：

```html
<section v-show="activeMenu==='dashboard'" class="page-view page-dashboard dashboard-screen">
  <!-- 顶部 Hero -->
  <div class="dashboard-hero">
    <div>
      <div class="dashboard-kicker">AI Medical Quality Control</div>
      <div class="dashboard-title">AI质控运营驾驶舱</div>
      <div class="dashboard-subtitle">住院病历一致性质控 · 风险预警 · 推送闭环 · 系统运行状态</div>
    </div>
    <div class="dashboard-hero-right">
      <div class="dashboard-time">{{ currentTime }}</div>
      <el-tag :type="overallHealth==='healthy'?'success':overallHealth==='degraded'?'warning':'danger'">
        {{ overallHealth==='healthy'?'系统正常':overallHealth==='degraded'?'部分异常':'系统异常' }}
      </el-tag>
      <el-button size="small" @click="loadDashboard">刷新</el-button>
    </div>
  </div>

  <!-- KPI -->
  <div class="dashboard-kpi-grid">
    ...
  </div>

  <!-- 主体图表 -->
  <div class="dashboard-grid">
    <div class="dashboard-panel panel-main-trend">
      <div class="panel-title">近30天质控趋势</div>
      <div id="dashTrendChart" class="dashboard-chart"></div>
    </div>

    <div class="dashboard-panel">
      <div class="panel-title">风险等级分布</div>
      <div id="dashSeverityChart" class="dashboard-chart small"></div>
    </div>

    <div class="dashboard-panel">
      <div class="panel-title">系统健康矩阵</div>
      ...
    </div>

    <div class="dashboard-panel">
      <div class="panel-title">科室风险TOP</div>
      ...
    </div>

    <div class="dashboard-panel panel-event-flow">
      <div class="panel-title">高风险事件流</div>
      ...
    </div>

    <div class="dashboard-panel">
      <div class="panel-title">前置机闭环</div>
      ...
    </div>
  </div>
</section>
```

---

## 10. 首页 JS 改造计划

文件：

```text
static/scripts/modules/dashboard.js
```

### 10.1 修改 `loadDashboard()`

第一版建议并发加载：

```javascript
const [
  summaryR,
  healthR,
  todayStatsR,
  dailyR,
  severityR,
  deptTopR,
  dimR,
  pendingFeedbackR,
  schedulerStatusR,
  relayLogsR,
] = await Promise.all([
  apiGet('/api/stats/summary').catch(...),
  apiGet('/api/health').catch(...),
  apiGet('/api/stats/today').catch(...),
  apiGet('/api/stats/daily', { params: { days: 30 } }).catch(...),
  apiGet('/api/stats/severity').catch(...),
  apiGet('/api/stats/anomaly-top', { params: { group_by: 'dept' } }).catch(...),
  apiGet('/api/stats/dimensions').catch(...),
  apiGet('/api/qc/feedback/cases', { params: { page: 1, limit: 1, status: 'pending', days: 30 } }).catch(...),
  apiGet('/api/scheduler/status').catch(...),
  apiGet('/api/patient-qc/relay-alert/logs', { params: { page: 1, limit: 20 } }).catch(...),
]);
```

### 10.2 增加 KPI 计算

```javascript
const todayTotal = Number(todayStatsR.data?.total || 0);
const todaySuccess = Number(todayStatsR.data?.success || 0);
const todayInconsistency = Number(todayStatsR.data?.inconsistency || 0);

const successRate = todayTotal ? todaySuccess / todayTotal * 100 : 0;

const relayItems = relayLogsR.data?.items || [];
const relayTotal = Number(relayLogsR.data?.total || relayItems.length || 0);
const relaySuccess = relayItems.filter(i => i.status === 'success').length;
const relayViewed = relayItems.filter(i => Number(i.viewed_flag || 0) === 1).length;
```

注意：

- 如果 relayLogs 只返回分页数据，统计只能作为“最近告警”估算。
- 更准确的统计应新增 `/relay-alert/summary`。

### 10.3 图表渲染方法拆分

建议新增：

```javascript
renderDashboardCharts() {
  this.renderDashTrendChart();
  this.renderDashSeverityChart();
  this.renderDashDimensionChart();
}
```

替代当前单一 `renderDash()`。

当前首页模板使用的图表容器是 `id="dashChart"`。如果改成 `dashTrendChart`、`dashSeverityChart`、`dashDimensionChart`，必须同时满足：

1. 删除或不再调用旧 `renderDash()` 对 `dashChart` 的依赖。
2. `this.getChart(id)` 使用新 ID 前确认 DOM 已渲染。
3. `loadDashboard()` 末尾在 `$nextTick()` 中统一调用 `renderDashboardCharts()`。
4. 页面切换后图表 resize 仍复用现有 `chartInstances` 管理逻辑，不重复创建失控实例。

### 10.4 点击跳转

新增：

```javascript
openDashboardTarget(target) {
  if (target === 'patient-qc') this.switchMenu('patient-qc');
  if (target === 'relay-alerts') {
    this.patientQcTab = 'relay-alerts';
    this.switchMenu('patient-qc');
  }
  if (target === 'feedback-pending') {
    this.switchMenu('feedback');
    this.switchFeedbackView('pending');
  }
}
```

实际实现时不要只设置 tab 后再调用 `switchMenu()`；当前 `switchMenu('patient-qc')` 会触发 `loadPatientQcList()`。推荐顺序：先 `switchMenu('patient-qc')`，再设置 `patientQcTab='relay-alerts'` 并调用 `loadRelayAlertLogs()`；或者新增 `switchPatientQcTab(tab)` 统一处理。

---

## 11. 首页 CSS 设计计划

文件：

```text
static/styles/pages/dashboard.css
```

建议只在 `.dashboard-screen` 下写样式。

### 11.1 背景

```css
.dashboard-screen {
  min-height: calc(100vh - 92px);
  padding: 18px;
  border-radius: 18px;
  background:
    radial-gradient(circle at 10% 10%, rgba(22,119,255,.24), transparent 28%),
    radial-gradient(circle at 90% 20%, rgba(19,194,194,.18), transparent 30%),
    linear-gradient(135deg, #071426 0%, #0b1d35 48%, #092b3a 100%);
  color: #e6f4ff;
}
```

### 11.2 Hero

```css
.dashboard-hero {
  display:flex;
  justify-content:space-between;
  align-items:center;
  padding:20px 24px;
  border:1px solid rgba(120,190,255,.22);
  border-radius:18px;
  background:rgba(8,24,48,.72);
  box-shadow:0 18px 48px rgba(0,0,0,.24);
  backdrop-filter: blur(12px);
}
```

### 11.3 KPI 卡片

```css
.dashboard-kpi-grid {
  display:grid;
  grid-template-columns:repeat(4, minmax(0, 1fr));
  gap:14px;
}

.dashboard-kpi-card {
  position:relative;
  overflow:hidden;
  padding:18px;
  border-radius:16px;
  background:linear-gradient(135deg, rgba(255,255,255,.10), rgba(255,255,255,.04));
  border:1px solid rgba(120,190,255,.18);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.12), 0 12px 32px rgba(0,0,0,.18);
}
```

### 11.4 图表面板

```css
.dashboard-grid {
  display:grid;
  grid-template-columns:1.1fr 1.7fr 1.1fr;
  gap:14px;
}

.dashboard-panel {
  border-radius:16px;
  padding:16px;
  background:rgba(8,24,48,.68);
  border:1px solid rgba(120,190,255,.18);
  box-shadow:0 12px 30px rgba(0,0,0,.16);
}

.panel-main-trend {
  grid-column: span 2;
}
```

### 11.5 响应式

```css
@media (max-width: 1280px) {
  .dashboard-kpi-grid { grid-template-columns:repeat(2, minmax(0, 1fr)); }
  .dashboard-grid { grid-template-columns:1fr; }
  .panel-main-trend { grid-column:auto; }
}

@media (max-width: 640px) {
  .dashboard-hero { flex-direction:column; align-items:flex-start; }
  .dashboard-kpi-grid { grid-template-columns:1fr; }
}
```

---

## 12. 菜单整合与首页大屏的先后顺序

建议执行顺序：

### 第 1 步：复核并修正菜单计划

先改：

```text
app/routers/menu.py
app/schemas.py（仅当后端返回 group/target/order 时）
static/scripts/navigation.js（新增，封装 fallback/menuTree/target 映射）
static/scripts/app.js
static/index.html
static/styles/components/sidebar.css
tests/test_menu_router.py
```

确保菜单稳定后，再改首页。

原因：

- 首页大屏需要更清晰的“工作台”入口。
- 菜单不稳会影响 dashboard 点击跳转和面包屑。

### 第 2 步：首页大屏 UI 升级

改：

```text
static/templates/pages/dashboard.html
static/scripts/modules/dashboard.js
static/styles/pages/dashboard.css
```

只改 dashboard 局部。

### 第 3 步：患者质控和前置机告警整合

改：

```text
static/scripts/app.js
static/templates/pages/patient_qc.html
static/scripts/modules/patient_qc.js
static/styles/pages/patient_qc.css
app/routers/patient_qc.py
```

用于支撑首页跳转“前置机告警”。

注意：如果第一版不做动态菜单，只做菜单文案/排序/分组的静态整理，则不需要新增 `static/scripts/navigation.js`，但仍必须同步桌面侧边栏和移动 Drawer 两处硬编码，避免两个入口不一致。

### 第 4 步：后端聚合接口性能优化

如首页请求过多，再新增：

```text
GET /api/stats/dashboard-overview
```

---

## 13. 菜单计划追加修正

### 13.1 `app/routers/menu.py` 必须补齐菜单

新增菜单：

```text
patient-qc
audit-types
relay
relay-alert-logs
config-runtime
```

其中 `relay-alert-logs` 和 `config-runtime` 是逻辑入口，不能作为新的 `activeMenu` 页面；它们必须通过 `target` 或前端映射跳到已有页面/tab。

`MENU_CONFIG` 也要同步更新：`admin` 应包含所有核心菜单；`clinician`、`auditor`、`dept_manager` 是否可见 `patient-qc`、`relay-alert-logs` 需要按当前权限策略明确，不能默认给所有角色打开配置类菜单。

### 13.2 `MENU_GROUPS`

推荐第一版在前端 `navigation.js` 中维护分组，后端仍返回平铺 catalog；这样不需要改 `RoleMenuInfo`。如果确实要求后端返回分组，则必须同步扩展 `app/schemas.py::RoleMenuInfo` 并增加测试。

前端分组建议：

```javascript
MENU_GROUPS = [
    {"id": "workbench", "label": "工作台", "icon": "🏠", "order": 10},
    {"id": "qc", "label": "质控业务", "icon": "🧑‍⚕️", "order": 20},
    {"id": "push", "label": "推送与调度", "icon": "🚀", "order": 30},
    {"id": "config", "label": "配置中心", "icon": "⚙️", "order": 40},
    {"id": "admin", "label": "系统管理", "icon": "👥", "order": 50},
    {"id": "ops", "label": "运维工具", "icon": "🛠️", "order": 60},
]
```

### 13.3 `relay-alert-logs` 映射

如果放在后端 catalog，需要 schema 支持 `group` 和 `target`：

```python
{
    "id": "relay-alert-logs",
    "label": "前置机告警",
    "icon": "📨",
    "group": "qc",
    "target": {"activeMenu": "patient-qc", "tab": "relay-alerts"},
}
```

如果不改后端 schema，则在 `static/scripts/navigation.js` 中维护同等映射。

### 13.4 `config-runtime` 映射

如果放在后端 catalog，需要 schema 支持 `group` 和 `target`：

```python
{
    "id": "config-runtime",
    "label": "运行总览",
    "icon": "🧭",
    "group": "config",
    "target": {"activeMenu": "config", "tab": "runtime-summary"},
}
```

如果不改后端 schema，则在 `static/scripts/navigation.js` 中维护同等映射。

### 13.5 当前权限管理接口注意事项

当前角色菜单分配页调用：

```text
GET /api/roles/menus/catalog
```

该接口来自 `app/routers/roles.py`，但复用 `app.routers.menu.MENU_CATALOG`。因此修改菜单目录时必须验证：

1. `/api/menu/all` 返回完整 catalog。
2. `/api/roles/menus/catalog` 返回完整 catalog。
3. `POST /api/roles/{role_id}/menus/{menu_id}` 能识别新增菜单 ID。
4. 已有 `RoleMenu` 表中旧 menu_id 不应被删除或重命名导致用户菜单消失。

---

## 14. 测试计划

### 14.1 后端测试

新增：

```text
tests/test_menu_router.py
```

覆盖：

1. `/api/menu/all` 包含 `groups`。
2. `/api/menu/all` 包含新增菜单。
3. `/api/roles/menus/catalog` 包含新增菜单。
4. admin 默认菜单包含所有核心菜单。
5. clinician 不包含 `config`、`access`、`debug`。
6. 如果后端返回 `target`，验证 `relay-alert-logs` target 正确。
7. 如果后端返回 `target`，验证 `config-runtime` target 正确。
8. 如果后端不返回 `groups/target`，测试应验证前端 fallback/navigation 配置，而不是强制 `/api/menu/all` 包含 `groups`。

如新增聚合接口：

```text
tests/test_dashboard_overview.py
```

覆盖：

1. 返回 today/rates/health/trend/severity/dept_top/alerts。
2. 空数据时不报错。
3. 除数为 0 时 rate 返回 0 或 null。
4. 日期范围正确。

### 14.2 前端手工测试

admin 登录后逐项点击：

```text
工作台 / 总览仪表盘
质控业务 / 患者质控总览
质控业务 / 前置机告警
质控业务 / 审计中心
质控业务 / 质控反馈
推送与调度 / 手动推送
推送与调度 / 定时任务
推送与调度 / 前置机接收人配置
配置中心 / 系统配置
配置中心 / 审计类型
配置中心 / 运行总览
系统管理 / 权限管理
运维工具 / 系统健康
运维工具 / Dify调试
```

确认：

```text
页面能打开
标题正确
数据能加载
控制台无 JS 报错
移动菜单一致
```

### 14.3 首页大屏手工验证

确认：

1. 首页进入后无白屏。
2. KPI 指标不出现 NaN。
3. 图表 resize 正常。
4. 无数据时显示空状态。
5. 高风险事件点击能跳转详情。
6. 待处理反馈点击能跳转反馈页。
7. 前置机告警点击能进入 patient-qc 的 relay-alerts tab。
8. 系统健康异常时颜色明显。
9. 1366x768 分辨率可展示首屏主要内容。
10. 移动端不会横向溢出。
11. 切换离开首页再返回，图表不重复叠加、不白屏。
12. `/api/patient-qc/relay-alert/logs` 失败时首页仍可加载其它指标。

---

## 15. 运行命令

```bash
python -m compileall app tests scripts
python scripts/check_naming_convention.py
python -m pytest tests/test_menu_router.py -q --tb=short
python -m pytest tests/test_runtime_summary_frontend_static.py tests/test_scheduler_runtime_summary_frontend_static.py tests/test_audit_types_runtime_summary_frontend_static.py -q --tb=short
python -m pytest -q --tb=short
```

如新增首页聚合接口：

```bash
python -m pytest tests/test_dashboard_overview.py -q --tb=short
```

---

## 16. 不建议第一版做的事情

1. 不引入 Vue Router。
2. 不整体替换 Element Plus。
3. 不把后台所有页面改成深色风格。
4. 不修改现有 API 路径。
5. 不删除旧 `activeMenu` key。
6. 不删除旧 `switchMenu()` legacy 映射。
7. 不把 dashboard 大屏样式写到全局。
8. 不第一版强制新增复杂权限模型。
9. 不第一版强依赖新聚合接口，除非性能确实不足。

---

## 17. 建议提交拆分

### Commit 1：统一菜单目录

```text
feat: unify navigation catalog and grouped menus
```

修改：

```text
app/routers/menu.py
app/schemas.py（仅后端 catalog 返回 group/target/order 时）
static/scripts/navigation.js（如改动态菜单则新增）
static/scripts/app.js
static/index.html
static/styles/components/sidebar.css
tests/test_menu_router.py
```

同时验证 `app/routers/roles.py` 的 `/api/roles/menus/catalog` 行为；如果只复用 `MENU_CATALOG` 不需要直接改该文件，也要有测试覆盖。

### Commit 2：首页大屏 UI

```text
feat: redesign dashboard as qc command center
```

修改：

```text
static/templates/pages/dashboard.html
static/scripts/modules/dashboard.js
static/styles/pages/dashboard.css
```

### Commit 3：患者质控与前置机告警入口

```text
feat: add relay alert tab to patient qc page
```

修改：

```text
app/routers/patient_qc.py
static/scripts/app.js
static/templates/pages/patient_qc.html
static/scripts/modules/patient_qc.js
static/styles/pages/patient_qc.css
```

`app/routers/patient_qc.py` 只在需要 `viewed_flag` 筛选或返回更多字段时修改；现有日志列表和 retry 接口已存在，不要重复新增 router。

### Commit 4：首页聚合接口（可选）

```text
feat: add dashboard overview stats endpoint
```

修改：

```text
app/routers/stats.py
tests/test_dashboard_overview.py
```

---

# 附：给开发 AI 的执行提示词

```markdown
请基于 pengpeng112/ai_mr_yiyyaa 当前 HEAD，继续优化系统界面和菜单，并将首页改造成更直观、更高端的 AI质控运营驾驶舱。

执行前阅读：
- app/routers/menu.py
- app/routers/stats.py
- app/routers/patient_qc.py
- static/index.html
- static/scripts/app.js
- static/scripts/modules/dashboard.js
- static/templates/pages/dashboard.html
- static/styles/pages/dashboard.css
- static/templates/pages/patient_qc.html
- static/scripts/modules/patient_qc.js
- static/styles/app.css
- static/styles/components/sidebar.css

一、菜单复核与修正
1. 不引入 Vue Router。
2. 不修改现有 API 路径。
3. 不删除现有 activeMenu key。
4. 不删除 switchMenu() 中 legacy 映射。
5. 当前前端主导航仍硬编码在 static/index.html，若改动态菜单必须保留 FALLBACK_MENU；若不改动态菜单，必须同步桌面侧边栏和移动 Drawer 两处。
6. 后端 app/routers/menu.py 补齐：
   - patient-qc
   - audit-types
   - relay
   - relay-alert-logs
   - config-runtime
7. /api/roles/menus/catalog 当前用于权限管理页，必须和 /api/menu/all 一样能看到新增菜单。
8. RoleMenuInfo 当前只有 id/label/icon/path；如果后端返回 group/target/order，先改 app/schemas.py 并加测试。否则将 group/target/order 放到前端 navigation.js。
9. 增加菜单分组：
   - workbench 工作台
   - qc 质控业务
   - push 推送与调度
   - config 配置中心
   - admin 系统管理
   - ops 运维工具
10. 如果采用后端分组，/api/menu/all 返回 groups、catalog、menus；如果采用前端分组，/api/menu/all 可保持平铺 catalog。
11. 如改动态菜单，前端新增 static/scripts/navigation.js。
12. 如改动态菜单，桌面侧边栏和移动 drawer 都从 menuTree 渲染，不再硬编码两份菜单。
13. 新菜单 target 映射：
    - relay-alert-logs -> activeMenu=patient-qc, patientQcTab=relay-alerts
    - config-runtime -> activeMenu=config, configTab=runtime-summary
14. loadCurrentMenu() 失败时使用 FALLBACK_MENU。

二、首页大屏
1. 只改 dashboard 局部，不影响其它页面。
2. dashboard 外层加 class：dashboard-screen。
3. 首页标题改为：AI质控运营驾驶舱。
4. 增加 Hero 区：
   - 标题
   - 副标题
   - 当前时间
   - 系统状态
   - 最近调度时间
   - 刷新按钮
5. KPI 区展示：
   - 今日推送总数
   - 今日成功率
   - 今日不一致
   - 高危问题
   - 待处理反馈
   - 前置机发送成功率
   - 医生查看率
   - 整改闭环率
6. 图表区展示：
   - 近30天质控趋势组合图
   - 风险等级分布环图
   - 科室风险TOP
   - 维度问题TOP
   - 系统健康矩阵
   - 高风险事件流
   - 前置机闭环面板
7. 第一版复用现有接口：
   - /api/stats/summary
   - /api/stats/today
   - /api/stats/daily?days=30
   - /api/stats/severity
   - /api/stats/anomaly-top?group_by=dept
   - /api/stats/dimensions
   - /api/health
    - /api/scheduler/status
    - /api/qc/feedback/cases?status=pending
    - /api/patient-qc/relay-alert/logs?page=1&limit=50
8. /api/patient-qc/relay-alert/logs 是分页列表，首页第一版只能标注为“最近告警”口径；不要把它包装成全量查看率。
9. 如果请求过多，再新增 /api/stats/dashboard-overview，不要第一步就强行重构。
10. dashboard.css 中所有新样式限定在 .dashboard-screen 下。
11. 深色大屏风格只用于首页，不影响其它后台页面。
12. 如果替换 dashChart 为多个 chart id，必须同步删除旧 renderDash 或改成兼容新 id，避免空 DOM 报错。

三、患者质控和前置机告警
1. patient_qc.html 增加 tab：
    - 患者总览
    - 前置机告警
2. app.js 的 data() 增加 patientQcTab、relayAlertLoading、relayAlertList、relayAlertTotal、relayAlertPage、relayAlertPageSize、relayAlertFilter；patient_qc.js 只放 methods。
3. patient_qc.js 增加 switchPatientQcTab、loadRelayAlertLogs、retryRelayAlert 等方法。
4. 前置机告警 tab 使用 /api/patient-qc/relay-alert/logs。
4. 展示：
   - patient_id
   - dept
   - severity
   - status
   - viewed_flag
   - view_count
   - viewer_name
   - last_viewed_at
   - evidence_summary
   - created_at
5. 后端 list_relay_alert_logs 只有在需要筛选时增加 viewed_flag 参数；现有返回字段已经包含 viewed_flag/view_count/viewer/evidence_summary。
6. 失败状态允许调用 /api/patient-qc/relay-alert/retry/{alert_id} 重试。

四、测试
1. 新增 tests/test_menu_router.py。
2. 验证 /api/menu/all 包含新增菜单和 groups。
3. 验证 admin/clinician 默认菜单权限。
4. 手工测试每个菜单入口。
5. 手工测试首页无 NaN、无 JS 错误、图表正常、移动端不横向溢出。
6. 执行：
   python -m compileall app tests scripts
   python scripts/check_naming_convention.py
   python -m pytest tests/test_menu_router.py -q --tb=short
   python -m pytest -q --tb=short

最终输出：
1. 修改文件列表。
2. 新菜单结构。
3. 首页大屏截图或说明。
4. 测试结果。
5. 未完成或需人工确认事项。
```
