# 执行任务书 `PROMPT-WP08`：全院级「用户与权限」界面重构 + 数据源与系统配置页（含 360 配置）重构

> **所属总计划**：`docs/ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md`（工作包 8 / 10）  
> **预计耗时**：约 3.5 小时  
> **前置依赖**：`WP-02`（`batch-update`、`access-bundle`、`departments/paged`、`/api/config/holography` 已就绪）  
> **先读文件顺序**：`AGENTS.md` → `开发起步包/README.md` → `00_AI协作规则.md` → `01_统一修改记录.md` 末 10 行 → `02_协作任务板.md` → **`prompts-064/PROMPT-00_通用事实基线与勘误_必读.md`** → `git status --short` 存 `review/064-wp08/git_status_before.txt`。

---

## 一、目标（用户反馈第 10 项）

1. **用户与权限**（`frontend/src/features/system/AccessPage.vue`，路由 `/system/access`）：原页面按单科试点设计，现全院 **2,383 用户 / 640 科室**。重构为清晰的 **「菜单权限 + 科室数据范围」双层授权中心**：多维筛选、完整分页、批量操作、角色一次性保存、无平铺科室复选框。
2. **数据源与系统配置**（`frontend/src/features/governance/ConfigPage.vue`，路由 `/governance/config`）：拆成分页签，每页签独立「测试 / 保存」，并新增 **「360 全息视图对接配置」** 页签（`S28` / `wfy` / 预览工具）。

> 现状：`AccessPage.vue` 约 20KB 只有 103 行、`ConfigPage.vue` 约 35KB 只有 143 行——是被压缩成超长单行的模板。**重写时必须正常缩进换行**。

---

## 二、开工前必做的「防回归盘点」（30 分钟，结果写进 `review/064-wp08/exec-log.md`）

1. 读完两个页面的 `<script>`，列出它们调用的**全部接口与参数**（这些调用在重构后必须仍然存在，除非改用 WP-02 新的等价接口）。
2. 在 `frontend/tests/unit/access-contracts.test.ts`、`frontend/tests/unit/config-contracts.test.ts`、`frontend/tests/e2e/`、`tests/test_access_configuration.py`、`tests/test_*frontend_static*.py` 中搜索这两个页面用到的 `data-testid`、文案、选择器：
   ```powershell
   Select-String -Path frontend/tests/unit/*.ts,frontend/tests/e2e/*.ts -Pattern "access|config|data-testid" | Select-Object -First 80
   ```
   **所有被测试引用的 `data-testid` 与关键中文文案必须在新页面中保留**；确需改变的，同步修改测试并在交付报告逐条列出。
3. `ConfigPage` 的保存逻辑：确认每个分区调用的保存端点（`/api/config/oracle`、`/postgresql`、`/emr-vastbase`、`/dify`、`/dify/targets`、`/push`、`/privacy-masking`、`/notify` 等）以及密码/API Key「留空不覆盖」的现有处理方式——**新页面完全沿用，不改后端**。

---

## 三、文件白名单
- 修改：`frontend/src/features/system/AccessPage.vue`、`frontend/src/features/governance/ConfigPage.vue`；需要拆分时可新增子组件到 `frontend/src/features/system/components/`、`frontend/src/features/governance/components/`
- 修改（仅同步断言）：`frontend/tests/unit/access-contracts.test.ts`、`frontend/tests/unit/config-contracts.test.ts`
- 新增：`frontend/tests/unit/access-page-rbac.test.ts`、`frontend/tests/unit/config-holography-tab.test.ts`、`review/064-wp08/`
- 登记：`开发起步包/01`、`02`
- **不改后端**（若发现 WP-02 接口缺陷，只做最小修复并在报告单列）。

---

## 四、`AccessPage.vue` 实现规范

顶层：`PageHeader`（title「用户与权限管理」，subtitle「全院账号、菜单可见权限与科室数据查询范围」）+ `<el-tabs v-model="activeTab">` 3 个页签。

### Tab 1「用户管理」
- `FilterPanel` 主行（每项带 `ma-field__label`）：
  1. 关键字（`q`：姓名/账号/工号，回车查询）；
  2. 角色（下拉：全部 / 未分配角色 / 各角色中文名）；
  3. 所属科室（`el-select filterable remote`，远程搜索调用 `GET /api/departments/paged?keyword=…&limit=20`；**不要一次性渲染 640 个选项也可接受 `filterable` 全量，但优先 remote**）；
  4. 账号状态（全部 / 已启用 / 已停用 / 待分配（`directory_pending`））；
  5. 数据范围（全部 / 全院 / 仅本科室 / 指定多科室）。
- 批量工具条（表格上方 flex 两端）：左「已选 N 人」+「批量分配角色」「批量设置数据范围」「批量启用/停用」（未选禁用）；右主按钮「新建用户」。
  - 批量弹窗确认文案写清人数；提交 `POST /api/users/batch-update`，**每批 ≤200**，超过时前端自动分批顺序提交并显示进度 `已完成 x / y`；失败的批次汇总提示。
- 表格 `DataTableShell` + `el-table max-height="calc(100vh - 400px)"`，分页 `layout="total, sizes, prev, pager, next, jumper"`、`[20, 50, 100]`（请求参数名 `page`、`limit`）：
  1. 多选（fixed left）；2. 姓名与工号（fixed left：姓名粗体 + 灰色 username）；3. 所属科室；4. 角色（tag；无角色橙色「待分配」）；5. **生效数据范围**（`effective_scope.label`：全院=紫、仅本科室=蓝、指定=青「指定 N 个科室」，`source==='user'` 时后缀小字「（个人设置）」）；6. 状态（`el-switch`，切换调用现有用户更新接口，二次确认）；7. 操作（fixed right，宽 160：「编辑」「重置密码」）。
- 新建/编辑弹窗（宽 600，`el-form label-position="top"` 两列）：
  - 「基础信息」：账号、姓名、所属科室（remote 搜索）、角色、启用开关；
  - 「数据查询范围」：单选 `跟随角色` / `个人设置：全院` / `个人设置：仅本科室` / `个人设置：指定科室`；选指定时出现 `el-select multiple filterable remote collapse-tags collapse-tags-tooltip`；
  - 保存时：基础信息走现有用户创建/更新接口；数据范围走现有用户 timeliness-access/等价接口或 `batch-update`（单人），以 WP-02 实现为准。

### Tab 2「角色与权限」
- 布局 `display:grid; grid-template-columns: 260px 1fr; gap:16px; align-items:start`（<960px 上下排列）。
- 左：角色卡列表（中文名 + 英文名小字 + 人数徽章；选中态浅蓝底 + 左 3px 蓝条）+「新建角色」。
- 右：
  - **粘性保存条**（`position:sticky; top:0; z-index:5; background:#fff; border-bottom:1px solid var(--ma-border); padding:12px 16px`）：「正在配置：<b>角色名</b>」+ 有改动时橙色 tag「有未保存修改」+ 主按钮「保存本角色权限」→ **一次调用 `PUT /api/roles/{id}/access-bundle`**；切换角色时若有未保存修改，弹确认框。
  - 区块①「菜单可见权限」：按 5 个分组（质控总览 / 病历时效管理 / 内涵与终末质控 / 质控规则中心 / 系统与运维，数据来自 `GET /api/roles/menus/catalog` 的 group 字段）渲染 5 张小卡，卡头「本组全选」，卡内 `grid-template-columns: repeat(auto-fill, minmax(180px, 1fr))` 复选菜单项（每组 ≤ 8 项，不违反「>20 平铺」红线）；hidden 菜单不显示。
  - 区块②「科室数据查询范围」：3 张可点选卡片（单选）：「全院数据」「仅本人所属科室」「指定多个科室」（每张卡一句中文说明）；选指定时显示 remote 多选 + 已选科室 `el-tag closable` 列表 + 「清空」。
  - 区块③「功能操作权限」（`el-collapse` 默认折叠）：按模块分组的权限复选（数据来自现有权限列表接口）。
- 删除旧的「每勾一个复选框弹一次确认」交互。

### Tab 3「科室目录」
- 搜索框（编码/名称）+「新增科室」；表格（编码、名称、用户数 `user_count`、操作「编辑」），数据来自 `GET /api/departments/paged`，分页 `[20,50,100]`。

---

## 五、`ConfigPage.vue` 实现规范

- 改为左侧竖向 `el-tabs tab-position="left"`（窄屏自动切顶部）共 6 个页签，每个页签内：`el-form label-position="top"` 两列网格（`grid-template-columns: repeat(2, minmax(260px,1fr)); gap: 0 24px`）+ 底部操作条（「测试连接」+ 主按钮「保存本页」）。
  1. **临床业务库（Oracle）**：主机、端口、服务名、账号、密码（`type="password" show-password`，placeholder「留空表示不修改」）；连接池参数放 `el-collapse`「高级参数」，标签全部中文（如「最小连接数」「最大连接数」「获取连接超时(秒)」，**禁止显示 `pool_min` 等英文键**）；测试结果用中文结构化卡片（成功/失败、耗时、错误信息），原始 JSON 折叠。
  2. **业务库（PostgreSQL，如启用）**：同上；数据源类型切换（`/api/config/data-source`）放这里顶部。
  3. **电子病历库（Vastbase）**：同上；`sslmode` 显示为「SSL 模式（可选，留空不传）」。
  4. **AI 引擎（Dify）**：默认地址（提示「只填基础地址，不要带 /workflows/run」）、API Key（留空不改）、超时、目标节点列表（沿用现有 `/dify/targets` 编辑能力）+「测试 Dify」。
  5. **360 全息视图**（新增，调用 `GET/POST /api/config/holography`）：启用开关、基础地址、系统编码（默认 `S28`）、非工号账号兜底工号（默认 `wfy`）、员工工号格式（正则，默认 `^[0-9]{4,10}$`，旁边小字说明「符合此格式的登录账号直接作为工号传给 360」）、非员工账号列表（`el-select multiple allow-create filterable`，默认 `admin`）、企微手机端显示（默认关）；**预览工具**：输入测试患者号 → 实时显示拼接 URL（用当前表单值本地拼，userCode 用后端返回的当前登录人 `user_code`）+「新窗口试打开」按钮。
  6. **推送、脱敏与通知**：推送参数（`/push`）、隐私脱敏（`/privacy-masking`）、通知渠道（`/notify`）分 3 个卡片，各自保存。
- 企微前置机配置不在本页（在 `/governance/relay`，WP-09 处理）；本页保留一个 `el-alert` 指引链接。
- 所有分区保存时：只提交本分区字段；后端返回中未在表单展示的字段，用 `rawExtras` 原样回传（若该分区后端接口本就是局部更新，则只发本分区字段）；密码/Key 为空不发送。

---

## 六、红线
1. 不平铺 640 科室；不压缩单行模板；所有输入有持久中文标签；不裸露英文键名与原始 JSON。
2. 不改变任何后端接口语义；密码/API Key 留空不覆盖；`X-Requested-With` 头保持。
3. 保留测试引用的 `data-testid` 与文案；禁止生产写入与 Git 写操作。

## 七、验收
- `frontend/tests/unit/access-page-rbac.test.ts`：筛选参数映射（`page/limit/q/role_id/...`）、未选用户时批量按钮禁用、超过 200 人自动分批调用次数正确、角色页「保存」只调用 1 次 `access-bundle`、选「指定多个科室」时 DOM 中复选框数量 < 50。
- `frontend/tests/unit/config-holography-tab.test.ts`：默认值 `S28/wfy` 回显、预览 URL 拼接正确、保存只提交 holography 段。
- 原有 `access-contracts.test.ts`、`config-contracts.test.ts` 全绿。

```powershell
python -m pytest tests/test_access_contracts.py tests/test_wp02_data_scope_and_holography.py tests/timeliness/test_access_configuration.py -q
cd frontend
npm run typecheck
npm run test:unit -- tests/unit/access-page-rbac.test.ts tests/unit/config-holography-tab.test.ts tests/unit/access-contracts.test.ts tests/unit/config-contracts.test.ts
npm run test:unit
npm run build
cd ..
python scripts/run_gates_20260906.py --quick
```
另：用 `npm run dev` 或已构建产物在 1440×900 与 1280×768 两种窗口下目测（或 Playwright 截图存 `review/064-wp08/screens/`），确认无横向溢出、无文字遮挡。收工写 `review/064-wp08/DELIVERY.md`，登记 01/02。
