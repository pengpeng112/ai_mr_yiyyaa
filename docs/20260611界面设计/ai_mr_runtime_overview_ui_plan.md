
# 运行总览页面紧凑版 UI 设计与前端改造方案

> 页面：运行总览  
> 目标：只改前端展示层，不修改后端接口和业务逻辑；保留配置状态、配置风险、运行模式、调度器配置、科室范围、审计类型清单等现有展示能力。  
> 设计方向：将当前“配置堆叠页”调整为“配置体检与运行态总览页”，用于快速判断系统是否具备安全运行条件。

---

## 1. 当前界面问题

从截图看，当前“运行总览”页面已经把很多配置状态都集中展示出来，但信息层级还可以优化：

1. 顶部配置 Tab 很长，状态标签较多，横向阅读压力大。
2. “配置信息”一行很有价值，但现在视觉权重偏弱。
3. “配置风险提示”列表较长，占据较高位置，用户需要滚动才能看运行模式、调度器、审计类型。
4. 风险提示缺少严重度分组，例如错误、警告、信息建议混在一起。
5. “运行模式”卡片展示了 daily_increment、discharge_final、manual、precheck，但缺少横向对比状态。
6. “调度器配置”信息很多，适合改成横向配置卡，而不是大块文本堆叠。
7. “科室范围”和“审计类型”表格有价值，但应更紧凑、更像配置清单。
8. 左侧菜单仍可继续去重，避免同一模块多次出现。

---

## 2. 推荐页面定位

```text
运行总览 / 配置体检中心
```

这个页面不是普通配置页，而是用于回答：

```text
1. 当前系统能不能跑？
2. 哪些配置存在风险？
3. 哪些运行模式启用？
4. 调度器会跑哪些审计类型？
5. 科室范围按什么语义解析？
6. 每个审计类型的数据源、Dify、SQL、显示是否完整？
```

---

## 3. 推荐页面结构

```text
顶部标题操作条 46px
├─ 运行总览
├─ 副标题：配置体检、运行模式、调度器、科室范围和审计链路总览
└─ 右侧：刷新体检 / 导出报告 / 跳转配置

模块状态条 40px
├─ PostgreSQL 数据源：已配置未测试
├─ Dify 配置：已配置未测试
├─ 科室过滤：未配置
├─ 推送参数：已配置未测试
├─ 通知渠道：已配置未测试
├─ 前置机推送：已配置未测试

运行健康摘要 42px
├─ 风险总数 78
├─ 错误 0
├─ 警告 5
├─ 信息 73
├─ 配置完整度 82%
└─ 当前兼容模式 legacy-compatible

主体区
├─ 左侧 70%
│  ├─ 配置风险提示
│  ├─ 运行模式
│  ├─ 调度器配置
│  ├─ 科室范围
│  └─ 审计类型清单
└─ 右侧 30%
   ├─ 配置体检摘要
   ├─ 当前运行链路
   ├─ 推荐处理顺序
   └─ 最近检查记录
```

---

## 4. 页面布局建议

### 4.1 顶部模块状态条

保留当前顶部模块入口，但改成更紧凑的状态胶囊：

```text
PostgreSQL 数据源   已配置·未测
Dify 配置           已配置·未测
科室过滤            未配置
推送参数            已配置·未测
通知渠道            已配置·未测
前置机推送          已配置·未测
运行总览            当前页
```

状态颜色：

```text
测试通过：绿色
已配置未测试：橙色
未配置：红色
禁用：灰色
当前页：蓝色
```

### 4.2 配置信息摘要

当前已有：

```text
只读模式：是
章节已映射：是
SQL 已排序：否
配置版本：legacy-compatible
```

建议压缩成一行摘要：

```text
只读模式 是 | 章节已映射 是 | SQL已排序 否 | 配置版本 legacy-compatible
```

这部分是系统能否安全运行的重要前置信息，应该放在顶部第二行。

### 4.3 配置风险提示

风险提示建议按级别分组：

```text
错误 0
警告 5
信息 73
```

默认只展示前 6 条高优先级风险，右侧提供：

```text
全部
仅警告
仅信息
复制风险
导出报告
```

列表每条建议展示：

```text
风险级别
风险编码
风险说明
影响路径
建议处理
```

例如：

```text
警告
audit_type_source_missing_sql
审计类型 discharge_vs_frontpage 的 discharge 数据源缺少 query_sql
路径：audit_type.discharge_vs_frontpage.sources.discharge.query_sql
建议：进入审计类型管理补充 SQL 或确认使用默认 SQL
```

### 4.4 运行模式

运行模式建议改为 2×2 网格，但保持卡片紧凑：

```text
daily_increment
discharge_final
manual
precheck
```

每张卡显示：

```text
run_mode
调用 Dify
写 Pushlog
检查 Relay
来源名影响
默认查询日期
科室范围
```

并用颜色标识：

```text
启用 / 调用 Dify / 写日志：绿色
禁用 / 不写日志：灰色
需要注意：橙色
```

### 4.5 调度器配置

建议每个 scheduler 一张紧凑卡：

```text
scheduler_daily
启用：是
运行模式：daily_increment
Cron：32 8 * * *
间隔：10 minutes
审计类型：progress_vs_nursing、jyjc_vs_bcnursing、admission_vs_first_progress、surgery_chain
科室范围：daily_increment

scheduler_discharge
启用：是
运行模式：discharge_final
Cron：22 13 * * *
间隔：10 minutes
审计类型：...
科室范围：discharge_final
```

### 4.6 科室范围

科室范围表建议保留，但增加“语义解释”：

```text
daily_increment：current_dept，按当前科室
discharge_final：discharge_dept，按出院科室
manual_default：request_defined，请求指定
patient_census：mode_defined，模式定义
```

### 4.7 审计类型清单

审计类型表建议紧凑展示：

```text
编码
名称
启用
默认调度
构建器
数据源
必需源
Dify 来源
URL
API Key
SQL
展示
```

优化点：

1. URL 不要完整暴露，改成“已配置”。
2. API Key 只显示“有/无”，不显示内容。
3. 数据源和必需源使用标签，长内容折叠。
4. SQL/展示状态用绿色/红色标签。
5. 点击审计类型跳转“审计类型管理”详情。

---

## 5. 紧凑尺寸建议

```text
主内容 padding：10px～12px
标题操作条高度：46px
模块状态条高度：40px
健康摘要条高度：42px
风险列表默认高度：220px～260px
运行模式卡片高度：118px～132px
调度器卡片高度：150px～170px
表格行高：38px～42px
Tab/按钮高度：28px～32px
卡片圆角：8px
卡片间距：8px
```

---

## 6. 只改前端的实现建议

### 6.1 不改后端接口

本次不要求新增接口。可先复用当前运行总览页面已有数据结构：

```text
配置状态
配置风险提示
运行模式
调度器配置
科室范围
审计类型
```

如果某些统计值后端没有直接返回，前端可由现有数组计算：

```text
风险总数 = warnings.length
警告数 = warnings.filter(level === 'warning').length
信息数 = warnings.filter(level === 'info').length
审计类型总数 = auditTypes.length
启用数 = auditTypes.filter(enabled).length
SQL 完整数 = auditTypes.filter(sql_ok).length
```

### 6.2 建议新增前端状态

```javascript
const overviewRiskFilter = ref('all')      // all / warning / info
const selectedRunMode = ref('daily_increment')
const selectedScheduler = ref('scheduler_daily')
const overviewKeyword = ref('')
const showAllWarnings = ref(false)
```

### 6.3 建议组件拆分

```text
RuntimeOverviewPage
├─ ConfigModuleTabs
├─ RuntimeHealthBar
├─ ConfigRiskPanel
├─ RunModeGrid
├─ SchedulerConfigCards
├─ DeptScopeTable
├─ AuditTypeRuntimeTable
└─ RuntimeSummaryAside
```

如果当前仍是单文件静态 Vue 页面，也可以先按区域拆模板块和 CSS 类，不必马上拆 SFC。

---

## 7. 本地 AI 执行提示词

```text
请对“运行总览”页面进行前端 UI 优化，只改前端，不修改后端接口和业务逻辑。

目标：将当前运行总览页面改为“配置体检与运行态总览页”。

要求：
1. 保留现有配置状态、配置风险提示、运行模式、调度器配置、科室范围、审计类型清单等功能。
2. 不修改后端接口，不改变现有数据结构。
3. 顶部使用 46px 标题操作条，右侧放“刷新体检 / 导出报告 / 跳转配置”。
4. 保留顶部模块状态入口，但改为紧凑状态胶囊，状态包括：已配置未测试、未配置、测试通过、当前页。
5. 增加一行运行健康摘要，显示：风险总数、错误、警告、信息、配置完整度、当前配置版本。
6. 配置风险提示按级别分组，默认只展示前 6 条高优先级风险，支持“全部/仅警告/仅信息”切换。
7. 运行模式改为 2×2 紧凑卡片：daily_increment、discharge_final、manual、precheck。
8. 调度器配置改为 scheduler_daily / scheduler_discharge 两张紧凑卡片。
9. 科室范围保留表格，但增加语义说明和允许留空状态。
10. 审计类型表格保持紧凑行高，URL 和 API Key 不直接暴露内容，只展示“已配置/有/无”。
11. 点击审计类型应能跳转或定位到审计类型管理对应规则。
12. 右侧增加运行摘要栏：配置体检摘要、运行链路、推荐处理顺序、最近检查记录。
13. 保证原有运行总览页面所有数据展示不丢失。
```

---

## 8. 回归测试清单

1. 运行总览页面是否正常打开。
2. 顶部模块状态是否正常显示。
3. 配置信息摘要是否正常显示。
4. 配置风险提示是否正常显示。
5. 风险筛选：全部/警告/信息是否正常。
6. 运行模式 daily_increment、discharge_final、manual、precheck 是否正常显示。
7. 调度器 scheduler_daily、scheduler_discharge 是否正常显示。
8. 科室范围表格是否正常显示。
9. 审计类型表格是否正常显示。
10. Dify URL 和 API Key 是否没有明文泄露。
11. 点击审计类型是否能跳转或定位。
12. 页面在 1366px 分辨率下是否可用，不出现严重横向错位。
13. 小屏幕下右侧摘要栏是否能下移显示。

---

## 当前实现状态（对照检查）

- **符合度**：75%
- **已落地**：配置元信息、配置风险提示按级别分组、运行模式卡片、调度器配置卡片、科室范围表格、审计类型清单、Dify URL/API Key 以“已配置/有/无”形式展示。
- **未落地**：
  1. 页面顶部独立的“模块状态条”（当前仅在 Tab 标签内显示状态胶囊）。
  2. 运行模式未按 2×2 紧凑网格展示。
  3. 审计类型表格仍显示完整 Dify URL（已脱敏但长度较长）。
  4. 右侧缺少运行摘要栏（配置体检摘要/运行链路/推荐处理顺序/最近检查记录）。
- **建议**：当前实现已满足“配置体检”核心诉求，右侧摘要栏可作为后续增强。
