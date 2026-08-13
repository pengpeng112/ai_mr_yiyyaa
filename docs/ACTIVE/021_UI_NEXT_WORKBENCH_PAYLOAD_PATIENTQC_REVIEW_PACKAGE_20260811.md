# 021 — UI Next 工作台图表 / 推送报文详情 / 患者质控布局 复核包

| 项 | 内容 |
| --- | --- |
| 文档编号 | 021 |
| 日期 | 2026-08-11 |
| 状态 | **供外部 AI / 人工复核**；不单独授权 Stage B（默认入口切换） |
| 范围 | 本会话内 UI Next 排障与可用性补丁 + 相关生产热更说明 |
| 默认入口 | 生产仍为 `UI_DEFAULT_ENTRY=legacy`（`/` 旧版；`/ui-next/` 并行） |
| 生产镜像标签（本会话末次） | `med-audit:pq-layout-20260811_202850`（此前含 `ui-payload-20260811_200205`、`ui-wb-20260811_190900` 等中间层，最终以 `latest` 为准） |

> **给复核 AI 的用法**：先读本文 §1–§4 意图与验收，再按 §5 文件清单 diff 代码，对照 §6 回归清单与 §7 红线。不要把本文件当作全量 017/019 前端改造说明；全量迁移见 019。

> **023 收口说明（2026-08-13）**：本文件仅作为 UI Next 局部复核证据和缺陷目录；它不构成 Stage A/B、真实 Dify/Relay 或生产写入授权。所有后续执行登记在 `ACTIVE/023_SYSTEM_COMPLETION_AND_ONE_SHOT_EXECUTION_PLAN_20260813.md`。

---

## 1. 背景与问题

### 1.1 工作台图表空白 / 旧布局

- 现象：KPI 有数，但「风险等级分布」「近 30 天趋势」空白；用户截图仍为旧布局文案。
- 根因：
  1. ECharts 在 `v-if` loading 骨架下初始化 → ref/容器宽高为 0。
  2. 生产 `static/ui-next/assets` 累积大量历史 hash 分包，浏览器缓存旧 `index-*.js` / `WorkbenchPage-*.js`。
  3. `/ui-next/` HTML 未强制 `Cache-Control: no-store`，入口易被缓存。
- 后端数据正常：`/api/stats/severity`、`/api/stats/daily`、`/api/stats/today` 均有数据（生产实测）。

### 1.2 质控记录缺少「推送 JSON / Dify 返回」

- 旧系统：`audit.html` 详情 / `log_detail.html` 可看 `request_json`、`response_json`、`mr_text`、`raw_debug`。
- 新 UI：`AuditRecordsPage` 详情抽屉仅有结论与维度，**未展示报文**，排障不便。
- 后端：`GET /api/logs/{id}` 已返回 `mr_text` / `request_json` / `response_json` / `raw_debug` 等，**无需新接口**。

### 1.3 患者质控右侧大块空白

- 现象：列表右侧约 1/3 空白。
- 根因：表格列全部固定 `width`，总宽约 1300px，宽屏无法铺满；旧版右侧「患者摘要」侧栏未迁移，空白更刺眼。

### 1.4 质控中心导出（分析，本会话未再改代码）

| 能力 | 接口 | 旧 UI | UI Next |
| --- | --- | --- | --- |
| 患者汇总 Excel | `GET /api/patient-qc/export/patient-visit-summary` | 有；旧端曾不传筛选 | 有；传筛选 + 确认 + total=0 禁用 |
| 质控记录 CSV | `GET /api/logs/export/csv` | 有 | 有 |
| 整改反馈 Excel | `GET /api/qc/feedback/export/excel` | 有（须 audit_type） | 有（闭环页） |

导出权限：`export_reports`（患者/日志）；均写 `ExportAuditLog`。

---

## 2. 本轮实施摘要

### 2.1 工作台（`WorkbenchPage.vue`）

- 图表容器改为 **`v-show` 常驻 DOM**（避免 ref 销毁）。
- 数据落入 `trendRows` / `severityItems`，`schedulePaintCharts` **宽高为 0 时重试**，`ResizeObserver` + 二次 `resize`。
- KPI 聚焦 AI 质控：今日核查量 / 不一致 / 高危 / AI 成功率；去掉「待处理反馈」类人工杂项占位。
- 风险/趋势 API 空时，可用近 7/14 日 `/logs` 本地聚合兜底。

### 2.2 入口缓存（`app/main.py` + `frontend/index.html`）

- 注册 `/ui-next`、`/ui-next/`、`/ui-next/index.html` 的 `FileResponse` 路径。
- **HTTP 中间件**对上述路径强制：
  - `Cache-Control: no-store, no-cache, must-revalidate, max-age=0`
  - `Pragma: no-cache` / `Expires: 0`
  - `X-Med-Audit-UI: ui-next-no-cache`
- `index.html` meta：`med-audit-ui-build` 用于辨认构建版本（当前示例：`pq-layout-20260811-v1`）。
- 生产部署策略：替换前 **清空** 容器内 `/app/static/ui-next` 再拷贝干净 `dist`，避免旧 hash 分包残留。

### 2.3 质控记录推送报文（`AuditRecordsPage.vue`）

详情抽屉新增区块 **「推送报文与 Dify 返回」**（Tab）：

| Tab | 数据源 | 用途 |
| --- | --- | --- |
| 推送 JSON | `request_json` 格式化 | 发给 Dify 的结构化入参 |
| Dify 响应 | `response_json` 或 `ai_result` | 模型原始/解析前输出 |
| 主输入文本 | `mr_text` | 工作流主文本 |
| 调试信息 | `raw_debug`（或缺省拼装） | run_id、parse 状态等 |

- 各 Tab **复制**按钮；支持剪贴板失败时 `textarea` 兜底。
- 描述项补充：`workflow_run_id`、`task_id`、`elapsed_ms`、`ai_version`、触发方式等。
- 列表「更多」文案：`推送详情（JSON）` → 仍打开 `/log_detail.html?id=`（旧完整页）。
- 维度数据兼容 `audit_result.dimensions` 与 `stored_audit.dimensions`。

### 2.4 患者质控布局（`PatientQcPage.vue`）

- 布局：`grid` **左表 + 右摘要 280px**。
- 列宽：关键列改为 `min-width`，表格 `width: 100%`。
- 点击行 → 选中并刷新右侧摘要；「详情」→ 抽屉。
- 列表加载后默认选中第一行（或保持选中），避免右侧空。
- 窄屏（≤960px）侧栏改纵向堆叠。

---

## 3. 主要变更文件（复核时优先）

| 路径 | 变更类型 | 说明 |
| --- | --- | --- |
| `frontend/src/features/workbench/WorkbenchPage.vue` | 重写/加固 | 图表时序、KPI、布局 |
| `frontend/src/features/quality/AuditRecordsPage.vue` | 功能补齐 | 推送报文 Tab、复制、元数据 |
| `frontend/src/features/quality/PatientQcPage.vue` | 布局 + 交互 | 左右分栏、选中摘要 |
| `frontend/index.html` | meta 构建标记 / 禁缓存 meta | 入口辨认 |
| `app/main.py` | 路由 + 中间件 | ui-next HTML 禁缓存 |
| `frontend/src/utils/patient-qc-contracts.ts` | 既有（导出参数） | 患者导出筛选键（本会话未改逻辑则仅作上下文） |
| `app/routers/patient_qc.py` / `logs.py` | 既有导出 | 复核导出契约时只读 |

**后端业务推送/Dify 调用路径本会话未改**（仅消费已有详情 API）。

---

## 4. 生产部署事实（便于对照）

| 项 | 值 |
| --- | --- |
| 服务 | `http://10.10.8.84:8000` |
| UI Next | `http://10.10.8.84:8000/ui-next/` |
| 默认入口 | `legacy`（未做 Stage B） |
| 部署方式 | 容器内热更 `static/ui-next` + `app/main.py`（相关次）；`docker commit` 打标签；**非**完整 registry 重建 |
| 健康 | 重启后 `healthy` |
| 回滚 | 使用 `med-audit:pre-*` / 前序 tag 回滚镜像或恢复旧 static |

**安全注意**：部署脚本曾误打印容器完整 Env 的历史风险；复核与后续脚本 **禁止** 输出密钥/密码。

---

## 5. 建议复核清单（给另一 AI）

### 5.1 代码正确性

- [ ] `WorkbenchPage`：loading 结束后图表是否一定在 DOM 可见后 init；dispose/重入是否泄漏 ECharts 实例。
- [ ] `paintCharts` 重试上限与失败静默是否可接受；无数据时 empty 与 clear 是否一致。
- [ ] `AuditRecordsPage`：`prettyJson` 对非法 JSON 字符串是否仅原文展示、不抛错。
- [ ] 复制按钮在无 HTTPS / 无 clipboard 权限时是否安全降级。
- [ ] `PatientQcPage`：选中态与分页/筛选刷新后一致性；`row-class-name` 与 Element Plus 类型。
- [ ] `main.py` 中间件是否仅作用于入口 HTML，**不**误伤 `/ui-next/assets/*` 长缓存策略（当前设计：仅 3 个 path）。

### 5.2 契约与权限

- [ ] 详情接口仍要求 `view_reports`；导出仍要求 `export_reports`。
- [ ] 报文区是否可能展示 PHI/病历正文 → 与既有详情权限一致；不新增更宽权限。
- [ ] 科室可见性：列表/详情仍走后端 visibility，前端仅展示。

### 5.3 回归场景（手工）

| # | 场景 | 期望 |
| --- | --- | --- |
| R1 | `/ui-next/` 强刷 | 响应头含 `cache-control: no-store`、`x-med-audit-ui`；meta `med-audit-ui-build` 为最新 |
| R2 | 工作台 | 标题「AI 质控工作台」；饼图/折线有数据（有业务数据时） |
| R3 | 质控记录 → 详情 | 可见「推送报文与 Dify 返回」四 Tab；成功推送记录有 request/response |
| R4 | 质控记录 → 更多 → 推送详情 | 打开 `/log_detail.html?id=` |
| R5 | 患者质控 | 右侧摘要有内容；点行切换；详情按钮开抽屉 |
| R6 | 患者导出 | 筛选后导出条数与 total 语义一致；0 条禁用 |
| R7 | 默认入口 | `/` 仍为 legacy；未 307 到 ui-next |

### 5.4 已知限制 / 非目标

- Stage B（`UI_DEFAULT_ENTRY=ui-next`）**未做**。
- WP6 四角色 canary、Relay 实发 **仍 BLOCKED**（见 020）。
- 告警记录页仍无专用导出。
- 患者质控详情抽屉内 **尚未** 嵌完整 request/response（仅质控记录页补齐）；若产品要求可后续对称补。
- 质控记录 CSV 导出参数与列表筛选字段未必 100% 对齐（如 severity），属既有缺口。
- 本会话未新增自动化单测覆盖 Workbench 图表 / Payload Tab / 侧栏布局。

---

## 6. 本地验证命令

```bash
# 前端类型检查
cd frontend && npm run build:docker

# 默认入口解析单测
python -m pytest tests/test_ui_default_entry.py -q

# 患者导出相关（若复核导出契约）
python -m pytest tests/test_patient_qc_export_filters.py tests/test_patient_visit_export_audit.py -q
```

生产只读检查（示例）：

```bash
curl -sI http://127.0.0.1:8000/ui-next/ | tr '[:upper:]' '[:lower:]' | grep -E 'cache-control|x-med-audit'
curl -s http://127.0.0.1:8000/ui-next/ | grep med-audit-ui-build
curl -s http://127.0.0.1:8000/api/health
```

---

## 7. 红线（复核 AI 不得擅自突破）

1. 不得切换 `UI_DEFAULT_ENTRY=ui-next`（Stage B）除非书面批准。
2. 不得批量 Relay 实发 / 全量 Dify 补跑。
3. 不得在文档或日志中写入密钥、SSH 密码、Fernet/JWT 明文。
4. 不得 `npm run build`（应用 `build:docker` 约定）。
5. 生产热更后若只改 static，须确认清空旧 assets，避免双版本并存。

---

## 8. 建议复核结论格式

请外部 AI 输出：

1. **通过 / 有条件通过 / 不通过**
2. **P0 / P1 / P2** 缺陷列表（含文件路径与复现步骤）
3. 是否发现 **PHI 过度暴露** 或 **缓存回退旧 UI** 风险
4. 是否建议补测项（单测/E2E）

---

## 9. 关联文档

| 编号 | 路径 | 关系 |
| --- | --- | --- |
| 017 | `docs/ACTIVE/017_FRONTEND_ARCHITECTURE_MENU_LAYOUT_REMEDIATION_PLAN_20260809.md` | 前端架构与入口开关 |
| 019 | `docs/ACTIVE/019_LEGACY_TO_UI_NEXT_FUNCTION_AND_FIGMA_PLAN_20260811.md` | 功能迁移矩阵 |
| 020 | `docs/ACTIVE/020_WP6_CANARY_ACCEPTANCE_BLOCKED_REPORT_20260811.md` | WP6 阻塞状态 |
| 101 | `docs/reference/101_FEATURE_BASELINE.md` | 能力基线 |

---

## 10. 变更时间线（本会话）

| 时间（约） | 动作 |
| --- | --- |
| 工作台图表 fix | loading 后 init + 重试；清理 assets；部署 `ui-wb-*` |
| 缓存中间件 | `main.py` 对 ui-next HTML `no-store`；验证响应头 |
| 推送报文 | `AuditRecordsPage` Tab；部署 `ui-payload-*` |
| 患者布局 | 右栏摘要 + 弹性列；部署 `pq-layout-20260811_202850` |

---

*文档结束。代码冲突时以仓库当前文件为准；生产 digest 以服务器 `docker images` / 容器内 `index.html` 的 `med-audit-ui-build` 为准。*
