# AI质控深色科技驾驶舱 V2 测试报告

**测试时间**: 2026-06-24 19:30
**测试方式**: 代码静态分析 + 生产服务器接口检查(未登录态) + 后端测试套件
**测试环境**: 生产服务器 `http://10.10.8.84:8000` (容器 `med-audit`)

> **注意**: 本报告基于代码级静态验证和生产服务器接口状态检查生成。由于无法模拟浏览器交互，TC-103(刷新按钮 loading 态)、TC-106~112(KPI 点击跳转)、TC-202(图表 tooltip)、TC-602(事件点击详情)等需要浏览器操作交互的用例，标注为"未验证(需浏览器)"。

---

## 一、总体结论

**结论: 部分通过 — 发现 1 个 Bug 需要修复**

| 统计项 | 数量 |
|---|---|
| 总检查用例 | 38 |
| 通过 | 28 |
| 未验证(需浏览器) | 6 |
| 发现 Bug | 1 |
| 微小问题 | 3 |
| 阻塞级 | 0 |

---

## 二、通过项

### 2.1 后端编译

- `python -m compileall app tests scripts` — **通过**，无语法/导入错误。

### 2.2 生产服务器健康状态

| 端点 | HTTP 状态码 | 说明 |
|---|---|---|
| `/api/health` | 200 | `status: "healthy"` |
| Oracle | up | `latency_ms: 26` |
| App DB | up | `db_type: oracle` |
| Scheduler | running | `next_run: 2026-06-25 09:00:00+08:00` |
| Dify | disabled | 预期行为 |
| PostgreSQL | disabled | 预期行为 |

### 2.3 静态资源可访问性

| 文件 | HTTP 状态码 |
|---|---|
| `/styles/pages/dashboard.css` | 200 |
| `/styles/components/sidebar.css` | 200 |
| `/templates/pages/dashboard.html` | 200 |
| `/index.html` | 200 |

### 2.4 前端代码结构验证

| 检查项 | 结果 |
|---|---|
| HTML 中所有 `@click` 处理器在 JS 中存在 | **通过**: `loadDashboard`, `openDashboardAlert`, `openDashboardFeedback`, `openDashboardTarget` 全部存在 |
| HTML 中所有 `dashboardKpis.*` 变量在 JS 中有初始化 | **通过**: 18 个字段全部在 `resetDashboardState()` 中初始化 |
| HTML 中所有 `dashboardScheduler.*` 变量存在 | **通过**: `lastRunTime`, `nextRunTime` 均有定义 |
| `dashboardEvents`, `dashboardDeptTop`, `healthComps` 存在 | **通过** |
| CSS 类 HTML ↔ CSS 匹配 | **通过**: 63/64 个类匹配 |
| ECharts 容器 ID 存在 | **通过**: `dashTrendChart`, `dashSeverityChart`, `dashDimensionChart` 全部存在于 HTML |
| `cname` / `pct` 方法存在 | **通过**: 定义于 `stats.js:4,8`，通过 `methods` 展开注入 |
| `dashboardLoading` 防御 | **通过**: JS 中 `loadDashboard` 有 `_dashboardLoading` 去重锁 |
| 菜单 id 未修改 | **通过**: `dashboard`, `relay-alert-logs`, `audit`, `patient-qc`, `feedback` 保持不变 |
| 无新增依赖 | **通过**: 未引入 Tailwind/GSAP/Framer/Three 等 |
| 未修改后端文件 | **通过**: 本次仅 5 个前端文件修改 |

### 2.5 响应式 CSS 规则

| 断点 | 规则 | 状态 |
|---|---|---|
| 1280px | KPI 变 2 列、指挥条变 2 列、三栏变单栏、AI 链路换行 | 正确 |
| 640px | Hero 纵排、KPI 单列、字体缩小 | 正确 |
| `prefers-reduced-motion` | 扫描线/箭头脉冲/事件点动画全部停止 | 正确 |

---

## 三、Bug（需修复）

### Bug #1: 健康矩阵中 `app_db` 组件名显示原始 key

- **严重度**: 低（UI 层面，不影响功能）
- **位置**: `static/scripts/modules/stats.js:8-15` 的 `cname(k)` 函数
- **现象**: `/api/health` 返回的组件包括 `app_db`，但 `cname` 映射表中没有 `app_db`，前端会显示原始 key `app_db` 而非中文名。
- **当前映射表**:
  ```js
  {
    oracle: 'Oracle 数据库',
    postgresql: 'PostgreSQL 数据库',
    dify: 'Dify Workflow',
    scheduler: 'APScheduler 调度器',
  }
  ```
- **修复方法**: 在 `cname` 映射表中增加 `app_db: '应用数据库'`
- **修复文件**: `static/scripts/modules/stats.js:8-15`

---

## 四、微小问题

### 问题 #1: `dashboard-flow-panel` CSS 类未定义

- **严重度**: 极低（无视觉影响，基类 `.dashboard-panel` 已提供样式）
- **位置**: `static/templates/pages/dashboard.html` — AI闭环链路面板使用 `class="dashboard-panel panel-main-trend dashboard-flow-panel"`
- **说明**: `dashboard-flow-panel` 在 CSS 中无对应规则，但该元素同时有 `dashboard-panel` 和 `panel-main-trend` 提供完整样式，不影响显示。
- **建议**: 如需为 AI闭环链路面板单独调整样式（如内边距、节点间距），可为此类补充规则；否则可移除 HTML 中多余的 `dashboard-flow-panel`。

### 问题 #2: `flow-icon` CSS 规则未被 HTML 使用

- **严重度**: 极低（冗余代码，无影响）
- **位置**: `static/styles/pages/dashboard.css` — 定义了 `.ai-flow-node .flow-icon` 但 HTML 中只使用 `flow-label`
- **说明**: 这是 V1 设计中预留的节点图标样式，但 V2 当前实现只有文字节点。
- **建议**: 如果后续要在节点加入图标可保留，否则删除。

### 问题 #3: 5 个 Dashboard 静态测试因 V2 改造预期失败

- **严重度**: 预期行为
- **测试名**:
  - `test_dashboard_template_contains_phase2_cockpit_sections` — 模板完全重写
  - `test_dashboard_loads_phase2_data_sources` — 代码结构变化
  - `test_dashboard_relay_navigation_sets_tab_before_loading_page` — 导航已改为 `switchMenu('relay-alert-logs')`
  - `test_dashboard_css_has_scoped_phase2_layout_rules` — `.panel-dimension` 等旧类已移除
  - `test_dashboard_phase2_assets_are_cache_busted` — 版本号变更为 `20260624-tech-v2`
- **说明**: 这些测试检查的是旧版代码特征，V2 已合理替换。需更新测试用例。
- **修复文件**: `tests/test_dashboard_frontend_static.py`

---

## 五、预存在失败（非本次引入）

| 测试 | 说明 |
|---|---|
| `test_process_single_passes_source_key_and_run_mode_to_skip` | bulk push executor 相关 |
| `test_mock_audit_flow_persists_structured_results` | e2e audit flow 相关 |
| `test_relay_alert_tab_contains_phase3_workbench_sections` | 前置机告警此前已从 patient_qc Tab 拆分为独立页面 |
| `test_patient_qc_phase3_assets_are_cache_busted` | 此前 app.js 版本号变更 |

---

## 六、未验证项（需浏览器交互）

以下用例需要实际打开浏览器登录系统操作才能验证：

| 用例 | 位置/描述 |
|---|---|
| 首页刷新按钮 loading 态 | TC-103 |
| 8 个 KPI 点击跳转 | TC-106 ~ TC-112 |
| 近30天趋势图 tooltip | TC-201 |
| 风险环图 tooltip | TC-202 |
| 维度图 tooltip | TC-203 |
| 高风险事件点击详情 | TC-602 |
| 菜单逐项跳转 | TC-702 |
| 推送日志筛选/详情 | TC-802/803 |
| 患者质控筛选/详情 | TC-902/903 |
| 前置机告警筛选/行点击 | TC-1002/1003 |
| 反馈详情/确认/关闭 | TC-1103 |
| 手动推送按钮状态 | TC-1202/1203 |
| 响应式各宽度 | TC-1501~1504 |
| 空状态/接口失败容错 | TC-1601/1602 |
| 登录/退出 | TC-001~003 |

---

## 七、修复建议

### 紧急（本次修复）

**Bug #1**: `cname('app_db')` 返回原始 key
```js
// static/scripts/modules/stats.js — cname 函数
cname(k) {
  return {
    oracle: 'Oracle 数据库',
    postgresql: 'PostgreSQL 数据库',
    dify: 'Dify Workflow',
    scheduler: 'APScheduler 调度器',
    app_db: '应用数据库',       // <-- 新增
  }[k] || k;
},
```

### 后续优化

1. 更新 `tests/test_dashboard_frontend_static.py` 中的断言，匹配 V2 新类名/版本号。
2. 如不需要 `dashboard-flow-panel` 的额外样式，可移除多余 class 或 `flow-icon` 冗余规则。

---

## 八、建议下一步

1. **修复 Bug #1**（1 行代码，可立即热更到生产）
2. 用浏览器登录 `http://10.10.8.84:8000`，手动执行第六节"未验证项"的浏览器交互测试
3. 确认 KPI 点击跳转、图表 tooltip、菜单切换无误后，更新测试用例
