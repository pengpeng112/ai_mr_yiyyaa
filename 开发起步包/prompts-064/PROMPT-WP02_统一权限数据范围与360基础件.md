# 执行任务书 `PROMPT-WP02`：全院统一 RBAC 数据范围后端 + 360 全息视图配置与通用组件

> **所属总计划**：`docs/ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md`（工作包 2 / 10）  
> **预计耗时**：约 3.0 小时  
> **前置依赖**：建议在 `WP-01` 完成后执行  
> **先读文件顺序**：`AGENTS.md` → `开发起步包/README.md` → `开发起步包/00_AI协作规则.md` → `开发起步包/01_统一修改记录.md` 末 10 行 → `开发起步包/02_协作任务板.md` → **`开发起步包/prompts-064/PROMPT-00_通用事实基线与勘误_必读.md`（冲突以它和真实代码为准）** → 先跑 `git status --short` 存到 `review/064-wp02/git_status_before.txt` 并保留他人未提交文件。

---

## 一、任务背景与已拍板业务口径

1. **统一菜单 + 科室双层权限（用户拍板 D5）**：
   - 生产现已有 **2,383 名全院用户 / 640 个科室**，但后端目前存在三套割裂的科室权限代码：`timeliness_access.py`（只管时效）、`dept_visibility.py`（只管 AI 质控与反馈）、`prearchive_admin.py`（独立写死），且 `/api/patient-qc/relay-alert/*` 硬编码仅 `admin` 可访问。
   - **目标**：抽取出全系统唯一的 `app/services/data_scope.py`，统一支持 3 种数据范围（`all` 全院 / `home` 仅本人所属科室 / `selected` 指定多个科室，**用户个人设置覆盖角色默认**），无缝打通 **质控总览、病历时效、AI 内涵质控、整改反馈、企微告警、归档前形式核查** 全部 6 大板块！同时补齐面向全院 2,383 人 / 640 科室的用户筛选、批量操作、角色一次性保存、科室分页 API。
2. **360 全息视图统一底座（用户拍板 D1）**：
   - 对接规范：《全息视图对接文档2.0-血透.docx》
     `http://10.10.8.231:8281/holography-platform/consultationView?patientId={患者号}&userCode={员工工号}&sysCode={系统编码}`
   - **已拍板口径**：全部做成后台可配置项；默认 `sys_code = "S28"`；`userCode` 取当前登录账号的员工工号——**注意 `User` 表没有 `emp_no` 字段，全院同步员工的 `username` 就是 HIS 工号（如 `003966`）**；`admin` 等非员工工号的系统账号兜底传 `wfy`（配置项 `fallback_user_code = "wfy"`）；院内 PC 端全量开启，移动端/企微 H5 默认隐藏（`enable_on_mobile = false`，可配置）。
   - **`userCode` 由后端统一计算，前端不要自己判断**（见任务 3）。
3. **菜单结构调整（用户拍板 D2 + 项 4 + 项 9 后端菜单目录先行对齐）**：
   - 菜单目录新增：`timeliness-stats`（「时效统计分析」，path `timeliness/stats`，置于 `timeliness` 分组首位）、`prearchive-rules`（「归档前形式预检规则」，path `governance/prearchive-rules`，置于 `governance` 分组）；
   - 将旧重复菜单 `audit`（path `quality/records`）设为 `hidden: True`（侧栏隐藏，但保留 ID 与路由，WP-05 再做重定向）。

---

## 二、允许修改与新增的文件白名单（严禁改动白名单外文件）

### 允许新增
1. `app/services/data_scope.py`
2. `frontend/src/utils/holography.ts`
3. `frontend/src/components/base/HolographyButton.vue`
4. `tests/test_wp02_data_scope_and_holography.py`
5. `frontend/tests/unit/holography.test.ts`
6. `frontend/src/features/timeliness/TimelinessStatsPage.vue`、`frontend/src/features/governance/PrearchiveRulesPage.vue`（各约 15 行的「建设中」占位页，WP-03/WP-06 填充）
7. `review/064-wp02/`

### 允许修改
1. `app/services/dept_visibility.py`
2. `app/services/timeliness_access.py`（**企微 H5 `mobile_timeliness.py` 依赖其 `timeliness_visibility` / `timeliness_department_options`，函数签名与返回结构不得改变**）
3. `app/routers/patient_qc.py`（`relay-alert/logs`、`relay-alert/logs/export`、`relay-alert/summary` 改为「登录 + 统一 `data_scope` 隔离」；`relay-alert/retry/{id}` 与 `alert-status-report` **保持 admin**（写操作/全院账实报告））
4. `app/routers/prearchive_admin.py`（`_scoped_dept_for_checks` 改为基于 `data_scope.py`，返回值语义保持兼容）
5. `app/routers/stats.py`、`app/routers/logs.py`、`app/routers/qc_feedback.py`（如它们已通过 `dept_visibility` 过滤，则只需 `dept_visibility` 内部委托即可，尽量不改路由代码）
6. `app/routers/users.py`、`app/routers/roles.py`、`app/routers/departments.py`、`app/schemas.py`（仅追加字段/新模型）
7. `app/routers/config.py` & `config/config.json.template`（新增 `holography_360` 配置段与读写端点）
8. `app/routers/menu.py` & `tests/test_menu_api.py`（对齐新菜单目录与断言）
9. `frontend/src/router/route-manifest.ts`、`frontend/src/layouts/AppSidebar.vue`（仅为新菜单补图标）、`frontend/tests/unit/route-manifest.test.ts`、`frontend/tests/unit/menu-intersect.test.ts`
10. `开发起步包/01_统一修改记录.md` & `开发起步包/02_协作任务板.md`

---

## 三、逐项超详细实施规范

### 任务 1：实现全系统唯一数据范围解析器 `app/services/data_scope.py`
1. 先仔细阅读 `app/services/timeliness_access.py` 和 `app/services/dept_visibility.py` 的全部逻辑与既有单测，**确保不破坏任何已有调用签名与返回值！**
2. 定义核心数据结构与解析函数：
   ```python
   @dataclass(frozen=True)
   class ResolvedDataScope:
       scope: Literal["all", "home", "selected"]
       source: str  # "admin" | "user" | "role" | "legacy_role_dept" | "default"
       dept_codes: tuple[str, ...]
       dept_names: tuple[str, ...]
       dept_ids: tuple[int, ...]
       label: str   # 中文展示标签：如 "全院" / "仅本科室（骨科一病区）" / "指定 3 个科室"

       @property
       def is_all(self) -> bool:
           return self.scope == "all"
   ```
3. 解析优先级（复用现有 `User.timeliness_access_json` / `Role.timeliness_access_json` 与 `RoleDepartment`，**零破坏表结构，不需跑表结构迁移**）：
   - Step 1：若用户是超级管理员（`role.name == "admin"` 或具备全院超级权限）→ `scope="all", source="admin", label="全院"`；
   - Step 2：解析 `user.timeliness_access_json`（如非空且含有效 `scope`）：
     - `all` → 全院；
     - `selected` → 取出 `department_codes`（同时兼容列表里传了 code 或 id），查询 `MED_DEPARTMENTS` 同步映射到 `dept_codes` + `dept_names` + `dept_ids`；
     - `home` → 查用户自身 `user.dept_id` / `his_dept_code` 映射到完整 `(code, name, id)`；
   - Step 3：若用户未覆盖，按同样规则解析 `role.timeliness_access_json`；
   - Step 4：若角色无 JSON 配置但 `MED_ROLE_DEPARTMENTS` 有绑定记录 → `scope="selected", source="legacy_role_dept"`，映射完整 `(codes, names, ids)`；
   - Step 5：全部为空时默认降级为安全最小权限 `scope="home", source="default"`（若用户无科室归属，则 `dept_codes=(), dept_names=(), dept_ids=()`，查询自动返回空集，**绝不越权放大成全院！**）。
4. 提供 4 个标准查询过滤辅助函数（处理 Oracle/SQLite 兼容）：
   - `apply_pushlog_scope(query, scope: ResolvedDataScope, model=PushLog)`：若 `is_all` 原样返回；若 `dept_names` 与 `dept_codes` 均空则 `query.filter(literal(False))`；否则过滤 `PushLog.dept.in_(set(dept_names) | set(dept_codes))`；
   - `apply_alert_scope(query, scope: ResolvedDataScope, model=QCRecordAlertLog)`：同上按 `dept` 匹配 `names | codes`；
   - `apply_feedback_scope(query, scope: ResolvedDataScope, model=QCFeedback)`：按 `dept_id.in_(dept_ids)` 或关联 `PushLog.dept`；
   - `apply_tlevent_scope(query, scope: ResolvedDataScope, model=TLEvent)`：按 `TLEvent.dept_code.in_(dept_codes)`。
5. 将 `dept_visibility.py`、`timeliness_access.py`、`stats.py`、`patient_qc.py`（包括 `/relay-alert/logs` 和 `/relay-alert/summary`，把硬编码的 `require_role("admin")` 改为普通已认证+按 `apply_alert_scope` 过滤，同时允许具备相应权限的角色查看本科室告警）、`prearchive_admin.py` 全部接入 `resolve_user_data_scope(db, current_user)`！

### 任务 2：全院级（2,383 人 / 640 科）RBAC 后端 API 升级
1. **`app/routers/users.py`**（现有 `GET /api/users` 已支持 `page`、`limit`（1–100）、`q`，返回 `UserListResponse{total,page,limit,items}`，**保持参数名与返回结构不变，只追加**）：
   - 追加可选筛选参数：`role_id: int | None`、`unassigned_role: bool = False`（只看无角色）、`dept_id: int | None`、`is_active: bool | None`、`directory_pending: bool | None`、`scope: str | None`（`all`/`home`/`selected`，按解析后的生效范围过滤——可先取当页再算，或对 `timeliness_access_json` 做 `LIKE` 粗筛后 Python 精筛，注意分页 total 要准确；若精确实现成本过高，`scope` 筛选允许只作用于「个人覆盖」与「角色默认」两类显式配置，并在交付报告说明）。
   - 每条 `UserInfo` 追加只读字段 `effective_scope: { scope, source, label, dept_count }`（`app/schemas.py` 的 `UserInfo` 加可选字段；批量计算，禁止 N+1）。
   - 新增 `POST /api/users/batch-update`（仅管理员权限）：
     ```json
     {
       "user_ids": [101, 102],
       "role_id": 3,
       "is_active": true,
       "data_scope": { "mode": "inherit_role" }
     }
     ```
     - `data_scope.mode` 支持 `"inherit_role"`（清空用户个人覆盖）、`"all"`、`"home"`、`"selected"`（配 `department_codes: [...]`）；
     - 安全护栏：单批 `len(user_ids) <= 200`；禁止禁用当前操作人自己；禁止禁用或降权最后一个活跃 `admin`；写操作审计日志。
2. **`app/routers/roles.py`**（现有逐项接口 `POST/DELETE /{role_id}/menus/{menu_id}`、`/{role_id}/departments/{dept_id}`、`/{role_id}/permissions/{permission_id}` 与 `PUT /{role_id}/timeliness-access` **全部保留**，旧前端仍可用）：
   - 新增一次性保存接口 `PUT /api/roles/{role_id}/access-bundle`（仅管理员权限）：
     ```json
     {
       "menu_ids": ["workbench", "timeliness-stats", "timeliness-events"],
       "permission_ids": [1, 2, 3],
       "data_scope": {
         "scope": "selected",
         "department_codes": ["040112", "030442"]
       }
     }
     ```
     在单个 DB 事务内原子同步：`RoleMenu`、`RolePermission`、`Role.timeliness_access_json`、并同步刷新 `RoleDepartment`（以兼容旧读取路径），返回最新角色详情。
3. **`app/routers/departments.py`**：
   - 现有 `GET /api/departments` 返回 `List[DepartmentInfo]`，被多处前端当作完整列表使用——**不要改它**。
   - 新增 `GET /api/departments/paged?keyword=&page=1&limit=20`（`limit` 上限 100），返回 `{ total, page, limit, items: [{id, code, name, user_count}] }`；`user_count` 用 1 条 `GROUP BY dept_id` 聚合，禁止 N+1。**注意路由注册顺序**：`/paged` 必须写在 `/{dept_id}` 之前，否则会被路径参数捕获返回 422。

### 任务 3：360 全息视图后台配置与前端通用按钮组件（严格遵循 D1 拍板）
1. **后端 `config/config.json.template` & `app/routers/config.py`**：
   - 在 `config/config.json.template` 顶层新增：
     ```json
     "holography_360": {
       "enabled": true,
       "base_url": "http://10.10.8.231:8281/holography-platform/consultationView",
       "sys_code": "S28",
       "fallback_user_code": "wfy",
       "employee_code_pattern": "^[0-9]{4,10}$",
       "non_employee_accounts": ["admin"],
       "enable_on_mobile": false
     }
     ```
   - 在 `app/routers/config.py` 新增：
     - `GET /api/config/holography`（**任意已登录用户可读**）：读取 `config.get("holography_360")`，缺失字段用上述默认值补全；**同时返回为当前登录人算好的 `user_code`**：
       ```python
       def resolve_holography_user_code(user, cfg) -> str:
           uname = (user.username or "").strip()
           non_emp = {s.strip().lower() for s in cfg.get("non_employee_accounts") or []}
           pattern = cfg.get("employee_code_pattern") or r"^[0-9]{4,10}$"
           if uname and uname.lower() not in non_emp and re.fullmatch(pattern, uname):
               return uname                      # 全院同步员工：username 就是 HIS 工号
           return (cfg.get("fallback_user_code") or "wfy").strip() or "wfy"   # admin 等系统账号
       ```
       （`employee_code_pattern` 写入前用 `re.compile` 校验，非法正则保存时返回 400。）
     - `POST /api/config/holography`（仅管理员可写）：Pydantic 校验 `base_url` 须以 `http://` 或 `https://` 开头（禁用时可空）、`sys_code` 非空（≤32 字符）、`fallback_user_code` 去首尾空格（默认 `"wfy"`）、`non_employee_accounts` 为字符串列表；按现有 `save_config` 写入并自动备份；**只更新 `holography_360` 段，不得覆盖其他配置段**。
2. **前端工具 `frontend/src/utils/holography.ts`**：
   - 导出类型 `HolographyConfig`（含 `enabled, base_url, sys_code, enable_on_mobile, user_code`）、常量 `DEFAULT_HOLOGRAPHY_CONFIG`（`enabled:false` 直到加载成功，避免未加载时误显示）、函数 `loadHolographyConfig(force?: boolean)`（模块级缓存 Promise，只请求一次；失败返回 `enabled:false`）、`buildHolographyUrl(patientId, cfg)`、`openHolography360(patientId, cfg)`。
   - **前端不做任何工号判断，直接用后端返回的 `cfg.user_code`。**
   - **`buildHolographyUrl` 精确规则**：
     - `cfg.enabled === false`、`cfg.user_code` 为空或 `patientId` 去除空格后为空 → 返回 `null`；
     - 用 `new URL(cfg.base_url)` + `url.searchParams.set('patientId', pid)` + `url.searchParams.set('userCode', cfg.user_code)` + `url.searchParams.set('sysCode', cfg.sys_code || 'S28')` 拼接，返回 `url.toString()`。
   - `openHolography360`：`window.open(url, '_blank', 'noopener,noreferrer')`，返回值为 null（被浏览器拦截）时 `ElMessage.warning('浏览器拦截了新窗口，请允许本站弹出窗口后重试')`。
3. **前端通用按钮组件 `frontend/src/components/base/HolographyButton.vue`**：
   ```vue
   <script setup lang="ts">
   import { computed, onMounted, ref } from 'vue'
   import {
     DEFAULT_HOLOGRAPHY_CONFIG,
     loadHolographyConfig,
     openHolography360,
     type HolographyConfig,
   } from '@/utils/holography'

   const props = withDefaults(defineProps<{
     patientId?: string | null
     label?: string
     size?: 'small' | 'default' | 'large'
     link?: boolean
     type?: 'primary' | 'default' | 'info'
   }>(), {
     label: '360全息',
     size: 'small',
     link: false,
     type: 'primary',
   })

   const cfg = ref<HolographyConfig>(DEFAULT_HOLOGRAPHY_CONFIG)

   onMounted(async () => {
     cfg.value = await loadHolographyConfig()
   })

   const hasPatientId = computed(() => Boolean(String(props.patientId || '').trim()))

   function handleClick() {
     if (!hasPatientId.value) return
     openHolography360(String(props.patientId).trim(), cfg.value)
   }
   </script>

   <template>
     <el-tooltip
       v-if="cfg.enabled"
       :content="hasPatientId ? '在新窗口打开患者 360 全息视图' : '缺少患者号，暂无法打开 360 全息视图'"
       placement="top"
     >
       <el-button
         :type="type"
         :size="size"
         :link="link"
         :plain="!link"
         :disabled="!hasPatientId"
         data-testid="holography-360-btn"
         @click.stop="handleClick"
       >
         {{ label }}
       </el-button>
     </el-tooltip>
   </template>
   ```
   （按钮在 `cfg.enabled === false` 时整体不渲染；本组件无需读取 auth store。）

### 任务 4：菜单目录与路由表前置对齐
1. 在 `app/routers/menu.py`（`MENU_CATALOG` 每项结构请照抄现有项，含 `group/path/route_name/target/legacy_tab/hidden` 等键）：
   - `timeliness` 组首位新增 `timeliness-stats`（label「时效统计分析」，path `timeliness/stats`，route_name `timeliness-stats`）；`MENU_CONFIG` 中加入 `admin`（自动）、`auditor`、`dept_manager`、`timeliness_reader`、`medical_affairs`（数据仍受各自科室范围约束，`timeliness_reader` 只能看到本科室排名）；
   - `governance` 组新增 `prearchive-rules`（label「归档前形式预检规则」，path `governance/prearchive-rules`，route_name `governance-prearchive-rules`），授权 `admin`、`auditor`；
   - 将 `audit` 设为 `hidden: True`（不删 ID；`clinician` 的 `MENU_CONFIG` 中保留 `audit` 不影响，侧栏按 hidden 过滤），并将 `patient-qc` label 改为「内涵质控工作台」；
   - 注意 `get_menu` 中现有「历史 RoleMenu 自动补齐 approvals」逻辑，新增菜单若需同样补齐（生产 `MED_ROLE_MENUS` 当前 0 行，角色走 `MENU_CONFIG` 默认），保持现有机制即可，不要另写补齐分支。
2. 在 `frontend/src/router/route-manifest.ts` 注册两条新路由（`menuId/name/path/component/group` 照抄同组现有项结构），组件指向占位页；`AppSidebar.vue` 为两个新菜单补图标（Element Plus 内置图标，如 `DataAnalysis`、`Files`）。
3. 同步更新 `tests/test_menu_api.py`（目录计数、角色矩阵）、`frontend/tests/unit/route-manifest.test.ts`、`frontend/tests/unit/menu-intersect.test.ts`（manifest ⊆ catalog 契约）。

---

## 四、绝对红线与禁令

1. 绝不可把无科室归属的普通用户解析成 `scope="all"`（必须返回空集合、安全默认拒绝）。
2. 绝不可破坏 `app/services/timeliness_access.py` 现有企微 H5 虚拟身份（`his_empno:*`）的本科室只读隔离！
3. 严禁修改 `prearchive_service/` 下任何文件；严禁 `git commit/push` 或连接生产写入。

---

## 五、验收测试与交付标准

1. `tests/test_wp02_data_scope_and_holography.py` 至少覆盖 10 个用例：
   - `admin` → `all`；
   - `home` 角色只能查到本科室的 `stats`、`logs`、`patient-qc`、`relay-alert`、`timeliness`；
   - `selected` 多科室角色精准匹配多科且不跨科；
   - 用户个人覆盖优先于角色默认；
   - 无科室普通用户安全返回 0 条而非全院；
   - `POST /api/users/batch-update` 正常批量改角色/范围 + 禁禁用自己 + 禁禁用最后管理员；
   - `PUT /api/roles/{id}/access-bundle` 原子保存菜单+权限+数据范围；
    - `GET/POST /api/config/holography` 默认值（`S28` + `wfy`）与更新校验；`GET` 返回的 `user_code`：用户名 `003966` → `003966`，`admin` → `wfy`，非法正则保存返回 400；
    - `relay-alert/logs` 与 `summary`：`home` 角色仅见本科室告警、`retry` 仍对非 admin 返回 403；
    - `GET /api/departments` 返回结构不变（仍是列表），`GET /api/departments/paged` 分页与 `user_count` 正确；
    - `GET /api/users` 旧参数 `page/limit/q` 行为不变，新筛选参数生效。
2. `frontend/tests/unit/holography.test.ts` 覆盖（mock `loadHolographyConfig` 返回值）：
    - `user_code='003966'` → URL 含 `patientId=00985003&userCode=003966&sysCode=S28`；
    - `user_code='wfy'` → `userCode=wfy`；
    - `enabled=false` 或空 `patientId` → 返回 `null`；
    - `HolographyButton` 在 `enabled=false` 时不渲染、无患者号时禁用。

**收工必跑验收命令（PowerShell，文件名写全）**：
```powershell
python -m compileall app tests scripts
python -m pytest tests/test_wp02_data_scope_and_holography.py tests/test_menu_api.py tests/test_dept_visibility.py tests/test_access_contracts.py tests/test_prearchive_rbac_matrix.py -q
python -m pytest tests/timeliness -q
cd frontend
npm run typecheck
npm run test:unit -- tests/unit/holography.test.ts tests/unit/route-manifest.test.ts tests/unit/menu-intersect.test.ts
npm run build
cd ..
python scripts/run_gates_20260906.py --quick
```
收工前写 `review/064-wp02/DELIVERY.md`，登记 `开发起步包/01_统一修改记录.md` 与 `02_协作任务板.md`（本地交付完成，未提交）。
