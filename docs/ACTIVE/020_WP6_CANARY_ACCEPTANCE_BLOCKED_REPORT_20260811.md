# 020 WP6 Canary 验收报告（阻塞）

> 日期：2026-08-11（Asia/Shanghai）  
> 状态：**BLOCKED — 缺少 CANARY_BASE_URL、四角色账号与测试科室**；已完成本地只读契约/自动化验收与一项本地权限补丁  
> 范围：UI Next `/ui-next/` WP6 canary 前置验收；**不切换默认入口、不删除 legacy、不触发 Dify/调度/历史重跑/真实告警**  
> Figma：用户已取消，未调用

> **023 收口说明（2026-08-13）**：本文件是 WP6 阻塞证据和验收矩阵，不是独立执行授权；后续是否补齐 canary 输入、部署或推进 Stage A/B，统一服从 `ACTIVE/023_SYSTEM_COMPLETION_AND_ONE_SHOT_EXECUTION_PLAN_20260813.md` §0.6/§9.1。

---

## 0. 总裁定

| 项 | 结论 |
| --- | --- |
| 是否进入默认入口切换（WP7） | **否** |
| 是否完成真实 canary 四角色逐页验收 | **否（阻塞）** |
| 本地契约与自动化回归 | **通过**（见第 6 节） |
| 生产写操作 / 部署 | **未执行** |

### 阻塞清单（必须由人工提供后才能续跑 canary）

| 阻塞项 | 状态 | 说明 |
| --- | --- | --- |
| `CANARY_BASE_URL` | **MISSING** | 用户消息为占位符；环境变量与仓库内无 canary 地址 |
| admin / dept_manager / auditor / clinician 账号口令 | **MISSING** | 无秘密存储路径可用；禁止自行创建生产账号 |
| 测试科室边界数据 | **MISSING** | 无法验证跨科隔离与下拉 NULL 科室实机表现 |
| 批准的脱敏长数据样例 | **MISSING** | 长文本/大量分页实机截图不可执行 |

仅发现 `MED_AUDIT_SSH_PASSWORD` 已设置，但本任务**禁止**未批准生产登录，且无 canary 基址，故未使用。

---

## 1. route-manifest × 四角色验收矩阵

来源：`frontend/src/router/route-manifest.ts`（15 个页面组件）∩ `app/routers/menu.py` `MENU_CONFIG` + 生产导航过滤。  
生成器：`python scripts/wp6_local_matrix.py`（只读、不连网）。

### 1.1 角色默认菜单（生产，`dev_only` 已过滤）

| 角色 | default_home | 导航 menu_id |
| --- | --- | --- |
| admin | dashboard | dashboard, patient-qc, audit, relay-alert-logs, feedback, push, push-progress, scheduler, audit-types, config, relay, config-runtime, health, access（14；debug 生产隐藏） |
| dept_manager | patient-qc | dashboard, patient-qc, audit, feedback, scheduler, health（6） |
| auditor | dashboard | dashboard, patient-qc, audit, feedback, health（5） |
| clinician | feedback | dashboard, audit, feedback（3） |

### 1.2 逐页矩阵

图例：

- **MENU_OK**：默认角色菜单包含且 manifest 有组件（前端可导航）  
- **NO_MENU**：默认菜单不含；深链应 403（前端 guard）  
- 实机列：`PASS` / `FAIL` / `BLOCKED`（本轮 canary 不可达）

| menu_id | path | risk | admin | dept_manager | auditor | clinician | 本地契约 | 实机 1366/768/390 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dashboard | /workbench | readonly | MENU_OK | MENU_OK | MENU_OK | MENU_OK | PASS（钻取 query 白名单单测/E2E mock） | BLOCKED |
| patient-qc | /quality/patients | readonly | MENU_OK | MENU_OK | MENU_OK | NO_MENU | PASS（筛选导出+科室 scope 本地测） | BLOCKED |
| audit | /quality/records | business-write | MENU_OK | MENU_OK | MENU_OK | MENU_OK | PASS（独立详情 E2E mock） | BLOCKED |
| relay-alert-logs | /closure/alerts | business-write | MENU_OK | NO_MENU | NO_MENU | NO_MENU | PASS（菜单契约） | BLOCKED |
| feedback | /closure/feedback | business-write | MENU_OK | MENU_OK | MENU_OK | MENU_OK | PASS（删除单请求契约） | BLOCKED |
| push | /tasks/push | system-write | MENU_OK | NO_MENU | NO_MENU | NO_MENU | PASS（mutation 契约单测） | BLOCKED |
| push-progress | /tasks/progress | readonly | MENU_OK | NO_MENU | NO_MENU | NO_MENU | PASS（processed/钻取/E2E mock） | BLOCKED |
| scheduler | /tasks/scheduler | system-write | MENU_OK | MENU_OK | NO_MENU | NO_MENU | PASS（本地双锁 UI/API 契约） | BLOCKED |
| audit-types | /governance/audit-types | system-write | MENU_OK | NO_MENU | NO_MENU | NO_MENU | PASS（类型契约单测） | BLOCKED |
| config | /governance/config | system-write | MENU_OK | NO_MENU | NO_MENU | NO_MENU | PASS（配置契约单测） | BLOCKED |
| relay | /governance/relay | system-write | MENU_OK | NO_MENU | NO_MENU | NO_MENU | PASS（E2E mock） | BLOCKED |
| config-runtime | /system/runtime | readonly | MENU_OK | NO_MENU | NO_MENU | NO_MENU | PASS（菜单/manifest） | BLOCKED |
| health | /system/health | readonly | MENU_OK | MENU_OK | MENU_OK | NO_MENU | PASS | BLOCKED |
| access | /system/access | system-write | MENU_OK | NO_MENU | NO_MENU | NO_MENU | PASS（E2E mock） | BLOCKED |
| debug | /system/debug | system-write | NO_MENU* | NO_MENU | NO_MENU | NO_MENU | PASS（生产过滤 dev_only） | BLOCKED |

\*admin 在非 production 环境菜单可含 debug；`ENVIRONMENT=production|prod` 时导航过滤。

### 1.3 横切验收项

| 验收项 | 本地 | 实机 canary |
| --- | --- | --- |
| 登录 / 刷新恢复 / 退出 | E2E mock PASS | BLOCKED |
| 后端菜单 ∩ 前端 manifest | `test_frontend_menu_manifest_contract` PASS | BLOCKED |
| 未知菜单 fail-closed | guards + unit PASS | BLOCKED |
| 无权限深链 403 | E2E mock PASS | BLOCKED |
| 前端隐藏 + 后端权限同时生效 | 菜单契约 PASS；见缺陷 D1 已本地修 | BLOCKED |
| dept_manager/clinician 科室隔离 | `dept_visibility` + 新 patient-qc scope 测 PASS | BLOCKED |
| auditor 不得危险写操作 | 无 push/config/manage_* 默认权限；反馈仍有 create/edit（产品口径待确认） | BLOCKED |
| 401 无 token / 失效 token | 客户端拦截器本地存在 | BLOCKED |
| 403 无权限角色 | 路由守卫 + require_permission 本地存在 | BLOCKED |
| 422 非法日期/枚举 | 导出 strict 422 本地 PASS | BLOCKED |
| 409/429 | 未在预发验证；禁止制造生产锁冲突 | BLOCKED / N/A |
| Oracle/历史 NULL 字段 | 静态代码有兼容点；实机未验 | BLOCKED |
| 长数据 / 横向溢出三视口 | Playwright mock 三视口 PASS；真数据 BLOCKED | BLOCKED |
| 工作台钻取白名单 / source 不进列表 API | unit + E2E mock PASS | BLOCKED |
| 任务中心 processed / 筛选分页 / 停轮询 / query_date 钻取 | 代码 + E2E mock PASS | BLOCKED |
| 患者筛选导出全部匹配 + 审计 count | 本地 pytest PASS | BLOCKED |

---

## 2. 本地发现缺陷与补丁

### D1 — 患者质控 API 仅 admin，与角色菜单/默认首页冲突（已本地修）

| 字段 | 内容 |
| --- | --- |
| 严重度 | P0（dept_manager 默认首页 `patient-qc`，但列表/详情/导出曾 `require_role("admin")` → 必 403） |
| 复现（静态） | `MENU_CONFIG["dept_manager"]` 含 `patient-qc`；`patient_qc.py` 列表/详情/导出依赖 admin |
| 修复 | 列表/详情 → `require_permission("view_reports")` + `visible_dept_names` / `apply_push_log_visibility`；导出 → `export_reports` + 同源科室 scope |
| 测试 | `tests/test_patient_qc_export_filters.py::test_dept_scope_limits_list_and_export_keys` 等 |
| 部署 | **未部署** canary/生产 |

Relay 告警相关端点仍为 admin-only，与仅 admin 菜单一致，**未改**。

### D2 — auditor 反馈写权限（未改，待产品确认）

`scripts/init_rbac.py` 为 auditor 分配 `create_feedback` / `edit_feedback`。若 WP6 要求 auditor **完全只读**，需产品确认后调整 RolePermission 与前端 mutations，**本轮未擅自收紧**。

---

## 3. 脱敏证据路径

| 证据 | 路径/命令 | 含患者正文/密钥？ |
| --- | --- | --- |
| 角色矩阵生成 | `python scripts/wp6_local_matrix.py` | 否 |
| 本报告 | `docs/ACTIVE/020_WP6_CANARY_ACCEPTANCE_BLOCKED_REPORT_20260811.md` | 否 |
| 自动化日志 | 本地 pytest / vitest / playwright 终端输出 | 否（mock） |
| 实机截图 | **无**（canary 阻塞） | — |

---

## 4. 回归命令与结果（本轮本地）

| 命令 | 结果 |
| --- | --- |
| `python scripts/wp6_local_matrix.py` | 通过 |
| `python -m compileall -q app tests scripts` | 通过 |
| 全量 `python -m pytest -q` | 通过（仅既有弃用警告） |
| `frontend: npm run typecheck` | 通过 |
| `frontend: npm run test:unit` | 14 文件 / 50 项通过 |
| `frontend: npm run build:docker` | 通过（仅 `frontend/dist/`） |
| `frontend: npm run test:e2e` | 46 通过 / 8 预期跳过 |
| `npm run build` | **未执行**（禁止同步 static） |

---

## 5. 续跑 canary 最小输入模板

请在安全渠道提供（勿写入 git）：

```text
CANARY_BASE_URL=https://.../ui-next/   # 或完整 origin，需可访问 /api 与 /ui-next/
ADMIN_USER=...
ADMIN_PASSWORD=...
DEPT_MANAGER_USER=...
DEPT_MANAGER_PASSWORD=...
DEPT_MANAGER_DEPTS=心内科,...
AUDITOR_USER=...
AUDITOR_PASSWORD=...
CLINICIAN_USER=...
CLINICIAN_PASSWORD=...
CLINICIAN_DEPT=心内科
APPROVED_TEST_PATIENT_HINT=仅合成/脱敏样例说明
```

提供后下一任可按本矩阵逐页填实机 PASS/FAIL，并在三视口留脱敏截图目录（如 `docs/reference/wp6_canary_evidence/`，禁止患者正文与 Authorization）。

---

## 6. 是否满足进入默认入口切换阶段

**不满足。** 原因：

1. WP6 真实 canary 四角色/三视口/真后端未执行（阻塞于凭证与地址）。  
2. 默认入口切换（WP7）依赖 WP6 ≥7 业务日观察、回滚演练、写页 Network 对照等（见 017/018）。  
3. 本轮仅本地补丁；**未**部署到 canary 镜像。  

---

## 7. 明确未执行

- 未登录生产 / canary 服务器  
- 未切换默认入口、未删除 legacy  
- 未调用 Dify、调度触发、历史重跑、Relay 真实发送  
- 未调用 Figma  
- 未创建/修改生产账号  
- 未改 SECRET_KEY / JWT / 调度双锁 / Relay 接收规则  
