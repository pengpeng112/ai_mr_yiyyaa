# 018 交接文档：017 前端架构整改（本地 WP0–WP5）完成度与未完成项

> 文档编号：018  
> 日期：2026-08-10（Asia/Shanghai）  
> 性质：**交接与状态事实**，供后续 AI / 人工接手；本身**不授权**生产部署、默认入口切换、删除 legacy、Dify/推送/调度/告警、改生产配置或数据库  
> 计划主文档：`docs/ACTIVE/017_FRONTEND_ARCHITECTURE_MENU_LAYOUT_REMEDIATION_PLAN_20260809.md`  
> 分支：`fix/ora-12609-p4-error-code`（本专项改动**尚未 git commit**）

---

## 0. 一句话结论

| 问题 | 答案 |
| --- | --- |
| **017 整份计划是否都完成了？** | **否。** 仅完成本地 **WP0–WP5**（含契约加固与本地验收）；**WP6 生产 canary、WP7 默认切换/legacy 退役未做**。 |
| 新前端能否当生产默认入口？ | **不能。** 默认仍是 legacy `/`；`/ui-next/` 仅为本地/并行 canary 入口。 |
| 是否触碰生产？ | **否。** |
| 下一任该先干什么？ | 读本文件 → 017 §22/§23 → 本地复现构建与冒烟 → **人工确认产品三项** → 再决定是否批准 WP6。不要重做 WP0–WP5 脚手架。 |
| git 干净吗？ | **否。** 017 相关与既有分支改动混在未提交工作区。 |

---

## 1. 计划完成度总览（按 017 工作包）

| 工作包 | 计划要求 | 状态 | 说明 |
| --- | --- | --- | --- |
| **WP0** 冻结基线 | 页面矩阵、角色菜单、API/权限、vendor 体积、三分辨率基线、脱敏 fixture、Node/离线决策 | **部分完成** | 文档与 fixture 已建；**真实浏览器人工截图/Console/Network 基线未做**，不得写成“浏览器基线已通过”。 |
| **WP1** 旧菜单收口 | 新分组、保留 menu ID、生产过滤 dev_only、隐藏占位、测试、menu_service、legacy navigation 对齐 | **完成（本地）** | 见 §2.1 |
| **WP2** 新工程 App Shell | frontend/、锁文件、Hash Router、Pinia、懒加载、API client、Docker multi-stage | **完成（本地）** | 见 §2.2；**院内离线 cache 制品交付未做** |
| **WP3** 只读 canary 页 | 健康→运行总览→工作台→任务进度 | **完成（本地功能迁移）** | 非像素级与 legacy 对照验收 |
| **WP4** 质控与闭环 | 质控记录→患者质控→告警→反馈只读→反馈写 | **完成（本地功能迁移）** | 写操作有二次确认；深度业务对照未全量抓包 |
| **WP5** 高风险写页 | 权限→Relay→配置→质控类型→调度→手动推送→Dify 调试 | **完成（本地功能迁移）** | 已做 mutation 契约单测与关键修复；**不等于生产可开写** |
| **WP6** 新入口灰度 | `/ui-next/` 并行 ≥7 日、扩角色、写页单独开关 | **未实施** | 本轮授权明确禁止 |
| **WP7** 默认切换与 legacy 退役 | 默认切新前端、/legacy 回退、删 static 源码 | **未实施** | 本轮授权明确禁止 |

### 1.1 对“本轮任务目标”的裁定

用户任务要求：

- 按 WP0→WP5 本地实施与验证 → **已做**  
- WP6/WP7 只出清单不得实施 → **已遵守**  
- 故：**授权范围内的实施目标已完成；017 全文（含发布与退役）未完成。**

---

## 2. 已完成项（接手可复用，勿重做脚手架）

### 2.1 后端菜单（WP1）

| 项 | 位置 |
| --- | --- |
| 菜单权威目录 | `app/routers/menu.py`：`MENU_GROUPS` / `MENU_CATALOG` / `MENU_CONFIG` / `schema_version=2` / `route_name` |
| 生产过滤 `dev_only` | `filter_menu_items_for_navigation` + `ENVIRONMENT`/`APP_ENV` |
| 占位隐藏 | `oracle-status`、`system-logs` → `hidden=True`，导航不返回 |
| `/api/menu/all` | 需管理员 |
| RoleMenu schema | `app/schemas.py` `RoleMenuInfo.route_name` |
| 死代码 | `app/services/menu_service.py` → deprecated 空桩（全仓无业务引用） |
| legacy 对齐 | `static/scripts/navigation.js` 分组/文案与后端一致 |
| 测试 | `tests/test_menu_api.py`；`tests/test_frontend_menu_manifest_contract.py` |

**推荐文案（已落地，待产品最终签字）：**

- `audit` → 质控记录  
- `relay` → 告警推送配置  
- `access` → 用户与权限  
- 分组：工作台 / 质控中心 / 闭环管理 / 任务中心 / 规则与配置 / 系统管理  

**menu ID 全部保留**（RoleMenu 兼容）。

### 2.2 新前端工程（WP2–WP5）

| 项 | 位置 |
| --- | --- |
| 工程根 | `frontend/`（Vue 3 + Vite + TS strict + Vue Router Hash + Pinia + Element Plus 按需） |
| 锁文件 | `frontend/package-lock.json`（**须纳入版本库**） |
| 路由白名单 | `frontend/src/router/route-manifest.ts`（与后端 menuId 交集，未知 fail-closed） |
| App Shell | `frontend/src/layouts/AppShell.vue`、`AppSidebar.vue` |
| API | `frontend/src/api/client.ts`、`errors.ts`、endpoints/* |
| mutation 契约 | `frontend/src/utils/mutation-contracts.ts` + unit 测试 |
| 构建产物 | `npm run build` → `frontend/dist` + 同步 `static/ui-next/`（gitignore 构建物） |
| 访问路径 | `http://<host>:8000/ui-next/`（Hash：`/ui-next/#/workbench`） |
| Docker | `Dockerfile` multi-stage Node 构建 → `/app/static/ui-next/` |
| 冒烟脚本 | `scripts/smoke_ui_next_local.py` |
| 说明 | `frontend/README.md`、`static/templates/README.md`（标明 legacy 并行） |

### 2.3 已迁移页面（功能级，非视觉验收签字）

| 页面 | menu_id | 路由 |
| --- | --- | --- |
| 工作台 | dashboard | `#/workbench` |
| 患者质控 | patient-qc | `#/quality/patients` |
| 质控记录 | audit | `#/quality/records` |
| 告警记录 | relay-alert-logs | `#/closure/alerts` |
| 整改反馈 | feedback | `#/closure/feedback` |
| 手动推送 | push | `#/tasks/push` |
| 任务进度 | push-progress | `#/tasks/progress` |
| 定时任务 | scheduler | `#/tasks/scheduler` |
| 质控类型 | audit-types | `#/governance/audit-types` |
| 系统配置 | config | `#/governance/config` |
| 告警推送配置 | relay | `#/governance/relay` |
| 运行总览 | config-runtime | `#/system/runtime` |
| 系统健康 | health | `#/system/health` |
| 用户与权限 | access | `#/system/access` |
| Dify 调试 | debug | `#/system/debug`（dev_only，生产菜单过滤） |

**未做页面组件（有意）：** `oracle-status`、`system-logs`（占位隐藏）。

### 2.4 本地验证证据（2026-08-10）

| 检查 | 结果 |
| --- | --- |
| `python -m pytest` | 全量通过 |
| `compileall` / `check_naming_convention` | 通过 |
| `npm run typecheck` / `test:unit` | 通过（约 17 unit） |
| Playwright 三分辨率 | 31 passed，2 skipped |
| 本地 uvicorn | `/ui-next/` 200、legacy `/` 200、菜单 401、admin 登录后 schema_version=2、占位隐藏、分组 6 |

### 2.5 过程中修过的关键契约缺陷

| 缺陷 | 修复 |
| --- | --- |
| 调度立即触发误用 body `{mode}` | 改为 `POST /api/scheduler/trigger?audit_run_mode=daily_increment\|discharge_final` |
| Relay/Dify 空密钥覆盖风险 | mutation builder：空 secret/空 base_url 不提交 |
| 手动推送 body 过简 | 对齐 dry_run / async_mode / replace_current / skip 等核心字段 |
| Docker `COPY .npm-cache*` 无缓存失败 | 改为整包 COPY frontend，有 cache 再 offline |

---

## 3. 未完成项清单（接手必读）

### 3.1 明确未实施（计划内，授权外）

| ID | 项 | 阻塞/依赖 |
| --- | --- | --- |
| U-01 | **WP6 生产 canary** | 人工批准；镜像重建；观察 ≥7 业务日 |
| U-02 | **WP7 默认入口切换** | WP6 通过 + 负责人签字 |
| U-03 | **legacy `/` 退役 / 删除 static 源码** | WP7 后两个发布周期无阻断 |
| U-04 | 生产 Docker 部署本专项镜像 | 禁止本交接文档自动授权 |

### 3.2 本地“部分完成 / 质量债”（WP0–WP5 内未收口）

| ID | 项 | 说明 | 建议优先级 |
| --- | --- | --- | --- |
| Q-01 | **真实浏览器人工三分辨率基线截图** | WP0 要求 1366/768/390 旧页截图与 Console/Network 基线；目前主要靠 Playwright mock | P1（WP6 前） |
| Q-02 | **与 legacy 请求体逐页抓包对照** | mutation 有单测与核心字段对齐，**未**对每个写页做浏览器 Network 新旧完整 diff | P0（开写页 canary 前） |
| Q-03 | **页面功能完整度 vs legacy** | 新页为可工作迁移，非 1:1 功能/UI 复刻（如手动推送高级节点池、历史重跑全 UI、配置全 tab 等可能弱于 legacy） | P1 |
| Q-04 | **Element Plus 初始包体积** | 仍约 160KB+ gzip；未达 017 理想 ≤450KB 全初始预算的“足够瘦”目标 | P2 |
| Q-05 | **院内 `npm ci --offline` 制品** | 本机 warm cache 可通过；**未**交付可分发的 `.npm-cache`/私服策略证明生产可复现 | P0（生产构建前） |
| Q-06 | **组件级 Vue Test Utils 覆盖** | 有 unit + e2e；AppSidebar/FilterPanel 等组件测未充分按 017 §15.2 铺开 | P2 |
| Q-07 | **产品三项签字** | 文案（质控记录/告警推送配置）、角色默认首页；技术已按建议落地 | P0（UI 定稿） |
| Q-08 | **git commit / PR** | 用户未要求提交；工作区脏 | 按用户指令 |
| Q-09 | **legacy frontend_regression_check 既有 high** | `app.js` import version mismatch（push.js query）为 **legacy 既有问题**，本专项未修 | 可选 |
| Q-10 | **menu_service 物理删除** | 现为 deprecated 桩；可在确认无外部导入后删除 | P3 |
| Q-11 | **History 模式 SPA fallback** | 首期故意 Hash，未改 FastAPI fallback | 二期 |
| Q-12 | **HttpOnly Cookie / CSP 等认证升级** | 017 明确另立计划，本专项不绑 | 另案 |
| Q-13 | **移动 H5 / log_detail 并入 SPA** | 首批明确不迁 | 另案 |
| Q-14 | **生产 ENVIRONMENT=production 下菜单过滤现场验证** | 本地逻辑已测；生产镜像未部署本改动 | WP6 |

### 3.3 017 验收清单对照（§19，摘要）

| 验收项 | 状态 |
| --- | --- |
| 一级分组 ≤6，生产无占位/开发页 | **本地逻辑完成**；生产未验 |
| 后端唯一业务目录 + 前端 manifest | **完成** |
| menu ID 与 RoleMenu 兼容 | **完成**（未改 ID） |
| 稳定 URL / 前进后退 / 刷新 | **e2e 完成**（mock） |
| 首屏不拉全模板、单页失败不白屏全站 | **架构完成** |
| 全局 store 非 god store | **完成** |
| 统一 AppShell 等基础组件 | **基本完成** |
| 三分辨率浏览器回归 | **Playwright 完成**；人工真后端未做 |
| 四角色菜单与 403 | **e2e 完成** |
| 旧新 API/mutation 契约一致 | **部分**（关键路径+单测；非全量抓包） |
| 离线构建+镜像 tag+canary+回滚演练 | **未完成**（仅本地 build + Dockerfile 具备） |
| 新前端默认入口后两周期无阻断再删 legacy | **未开始** |

---

## 4. 红线与禁止项（下一任必须遵守）

1. **不要**在未书面批准下做 WP6/WP7、改生产默认入口、删 `static/` legacy。  
2. **不要**改 menu ID（可改 label/group/order）。  
3. **不要**把前端菜单隐藏当唯一权限；API 仍须 RBAC。  
4. **不要**改 `mr_text`/`mr_txt`、daily/discharge 双锁、current/superseded、Relay 部分更新、secret 留空保留等后端语义。  
5. **不要**为“界面好看”省略 mutation 字段或把空字符串密钥提交覆盖。  
6. **不要**构建时拉生产 OpenAPI；不要把 `docker commit` 当正式发布。  
7. **不要**在日志/截图/trace 落患者正文、密钥、request/response 原文。  
8. 本交接文档**不授权**生产写操作。

---

## 5. 关键路径索引

```
docs/ACTIVE/017_FRONTEND_ARCHITECTURE_MENU_LAYOUT_REMEDIATION_PLAN_20260809.md  # 作业书
docs/ACTIVE/018_HANDOVER_AFTER_017_FRONTEND_LOCAL_WP0_WP5_20260810.md          # 本交接
docs/reference/wp0_frontend_baseline_fixtures/                                 # WP0 基线
app/routers/menu.py
frontend/                          # 新前端源码
static/                            # legacy（默认入口）
static/ui-next/                    # 构建产物（通常 gitignore）
tests/test_menu_api.py
tests/test_frontend_menu_manifest_contract.py
scripts/smoke_ui_next_local.py
Dockerfile                         # multi-stage ui-next
```

---

## 6. 接手后建议验证命令

```powershell
# Python
python -m pytest tests/test_menu_api.py tests/test_frontend_menu_manifest_contract.py -q
python -m pytest -q
python -m compileall app tests scripts
python scripts/check_naming_convention.py

# Frontend
Set-Location frontend
npm ci
npm run typecheck
npm run test:unit
npm run build
npx playwright install chromium   # 首次
npm run test:e2e

# 本地服务冒烟
# 终端1: $env:ENABLE_SCHEDULER="false"; uvicorn app.main:app --host 127.0.0.1 --port 8000
# 终端2:
python scripts/smoke_ui_next_local.py --password <本地管理员密码>
# 浏览器: http://127.0.0.1:8000/  与  http://127.0.0.1:8000/ui-next/
```

---

## 7. WP6 前置条件（复制自 017，执行前须人工批准）

1. 产品确认文案与角色默认首页（017 §21）。  
2. 隔离环境可 `npm ci --offline`（或交付 `.npm-cache`/院内 registry）+ Docker multi-stage 可 tag 重建。  
3. Q-02 关键写页 Network 新旧对照通过。  
4. 管理员测试账号 canary；写页默认关闭或限账号。  
5. 监控：JS 错误、4xx/5xx、重复请求、敏感信息抽检。  
6. 回滚演练：用户回 `/` 或镜像回退，不改 DB/配置。  
7. 连续 ≥7 业务日观察后再扩角色。

---

## 8. 给下一任 AI 的精简提示词

```text
你在 Med-Audit 仓库接手 017 前端整改。先读 docs/INDEX.md 与
docs/ACTIVE/018_HANDOVER_AFTER_017_FRONTEND_LOCAL_WP0_WP5_20260810.md。
WP0–WP5 本地脚手架与页面迁移已完成，禁止推倒重做。
未完成：WP6 生产 canary、WP7 默认切换/legacy 退役、离线构建制品证明、
legacy 抓包全量对照、人工三分辨率真后端基线、git 提交。
默认入口仍是 /；/ui-next/ 为并行入口。
禁止生产、禁止 Dify/推送/调度/告警、禁止删 static legacy，除非用户对具体动作书面批准。
改菜单只许改文案/分组/顺序，禁止改 menu ID。
```

---

## 9. 是否触碰生产

**否。**

---

## 10. 与 016 等其他交接的关系

- **016**：015 整合整改 / 生产热更 / 011·012 主线，**仍然有效**。  
- **018**：仅覆盖 **017 前端架构本地 WP0–WP5** 专项。  
- 不要把 018 的“前端本地完成”误解为全系统或生产前端已切换。
