# 执行任务书 `PROMPT-WP03`：质控总览重构（首屏秒开 + 四大态势卡）+ 病历时效统计分析专页

> **所属总计划**：`docs/ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md`（工作包 3 / 10）  
> **预计耗时**：约 3.0 小时  
> **前置依赖**：必须已完成 `WP-01`（`GET /api/stats/workbench-overview`）与 `WP-02`（`data_scope.py` + `HolographyButton.vue` + `timeliness-stats` 占位路由）  
> **先读文件顺序**：`AGENTS.md` → `开发起步包/README.md` → `开发起步包/00_AI协作规则.md` → `开发起步包/01_统一修改记录.md` 末 10 行 → `开发起步包/02_协作任务板.md` → **`开发起步包/prompts-064/PROMPT-00_通用事实基线与勘误_必读.md`** → `git status --short` 存 `review/064-wp03/git_status_before.txt`。

---

## 一、任务背景与目标

1. **质控总览（需求 1、2、3）**：`frontend/src/features/workbench/WorkbenchPage.vue`（菜单 ID `dashboard`，路由 `/workbench`）首屏由 10~14 个串行请求改为 **只调 1 次 `GET /api/stats/workbench-overview`**；顶部 4 张板块态势卡（AI 内涵 / 病历时效 / 归档前核查 / 告警与系统健康）可点击跳转；高危清单带 360 全息按钮。
2. **病历时效统计分析专页（需求 4）**：新接口 `GET /api/timeliness/stats/analytics` + 页面 `TimelinessStatsPage.vue`（路由 `/timeliness/stats`），展示 **科室锁定排名、医生锁定排名**、规则节点超时分布、每日趋势、KPI，排行可点击钻取到台账。

### 1.1 统计口径（必须严格照此实现，与现有 `_monthly_rows` 一致）

| 指标 | 数据来源与口径 |
| --- | --- |
| **锁定次数**（科室/医生锁定排名的主指标） | `TLApproval` 中 `apply_date_time` 落在统计区间的行数。每行 = JHEMR 一次「超时被锁→申请解锁」记录。科室维度按 `TLApproval.dept_code`，医生维度按 `TLApproval.apply_user_id` |
| 待审批锁定 | 上述行中 `flag == '1'` |
| 已解锁 | `flag == '2'` |
| 已豁免 | `penalty_exempt == True` |
| 有效扣罚（元） | `flag == '2'` 且 `penalty_exempt` 非真时 `COALESCE(penalty_amount, 200)` 求和 |
| 事件总数 / 按时 / 超时完成 / 超时未完成 / 预警中 | `TLEvent` 中 `t0` 落在统计区间；状态分别 `COMPLETED_ON_TIME` / `COMPLETED_LATE` / `OVERDUE` / `WARNING`；科室按 `TLEvent.dept_code`，医生按 `TLEvent.responsible_doctor_id` |
| 按时率 % | `COMPLETED_ON_TIME / (COMPLETED_ON_TIME + COMPLETED_LATE) × 100`，分母 0 记 0.0，保留 1 位 |
| 平均超时小时 | `OVERDUE` + `COMPLETED_LATE` 事件 `overdue_minutes` 平均 / 60，保留 1 位 |

> ⚠️ `TLEvent` 没有 `lock_status`、`t0_time`、`deadline_at`，**不要写这些字段**。

---

## 二、文件白名单

### 允许新增
1. `app/timeliness/stats_service.py`
2. `frontend/src/api/endpoints/workbench.ts`、`frontend/src/api/endpoints/timelinessStats.ts`
3. `tests/test_wp03_timeliness_stats.py`
4. `frontend/tests/unit/timeliness-stats-page.test.ts`、`frontend/tests/unit/workbench-overview.test.ts`
5. `review/064-wp03/`

### 允许修改
1. `app/routers/timeliness.py`（新增 `GET /stats/analytics`，**注册在 `/stats/monthly` 附近，不改现有端点**）
2. `app/routers/mobile_timeliness.py`（可选：`/api/mobile/timeliness/stats` 内部改为复用 `stats_service.py`，**响应字段 100% 不变**；若改动风险大可不动，交付报告说明）
3. `frontend/src/features/workbench/WorkbenchPage.vue`
4. `frontend/src/features/timeliness/TimelinessStatsPage.vue`（替换占位页）
5. 既有前端单测中引用 Workbench 旧 DOM/旧请求的断言（如 `frontend/tests/unit/` 下 workbench 相关文件）——只做同步修正，不削弱断言
6. `开发起步包/01_统一修改记录.md`、`02_协作任务板.md`

---

## 三、后端实施

### 3.1 `app/timeliness/stats_service.py`
```python
def compute_timeliness_analytics(
    db: Session, *, current_user: User,
    date_from: date, date_to: date,           # 闭区间，内部转为 [date_from 00:00, date_to+1 00:00)
    dept_code: str | None = None, top_n: int = 15,
) -> dict: ...
```
- **可见性**：先读 `app/routers/timeliness.py` 中 `_monthly_rows` 的写法，照抄 `visibility = timeliness_visibility(db, current_user)` + `visibility.apply(query, TLEvent.dept_code / TLApproval.dept_code)` + `_filter_dept(...)`（WP-02 后它们内部已委托 `data_scope`）。
- **全部用 SQL 聚合**（`func.count`、`func.sum(case(...))`、`group_by`），**禁止 `.all()` 拉全表到 Python 循环计数**。
- 日期按天截断写方言辅助函数：
  ```python
  def _day_bucket(col, dialect_name: str):
      if dialect_name == "oracle":
          return func.trunc(col)          # 结果是 DATE
      return func.date(col)               # SQLite 返回 'YYYY-MM-DD' 字符串
  ```
  返回前统一格式化为 `YYYY-MM-DD` 字符串。`dialect_name = db.get_bind().dialect.name`。
- 中文名映射：科室名用 1 次查询 `Department(code, name)` 建字典；医生名复用 `_display_maps(db)["staff"]`（每次请求最多调 1 次）。
- 返回结构（**键名一个都不要改，前端按此读取**）：
  ```json
  {
    "date_from": "2026-11-01", "date_to": "2026-11-19", "scope_label": "全院",
    "summary": {
      "total_events": 0, "on_time_count": 0, "late_completed_count": 0,
      "overdue_count": 0, "warning_count": 0, "on_time_rate": 0.0,
      "locked_count": 0, "locked_pending": 0, "unlocked_count": 0,
      "exempt_count": 0, "penalty_amount_total": 0
    },
    "dept_ranking": [
      { "dept_code": "", "dept_name": "", "locked_count": 0, "locked_pending": 0,
        "overdue_count": 0, "total_events": 0, "on_time_rate": 0.0, "penalty_amount_total": 0 }
    ],
    "doctor_ranking": [
      { "doctor_code": "", "doctor_name": "", "dept_code": "", "dept_name": "",
        "locked_count": 0, "overdue_count": 0, "total_events": 0,
        "on_time_rate": 0.0, "avg_overdue_hours": 0.0, "penalty_amount_total": 0 }
    ],
    "rule_breakdown": [
      { "rule_code": "", "rule_name": "", "overdue_count": 0, "late_completed_count": 0, "total_events": 0 }
    ],
    "daily_trend": [
      { "date": "2026-11-01", "total": 0, "overdue": 0, "locked": 0, "on_time_rate": 0.0 }
    ]
  }
  ```
  - `dept_ranking`：事件聚合（按 `TLEvent.dept_code`）与锁定聚合（按 `TLApproval.dept_code`）在 Python 中按 `dept_code` **合并**（参照 `_monthly_rows` 合并方式），按 `locked_count DESC, overdue_count DESC` 排序取前 `top_n`；
  - `doctor_ranking`：事件按 `(responsible_doctor_id, dept_code)`、锁定按 `(apply_user_id, dept_code)` 合并，排序同上，**返回前 100 条**（前端分页/搜索）；
  - `rule_breakdown`：按 `TLEvent.rule_code` 聚合，`rule_name` 从 `TLRule` 映射；
  - `daily_trend`：事件按 `t0` 天聚合 + 锁定按 `apply_date_time` 天聚合后按日期合并，区间内无数据的日期补 0。

### 3.2 路由 `GET /api/timeliness/stats/analytics`
- 依赖与 `stats_monthly` 相同的 `require_permission(PERM_VIEW)`；
- 参数：`date_from: str | None`、`date_to: str | None`（`YYYY-MM-DD`，默认本月 1 日 ~ 今天）、`dept: str | None`（与现有 `stats/monthly` 的 `dept` 参数同名同语义）、`top_n: int = Query(15, ge=5, le=50)`；
- 校验：日期格式错误或 `date_from > date_to` → 400（英文 `detail`）；跨度 > 366 天 → 400。

---

## 四、前端实施（照骨架写，不要自由排版）

> 已安装 `echarts`、`element-plus`、`dayjs`。所有 ECharts 实例：`onMounted` 初始化、`window.addEventListener('resize', …)`、`onBeforeUnmount` 中 `removeEventListener` + `chart.dispose()`。数据为空时显示 `<EmptyState description="当前周期暂无统计数据" />`，不初始化图表。

### 4.1 `WorkbenchPage.vue`（路由 `/workbench`）

**先读现有文件**：保留现有的 `go(path)` 无权限 `ElMessage.info` 提示逻辑和 keepAlive/`onActivated` 行为。

- **请求**：`onMounted`/`onActivated`（距上次加载 >30s 才重新拉）只调 `fetchWorkbenchOverview({ days: 30 })`；刷新按钮传 `force_refresh: true`；**删除**原来对 `/health`、`/stats/today`、`/stats/daily`、`/stats/severity`、`/stats/anomaly-top`、`/scheduler/status`、`/patient-qc/relay-alert/summary`、`/logs`、`/timeliness/*` 的分散调用。
- **跳转路径（全部用真实路由）**：

| 点击位置 | `go(...)` 目标 |
| --- | --- |
| AI 内涵卡整卡 | `/quality/patients` |
| AI 卡「高危清单」 | `/quality/patients?severity=high` |
| AI 卡「整改闭环」 | `/closure/feedback` |
| 时效卡整卡 / 「时效统计」 | `/timeliness/stats` |
| 时效卡「超时台账」 | `/quality/timeliness-events?status=OVERDUE` |
| 时效卡「解锁审批」 | `/timeliness/approvals?flag=1` |
| 预检卡整卡 / 「进入核查台」 | `/governance/workbench` |
| 预检卡「形式规则」 | `/governance/prearchive-rules` |
| 健康卡整卡 / 「调度管理」 | `/tasks/scheduler` |
| 健康卡「未读告警」 | `/closure/alerts?quick=unviewed` |
| 科室柱状图点击 | `/quality/patients?dept=<科室名>`（先读 `PatientQcPage.vue` 现有 route query 参数名，用它支持的键，例如 `dept`/`dept_name`） |
| 高危表「查看详情」 | 与现有高危列表行为一致（读原代码；通常是打开 `/quality/patient-detail?patient_id=…&visit_number=…` 独立页或患者页抽屉） |

- **页面结构（4 层）**：
  1. `PageHeader`：title「质控总览」，subtitle「实时态势 · 数据范围：{scope_label} · 更新于 HH:mm:ss」；actions：「刷新数据」、主按钮「处理高危病历」。
  2. **四卡矩阵** `.pillar-grid { display:grid; grid-template-columns: repeat(4, minmax(220px,1fr)); gap:16px; margin-bottom:16px }`，`@media (max-width:1200px){ grid-template-columns: repeat(2,1fr) }`。每张 `<article class="pillar-card pillar-card--{blue|amber|cyan|emerald}">`：
     - 头部：标题 + 右侧 `el-tag size="small" effect="light"`；
     - 主数字 `.pillar-card__num { font-size:28px; font-weight:700 }` + 单位小字；
     - 3 个子指标一行（`.pillar-card__metrics { display:flex; gap:12px; font-size:12px; color: var(--ma-text-secondary) }`）；
     - 底部链接区 `@click.stop`，`el-button link size="small"`。
     - 卡片样式：白底、`1px solid var(--ma-border)`、`border-top:3px solid <色>`（蓝 `var(--ma-blue-600)`、橙 `var(--ma-orange-500)`、青 `var(--ma-cyan-600)`、绿 `var(--ma-green-500)`；健康卡异常时改红 `var(--ma-red-500)`）、`border-radius: var(--ma-radius)`、`padding:16px`、`cursor:pointer`、hover `transform: translateY(-2px); box-shadow: var(--ma-shadow)`。
     - 四卡字段映射：
       - AI 卡：主数字 `ai_qc.today_pushed`（今日核查），标签「高危 {today_high_risk}」，子指标 近30天高危 `severity_counts.high` / 中危 `severity_counts.medium` / 今日成功 `today_success`；
       - 时效卡：主数字 `timeliness.inpatient_overdue`（在院已超时），标签「待审批 {locked_pending}」（>0 用 warning），子指标 临期预警 `inpatient_warning` / 本月锁定 `month_locked_total` / 本月按时率 `month_on_time_rate`%；
       - 预检卡：主数字 `prearchive.total_checked`（已核查病历），标签按 `mode` 映射中文（`shadow`→「影子模式」、`shadow_idle`→「影子待数据」、`unconfigured`→「待接入」、其他→「运行中」）；`available=false` 时主数字显示「—」并在子指标位置显示 `status_message`；
       - 健康卡：主数字 `relay.unviewed`（企微未读告警），标签 `system.status==='ok'` →「运行正常」否则「存在异常」，子指标 已送达 `relay.success` / 失败 `relay.failed` / 调度 `scheduler_running ? '运行中':'未启动'`。
  3. **双图区** `.chart-grid { display:grid; grid-template-columns: 3fr 2fr; gap:16px }`（<1024px 单列），每图白卡、`.chart-box{height:300px}`：左「近 30 天 AI 质控量与高危趋势」（柱=total，线=high），右「异常高发科室 TOP10」（横向柱，`yAxis.inverse=true`，柱尾显示数值）。
  4. **最新高危待处理患者**白卡：`el-table border stripe size="small" max-height="380"`，列：患者（fixed left：姓名粗体 + 下行 `患者号 · 第N次`）、科室、质控类型、风险 `<RiskTag>`、核心缺陷摘要（tooltip）、核查时间、操作（fixed right，宽 170：「查看详情」+ `<HolographyButton :patient-id="row.patient_id" link />`）。
- 加载中：四卡与图区显示 `SkeletonBlock`；接口失败：`ErrorState` + 重试。

### 4.2 `TimelinessStatsPage.vue`（路由 `/timeliness/stats`）

1. `PageHeader`：title「病历时效统计分析」，subtitle「科室与医生锁定排名、规则节点超时分布与趋势」；actions：「刷新」、「前往月度考核」（`/quality/timeliness-monthly`）。
2. `FilterPanel`（主行 3 个控件，每个带 `<label class="ma-field__label">`）：
   - 「快捷周期」`el-radio-group size="small"`：近7天 / 本月（默认）/ 上月 / 近30天 / 自定义（选自定义时才启用日期框）；
   - 「统计周期」`el-date-picker type="daterange" value-format="YYYY-MM-DD" range-separator="至"`；
   - 「科室」`el-select filterable clearable placeholder="全部可见科室"`（选项来源：现有 `/api/timeliness/dicts` 或 timeliness 页已在用的科室下拉接口，先读 `EventLedgerPage.vue` 复用同一来源）。
3. `SummaryStrip` 6 卡：事件总数（info）、按时完成率%（success）、锁定次数 `locked_count`（danger）、待审批锁定 `locked_pending`（warning）、超时未完成 `overdue_count`（danger）、有效扣罚（元）`penalty_amount_total`（warning）。
4. 双图白卡（`grid-template-columns: 1fr 1fr; gap:16px`，图高 360px）：
   - 左「科室锁定排名 TOP15」：头部右侧 `el-radio-group size="small"` 切换 `按锁定次数 / 按超时未完成 / 按扣罚金额`（前端对 `dept_ranking` 重新排序即可）；横向柱状，点击柱 → `router.push({ path: '/quality/timeliness-events', query: { dept: row.dept_code } })`（参数名以 `EventLedgerPage.vue` 现有 `applyRouteQuery` 支持的为准）；
   - 右「规则节点超时分布」：横向堆叠柱（超时未完成=红、超时完成=橙），点击 → `/quality/timeliness-events?rule_code=…`（同样以台账页支持的参数名为准，不支持则在 WP-04 补，交付报告注明）。
5. 「医生锁定排名」白卡：头部 排序切换（同上 3 项）+ `el-input clearable placeholder="输入医生姓名或工号"`（带 label「医生搜索」）；`el-table max-height="420" border stripe`，前端分页 `el-pagination layout="total, sizes, prev, pager, next" :page-sizes="[20,50,100]"`。列：排名（1/2/3 用圆形彩色徽章）、医生、工号、科室、**锁定次数（红色加粗）**、超时未完成、事件总数、按时率（`<el-progress :percentage="row.on_time_rate" :stroke-width="8" />`）、平均超时(小时)、有效扣罚(元)、操作「查看台账」（跳台账页带医生参数）。
6. 「每日趋势」白卡（高 280px）：双 Y 轴——左轴柱（每日超时、每日锁定），右轴线（按时率 %）。

---

## 五、红线

1. SQL 必须 SQLite（测试）与 Oracle（生产）都能跑；方言差异用 `dialect_name` 分支。
2. 不改现有 `stats/monthly`、`export/monthly`、手机端 `/api/mobile/timeliness/stats` 的响应结构。
3. 前端不裸露英文状态码、规则码不能作为唯一展示文本（规则名优先，规则码作小字）。
4. 禁止生产写入与 Git 写操作。

## 六、验收

1. `tests/test_wp03_timeliness_stats.py`：
   - 构造 TLEvent/TLApproval 样本，`2026-11-01~2026-11-10` 区间外样本不计入；
   - `locked_count` = 区间内 TLApproval 行数，科室/医生合并正确，排序正确；
   - `on_time_rate`、`penalty_amount_total`（豁免不计、空金额按 200）准确；
   - `home` 范围用户只统计本科室，传别的 `dept` 不越权；
   - 非法日期/倒序/超 366 天返回 400；
   - `daily_trend` 缺失日期补 0。
2. 前端单测：Workbench 只调用 1 次 overview 接口、四卡跳转路径正确；统计页 KPI 渲染、医生排序切换与搜索过滤生效。

```powershell
python -m compileall app tests scripts
python -m pytest tests/test_wp03_timeliness_stats.py tests/timeliness/test_api_timeliness.py tests/timeliness/test_mobile_timeliness_20261116.py tests/test_wp01_perf_and_overview.py -q
cd frontend
npm run typecheck
npm run test:unit -- tests/unit/timeliness-stats-page.test.ts tests/unit/workbench-overview.test.ts
npm run test:unit
npm run build
cd ..
python scripts/run_gates_20260906.py --quick
```
收工写 `review/064-wp03/DELIVERY.md`，登记 01/02（本地交付完成，未提交）。
